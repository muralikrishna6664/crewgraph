from fastapi import FastAPI, HTTPException
from redis.exceptions import ResponseError

from app import queries
from app.db import get_graph

app = FastAPI(title="CrewGraph")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


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
