import json
from uuid import uuid4

import pytest
from falkordb import FalkorDB

from agents.llm import call
from agents.planner import Planner, validate_dag
from app.queries import ready_tasks


def test_mock_provider_returns_canned_dag_and_token_counts(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "mock")

    response = call("Plan tasks", "Build a to-do app")

    assert len(json.loads(response.text)["tasks"]) == 4
    assert response.input_tokens > 0
    assert response.output_tokens > 0


def test_validate_dag_rejects_cycles() -> None:
    dag = {
        "tasks": [
            {
                "id": "first",
                "title": "First",
                "skill": "backend",
                "depends_on": ["second"],
            },
            {
                "id": "second",
                "title": "Second",
                "skill": "frontend",
                "depends_on": ["first"],
            },
        ]
    }

    with pytest.raises(ValueError, match="cycle"):
        validate_dag(json.dumps(dag))


def test_mock_planner_writes_valid_dag_to_temporary_graph(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    graph = FalkorDB().select_graph(f"test_planner_{uuid4().hex}")

    try:
        response = call("Plan a project", "Build a to-do app with a REST API and page")
        assert response.input_tokens > 0
        assert response.output_tokens > 0

        tasks = Planner().plan(
            "Build a to-do app with a REST API and a simple web page", graph
        )
        assert len(tasks) == 4
        assert len({task["id"] for task in tasks}) == len(tasks)

        ready = ready_tasks(graph)
        assert {task.properties["id"] for task in ready} == {"todo-api"}
    finally:
        graph.delete()
