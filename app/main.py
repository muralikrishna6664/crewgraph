import logging
import os
from pathlib import Path
from threading import Lock, Thread
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from falkordb.graph import Graph
from falkordb.node import Node
from pydantic import BaseModel
from redis.exceptions import ResponseError

from agents.planner import Planner
from agents.worker import _workspace_path
from app import queries
from app.auth import (
    DemoSession,
    auth_enabled,
    create_session_token,
    verify_password,
    verify_session_token,
)
from app.db import get_graph
from app.orchestrator import run_project
from app.schema import init_project

app = FastAPI(title="CrewGraph")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
_demo_lock = Lock()
_demo_runs_lock = Lock()
_demo_runs: dict[str, dict[str, str]] = {}
_max_artifact_size = 256 * 1024
_default_prompt = "build a to-do app with a REST API and a simple web page"
_session_cookie = "crewgraph_session"


class DemoRunRequest(BaseModel):
    """Options for starting a generated project run."""

    prompt: str = _default_prompt
    flaw: bool = False


class LoginRequest(BaseModel):
    """Credentials for one of the synthetic demo accounts."""

    username: str
    password: str


def current_session(request: Request) -> DemoSession | None:
    """Resolve the request's signed session when authentication is enabled."""
    if not auth_enabled():
        return None
    authorization = request.headers.get("authorization", "")
    token = request.cookies.get(_session_cookie)
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    session = verify_session_token(token) if token else None
    if session is None:
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid session token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return session


def _ensure_project_access(
    project_id: str, session: DemoSession | None
) -> None:
    """Hide projects whose graph name is outside the authenticated tenant."""
    if session is not None and not project_id.startswith(f"{session.tenant}_"):
        raise HTTPException(status_code=404, detail="Project not found")


@app.get("/")
def dashboard(request: Request) -> Response:
    """Serve the dashboard or redirect unauthenticated users to sign-in."""
    if auth_enabled():
        try:
            current_session(request)
        except HTTPException:
            return RedirectResponse("/login", status_code=303)
    page = Path(__file__).parent / "static" / "index.html"
    return FileResponse(page, media_type="text/html")


@app.get("/login")
def login_page() -> FileResponse:
    """Serve the public demo sign-in page."""
    page = Path(__file__).parent / "static" / "login.html"
    return FileResponse(page, media_type="text/html")


@app.post("/auth/login")
def login(credentials: LoginRequest, request: Request, response: Response) -> dict[str, str]:
    """Verify a demo account and issue a signed session token."""
    if not verify_password(credentials.username, credentials.password):
        raise HTTPException(status_code=401, detail="Invalid tenant or password")
    token = create_session_token(credentials.username)
    response.set_cookie(
        _session_cookie,
        token,
        max_age=8 * 60 * 60,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        path="/",
    )
    return {
        "token": token,
        "username": credentials.username,
        "tenant": credentials.username,
    }


@app.post("/auth/logout")
def logout(response: Response) -> dict[str, str]:
    """Clear the browser's demo session cookie."""
    response.delete_cookie(_session_cookie, path="/", httponly=True, samesite="lax")
    return {"status": "logged out"}


@app.get("/config")
def public_config() -> dict[str, object]:
    """Return the configured model mode for the dashboard badge."""
    provider = os.environ.get("LLM_PROVIDER", "mock").lower()
    if provider == "mock":
        return {"llm_mode": "Mock LLM mode", "auth_enabled": auth_enabled()}
    if provider == "openai":
        return {"llm_mode": "Live LLM", "auth_enabled": auth_enabled()}
    raise HTTPException(status_code=503, detail=f"Unsupported LLM_PROVIDER: {provider}")


