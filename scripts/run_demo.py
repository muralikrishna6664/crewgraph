"""Plan and run the synthetic to-do application demo."""

import os

from agents.planner import Planner
from app import queries
from app.orchestrator import run_project
from app.schema import init_project

REQUEST = "build a to-do app with a REST API and a simple web page"
PROJECT_ID = "todo_demo"


def main() -> None:
    """Create a mock plan, run all eligible tasks, and print final task statuses."""
    os.environ["LLM_PROVIDER"] = "mock"
    graph = init_project(PROJECT_ID)
    queries.create_project(graph, PROJECT_ID)
    tasks = Planner().plan(REQUEST, graph)
    queries.link_tasks_to_project(
        graph, PROJECT_ID, [task["id"] for task in tasks]
    )

    print(f"Running demo project {PROJECT_ID} in mock mode.")
    statuses = run_project(graph)
    for task in statuses:
        print(f"{task.properties['id']}: {task.properties['status']}")


if __name__ == "__main__":
    main()
