"""Exercise the localhost dashboard flaw, approval, and release flow."""

import argparse
import json
import os
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def request_json(
    base_url: str,
    path: str,
    body: dict[str, object] | None = None,
    token: str | None = None,
) -> object:
    """Call a localhost JSON endpoint and return its decoded response."""
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"} if data is not None else {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(
        f"{base_url}{path}",
        data=data,
        headers=headers,
        method="POST" if data is not None else "GET",
    )
    try:
        with urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        response_body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"{request.method} {path} returned HTTP {error.code}: {response_body}"
        ) from error
    except URLError as error:
        raise RuntimeError(f"Could not reach local dashboard API: {error.reason}") from error


def flow_state(status: dict[str, object]) -> str:
    """Summarize a release-status response for the run timeline."""
    if status.get("released"):
        return "Released"
    reasons = status.get("reasons", [])
    if reasons == ["Human approval is required"]:
        return "Waiting for approval"
    if status.get("can_release"):
        return "Release eligible"
    if any("Open bugs remain" in str(reason) for reason in reasons):
        return "Repairing open bugs"
    return "Running tasks"


def verify_repaired_demo(
    base_url: str, project_id: str, token: str | None = None
) -> None:
    """Require the flaw demo to finish tests, security, and bug repair."""
    graph = request_json(base_url, f"/projects/{project_id}/graph", token=token)
    events = request_json(base_url, f"/projects/{project_id}/events", token=token)
    if not isinstance(graph, dict) or not isinstance(events, list):
        raise RuntimeError("Dashboard returned an invalid graph or event response")

    nodes = graph.get("nodes", [])
    tasks = {
        node.get("properties", {}).get("id"): node
        for node in nodes
        if node.get("label") == "Task"
    }
    for task_id in ("todo-tests", "todo-security"):
        if tasks.get(task_id, {}).get("status") != "done":
            raise RuntimeError(f"Required task did not pass: {task_id}")

    bugs = [node for node in nodes if node.get("label") == "Bug"]
    if not bugs or any(bug.get("status") != "fixed" for bug in bugs):
        raise RuntimeError("The flaw was not found and marked fixed")
    fix_edges = [
        edge for edge in graph.get("edges", []) if edge.get("type") == "FIXES"
    ]
    if not fix_edges:
        raise RuntimeError("No repair artifact is linked to the detected bug")

    event_types = [event.get("type") for event in events]
    if "bug found" not in event_types or "bug fixed" not in event_types:
        raise RuntimeError("The event feed is missing repair or task-completion events")
    if event_types.index("bug found") >= event_types.index("bug fixed"):
        raise RuntimeError("The bug was fixed before a finding was recorded")
    debugger_artifacts = [
        node
        for node in nodes
        if node.get("label") == "Artifact"
        and node.get("properties", {}).get("kind") == "backend"
        and ":repair:" in str(node.get("id", ""))
    ]
    if not debugger_artifacts:
        raise RuntimeError("No debugger repair artifact is present in the graph")
    for task_id in ("todo-tests", "todo-security"):
        if not any(
            event.get("type") == "task done" and event.get("task_id") == task_id
            for event in events
        ):
            raise RuntimeError(f"Task completion event is missing for {task_id}")


def run_flow(
    base_url: str,
    timeout: int,
    username: str | None = None,
    password: str | None = None,
) -> list[str]:
    """Run the flaw demo, wait for approval, approve it, and await release."""
    token = None
    if username or password:
        if not username or not password:
            raise RuntimeError("Both --username and --password are required for login")
        login = request_json(
            base_url,
            "/auth/login",
            {"username": username, "password": password},
        )
        if not isinstance(login, dict) or not isinstance(login.get("token"), str):
            raise RuntimeError("Login endpoint did not return a signed session token")
        token = login["token"]

    def api(path: str, body: dict[str, object] | None = None) -> object:
        return request_json(base_url, path, body, token)

    started_at = time.monotonic()
    deadline = started_at + timeout
    timeline: list[str] = []

    def record(state: str) -> None:
        if not timeline or timeline[-1] != state:
            elapsed = int(time.monotonic() - started_at)
            line = f"[{elapsed:02d}s] {state}"
            timeline.append(state)
            print(line, flush=True)

    response = api("/demo/run", {"flaw": True})
    if not isinstance(response, dict) or not isinstance(response.get("project_id"), str):
        raise RuntimeError("Demo endpoint did not return a project ID")
    project_id = response["project_id"]
    record(f"Started flaw demo: {project_id}")

    approval_sent = False
    seen_events: set[str] = set()
    while time.monotonic() < deadline:
        run_status = api(f"/demo/runs/{project_id}")
        if not isinstance(run_status, dict):
            raise RuntimeError("Demo-run endpoint returned invalid data")
        if run_status.get("status") == "failed":
            message = run_status.get("message") or "unspecified background failure"
            record(f"Run failed: {message}")
            raise RuntimeError(f"Demo run failed: {message}")

        events = api(f"/projects/{project_id}/events")
        if not isinstance(events, list):
            raise RuntimeError("Project events endpoint returned invalid data")
        for event in events:
            event_id = str(event.get("id", ""))
            if not event_id or event_id in seen_events:
                continue
            seen_events.add(event_id)
            event_type = event.get("type")
            if event_type == "bug found":
                record("Bug found")
            elif (
                event_type == "artifact created"
                and str(event.get("detail", "")).startswith("debugger created ")
            ):
                record("Debugger fix recorded")
            elif event_type == "bug fixed":
                record("Bug fixed")
            elif event_type == "task done" and event.get("task_id") == "todo-tests":
                record("Tester passed")
            elif event_type == "task done" and event.get("task_id") == "todo-security":
                record("Security passed")

        status = api(f"/projects/{project_id}/release-status")
        if not isinstance(status, dict):
            raise RuntimeError("Release-status endpoint returned invalid data")

        state = flow_state(status)
        record("Released" if state == "Released" else "Running...")
        if status.get("released"):
            if not approval_sent:
                raise RuntimeError("Project was released before this checker approved it")
            return timeline

        if (
            state == "Waiting for approval"
            and not approval_sent
            and run_status.get("status") == "finished"
        ):
            verify_repaired_demo(base_url, project_id, token)
            if flow_state(status) != "Waiting for approval":
                raise RuntimeError("Project is not waiting solely for human approval")
            record("Human approval is required")
            api(f"/projects/{project_id}/approve", {})
            approval_sent = True
            record("Approval submitted")
        elif run_status.get("status") == "finished" and not approval_sent:
            if state != "Waiting for approval":
                raise RuntimeError(
                    "Demo finished without reaching the approval-only release gate: "
                    + "; ".join(str(reason) for reason in status.get("reasons", []))
                )

        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(1, remaining))

    raise TimeoutError(f"Project did not reach released state within {timeout} seconds")


def main() -> int:
    """Run the dashboard flow checker against the local API."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--username", default=os.getenv("CREWGRAPH_USERNAME"))
    parser.add_argument("--password", default=os.getenv("CREWGRAPH_PASSWORD"))
    args = parser.parse_args()
    parsed = urlsplit(args.base_url)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"localhost", "127.0.0.1"}
        or parsed.username
        or parsed.password
        or parsed.path not in ("", "/")
        or args.timeout < 1
    ):
        parser.error("Use an http localhost URL and a positive timeout.")

    try:
        run_flow(
            args.base_url.rstrip("/"),
            args.timeout,
            args.username,
            args.password,
        )
    except (RuntimeError, TimeoutError) as error:
        print(f"Dashboard flow failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