def _prepare_demo(project_id: str, prompt: str, flaw: bool) -> None:
    """Persist the requested plan before returning its project ID."""
    with _demo_lock:
        previous_flaw = os.environ.get("DEMO_FLAW")
        os.environ["DEMO_FLAW"] = "1" if flaw else "0"
        try:
            graph = init_project(project_id)
            queries.create_project(graph, project_id)
            queries.update_project_prompt(graph, project_id, prompt)
            tasks = Planner().plan(prompt, graph)
            queries.link_tasks_to_project(
                graph, project_id, [task["id"] for task in tasks]
            )
        except Exception:
            logging.exception("Demo preparation failed for project %s", project_id)
            raise
        finally:
            if previous_flaw is None:
                os.environ.pop("DEMO_FLAW", None)
            else:
                os.environ["DEMO_FLAW"] = previous_flaw


def _run_demo(project_id: str, flaw: bool) -> None:
    """Run a prepared project in an isolated background thread."""
    try:
        try:
            step_delay_ms = int(os.environ.get("DEMO_STEP_DELAY_MS", "1200"))
        except ValueError as error:
            raise ValueError(
                "DEMO_STEP_DELAY_MS must be a non-negative integer"
            ) from error
        if step_delay_ms < 0:
            raise ValueError("DEMO_STEP_DELAY_MS must be a non-negative integer")
        with _demo_lock:
            previous_flaw = os.environ.get("DEMO_FLAW")
            os.environ["DEMO_FLAW"] = "1" if flaw else "0"
            try:
                run_project(init_project(project_id), step_delay_ms=step_delay_ms)
            finally:
                if previous_flaw is None:
                    os.environ.pop("DEMO_FLAW", None)
                else:
                    os.environ["DEMO_FLAW"] = previous_flaw
    except Exception as error:
        logging.exception("Demo run failed for project %s", project_id)
        with _demo_runs_lock:
            _demo_runs[project_id] = {
                "status": "failed",
                "message": str(error) or type(error).__name__,
            }
    else:
        with _demo_runs_lock:
            _demo_runs[project_id] = {"status": "finished", "message": ""}


@app.post("/demo/run", status_code=202)
def start_demo(
    request: DemoRunRequest,
    session: DemoSession | None = Depends(current_session),
) -> dict[str, str]:
    """Plan and start a build request in a background thread."""
    tenant_prefix = f"{session.tenant}_" if session is not None else ""
    project_id = f"{tenant_prefix}dashboard_demo_{uuid4().hex[:12]}"
    with _demo_runs_lock:
        _demo_runs[project_id] = {"status": "starting", "message": ""}
    try:
        _prepare_demo(project_id, request.prompt, request.flaw)
    except Exception as error:
        logging.exception("Demo preparation failed for project %s", project_id)
        with _demo_runs_lock:
            _demo_runs[project_id] = {
                "status": "failed",
                "message": str(error) or type(error).__name__,
            }
        return {"project_id": project_id, "status": "failed"}
    with _demo_runs_lock:
        _demo_runs[project_id] = {"status": "running", "message": ""}
    thread = Thread(
        target=_run_demo,
        args=(project_id, request.flaw),
        name=f"crewgraph-demo-{project_id}",
        daemon=True,
    )
    thread.start()
    return {"project_id": project_id, "status": "started"}


@app.get("/demo/runs/{project_id}")
def demo_run_status(
    project_id: str,
    session: DemoSession | None = Depends(current_session),
) -> dict[str, str]:
    """Return a run status, falling back to unknown for an existing project."""
    _ensure_project_access(project_id, session)
    with _demo_runs_lock:
        status = _demo_runs.get(project_id)
    if status is None:
        _project_nodes(project_id)
        return {
            "project_id": project_id,
            "status": "unknown",
            "message": "No in-process run status is available.",
        }
    return {"project_id": project_id, **status}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _node_id(node: Node) -> str:
    """Return a stable dashboard identifier for a FalkorDB node."""
    properties = node.properties
    labels = node.labels
    label = labels[0] if labels else "Node"
    value = (
        properties.get("id")
        or properties.get("name")
        or properties.get("path")
        or f"{label}:{node.id}"
    )
    return str(value)


