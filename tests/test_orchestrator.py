from uuid import uuid4

from falkordb import FalkorDB

from agents.planner import Planner
from app import queries
from app.orchestrator import run_project


def test_mock_orchestrator_completes_tasks_and_records_linked_artifacts(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setattr(
        "agents.worker.WORKSPACE_ROOT", tmp_path / "workspace"
    )
    graph_name = f"test_orchestrator_{uuid4().hex}"
    graph = FalkorDB().select_graph(graph_name)

    try:
        queries.create_project(graph, graph_name)
        tasks = Planner().plan(
            "build a to-do app with a REST API and a simple web page", graph
        )
        queries.link_tasks_to_project(
            graph, graph_name, [task["id"] for task in tasks]
        )

        final_tasks = run_project(graph)

        assert len(final_tasks) == 3
        assert {task.properties["status"] for task in final_tasks} == {"done"}
        artifacts = queries.task_artifacts(graph)
        assert artifacts
        assert {item["task"]["id"] for item in artifacts} == {
            task["id"] for task in tasks
        }
        assert all(item["agents"] for item in artifacts)
        assert any(
            item["artifact"]["kind"] == "api_contract"
            and item["artifact"]["content"]
            for item in artifacts
        )
        assert (tmp_path / "workspace" / graph_name).is_dir()
    finally:
        graph.delete()
