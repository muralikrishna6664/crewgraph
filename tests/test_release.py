from uuid import uuid4

from fastapi.testclient import TestClient
from falkordb import FalkorDB

from app import queries
from app.main import app
from app.orchestrator import run_project


def test_release_status_reports_blockers_and_allows_approved_complete_project() -> None:
    project_id = f"test_release_{uuid4().hex}"
    graph = FalkorDB().select_graph(project_id)
    client = TestClient(app)

    try:
        queries.create_project(graph, project_id)
        queries.create_task_dag(
            graph,
            [{"id": "work", "title": "Implement work", "skill": "backend"}],
            [],
        )

        blocked = client.get(f"/projects/{project_id}/release-status")
        assert blocked.status_code == 200
        assert blocked.json()["can_release"] is False
        assert any("not done" in reason for reason in blocked.json()["reasons"])
        assert any("approval" in reason for reason in blocked.json()["reasons"])

        approval = client.post(f"/projects/{project_id}/approve")
        assert approval.status_code == 200
        assert approval.json()["status"] == "approved"
        assert queries.complete_task(graph, "work") is not None

        allowed = client.get(f"/projects/{project_id}/release-status")
        assert allowed.status_code == 200
        assert allowed.json() == {
            "can_release": True,
            "released": True,
            "reasons": [],
        }
        assert queries.can_release(graph, project_id)

        released_tasks = run_project(graph)
        assert any(
            task.properties["id"] == f"{project_id}:release"
            and task.properties["status"] == "done"
            for task in released_tasks
        )
        released = client.get(f"/projects/{project_id}/release-status")
        assert released.json()["released"] is True
    finally:
        graph.delete()


def test_open_bug_blocks_release_even_after_approval() -> None:
    project_id = f"test_release_bug_{uuid4().hex}"
    graph = FalkorDB().select_graph(project_id)
    client = TestClient(app)

    try:
        queries.create_project(graph, project_id)
        queries.create_task_dag(
            graph,
            [{"id": "work", "title": "Implement work", "skill": "backend"}],
            [],
        )
        artifact = queries.record_artifact(
            graph, "work", "backend", "main.py", "backend", "pass"
        )
        queries.record_bug(
            graph, "bug", "Open issue", "high", artifact.properties["id"]
        )
        queries.complete_task(graph, "work")
        client.post(f"/projects/{project_id}/approve")

        status = client.get(f"/projects/{project_id}/release-status")

        assert status.status_code == 200
        assert status.json()["can_release"] is False
        assert status.json()["released"] is False
        assert any("Open bugs" in reason for reason in status.json()["reasons"])
    finally:
        graph.delete()