def _project_nodes(project_id: str) -> tuple[Graph, list[Node], bool]:
    """Load project nodes and identify a registered project that is starting."""
    graph = get_graph(project_id)
    try:
        nodes = queries.graph_nodes(graph)
    except ResponseError as error:
        if "Invalid graph operation on empty key" not in str(error):
            raise
        nodes = []
    project_exists = any(
        "Project" in node.labels
        and node.properties.get("id") == project_id
        for node in nodes
    )
    if not project_exists:
        with _demo_runs_lock:
            run = _demo_runs.get(project_id)
        if run is not None and run.get("status") in {"starting", "running"}:
            return graph, [], True
        raise HTTPException(status_code=404, detail="Project not found")
    return graph, nodes, False


@app.get("/projects")
def projects(
    session: DemoSession | None = Depends(current_session),
) -> list[str]:
    """List project IDs backed by Project nodes in FalkorDB."""
    project_ids = queries.list_projects()
    if session is None:
        return project_ids
    return [
        project_id
        for project_id in project_ids
        if project_id.startswith(f"{session.tenant}_")
    ]


@app.get("/projects/{project_id}/graph")
def project_graph(
    project_id: str,
    session: DemoSession | None = Depends(current_session),
) -> dict[str, object]:
    """Return project nodes and relationships in dashboard-friendly JSON."""
    _ensure_project_access(project_id, session)
    graph, nodes, starting = _project_nodes(project_id)
    if starting:
        return {"nodes": [], "edges": [], "status": "starting"}
    node_records = []
    for node in nodes:
        if "Event" in node.labels:
            continue
        properties = node.properties
        labels = node.labels
        node_records.append(
            {
                "label": labels[0] if labels else "Node",
                "id": _node_id(node),
                "title": properties.get("title")
                or properties.get("name")
                or properties.get("path")
                or properties.get("type")
                or properties.get("id", ""),
                "status": properties.get("status"),
                "severity": properties.get("severity"),
                "properties": properties,
            }
        )
    edge_records = [
        {
            "source": _node_id(source),
            "target": _node_id(target),
            "type": relationship,
        }
        for source, relationship, target in queries.graph_edges(graph)
        if "Event" not in source.labels and "Event" not in target.labels
    ]
    project = next(
        node
        for node in nodes
        if "Project" in node.labels and node.properties.get("id") == project_id
    )
    project_properties = project.properties
    prompt = project_properties.get("prompt")
    tasks = [node for node in node_records if node["label"] == "Task"]
    dependency_edges = [
        edge for edge in edge_records if edge["type"] == "DEPENDS_ON"
    ]
    tasks_with_dependencies = {
        str(edge["source"]) for edge in dependency_edges
    }
    depended_on_tasks = {str(edge["target"]) for edge in dependency_edges}
    prompt_node_id = f"prompt:{project_id}"
    output_node_id = f"output:{project_id}"
    prompt_node = {
        "label": "Prompt",
        "id": prompt_node_id,
        "title": "Prompt",
        "status": None,
        "severity": None,
        "properties": {"prompt": prompt if isinstance(prompt, str) else ""},
    }
    release = queries.release_status(graph, project_id)
    output_status = "released" if release["released"] else "pending"
    output_node = {
        "label": "Output",
        "id": output_node_id,
        "title": "Output",
        "status": output_status,
        "severity": None,
        "properties": {"status": output_status},
    }
    frame_edges = [
        {
            "source": prompt_node_id,
            "target": str(task["id"]),
            "type": "STARTS",
        }
        for task in tasks
        if str(task["id"]) not in tasks_with_dependencies
    ] + [
        {
            "source": str(task["id"]),
            "target": output_node_id,
            "type": "OUTPUTS",
        }
        for task in tasks
        if str(task["id"]) not in depended_on_tasks
    ]
    if not tasks:
        frame_edges = [{"source": prompt_node_id, "target": output_node_id, "type": "STARTS"}]
    return {
        "nodes": [*node_records, prompt_node, output_node],
        "edges": [*edge_records, *frame_edges],
    }


