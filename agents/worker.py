"""Run one claimed task and save its generated file artifacts."""

import json
from pathlib import Path, PureWindowsPath

from falkordb.graph import Graph
from falkordb.node import Node

from agents.runner import Agent
from app import queries

WORKSPACE_ROOT = Path(__file__).resolve().parents[1] / "workspace"


def _task_node(task: Node | dict[str, object]) -> dict[str, object]:
    """Return task properties from a FalkorDB node or property mapping."""
    return task.properties if isinstance(task, Node) else task


def _workspace_path(project_id: str, relative_path: str) -> Path:
    """Resolve a generated path while keeping it inside the project workspace."""
    if (
        not project_id
        or Path(project_id).name != project_id
        or Path(project_id).is_absolute()
        or PureWindowsPath(project_id).is_absolute()
    ):
        raise ValueError("Project ID must be a single safe path component")
    candidate_path = Path(relative_path)
    if (
        not relative_path
        or candidate_path.is_absolute()
        or PureWindowsPath(relative_path).is_absolute()
        or ".." in candidate_path.parts
        or ".." in PureWindowsPath(relative_path).parts
    ):
        raise ValueError(f"Generated file path is not relative and safe: {relative_path}")

    project_root = (WORKSPACE_ROOT / project_id).resolve()
    destination = (project_root / candidate_path).resolve()
    if not destination.is_relative_to(project_root):
        raise ValueError(f"Generated file path escapes project workspace: {relative_path}")
    return destination


def run_task(graph: Graph, agent: Agent, task: Node | dict[str, object]) -> list[str]:
    """Generate task files from graph context, record artifacts, and complete it."""
    properties = _task_node(task)
    task_id = properties.get("id")
    skill = properties.get("skill")
    if not isinstance(task_id, str) or not isinstance(skill, str):
        raise ValueError("Task must have string id and skill properties")
    if skill not in agent.skills:
        raise ValueError(f"Agent {agent.name} does not have the {skill} skill")

    context = queries.handoff_context(graph, task_id)
    if context is None:
        raise ValueError(f"Task not found: {task_id}")
    if skill == "frontend" and not any(
        artifact.get("kind") == "api_contract" and artifact.get("content")
        for artifact in context["artifacts"]
    ):
        raise ValueError(f"Task {task_id} has no API contract artifact in its context")

    response = agent.run({"task": properties, "handoff_context": context})
    try:
        payload = json.loads(response.text)
    except json.JSONDecodeError as error:
        raise ValueError(f"Agent {agent.name} returned invalid JSON") from error
    files = payload.get("files") if isinstance(payload, dict) else None
    if not isinstance(files, dict) or not files:
        raise ValueError(f"Agent {agent.name} returned no files")

    project_id = graph.name
    recorded_paths: list[str] = []
    for relative_path, content in files.items():
        if not isinstance(relative_path, str) or not isinstance(content, str):
            raise ValueError("Generated files must map relative path strings to content strings")
        destination = _workspace_path(project_id, relative_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
        kind = "api_contract" if Path(relative_path).name == "API_CONTRACT.md" else skill
        queries.record_artifact(
            graph,
            task_id,
            agent.name,
            relative_path,
            kind,
            content,
        )
        recorded_paths.append(relative_path)

    if queries.complete_task(graph, task_id) is None:
        raise ValueError(f"Could not complete task: {task_id}")
    return recorded_paths
