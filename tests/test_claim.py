from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from falkordb import FalkorDB
from falkordb.node import Node

from app.queries import claim_task, complete_task, create_task_dag, ready_tasks


def test_concurrent_claim_is_won_once_and_dag_advances() -> None:
    graph_name = f"test_claim_{uuid4().hex}"
    graph = FalkorDB().select_graph(graph_name)
    tasks = [
        {"id": "task-1", "title": "First task"},
        {"id": "task-2", "title": "Second task"},
        {"id": "task-3", "title": "Third task"},
    ]
    dependencies = [
        {"task_id": "task-2", "depends_on": "task-1"},
        {"task_id": "task-3", "depends_on": "task-2"},
    ]

    try:
        create_task_dag(graph, tasks, dependencies)
        create_task_dag(graph, tasks, dependencies)
        assert {
            task.properties["id"] for task in ready_tasks(graph)
        } == {"task-1"}

        barrier = Barrier(20)

        def attempt_claim(index: int) -> Node | None:
            worker_graph = FalkorDB().select_graph(graph_name)
            barrier.wait(timeout=10)
            return claim_task(worker_graph, "task-1", f"agent-{index}", 60)

        with ThreadPoolExecutor(max_workers=20) as executor:
            claims = list(executor.map(attempt_claim, range(20)))

        winners = [claim for claim in claims if claim is not None]
        assert len(winners) == 1
        assert winners[0].properties["status"] == "claimed"
        assert winners[0].properties["claimed_by"].startswith("agent-")
        assert winners[0].properties["lease_until"] > 0

        completed = complete_task(graph, "task-1")
        assert completed is not None
        assert completed.properties["status"] == "done"
        assert {
            task.properties["id"] for task in ready_tasks(graph)
        } == {"task-2"}

        assert claim_task(graph, "task-2", "agent-next", 60) is not None
        complete_task(graph, "task-2")
        assert {
            task.properties["id"] for task in ready_tasks(graph)
        } == {"task-3"}
    finally:
        graph.delete()
