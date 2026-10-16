"""Repair open bugs by generating and recording fixed file versions."""

import json

from falkordb.graph import Graph

from agents.runner import Agent
from agents.worker import _workspace_path
from app import queries


class DebuggerAgent(Agent):
    """Ask the configured model for fixes to files linked to open bugs."""

    def __init__(self) -> None:
        super().__init__(
            name="debugger",
            role="Repair files responsible for open bugs",
            skills=["debugger"],
            system_prompt=(
                "Repair generated file. Use the bug, the linked artifact, and "
                "handoff_context to produce a corrected complete file. Return JSON "
                "with a files object mapping file paths to complete file contents."
            ),
        )

    def repair_open_bugs(self, graph: Graph) -> list[str]:
        """Repair each open bug and return the bug IDs with linked fix artifacts."""
        fixed_bug_ids: list[str] = []
        for entry in queries.open_bugs(graph):
            bug = entry["bug"]
            source_artifact = entry["artifact"]
            task_id = source_artifact.get("task_id")
            path = source_artifact.get("path")
            bug_id = bug.get("id")
            if not all(isinstance(value, str) for value in (task_id, path, bug_id)):
                raise ValueError("Open bug artifact is missing task_id, path, or bug id")

            context = queries.handoff_context(graph, task_id)
            if context is None:
                raise ValueError(f"Bug source task not found: {task_id}")
            linked_artifact = next(
                (
                    artifact
                    for artifact in context["artifacts"]
                    if artifact.get("id") == source_artifact.get("id")
                ),
                None,
            )
            if linked_artifact is None:
                raise ValueError(f"Bug source artifact not found in task context: {path}")

            response = self.run(
                {
                    "bug": bug,
                    "artifact": linked_artifact,
                    "handoff_context": context,
                }
            )
            try:
                payload = json.loads(response.text)
            except json.JSONDecodeError as error:
                raise ValueError("Debugger returned invalid JSON") from error
            files = payload.get("files") if isinstance(payload, dict) else None
            if not isinstance(files, dict) or path not in files:
                raise ValueError(f"Debugger did not return a fix for {path}")
            content = files[path]
            if not isinstance(content, str):
                raise ValueError(f"Debugger returned invalid content for {path}")

            destination = _workspace_path(graph.name, path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8")
            repaired_artifact = queries.record_artifact(
                graph,
                task_id,
                self.name,
                path,
                source_artifact.get("kind", "backend"),
                content,
                artifact_id=f"{task_id}:{path}:repair:{bug_id}",
            )
            queries.link_artifact_fixes_bug(
                graph, repaired_artifact.properties["id"], bug_id
            )
            fixed_bug_ids.append(bug_id)
        return fixed_bug_ids
