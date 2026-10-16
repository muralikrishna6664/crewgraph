from uuid import uuid4

from falkordb import FalkorDB
import pytest

from agents.debugger import DebuggerAgent
from agents.planner import Planner
from app import queries
from app.orchestrator import run_project


@pytest.mark.parametrize("flaw", [False, True])
def test_mock_orchestrator_runs_real_http_checks(
    monkeypatch, tmp_path, flaw: bool
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("DEMO_FLAW", "1" if flaw else "0")
    monkeypatch.setattr(
        "agents.worker.WORKSPACE_ROOT", tmp_path / "workspace"
    )
    debugger_calls: list[str] = []
    repair_open_bugs = DebuggerAgent.repair_open_bugs

    def track_debugger(
        debugger: DebuggerAgent, graph
    ) -> list[str]:
        debugger_calls.append(graph.name)
        return repair_open_bugs(debugger, graph)

    monkeypatch.setattr(DebuggerAgent, "repair_open_bugs", track_debugger)
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
        statuses = {task.properties["id"]: task.properties["status"] for task in final_tasks}
        if flaw:
            assert statuses == {
                "todo-api": "done",
                "todo-page": "done",
                "todo-tests": "done",
            }
        else:
            assert set(statuses.values()) == {"done"}

        artifacts = queries.task_artifacts(graph)
        assert artifacts
        assert {"todo-api", "todo-page"} <= {
            item["task"]["id"] for item in artifacts
        }
        assert all(item["agents"] for item in artifacts)
        assert any(
            item["artifact"]["kind"] == "api_contract"
            and item["artifact"]["content"]
            for item in artifacts
        )
        bugs = queries.open_bugs(graph)
        if flaw:
            assert debugger_calls == [graph_name]
            all_bugs = queries.bugs(graph)
            assert queries.count_bugs(graph) >= 1
            assert all(bug["bug"]["status"] == "fixed" for bug in all_bugs)
            assert bugs == []
            assert all(bug["artifact"]["kind"] == "backend" for bug in all_bugs)
            assert all(queries.bug_fix_artifacts(
                graph, bug["bug"]["id"]
            ) for bug in all_bugs)
            assert any(
                fixed.properties["id"] != bug["artifact"]["id"]
                for bug in all_bugs
                for fixed in queries.bug_fix_artifacts(graph, bug["bug"]["id"])
            )
        else:
            assert debugger_calls == []
            assert bugs == []
            assert queries.count_bugs(graph) == 0
        assert (tmp_path / "workspace" / graph_name).is_dir()
    finally:
        graph.delete()
