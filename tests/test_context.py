from uuid import uuid4

from fastapi.testclient import TestClient
from falkordb import FalkorDB

from app.main import app
from app.queries import (
    create_task_dag,
    handoff,
    record_artifact,
    record_bug,
    record_lesson,
    record_vulnerability,
)


def test_task_context_endpoint_returns_dependency_evidence_and_lessons() -> None:
    graph_name = f"test_context_{uuid4().hex}"
    graph = FalkorDB().select_graph(graph_name)
    tasks = [
        {"id": "prerequisite", "title": "Build service", "skill": "backend"},
        {"id": "requested", "title": "Build page", "skill": "frontend"},
    ]

    try:
        create_task_dag(
            graph,
            tasks,
            [{"task_id": "requested", "depends_on": "prerequisite"}],
        )
        artifact = record_artifact(
            graph, "prerequisite", "backend-agent", "src/service.py", "source"
        )
        record_bug(graph, "bug-1", artifact.properties["id"], "open")
        record_vulnerability(
            graph,
            "vulnerability-1",
            artifact.properties["id"],
            "input-validation",
            "medium",
            "open",
        )
        record_lesson(graph, "lesson-1", "Validate user input at the API boundary.")
        handoff(graph, "requested", "planner", "frontend-agent", "Dependencies ready")

        response = TestClient(app).get(
            f"/projects/{graph_name}/tasks/requested/context"
        )

        assert response.status_code == 200
        context = response.json()
        assert context["task"]["id"] == "requested"
        assert [item["id"] for item in context["artifacts"]] == [
            artifact.properties["id"]
        ]
        assert {item["id"] for item in context["issues"]} == {
            "bug-1",
            "vulnerability-1",
        }
        assert [item["id"] for item in context["lessons"]] == ["lesson-1"]
    finally:
        graph.delete()


def test_task_context_endpoint_returns_404_for_unknown_task() -> None:
    graph_name = f"test_context_missing_{uuid4().hex}"
    graph = FalkorDB().select_graph(graph_name)

    try:
        create_task_dag(
            graph, [{"id": "existing", "title": "Existing", "skill": "backend"}], []
        )
        response = TestClient(app).get(
            f"/projects/{graph_name}/tasks/missing/context"
        )

        assert response.status_code == 404
    finally:
        graph.delete()
