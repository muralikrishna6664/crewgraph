"""Run independent mock CrewGraph projects in parallel against local FalkorDB."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
from time import perf_counter
from uuid import uuid4

from agents.planner import Planner
from app import queries
from app.orchestrator import run_project
from app.schema import init_project

REQUEST = "build a to-do app with a REST API and a simple web page"


def run_one_project(project_id: str) -> dict[str, object]:
    """Run one isolated mock project and remove its temporary graph."""
    graph = None
    try:
        graph = init_project(project_id)
        queries.create_project(graph, project_id)
        tasks = Planner().plan(REQUEST, graph)
        queries.link_tasks_to_project(
            graph, project_id, [task["id"] for task in tasks]
        )
        statuses = run_project(graph, step_delay_ms=0)
        return {
            "project_id": project_id,
            "tasks": len(tasks),
            "failures": sum(
                task.properties.get("status") != "done" for task in statuses
            ),
            "lease_recovery": any(
                task.properties.get("failure_reason") == "Recovered expired lease"
                for task in statuses
            ),
            "error": "",
        }
    finally:
        if graph is not None:
            graph.delete()
            graph.client.close()


def main() -> None:
    """Run the requested number of mock projects and report throughput."""
    parser = argparse.ArgumentParser(description="Load test local CrewGraph projects.")
    parser.add_argument("--projects", type=int, default=20)
    parser.add_argument("--workers", type=int)
    args = parser.parse_args()
    if args.projects < 1 or (args.workers is not None and args.workers < 1):
        parser.error("projects and workers must be positive integers")

    prior_provider = os.environ.get("LLM_PROVIDER")
    prior_flaw = os.environ.get("DEMO_FLAW")
    os.environ["LLM_PROVIDER"] = "mock"
    os.environ["DEMO_FLAW"] = "0"
    run_id = uuid4().hex[:10]
    project_ids = [f"load_{run_id}_{index:03d}" for index in range(args.projects)]
    results: list[dict[str, object]] = []
    start = perf_counter()
    try:
        with ThreadPoolExecutor(max_workers=args.workers or args.projects) as executor:
            futures = {
                executor.submit(run_one_project, project_id): project_id
                for project_id in project_ids
            }
            for future in as_completed(futures):
                project_id = futures[future]
                try:
                    results.append(future.result())
                except Exception as error:
                    results.append(
                        {
                            "project_id": project_id,
                            "tasks": 0,
                            "failures": 1,
                            "lease_recovery": False,
                            "error": f"{type(error).__name__}: {error}",
                        }
                    )
    finally:
        if prior_provider is None:
            os.environ.pop("LLM_PROVIDER", None)
        else:
            os.environ["LLM_PROVIDER"] = prior_provider
        if prior_flaw is None:
            os.environ.pop("DEMO_FLAW", None)
        else:
            os.environ["DEMO_FLAW"] = prior_flaw

    elapsed = perf_counter() - start
    total_tasks = sum(int(result["tasks"]) for result in results)
    failures = sum(int(result["failures"]) for result in results)
    recovery_happened = any(bool(result["lease_recovery"]) for result in results)
    print(f"Projects: {len(project_ids)}")
    print(f"Tasks: {total_tasks}")
    print(f"Total time: {elapsed:.2f} seconds")
    print(f"Tasks per second: {total_tasks / elapsed:.2f}")
    print(f"Failures: {failures}")
    print(f"Lease recovery happened: {'yes' if recovery_happened else 'no'}")
    for result in results:
        if result["error"]:
            print(f"{result['project_id']}: {result['error']}")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
