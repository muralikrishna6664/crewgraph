from scripts import seed


def test_seed_project_merges_project_task_and_dependency_relationships(
    monkeypatch,
) -> None:
    class FakeGraph:
        def __init__(self) -> None:
            self.queries: list[tuple[str, dict[str, object]]] = []
            self.read_queries: list[str] = []

        def query(self, query: str, params: dict[str, object]) -> None:
            self.queries.append((query, params))

        def ro_query(self, query: str) -> object:
            self.read_queries.append(query)

            class Result:
                result_set = []

            return Result()

    graph = FakeGraph()
    monkeypatch.setattr(seed, "init_project", lambda project_id: graph)

    tasks = seed.PROJECT_SEEDS["tenant_a"]
    assert seed.seed_project("tenant_a", tasks) == []

    project_query, project_params = graph.queries[0]
    task_query, task_params = graph.queries[1]
    dependency_query, dependency_params = graph.queries[2]
    link_query, link_params = graph.queries[3]
    assert "MERGE (project:Project {id: $project_id})" in project_query
    assert "MERGE (task:Task {id: data.id})" in task_query
    assert "MERGE (task)-[:DEPENDS_ON]->(prerequisite)" in dependency_query
    assert "MERGE (task)-[:PART_OF]->(project)" in link_query
    assert project_params["project_id"] == "tenant_a"
    assert task_params["tasks"][0]["status"] == "ready"
    assert task_params["tasks"][1]["status"] == "pending"
    assert dependency_params["deps"] == [
        {"task_id": "tenant_a-task-002", "depends_on": "tenant_a-task-001"},
        {"task_id": "tenant_a-task-003", "depends_on": "tenant_a-task-002"},
    ]
    assert link_params["task_ids"] == [task["id"] for task in tasks]
    assert graph.read_queries


def test_seed_creates_a_graph_for_each_project(monkeypatch, capsys) -> None:
    seeded: list[tuple[str, list[dict[str, str]]]] = []

    def fake_seed_project(
        project_id: str, tasks: list[dict[str, str]]
    ) -> list[object]:
        seeded.append((project_id, tasks))
        return []

    monkeypatch.setattr(seed, "seed_project", fake_seed_project)

    seed.main()

    assert [project_id for project_id, _ in seeded] == ["tenant_a", "tenant_b"]
    assert "Ready tasks for tenant_a:" in capsys.readouterr().out
    assert all(len(tasks) == 3 for _, tasks in seeded)
    assert all(
        task["id"].startswith(f"{project_id}-")
        for project_id, tasks in seeded
        for task in tasks
    )
