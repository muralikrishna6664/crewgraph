from threading import Event

from fastapi.testclient import TestClient

import app.main as main


def test_dashboard_serves_external_light_styles_and_script() -> None:
    client = TestClient(main.app)
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "cytoscape@3.30.4" in response.text
    assert '<link rel="stylesheet" href="/static/style.css">' in response.text
    assert '<script src="/static/app.js" defer></script>' in response.text
    script = client.get("/static/app.js").text
    styles = client.get("/static/style.css").text
    assert "<script>" not in response.text
    assert 'banner.textContent = "No projects yet. Click Run demo."' in script
    assert 'case "Approval": return `Approval (${properties.status || "pending"})`;' in script
    assert 'case "Project": return properties.name || "Project";' in script
    assert 'case "Lesson": return properties.title || properties.content || "Lesson";' in script
    assert 'case "Review":' in script
    assert 'done: "#55e69a", ready: "#f5bd4f", claimed: "#5b9dff"' in script
    assert 'new Date(timestamp).toLocaleTimeString()' in script
    assert 'content.title = String(value);' in script
    assert "Run demo with flaw" in response.text
    assert 'name: "preset"' in script
    assert "calculateGraphPositions(nodes, graph.edges)" in script
    assert 'window.addEventListener("resize"' in script
    assert '? request(`/demo/runs/${encodeURIComponent(projectId)}`)' in script
    assert 'width: 40, height: 40' in script
    assert '"text-wrap": "wrap", "text-max-width": 120, "font-size": 12' in script
    assert 'label: "data(title)"' in script
    assert 'case "Task": return properties.title || "Task";' in script
    assert "grid-template-columns: minmax(0, 1fr)" in styles
    assert "section, aside {" in styles
    assert "min-width: 0;" in styles
    assert "#graph { width: 100%; height: 100%; min-width: 0;" in styles
    assert 'case "Artifact": return properties.path || "Artifact";' in script
    assert 'case "Agent": return properties.name || "Agent";' in script
    assert 'case "Bug": return properties.title || "Bug";' in script
    assert "String(label).slice(0, 16)" in script
    assert 'label: ""' in script
    assert 'selector: "edge.edge-visible"' in script
    assert "nodeIdsKey !== lastNodeIds" in script
    assert 'cy.fit(cy.elements(), 28)' in script
    assert 'id="legend"' in response.text
    assert 'release.reasons[0] === "Human approval is required"' in script
    assert 'banner.textContent = "Human approval is required"' in script
    assert 'banner.textContent = "Released."' in script
    assert 'banner.textContent = "Running..."' in script
    assert "Run failed: ${run.message}" in script
    assert "banner.textContent = \"Starting...\"" in script
    assert "Date.now() - activeRunStartedAt < 5000" in script
    assert "consecutiveRefreshFailures >= 3" in script
    assert "consecutiveRefreshFailures = 0" in script
    assert "const projectRefreshVersion = ++projectsRefreshVersion" in script
    assert "if (projectRefreshVersion !== projectsRefreshVersion)" in script
    assert "preferred || picker.value || activeRunId" in script
    assert "projectNames.push(activeRunId)" in script
    assert "await refreshProjects(started.project_id)" in script
    assert "picker.value = started.project_id" in script
    assert "const previous = activeRunId || picker.value" in script
    assert "color-scheme: light" in styles
    assert "background: #fff;" in styles
    assert "label { color: #526277;" in styles
    assert ".login-card .login-kicker { color: #7046ad;" in styles
    assert "@media (prefers-reduced-motion: reduce)" in styles
    assert "function pulseWorkingNode(node)" in script
    assert "function animateFoundBug(bugId)" in script


def test_demo_endpoint_starts_a_background_run(monkeypatch) -> None:
    started = Event()
    captured: dict[str, object] = {}

    def fake_prepare(project_id: str, prompt: str, flaw: bool) -> None:
        captured["prepared"] = (project_id, prompt, flaw)

    def fake_run(project_id: str, flaw: bool) -> None:
        captured["project_id"] = project_id
        captured["flaw"] = flaw
        started.set()

    monkeypatch.setattr(main, "_prepare_demo", fake_prepare)
    monkeypatch.setattr(main, "_run_demo", fake_run)

    response = TestClient(main.app).post(
        "/demo/run", json={"prompt": "Build a tiny service", "flaw": True}
    )

    assert response.status_code == 202
    assert response.json()["status"] == "started"
    assert started.wait(timeout=2)
    assert captured["project_id"] == response.json()["project_id"]
    assert captured["flaw"] is True
    assert captured["prepared"] == (
        response.json()["project_id"],
        "Build a tiny service",
        True,
    )
    run_status = TestClient(main.app).get(
        f"/demo/runs/{response.json()['project_id']}"
    )
    assert run_status.status_code == 200
    assert run_status.json()["status"] == "running"


def test_missing_in_process_run_status_falls_back_to_existing_project(monkeypatch) -> None:
    project_id = "test-dashboard-run-status-lost"
    monkeypatch.setattr(main, "_project_nodes", lambda _: (object(), [], False))

    response = TestClient(main.app).get(f"/demo/runs/{project_id}")

    assert response.status_code == 200
    assert response.json() == {
        "project_id": project_id,
        "status": "unknown",
        "message": "No in-process run status is available.",
    }


def test_demo_run_failure_is_logged_and_reported(monkeypatch, caplog) -> None:
    project_id = "test-dashboard-run-failure"

    def fail_run(graph) -> None:
        raise RuntimeError("synthetic run failure")

    monkeypatch.setattr(main, "init_project", lambda _: object())
    monkeypatch.setattr(main, "run_project", fail_run)

    main._run_demo(project_id, True)

    response = TestClient(main.app).get(f"/demo/runs/{project_id}")
    assert response.status_code == 200
    assert response.json() == {
        "project_id": project_id,
        "status": "failed",
        "message": "synthetic run failure",
    }
    assert "Demo run failed for project test-dashboard-run-failure" in caplog.text
    assert "Traceback" in caplog.text
