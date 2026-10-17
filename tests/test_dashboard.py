from threading import Event

from fastapi.testclient import TestClient

import app.main as main


def test_dashboard_root_serves_single_page() -> None:
    response = TestClient(main.app).get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "cytoscape@3.30.4" in response.text
    assert "Run demo with flaw" in response.text
    assert 'name: "breadthfirst", directed: true' in response.text
    assert 'direction: "TB"' in response.text
    assert 'width: 40, height: 40' in response.text
    assert '"text-wrap": "wrap", "text-max-width": 120, "font-size": 12' in response.text
    assert 'label: ""' in response.text
    assert 'selector: "edge.edge-visible"' in response.text
    assert "nodeIdsKey !== lastNodeIds" in response.text
    assert 'cy.fit(cy.elements(), 28)' in response.text
    assert 'id="legend"' in response.text
    assert 'release.reasons[0] === "Human approval is required"' in response.text
    assert 'banner.textContent = "Human approval is required"' in response.text
    assert 'banner.textContent = "Released."' in response.text


def test_demo_endpoint_starts_a_background_run(monkeypatch) -> None:
    started = Event()
    captured: dict[str, object] = {}

    def fake_prepare(project_id: str, flaw: bool) -> None:
        captured["prepared"] = (project_id, flaw)

    def fake_run(project_id: str, flaw: bool) -> None:
        captured["project_id"] = project_id
        captured["flaw"] = flaw
        started.set()

    monkeypatch.setattr(main, "_prepare_demo", fake_prepare)
    monkeypatch.setattr(main, "_run_demo", fake_run)

    response = TestClient(main.app).post("/demo/run", json={"flaw": True})

    assert response.status_code == 202
    assert response.json()["status"] == "started"
    assert started.wait(timeout=2)
    assert captured["project_id"] == response.json()["project_id"]
    assert captured["flaw"] is True
    assert captured["prepared"] == (response.json()["project_id"], True)
