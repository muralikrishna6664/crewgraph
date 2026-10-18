from uuid import uuid4

from fastapi.testclient import TestClient
from falkordb import FalkorDB
from redis.exceptions import ResponseError

from app import queries
import app.main as main
from app.main import app
from agents import worker


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
        queries.update_project_prompt(graph, project_id, "Build a tiny demo")
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
        prompt_node = next(node for node in graph_data["nodes"] if node["label"] == "Prompt")
        output_node = next(node for node in graph_data["nodes"] if node["label"] == "Output")
        assert prompt_node["properties"]["prompt"] == "Build a tiny demo"
        assert output_node["properties"]["status"] == "pending"

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


def test_artifact_listing_and_preview_use_registered_bounded_workspace_files(
    tmp_path, monkeypatch
) -> None:
    project_id = f"test_artifacts_{uuid4().hex}"
    graph = FalkorDB().select_graph(project_id)
    workspace_root = tmp_path / "workspace"
    monkeypatch.setattr(worker, "WORKSPACE_ROOT", workspace_root)
    client = TestClient(app)

    try:
        queries.create_project(graph, project_id)
        queries.create_task_dag(
            graph,
            [{"id": "task-1", "title": "Build page", "skill": "frontend"}],
            [],
        )
        queries.link_tasks_to_project(graph, project_id, ["task-1"])
        artifact = queries.record_artifact(
            graph,
            "task-1",
            "frontend-agent",
            "dashboard/index.html",
            "frontend",
            "<h1>Real artifact</h1>",
        )
        file_path = workspace_root / project_id / "dashboard" / "index.html"
        file_path.parent.mkdir(parents=True)
        file_path.write_text("<h1>Real artifact</h1>", encoding="utf-8")

        listed = client.get(f"/projects/{project_id}/artifacts")
        assert listed.status_code == 200
        assert listed.json() == [
            {
                "id": artifact.properties["id"],
                "path": "dashboard/index.html",
                "version": 1,
                "agents": ["frontend-agent"],
                "ts": artifact.properties["ts"],
            }
        ]
        preview = client.get(
            f"/projects/{project_id}/artifacts/{artifact.properties['id']}"
        )
        assert preview.status_code == 200
        assert preview.json()["content"] == "<h1>Real artifact</h1>"

        unsafe = queries.record_artifact(
            graph,
            "task-1",
            "frontend-agent",
            "../outside.html",
            "frontend",
            "",
            artifact_id="unsafe-path",
        )
        assert unsafe.properties["id"] == "unsafe-path"
        assert client.get(
            f"/projects/{project_id}/artifacts/unsafe-path"
        ).status_code == 400

        monkeypatch.setattr(main, "_max_artifact_size", 2)
        assert client.get(
            f"/projects/{project_id}/artifacts/{artifact.properties['id']}"
        ).status_code == 413
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
