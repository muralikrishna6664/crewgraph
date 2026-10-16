from app import db
import pytest


def test_get_graph_selects_project_graph(monkeypatch: pytest.MonkeyPatch) -> None:
    selected: list[str] = []

    class FakeFalkorDB:
        def select_graph(self, graph_id: str) -> str:
            selected.append(graph_id)
            return graph_id

    monkeypatch.setattr(db, "FalkorDB", FakeFalkorDB)

    assert db.get_graph("demo-project") == "demo-project"
    assert selected == ["demo-project"]
