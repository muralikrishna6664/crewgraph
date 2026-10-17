"""Claim and execute ready project tasks in parallel."""

from concurrent.futures import ThreadPoolExecutor
import time

from falkordb.graph import Graph
from falkordb.node import Node

from agents.backend import BackendAgent
from agents.debugger import DebuggerAgent
from agents.frontend import FrontendAgent
from agents.runner import Agent
from agents.security import SecurityAgent
from agents.tester import TesterAgent
from agents.worker import run_task
from app import queries
from app.db import get_client


def _run_with_own_graph(
    project_id: str, agent: Agent, task: Node
) -> list[str]:
    """Run a task using a separate FalkorDB client connection."""
    client = get_client()
    try:
        return run_task(client.select_graph(project_id), agent, task)
    finally:
        client.close()


def run_project(
    graph: Graph, agents: list[Agent] | None = None, lease_seconds: int = 300
) -> list[Node]:
    """Run matching ready tasks until work is complete or no progress is possible."""
    available_agents = agents or [
        BackendAgent(),
        FrontendAgent(),
        TesterAgent(),
        SecurityAgent(),
    ]
    agents_by_skill = {
        skill: agent for agent in available_agents for skill in agent.skills
    }
    debugger = DebuggerAgent()

    while True:
        queries.recover_expired_leases(graph, int(time.time() * 1000))
        claims: list[tuple[Agent, Node]] = []
        for task in queries.ready_tasks(graph):
            skill = task.properties.get("skill")
            agent = agents_by_skill.get(skill)
            if agent is None:
                continue
            claimed_task = queries.claim_task(
                graph,
                task.properties["id"],
                agent.name,
                lease_seconds,
            )
            if claimed_task is not None:
                claims.append((agent, claimed_task))

        if not claims:
            break

        with ThreadPoolExecutor(max_workers=len(claims)) as executor:
            futures = [
                executor.submit(
                    _run_with_own_graph, graph.name, agent, task
                )
                for agent, task in claims
            ]
            for future in futures:
                future.result()

        if agents_by_skill:
            for _, task in claims:
                task_id = task.properties.get("id")
                task_skill = task.properties.get("skill")
                if not isinstance(task_id, str):
                    continue
                current_task = queries.get_task(graph, task_id)
                if (
                    current_task is None
                    or current_task.properties.get("status") != "failed"
                    or current_task.properties.get("skill")
                    not in ("tester", "security")
                ):
                    continue
                repair_agent = agents_by_skill.get(task_skill)
                if repair_agent is None:
                    continue

                for _ in range(2):
                    fixed_bug_ids = debugger.repair_open_bugs(graph)
                    if not fixed_bug_ids:
                        break
                    queries.prepare_task_retry(graph, task_id)
                    claimed_task = queries.claim_task(
                        graph, task_id, repair_agent.name, lease_seconds
                    )
                    if claimed_task is None:
                        raise RuntimeError(f"Could not re-claim repaired task: {task_id}")
                    _run_with_own_graph(graph.name, repair_agent, claimed_task)
                    current_task = queries.get_task(graph, task_id)
                    if (
                        current_task is not None
                        and current_task.properties.get("status") == "done"
                    ):
                        queries.mark_bugs_fixed(graph, fixed_bug_ids)
                        break

    if queries.can_release(graph, graph.name):
        release_task = queries.create_release_task(graph, graph.name)
        queries.complete_task(graph, release_task.properties["id"])

    return queries.project_task_statuses(graph)
