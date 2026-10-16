from app import schema
from redis.exceptions import ResponseError


def test_init_project_selects_graph_and_creates_required_indexes(
    monkeypatch,
) -> None:
    class FakeGraph:
        def __init__(self) -> None:
            self.queries: list[tuple[str, dict[str, object] | None]] = []

        def query(
            self, query: str, params: dict[str, object] | None = None
        ) -> None:
            self.queries.append((query, params))

    graph = FakeGraph()
    selected: list[str] = []

    def fake_get_graph(project_id: str) -> FakeGraph:
        selected.append(project_id)
        return graph

    monkeypatch.setattr(schema, "get_graph", fake_get_graph)

    result = schema.init_project("tenant_a")

    assert result is graph
    assert selected == ["tenant_a"]
    assert [query for query, _ in graph.queries] == [
        schema.queries.create_task_id_index(),
        schema.queries.create_artifact_id_index(),
        schema.queries.create_bug_id_index(),
    ]


def test_init_project_ignores_already_indexed_errors(monkeypatch) -> None:
    class ExistingIndexesGraph:
        def query(self, query: str) -> None:
            raise ResponseError("Attribute 'id' is already indexed")

    monkeypatch.setattr(schema, "get_graph", lambda project_id: ExistingIndexesGraph())

    assert isinstance(schema.init_project("tenant_a"), ExistingIndexesGraph)


def test_init_project_reraises_other_response_errors(monkeypatch) -> None:
    error = ResponseError("Unable to create index")

    class FailingGraph:
        def query(self, query: str) -> None:
            raise error

    monkeypatch.setattr(schema, "get_graph", lambda project_id: FailingGraph())

    try:
        schema.init_project("tenant_a")
    except ResponseError as raised:
        assert raised is error
    else:
        raise AssertionError("Expected a non-duplicate index error to be re-raised")


def test_schema_constants_list_model_labels_and_edges() -> None:
    assert schema.NODE_LABELS == (
        "Project",
        "Task",
        "Agent",
        "Skill",
        "Artifact",
        "Bug",
        "Vulnerability",
        "Episode",
        "Lesson",
        "Approval",
        "Review",
    )
    assert schema.EDGE_TYPES == (
        "DEPENDS_ON",
        "NEEDS",
        "HAS_SKILL",
        "PRODUCED_BY",
        "FOR_TASK",
        "HANDED_OFF_TO",
        "FOUND_IN",
        "FIXED_BY",
        "BLOCKS",
        "APPROVES",
        "REVIEWS",
        "DERIVED_FROM",
        "PART_OF",
    )
