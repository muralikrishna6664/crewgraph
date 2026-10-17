from uuid import uuid4

from fastapi.testclient import TestClient
from falkordb import FalkorDB

from app import queries
from app.main import app


def test_project_graph_and_events_endpoints_return_persisted_data() -> None:
    project_id = f"test_dashboard_{uuid4().hex}"
    graph = FalkorDB().select_graph(project_id)
    client = TestClient(app)

    try:
        queries.create_project(graph, project_id)
        queries.create_task_dag(
            graph,
            [{"id": "task-1", "title": "Build service", "skill": "backend"}],
            [],
        )
        queries.link_tasks_to_project(graph, project_id, ["task-1"])
        assert queries.claim_task(graph, "task-1", "backend-agent", 60) is not None
        artifact = queries.record_artifact(
            graph, "task-1", "backend-agent", "main.py", "backend", "source"
        )
        queries.record_bug(
            graph, "bug-1", "Example finding", "medium", artifact.properties["id"]
        )
        queries.record_event(
            graph,
            "task claimed",
            task_id="task-1",
            detail="Dashboard event node",
        )
        assert queries.complete_task(graph, "task-1") is not None
        queries.mark_bugs_fixed(graph, ["bug-1"])

        projects_response = client.get("/projects")
        graph_response = client.get(f"/projects/{project_id}/graph")
        events_response = client.get(f"/projects/{project_id}/events")

        assert projects_response.status_code == 200
        assert project_id in projects_response.json()

        assert graph_response.status_code == 200
        graph_data = graph_response.json()
        task = next(node for node in graph_data["nodes"] if node["id"] == "task-1")
        assert task["label"] == "Task"
        assert task["title"] == "Build service"
        assert task["status"] == "done"
        assert {"source": "task-1", "target": project_id, "type": "PART_OF"} in (
            graph_data["edges"]
        )
        assert any(edge["type"] == "FOUND_IN" for edge in graph_data["edges"])
        assert all(node["label"] != "Event" for node in graph_data["nodes"])
        visible_node_ids = {node["id"] for node in graph_data["nodes"]}
        assert all(
            edge["source"] in visible_node_ids and edge["target"] in visible_node_ids
            for edge in graph_data["edges"]
        )

        assert events_response.status_code == 200
        events = events_response.json()
        event_types = [event["type"] for event in events]
        assert event_types == [
            "task claimed",
            "artifact created",
            "bug found",
            "task claimed",
            "task done",
            "bug fixed",
        ]
        assert any(event["detail"] == "Dashboard event node" for event in events)
        timestamps = [event["ts"] for event in events]
        assert timestamps == sorted(timestamps)
    finally:
        graph.delete()
