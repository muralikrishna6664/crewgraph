from scripts import cleanup_graphs


class FakeGraph:
    def __init__(self) -> None:
        self.deleted = False

    def delete(self) -> None:
        self.deleted = True


class FakeClient:
    def __init__(self) -> None:
        self.graphs = {
            "keep-me": FakeGraph(),
            "remove-me": FakeGraph(),
        }
        self.closed = False

    def list_graphs(self) -> list[str]:
        return list(self.graphs)

    def select_graph(self, name: str) -> FakeGraph:
        return self.graphs[name]

    def close(self) -> None:
        self.closed = True


def test_cleanup_graphs_defaults_to_dry_run_and_preserves_keep_list(
    monkeypatch, capsys
) -> None:
    client = FakeClient()
    monkeypatch.setattr(cleanup_graphs, "FalkorDB", lambda: client)

    targets = cleanup_graphs.cleanup_graphs({"keep-me"}, yes=False)

    assert targets == ["remove-me"]
    assert not client.graphs["keep-me"].deleted
    assert not client.graphs["remove-me"].deleted
    assert client.closed
    assert "Would delete: remove-me" in capsys.readouterr().out


def test_cleanup_graphs_deletes_only_outside_keep_list_when_confirmed(
    monkeypatch, capsys
) -> None:
    client = FakeClient()
    monkeypatch.setattr(cleanup_graphs, "FalkorDB", lambda: client)

    targets = cleanup_graphs.cleanup_graphs({"keep-me"}, yes=True)

    assert targets == ["remove-me"]
    assert not client.graphs["keep-me"].deleted
    assert client.graphs["remove-me"].deleted
    assert client.closed
    assert "Deleted: remove-me" in capsys.readouterr().out


def test_cleanup_graphs_rejects_unknown_keep_names_without_deleting(
    monkeypatch,
) -> None:
    client = FakeClient()
    monkeypatch.setattr(cleanup_graphs, "FalkorDB", lambda: client)

    try:
        cleanup_graphs.cleanup_graphs({"typo"}, yes=True)
    except ValueError as error:
        assert "unknown graphs: typo" in str(error)
    else:
        raise AssertionError("Unknown keep-list names should stop deletion")

    assert all(not graph.deleted for graph in client.graphs.values())
    assert client.closed
