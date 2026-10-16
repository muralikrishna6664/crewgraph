"""Claim and execute ready project tasks in parallel."""

from concurrent.futures import ThreadPoolExecutor

from falkordb import FalkorDB
from falkordb.graph import Graph
from falkordb.node import Node

from agents.backend import BackendAgent
from agents.frontend import FrontendAgent
from agents.runner import Agent
from agents.worker import run_task
from app import queries


def _run_with_own_graph(
    project_id: str, agent: Agent, task: Node
) -> list[str]:
    """Run a task using a separate FalkorDB client connection."""
    client = FalkorDB()
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
        Agent(
            name="tester",
            role="Write tests for the project",
            skills=["tester"],
            system_prompt=(
                "Generate task files. Create concise tests for the task using "
                "dependency artifacts in handoff_context. Return JSON with a files "
                "object mapping safe relative paths to complete file contents."
            ),
        ),
    ]
    agents_by_skill = {
        skill: agent for agent in available_agents for skill in agent.skills
    }

    while True:
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

    return queries.project_task_statuses(graph)