@app.get("/projects/{project_id}/events")
def project_events(
    project_id: str,
    session: DemoSession | None = Depends(current_session),
) -> list[dict[str, object]]:
    """Return recent persisted project events in chronological order."""
    _ensure_project_access(project_id, session)
    graph, _, starting = _project_nodes(project_id)
    if starting:
        return []
    return [event.properties for event in queries.project_events(graph)]


@app.get("/projects/{project_id}/artifacts")
def project_artifacts(
    project_id: str,
    session: DemoSession | None = Depends(current_session),
) -> list[dict[str, object]]:
    """List graph-backed project files with their version and producing agents."""
    _ensure_project_access(project_id, session)
    graph, _, starting = _project_nodes(project_id)
    if starting:
        return []
    artifact_items = queries.task_artifacts(graph)
    artifact_items.sort(
        key=lambda item: (
            int(item["artifact"].get("ts", 0)),
            str(item["artifact"].get("path", "")),
        )
    )
    versions: dict[str, int] = {}
    records: list[dict[str, object]] = []
    for item in artifact_items:
        artifact = item["artifact"]
        path = str(artifact.get("path", ""))
        versions[path] = versions.get(path, 0) + 1
        records.append(
            {
                "id": artifact.get("id"),
                "path": path,
                "version": versions[path],
                "agents": item["agents"],
                "ts": artifact.get("ts"),
            }
        )
    return records


@app.get("/projects/{project_id}/artifacts/{artifact_id:path}")
def project_artifact(
    project_id: str,
    artifact_id: str,
    session: DemoSession | None = Depends(current_session),
) -> dict[str, object]:
    """Read a bounded workspace file only when it is registered in this graph."""
    _ensure_project_access(project_id, session)
    graph, _, starting = _project_nodes(project_id)
    if starting:
        raise HTTPException(status_code=404, detail="Artifact not found")
    artifact = queries.artifact_by_id(graph, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    relative_path = artifact.properties.get("path")
    if not isinstance(relative_path, str):
        raise HTTPException(status_code=404, detail="Artifact path is unavailable")
    try:
        path = _workspace_path(project_id, relative_path)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="Unsafe artifact path") from error
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Artifact file not found")
    size = path.stat().st_size
    if size > _max_artifact_size:
        raise HTTPException(status_code=413, detail="Artifact exceeds the preview size limit")
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise HTTPException(status_code=415, detail="Artifact is not UTF-8 text") from error
    return {
        "id": artifact.properties.get("id"),
        "path": relative_path,
        "size": size,
        "content": content,
    }


@app.get("/projects/{project_id}/tasks/{task_id}/context")
def task_context(
    project_id: str,
    task_id: str,
    session: DemoSession | None = Depends(current_session),
) -> dict[str, object]:
    """Return task handoff context from its project graph."""
    _ensure_project_access(project_id, session)
    try:
        context = queries.handoff_context(get_graph(project_id), task_id)
    except ResponseError as error:
        if "Invalid graph operation on empty key" not in str(error):
            raise
        context = None
    if context is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return context


@app.post("/projects/{project_id}/approve")
def approve_project(
    project_id: str,
    session: DemoSession | None = Depends(current_session),
) -> dict[str, object]:
    """Record human approval for a project's release."""
    _ensure_project_access(project_id, session)
    graph = get_graph(project_id)
    try:
        approval = queries.approve_project(graph, project_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    run_project(graph)
    return {"project_id": project_id, "status": approval.properties["status"]}


@app.get("/projects/{project_id}/release-status")
def project_release_status(
    project_id: str,
    session: DemoSession | None = Depends(current_session),
) -> dict[str, object]:
    """Return the release gate status and all blocking reasons."""
    _ensure_project_access(project_id, session)
    graph, _, starting = _project_nodes(project_id)
    if starting:
        return {
            "can_release": False,
            "released": False,
            "reasons": ["Project is starting"],
            "status": "starting",
        }
    return queries.release_status(graph, project_id)
