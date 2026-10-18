from fastapi.testclient import TestClient

import app.main as main


def test_demo_run_uses_configured_step_delay(monkeypatch) -> None:
    project_id = "test-dashboard-step-delay"
    graph = object()
    captured: list[tuple[object, int]] = []
    monkeypatch.setenv("DEMO_STEP_DELAY_MS", "35")
    monkeypatch.setattr(main, "init_project", lambda _: graph)
    monkeypatch.setattr(
        main,
        "run_project",
        lambda current_graph, step_delay_ms: captured.append(
            (current_graph, step_delay_ms)
        ),
    )

    try:
        main._run_demo(project_id, False)

        assert captured == [(graph, 35)]
        assert main._demo_runs[project_id]["status"] == "finished"
    finally:
        with main._demo_runs_lock:
            main._demo_runs.pop(project_id, None)


def test_demo_run_failure_is_logged_and_reported(monkeypatch, caplog) -> None:
    project_id = "test-dashboard-run-failure"

    def fail_run(graph, step_delay_ms: int) -> None:
        assert step_delay_ms == 0
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
