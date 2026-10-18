from threading import Event
from uuid import uuid4

from fastapi.testclient import TestClient
from falkordb import FalkorDB
from redis.exceptions import ResponseError

from app import queries
from app.auth import auth_enabled, verify_session_token
from app.main import app
import app.main as main


def _delete_graph(graph) -> None:
    """Delete a test graph and ignore FalkorDB's empty-key response."""
    try:
        graph.delete()
    except ResponseError as error:
        if "Invalid graph operation on empty key" not in str(error):
            raise


def test_auth_is_disabled_when_not_enabled_explicitly(monkeypatch) -> None:
    monkeypatch.delenv("AUTH_ENABLED", raising=False)

    assert auth_enabled() is False


def test_missing_invalid_and_valid_demo_sessions(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("SECRET_KEY", "test-session-signing-key")
    client = TestClient(app)
    redirect_client = TestClient(app, follow_redirects=False)

    assert client.get("/projects").status_code == 401
    invalid_client = TestClient(app)
    invalid_client.headers["Authorization"] = "Bearer invalid-token"
    assert invalid_client.get("/projects").status_code == 401
    assert redirect_client.get("/").status_code == 303
    assert client.get("/login").status_code == 200

    rejected = client.post(
        "/auth/login", json={"username": "acme", "password": "incorrect"}
    )
    assert rejected.status_code == 401
    login = client.post(
        "/auth/login", json={"username": "acme", "password": "acme-demo-2026!"}
    )
    assert login.status_code == 200
    result = login.json()
    assert result["tenant"] == "acme"
    session = verify_session_token(result["token"])
    assert session is not None
    assert session.username == "acme"
    assert session.tenant == "acme"
    assert client.get("/").status_code == 200

    logout = client.post("/auth/logout")
    assert logout.status_code == 200
    assert client.get("/projects").status_code == 401


def test_tenant_cannot_list_read_or_approve_another_tenant_project(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("SECRET_KEY", "tenant-test-signing-key")
    suffix = uuid4().hex
    acme_id = f"acme_project_{suffix}"
    globex_id = f"globex_project_{suffix}"
    acme_graph = FalkorDB().select_graph(acme_id)
    globex_graph = FalkorDB().select_graph(globex_id)
    client = TestClient(app)

    try:
        queries.create_project(acme_graph, acme_id)
        queries.create_project(globex_graph, globex_id)
        login = client.post(
            "/auth/login", json={"username": "acme", "password": "acme-demo-2026!"}
        )
        assert login.status_code == 200

        projects = client.get("/projects")
        assert projects.status_code == 200
        assert acme_id in projects.json()
        assert globex_id not in projects.json()
        assert client.get(f"/projects/{acme_id}/graph").status_code == 200

        foreign_endpoints = [
            ("GET", f"/projects/{globex_id}/graph"),
            ("GET", f"/projects/{globex_id}/events"),
            ("GET", f"/projects/{globex_id}/artifacts"),
            ("GET", f"/projects/{globex_id}/artifacts/secret"),
            ("GET", f"/projects/{globex_id}/tasks/missing/context"),
            ("GET", f"/projects/{globex_id}/release-status"),
            ("POST", f"/projects/{globex_id}/approve"),
            ("GET", f"/demo/runs/{globex_id}"),
        ]
        for method, path in foreign_endpoints:
            response = client.request(method, path)
            assert response.status_code == 404, (method, path, response.text)
    finally:
        _delete_graph(acme_graph)
        _delete_graph(globex_graph)


def test_authenticated_demo_graph_name_is_prefixed_with_tenant(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("SECRET_KEY", "tenant-run-signing-key")
    prepared = Event()
    started = Event()

    def fake_prepare(project_id: str, prompt: str, flaw: bool) -> None:
        prepared.set()

    def fake_run(project_id: str, flaw: bool) -> None:
        started.set()

    monkeypatch.setattr(main, "_prepare_demo", fake_prepare)
    monkeypatch.setattr(main, "_run_demo", fake_run)
    client = TestClient(app)
    login = client.post(
        "/auth/login", json={"username": "acme", "password": "acme-demo-2026!"}
    )
    assert login.status_code == 200

    response = client.post("/demo/run", json={"prompt": "Build a demo"})

    assert response.status_code == 202
    project_id = response.json()["project_id"]
    assert project_id.startswith("acme_dashboard_demo_")
    assert prepared.wait(timeout=1)
    assert started.wait(timeout=1)
    with main._demo_runs_lock:
        main._demo_runs.pop(project_id, None)
