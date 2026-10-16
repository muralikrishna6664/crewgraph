"""Seed two isolated project graphs with synthetic task data."""

from app import queries
from app.schema import init_project
from falkordb.node import Node

PROJECT_SEEDS = {
    "tenant_a": [
        {
            "id": "tenant_a-task-001",
            "title": "Create the demo landing page",
            "status": "pending",
            "skill": "frontend",
            "ts": "2026-10-15T00:00:00Z",
        },
        {
            "id": "tenant_a-task-002",
            "title": "Add a health check API",
            "status": "pending",
            "skill": "backend",
            "ts": "2026-10-15T00:00:00Z",
        },
        {
            "id": "tenant_a-task-003",
            "title": "Write API smoke tests",
            "status": "pending",
            "skill": "testing",
            "ts": "2026-10-15T00:00:00Z",
        },
    ],
    "tenant_b": [
        {
            "id": "tenant_b-task-001",
            "title": "Build a notes list view",
            "status": "pending",
            "skill": "frontend",
            "ts": "2026-10-15T00:00:00Z",
        },
        {
            "id": "tenant_b-task-002",
            "title": "Create a notes API",
            "status": "pending",
            "skill": "backend",
            "ts": "2026-10-15T00:00:00Z",
        },
        {
            "id": "tenant_b-task-003",
            "title": "Review notes API input handling",
            "status": "pending",
            "skill": "security",
            "ts": "2026-10-15T00:00:00Z",
        },
    ],
}


def seed_project(project_id: str, tasks: list[dict[str, str]]) -> list[Node]:
    """Initialize and populate one project's graph with its synthetic tasks."""
    graph = init_project(project_id)
    dependencies = [
        {"task_id": task["id"], "depends_on": prerequisite["id"]}
        for prerequisite, task in zip(tasks, tasks[1:])
    ]
    queries.create_project(graph, project_id)
    queries.create_task_dag(graph, tasks, dependencies)
    queries.link_tasks_to_project(
        graph, project_id, [task["id"] for task in tasks]
    )
    return queries.ready_tasks(graph)


def main() -> None:
    """Seed the tenant_a and tenant_b graphs."""
    ready_by_project: list[tuple[str, list[Node]]] = []
    for project_id, tasks in PROJECT_SEEDS.items():
        ready_by_project.append((project_id, seed_project(project_id, tasks)))
        print(f"Seeded {project_id} with {len(tasks)} tasks.")
    for project_id, tasks in ready_by_project:
        print(f"Ready tasks for {project_id}:")
        for task in tasks:
            print(f"- {task.properties['id']}: {task.properties.get('title', '')}")


if __name__ == "__main__":
    main()
