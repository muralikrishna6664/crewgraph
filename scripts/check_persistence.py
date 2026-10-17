"""Verify a mock repair run survives restarting the local FalkorDB service."""

import json
import os
from pathlib import Path
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


API_URL = os.getenv("CREWGRAPH_API_URL", "http://localhost:8000").rstrip("/")
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _request_json(path: str, method: str = "GET", body: object | None = None) -> object:
    """Send a JSON request to the local CrewGraph API and return its response."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = Request(
        f"{API_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method=method,
    )
    try:
        with urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"API returned HTTP {error.code}: {detail}") from error
    except URLError as error:
        raise RuntimeError(f"Could not reach CrewGraph at {API_URL}: {error}") from error


def _run_demo() -> str:
    """Run the local demo with its synthetic defect and wait for repair checks."""
    health = _request_json("/health")
    if health != {"status": "ok"}:
        raise RuntimeError(f"CrewGraph API is not healthy: {health}")

    started = _request_json("/demo/run", method="POST", body={"flaw": True})
    if not isinstance(started, dict) or not isinstance(
        started.get("project_id"), str
    ):
        raise RuntimeError(f"Demo API returned an invalid response: {started}")
    project_id = started["project_id"]
    print(f"Started flawed demo: {project_id}")

    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        run = _request_json(f"/demo/runs/{project_id}")
        if isinstance(run, dict) and run.get("status") == "finished":
            break
        if isinstance(run, dict) and run.get("status") == "failed":
            raise RuntimeError(f"Demo run failed: {run.get('message')}")
        time.sleep(0.5)
    else:
        raise TimeoutError(f"Demo run did not finish within 90 seconds: {project_id}")

    projects = _request_json("/projects")
    if not isinstance(projects, list) or project_id not in projects:
        raise RuntimeError(f"Project is missing before restart: {project_id}")
    print("Demo finished; project is present before restart.")
    return project_id


def _restart_falkordb() -> None:
    """Restart only the Compose FalkorDB service without removing its volume."""
    subprocess.run(
        ["docker", "compose", "restart", "falkordb"],
        cwd=PROJECT_ROOT,
        check=True,
        timeout=90,
    )


def _load_graph_after_restart(project_id: str) -> dict[str, object]:
    """Retry graph reads until FalkorDB is ready after its container restart."""
    path = f"/projects/{project_id}/graph"
    deadline = time.monotonic() + 60
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            result = _request_json(path)
            if not isinstance(result, dict):
                raise RuntimeError(f"Graph API returned an invalid payload: {result}")
            return result
        except (RuntimeError, TimeoutError) as error:
            last_error = error
            time.sleep(1)
    raise TimeoutError(
        f"Could not read project graph after FalkorDB restart: {last_error}"
    )


def _verify_graph(project_id: str, graph: dict[str, object]) -> None:
    """Require the project, completed tasks, fixed bug, and repair edge to persist."""
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise RuntimeError("Graph response did not contain nodes and edges arrays")

    project_nodes = [
        node
        for node in nodes
        if isinstance(node, dict)
        and node.get("label") == "Project"
        and node.get("id") == project_id
    ]
    tasks = [
        node
        for node in nodes
        if isinstance(node, dict) and node.get("label") == "Task"
    ]
    bugs = [
        node
        for node in nodes
        if isinstance(node, dict) and node.get("label") == "Bug"
    ]
    fixed_bugs = [bug for bug in bugs if bug.get("status") == "fixed"]
    node_by_id = {
        node["id"]: node
        for node in nodes
        if isinstance(node, dict) and isinstance(node.get("id"), str)
    }
    fix_edges = [
        edge
        for edge in edges
        if isinstance(edge, dict)
        and edge.get("type") == "FIXES"
        and edge.get("source") in node_by_id
        and edge.get("target") in node_by_id
        and node_by_id[edge["source"]].get("label") == "Artifact"
        and node_by_id[edge["target"]].get("label") == "Bug"
    ]

    missing: list[str] = []
    if not project_nodes:
        missing.append("Project node")
    if not tasks or any(task.get("status") != "done" for task in tasks):
        missing.append("completed Tasks")
    if not bugs or not fixed_bugs:
        missing.append("fixed Bug")
    if not fix_edges:
        missing.append("Artifact-[:FIXES]->Bug edge")
    if missing:
        raise RuntimeError("Persistence check missing: " + ", ".join(missing))

    print(f"Project node: present ({project_id})")
    print(f"Tasks: {len(tasks)} present; all done")
    print(f"Bug nodes: {len(bugs)} present; fixed: {len(fixed_bugs)}")
    print(f"Artifact-[:FIXES]->Bug edges: {len(fix_edges)} present")


def main() -> None:
    """Build a flawed demo, restart FalkorDB, and verify persisted graph data."""
    project_id = _run_demo()
    _restart_falkordb()
    print("Restarted FalkorDB with `docker compose restart falkordb`.")
    graph = _load_graph_after_restart(project_id)
    _verify_graph(project_id, graph)
    print("Persistence check passed.")


if __name__ == "__main__":
    main()
