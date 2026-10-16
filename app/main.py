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
