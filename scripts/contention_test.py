"""Measure concurrent task claims and handoff-context reads on one local graph."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from math import ceil
from threading import Barrier, Semaphore
from time import perf_counter
from uuid import uuid4

from falkordb import FalkorDB

from app import queries
from app.schema import init_project

MAX_IN_FLIGHT_QUERIES = 8
_query_slots = Semaphore(MAX_IN_FLIGHT_QUERIES)


def _worker(
    worker_id: int, graph_name: str, start_barrier: Barrier
) -> dict[str, object]:
    """Claim available tasks and read each winner's handoff context."""
    client = FalkorDB()
    graph = client.select_graph(graph_name)
    reads = 0
    writes = 0
    claims = 0
    latencies: list[float] = []
    winners: list[str] = []

    try:
        start_barrier.wait(timeout=30)
        while True:
            with _query_slots:
                ready = queries.ready_tasks(graph)
            reads += 1
            if not ready:
                break

            made_progress = False
            for task in ready:
                task_id = task.properties["id"]
                started = perf_counter()
                with _query_slots:
                    claimed = queries.claim_task(
                        graph,
                        task_id,
                        f"worker-{worker_id}",
                        lease_seconds=300,
                    )
                latencies.append(perf_counter() - started)
                writes += 1
                if claimed is None:
                    continue

                claims += 1
                writes += 1
                winners.append(task_id)
                with _query_slots:
                    context = queries.handoff_context(graph, task_id)
                reads += 1
                if context is None:
                    raise RuntimeError(f"Claimed task context missing: {task_id}")
                made_progress = True

            if not made_progress:
                break
    finally:
        client.close()

    return {
        "reads": reads,
        "writes": writes,
        "claims": claims,
        "latencies": latencies,
        "winners": winners,
    }


def run_contention_test(workers: int, task_count: int) -> dict[str, object]:
    """Run a shared-graph claim workload and remove its temporary graph."""
    graph_name = f"contention_{uuid4().hex}"
    graph = init_project(graph_name)
    try:
        queries.create_project(graph, graph_name)
        tasks = [
            {
                "id": f"{graph_name}:task:{index}",
                "title": f"Synthetic contention task {index}",
                "skill": "backend",
            }
            for index in range(task_count)
        ]
        queries.create_task_dag(graph, tasks, [])
        queries.link_tasks_to_project(
            graph, graph_name, [task["id"] for task in tasks]
        )

        barrier = Barrier(workers)
        start = perf_counter()
        with ThreadPoolExecutor(max_workers=workers) as executor:
            results = list(
                executor.map(
                    lambda worker_id: _worker(worker_id, graph_name, barrier),
                    range(workers),
                )
            )
        elapsed = perf_counter() - start

        winners: dict[str, int] = {}
        latencies: list[float] = []
        reads = 0
        writes = 0
        claims = 0
        for result in results:
            reads += int(result["reads"])
            writes += int(result["writes"])
            claims += int(result["claims"])
            latencies.extend(result["latencies"])
            for task_id in result["winners"]:
                winners[task_id] = winners.get(task_id, 0) + 1

        duplicates = sum(count - 1 for count in winners.values() if count > 1)
        sorted_latencies = sorted(latencies)
        p95 = (
            sorted_latencies[ceil(len(sorted_latencies) * 0.95) - 1]
            if sorted_latencies
            else 0.0
        )
        return {
            "workers": workers,
            "tasks": task_count,
            "max_in_flight_queries": MAX_IN_FLIGHT_QUERIES,
            "elapsed": elapsed,
            "claims": claims,
            "claims_per_second": claims / elapsed if elapsed else 0.0,
            "p95_ms": p95 * 1000,
            "duplicates": duplicates,
            "reads": reads,
            "writes": writes,
        }
    finally:
        graph.delete()
        graph.client.close()


def main() -> None:
    """Run and print the requested single-project contention benchmark."""
    parser = argparse.ArgumentParser(
        description="Benchmark concurrent task claims against local FalkorDB."
    )
    parser.add_argument("--workers", type=int, default=50)
    parser.add_argument("--tasks", type=int, default=500)
    args = parser.parse_args()
    if args.workers < 1 or args.tasks < 1:
        parser.error("workers and tasks must be positive integers")

    result = run_contention_test(args.workers, args.tasks)
    print(f"Workers: {result['workers']}")
    print(f"Tasks: {result['tasks']}")
    print(f"Max in-flight query actions: {result['max_in_flight_queries']}")
    print(f"Elapsed: {result['elapsed']:.2f} seconds")
    print(f"Claims per second: {result['claims_per_second']:.2f}")
    print(f"p95 claim-call latency: {result['p95_ms']:.2f} ms")
    print(f"Duplicate claims: {result['duplicates']}")
    print(f"Reads: {result['reads']}")
    print(f"Writes: {result['writes']}")
    print("Counts include ready/context reads and claim plus claim-event writes; setup excluded.")
    if result["duplicates"] or result["claims"] != result["tasks"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
