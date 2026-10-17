from uuid import uuid4

from fastapi.testclient import TestClient
from falkordb import FalkorDB
from redis.exceptions import ResponseError

from app import queries
import app.main as main
from app.main import app


def _delete_test_graph(graph) -> None:
    """Delete a temporary graph, allowing FalkorDB's empty-graph response."""
    try:
        graph.delete()
    except ResponseError as error:
        if "Invalid graph operation on empty key" not in str(error):
            raise


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
        queries.approve_project(graph, project_id)

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
        bug_node = next(node for node in graph_data["nodes"] if node["id"] == "bug-1")
        assert bug_node["status"] == "fixed"
        approval_node = next(
            node
            for node in graph_data["nodes"]
            if node["label"] == "Approval"
        )
        assert approval_node["status"] == "approved"
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
        _delete_test_graph(graph)


def test_registered_starting_project_endpoints_return_empty_payloads() -> None:
    project_id = f"test_dashboard_starting_{uuid4().hex}"
    graph = FalkorDB().select_graph(project_id)
    client = TestClient(app)

    try:
        with main._demo_runs_lock:
            main._demo_runs[project_id] = {"status": "starting", "message": ""}

        graph_response = client.get(f"/projects/{project_id}/graph")
        events_response = client.get(f"/projects/{project_id}/events")
        release_response = client.get(f"/projects/{project_id}/release-status")

        assert graph_response.status_code == 200
        assert graph_response.json() == {
            "nodes": [],
            "edges": [],
            "status": "starting",
        }
        assert events_response.status_code == 200
        assert events_response.json() == []
        assert release_response.status_code == 200
        assert release_response.json() == {
            "can_release": False,
            "released": False,
            "reasons": ["Project is starting"],
            "status": "starting",
        }
    finally:
        with main._demo_runs_lock:
            main._demo_runs.pop(project_id, None)
        _delete_test_graph(graph)


def test_unknown_project_graph_events_and_release_endpoints_return_404() -> None:
    project_id = f"test_dashboard_unknown_{uuid4().hex}"
    graph = FalkorDB().select_graph(project_id)
    client = TestClient(app)

    try:
        assert client.get(f"/projects/{project_id}/graph").status_code == 404
        assert client.get(f"/projects/{project_id}/events").status_code == 404
        assert client.get(f"/projects/{project_id}/release-status").status_code == 404
    finally:
        _delete_test_graph(graph)
