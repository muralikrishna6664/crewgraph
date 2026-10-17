from app import db
import pytest


def test_get_graph_selects_project_graph(monkeypatch: pytest.MonkeyPatch) -> None:
    selected: list[str] = []

    class FakeFalkorDB:
        def __init__(self, host: str) -> None:
            assert host == "localhost"

        def select_graph(self, graph_id: str) -> str:
            selected.append(graph_id)
            return graph_id

    monkeypatch.setattr(db, "FalkorDB", FakeFalkorDB)

    assert db.get_graph("demo-project") == "demo-project"
    assert selected == ["demo-project"]


def test_get_graph_uses_configured_falkordb_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hosts: list[str] = []

    class FakeFalkorDB:
        def __init__(self, host: str) -> None:
            hosts.append(host)

        def select_graph(self, graph_id: str) -> str:
            return graph_id

    monkeypatch.setenv("FALKORDB_HOST", "falkordb")
    monkeypatch.setattr(db, "FalkorDB", FakeFalkorDB)

    assert db.get_graph("demo-project") == "demo-project"
    assert hosts == ["falkordb"]
