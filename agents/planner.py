"""Planner agent that validates and stores task DAGs."""

import json
from collections.abc import Callable

from falkordb.graph import Graph

from agents.llm import LLMResponse, call
from agents.runner import Agent
from app.queries import create_task_dag

PLANNER_PROMPT = """Create a task DAG for the user's software request.
Return one JSON object with a "tasks" array. Each task must have string fields
"id", "title", and "skill", plus a "depends_on" array of task IDs. A task depends
on each ID in its depends_on array. Use unique IDs and include only known task IDs.
Return JSON only."""


def validate_dag(payload: str) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Parse and validate task fields, dependency IDs, and cycle-free ordering."""
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as error:
        raise ValueError("Planner response is not valid JSON") from error

    if not isinstance(data, dict) or not isinstance(data.get("tasks"), list):
        raise ValueError("Planner response must contain a tasks array")
    if not data["tasks"]:
        raise ValueError("Planner response must contain at least one task")

    tasks: list[dict[str, str]] = []
    dependency_lists: dict[str, list[str]] = {}
    task_ids: set[str] = set()
    for task in data["tasks"]:
        if not isinstance(task, dict):
            raise ValueError("Each task must be a JSON object")
        task_id = task.get("id")
        title = task.get("title")
        skill = task.get("skill")
        depends_on = task.get("depends_on", [])
        if (
            not isinstance(task_id, str)
            or not task_id.strip()
            or not isinstance(title, str)
            or not title.strip()
            or not isinstance(skill, str)
            or not skill.strip()
            or not isinstance(depends_on, list)
            or any(not isinstance(dependency, str) for dependency in depends_on)
        ):
            raise ValueError(
                "Tasks need non-empty id, title, skill strings and a string depends_on list"
            )
        if task_id in task_ids:
            raise ValueError(f"Duplicate task id: {task_id}")
        task_ids.add(task_id)
        dependency_lists[task_id] = depends_on
        tasks.append({"id": task_id, "title": title, "skill": skill})

    deps: list[dict[str, str]] = []
    for task_id, depends_on in dependency_lists.items():
        for dependency_id in depends_on:
            if dependency_id not in task_ids:
                raise ValueError(
                    f"Task {task_id} depends on unknown task id: {dependency_id}"
                )
            deps.append({"task_id": task_id, "depends_on": dependency_id})

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> None:
        if task_id in visiting:
            raise ValueError("Task dependencies contain a cycle")
        if task_id in visited:
            return
        visiting.add(task_id)
        for dependency_id in dependency_lists[task_id]:
            visit(dependency_id)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in task_ids:
        visit(task_id)

    return tasks, deps


class Planner(Agent):
    """Create a validated DAG from a request and write it to a project graph."""

    def __init__(
        self, llm_call: Callable[[str, str], LLMResponse] = call
    ) -> None:
        super().__init__(
            name="planner",
            role="Break software requests into a dependency-aware task DAG",
            skills=["planning", "task decomposition"],
            system_prompt=PLANNER_PROMPT,
        )
        self._llm_call = llm_call

    def plan(self, request: str, graph: Graph) -> list[dict[str, str]]:
        """Plan tasks for a request, validate them, and persist them to the graph."""
        if not request.strip():
            raise ValueError("Request must not be empty")
        response = self._llm_call(self.system_prompt, request)
        tasks, deps = validate_dag(response.text)
        create_task_dag(graph, tasks, deps)
        return tasks

    def run(self, context: dict[str, object]) -> list[dict[str, str]]:
        """Plan and persist a DAG from context containing request and graph."""
        request = context.get("request")
        graph = context.get("graph")
        if not isinstance(request, str) or not isinstance(graph, Graph):
            raise ValueError("Planner context requires a request string and FalkorDB graph")
        return self.plan(request, graph)
