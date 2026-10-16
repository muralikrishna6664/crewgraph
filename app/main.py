from fastapi import FastAPI, HTTPException
from falkordb.graph import Graph
from falkordb.node import Node
from redis.exceptions import ResponseError

from app import queries
from app.db import get_graph

app = FastAPI(title="CrewGraph")


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


def _project_nodes(project_id: str) -> tuple[Graph, list[Node]]:
    """Load a project graph and return its nodes or report a missing project."""
    graph = get_graph(project_id)
    try:
        nodes = queries.graph_nodes(graph)
    except ResponseError as error:
        if "Invalid graph operation on empty key" not in str(error):
            raise
        nodes = []
    if not any(
        "Project" in node.labels
        and node.properties.get("id") == project_id
        for node in nodes
    ):
        raise HTTPException(status_code=404, detail="Project not found")
    return graph, nodes


@app.get("/projects")
def projects() -> list[str]:
    """List project IDs backed by Project nodes in FalkorDB."""
    return queries.list_projects()


@app.get("/projects/{project_id}/graph")
def project_graph(project_id: str) -> dict[str, list[dict[str, object]]]:
    """Return project nodes and relationships in dashboard-friendly JSON."""
    graph, nodes = _project_nodes(project_id)
    node_records = []
    for node in nodes:
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
    ]
    return {"nodes": node_records, "edges": edge_records}


@app.get("/projects/{project_id}/events")
def project_events(project_id: str) -> list[dict[str, object]]:
    """Return recent persisted project events in chronological order."""
    graph, _ = _project_nodes(project_id)
    return [event.properties for event in queries.recent_events(graph)]


@app.get("/projects/{project_id}/tasks/{task_id}/context")
def task_context(project_id: str, task_id: str) -> dict[str, object]:
    """Return task handoff context from its project graph."""
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
def approve_project(project_id: str) -> dict[str, object]:
    """Record human approval for a project's release."""
    graph = get_graph(project_id)
    try:
        approval = queries.approve_project(graph, project_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {"project_id": project_id, "status": approval.properties["status"]}


@app.get("/projects/{project_id}/release-status")
def project_release_status(project_id: str) -> dict[str, object]:
    """Return the release gate status and all blocking reasons."""
    return queries.release_status(get_graph(project_id), project_id)
