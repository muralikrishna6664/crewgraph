"""Plan and run the synthetic to-do application demo."""

import argparse
import os
from uuid import uuid4

from agents.planner import Planner
from app import queries
from app.orchestrator import run_project
from app.schema import init_project

REQUEST = "build a to-do app with a REST API and a simple web page"


def main() -> None:
    """Create a mock plan, run it, and print task statuses and discovered bugs."""
    parser = argparse.ArgumentParser(description="Run the synthetic to-do app demo.")
    parser.add_argument(
        "--flaw",
        action="store_true",
        help="make the mock backend accept an empty to-do title",
    )
    parser.add_argument(
        "--auto-approve",
        action="store_true",
        help="approve the project and run the gated release task",
    )
    args = parser.parse_args()
    os.environ["LLM_PROVIDER"] = "mock"
    if args.flaw:
        os.environ["DEMO_FLAW"] = "1"
    else:
        os.environ.setdefault("DEMO_FLAW", "0")
    project_id = f"todo_demo_{uuid4().hex[:8]}"
    graph = init_project(project_id)
    queries.create_project(graph, project_id)
    tasks = Planner().plan(REQUEST, graph)
    queries.link_tasks_to_project(
        graph, project_id, [task["id"] for task in tasks]
    )

    print(f"Running demo project {project_id} in mock mode.")
    statuses = run_project(graph)
    if args.auto_approve:
        queries.approve_project(graph, project_id)
        statuses = run_project(graph)
    else:
        gate = queries.release_status(graph, project_id)
        if not gate["can_release"]:
            print("Waiting for approval.")
            for reason in gate["reasons"]:
                print(f"- {reason}")
    for task in statuses:
        print(f"{task.properties['id']}: {task.properties['status']}")
    bugs = queries.open_bugs(graph)
    print(f"Open bugs: {len(bugs)}")
    for bug in bugs:
        print(
            f"- {bug['bug'].get('title')} "
            f"(severity: {bug['bug'].get('severity')}, "
            f"artifact: {bug['artifact'].get('path')})"
        )


if __name__ == "__main__":
    main()
