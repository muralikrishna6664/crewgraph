from threading import Event

from fastapi.testclient import TestClient

import app.main as main


def test_dashboard_root_serves_single_page() -> None:
    response = TestClient(main.app).get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "cytoscape@3.30.4" in response.text
    assert "Run demo with flaw" in response.text


def test_demo_endpoint_starts_a_background_run(monkeypatch) -> None:
    started = Event()
    captured: dict[str, object] = {}

    def fake_run(project_id: str, flaw: bool) -> None:
        captured["project_id"] = project_id
        captured["flaw"] = flaw
        started.set()

    monkeypatch.setattr(main, "_run_demo", fake_run)

    response = TestClient(main.app).post("/demo/run", json={"flaw": True})

    assert response.status_code == 202
    assert response.json()["status"] == "started"
    assert started.wait(timeout=2)
    assert captured["project_id"] == response.json()["project_id"]
    assert captured["flaw"] is True
