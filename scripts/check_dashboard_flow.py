"""Exercise the localhost dashboard flaw, approval, and release flow."""

import argparse
import json
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def request_json(base_url: str, path: str, body: dict[str, object] | None = None) -> object:
    """Call a localhost JSON endpoint and return its decoded response."""
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = Request(
        f"{base_url}{path}",
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
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


def verify_repaired_demo(base_url: str, project_id: str) -> None:
    """Require the flaw demo to finish tests, security, and bug repair."""
    graph = request_json(base_url, f"/projects/{project_id}/graph")
    events = request_json(base_url, f"/projects/{project_id}/events")
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
    if not any(edge.get("type") == "FIXES" for edge in graph.get("edges", [])):
        raise RuntimeError("No repair artifact is linked to the detected bug")

    event_types = {event.get("type") for event in events}
    if not {"bug found", "bug fixed", "task done"} <= event_types:
        raise RuntimeError("The event feed is missing repair or task-completion events")


def run_flow(base_url: str, timeout: int) -> list[str]:
    """Run the flaw demo, wait for approval, approve it, and await release."""
    started_at = time.monotonic()
    deadline = started_at + timeout
    timeline: list[str] = []

    def record(state: str) -> None:
        if not timeline or timeline[-1] != state:
            elapsed = int(time.monotonic() - started_at)
            line = f"[{elapsed:02d}s] {state}"
            timeline.append(state)
            print(line, flush=True)

    response = request_json(base_url, "/demo/run", {"flaw": True})
    if not isinstance(response, dict) or not isinstance(response.get("project_id"), str):
        raise RuntimeError("Demo endpoint did not return a project ID")
    project_id = response["project_id"]
    record(f"Started flaw demo: {project_id}")

    approval_sent = False
    while time.monotonic() < deadline:
        status = request_json(
            base_url, f"/projects/{project_id}/release-status"
        )
        if not isinstance(status, dict):
            raise RuntimeError("Release-status endpoint returned invalid data")

        state = flow_state(status)
        record(state)
        if status.get("released"):
            if not approval_sent:
                raise RuntimeError("Project was released before this checker approved it")
            return timeline

        if state == "Waiting for approval" and not approval_sent:
            verify_repaired_demo(base_url, project_id)
            record("Tester and security passed; all detected bugs are fixed")
            request_json(base_url, f"/projects/{project_id}/approve", {})
            approval_sent = True
            record("Approval submitted")

        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(1, remaining))

    raise TimeoutError(f"Project did not reach released state within {timeout} seconds")


def main() -> int:
    """Run the dashboard flow checker against the local API."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=int, default=60)
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
        run_flow(args.base_url.rstrip("/"), args.timeout)
    except (RuntimeError, TimeoutError) as error:
        print(f"Dashboard flow failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
