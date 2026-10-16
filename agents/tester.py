"""Run contract-driven HTTP checks against a local generated API."""

import json
import socket
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from falkordb.graph import Graph

from agents.runner import Agent
from agents.worker import _workspace_path
from app import queries


class TesterAgent(Agent):
    """Run real localhost HTTP checks from a backend API contract."""

    def __init__(self) -> None:
        super().__init__(
            name="tester",
            role="Test the generated API using its contract and real HTTP requests",
            skills=["tester"],
            system_prompt="Execute deterministic HTTP checks; do not use an LLM verdict.",
        )


def _free_local_port() -> int:
    """Choose a currently free TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def _request(
    method: str, url: str, payload: dict[str, object] | None = None
) -> tuple[int, bytes]:
    """Send one HTTP request only to the local generated application."""
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"} if body is not None else {},
        method=method,
    )
    try:
        with urlopen(request, timeout=3) as response:
            return response.status, response.read()
    except HTTPError as error:
        return error.code, error.read()


def _wait_until_ready(process: subprocess.Popen[bytes], base_url: str) -> bool:
    """Wait for the local Uvicorn server to accept requests or exit."""
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        try:
            _request("GET", f"{base_url}/openapi.json")
            return True
        except URLError:
            time.sleep(0.1)
    return False


def _check_contract(
    contract: dict[str, object], base_url: str
) -> list[tuple[str, int | None, int, str]]:
    """Run each contract check, capturing created IDs for later endpoints."""
    endpoints = contract.get("endpoints")
    if not isinstance(endpoints, list) or not endpoints:
        raise ValueError("API contract must have a non-empty endpoints list")

    captured_id: object | None = None
    failures: list[tuple[str, int | None, int, str]] = []
    for endpoint in endpoints:
        if not isinstance(endpoint, dict):
            raise ValueError("Each API contract endpoint must be an object")
        method = endpoint.get("method")
        path = endpoint.get("path")
        expected_status = endpoint.get("expected_status")
        if (
            not isinstance(method, str)
            or not isinstance(path, str)
            or not isinstance(expected_status, int)
        ):
            raise ValueError("API contract endpoints need method, path, and expected_status")

        if endpoint.get("use_captured_id"):
            if captured_id is None:
                failures.append(
                    (f"{method} {path}", None, expected_status, "No ID was returned by POST")
                )
                continue
            path = path.replace("{id}", str(captured_id))

        payload = endpoint.get("json")
        if payload is not None and not isinstance(payload, dict):
            raise ValueError(f"Endpoint payload must be an object: {method} {path}")

        try:
            status, response_body = _request(
                method, f"{base_url}{path}", payload
            )
        except (URLError, TimeoutError, OSError) as error:
            failures.append(
                (f"{method} {path}", None, expected_status, str(error))
            )
            continue

        if status != expected_status:
            failures.append(
                (
                    f"{method} {path}",
                    status,
                    expected_status,
                    "HTTP status did not match the API contract",
                )
            )
        if endpoint.get("capture_id") and 200 <= status < 300:
            try:
                response_json = json.loads(response_body.decode("utf-8"))
                captured_id = response_json["id"]
            except (json.JSONDecodeError, KeyError, TypeError) as error:
                failures.append(
                    (
                        f"{method} {path} response",
                        status,
                        expected_status,
                        f"Response did not include a usable id: {error}",
                    )
                )
    return failures


def test_task(
    graph: Graph,
    agent: Agent,
    task: dict[str, object],
    context: dict[str, object],
) -> list[str]:
    """Test the API over localhost and record bugs or complete the tester task."""
    task_id = task.get("id")
    if not isinstance(task_id, str):
        raise ValueError("Tester task must have a string id")

    artifacts = context.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValueError("Task context does not contain artifacts")
    contract_artifacts = [
        item
        for item in artifacts
        if isinstance(item, dict)
        and item.get("kind") == "api_contract"
        and isinstance(item.get("content"), str)
    ]
    backend_artifacts = [
        item
        for item in artifacts
        if isinstance(item, dict)
        and item.get("kind") == "backend"
        and isinstance(item.get("id"), str)
    ]
    if not contract_artifacts or not backend_artifacts:
        raise ValueError("Tester requires API contract and backend source artifacts")

    contract = json.loads(contract_artifacts[0]["content"])
    project_id = graph.name
    main_path = _workspace_path(project_id, "main.py")
    if not main_path.is_file():
        raise ValueError(f"Generated API entry point is missing: {main_path}")

    port = _free_local_port()
    base_url = f"http://127.0.0.1:{port}"
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=main_path.parent,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    failures: list[tuple[str, int | None, int, str]]
    try:
        if _wait_until_ready(process, base_url):
            failures = _check_contract(contract, base_url)
        else:
            failures = [
                ("server startup", None, 200, "Generated API did not start on localhost")
            ]
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    if failures:
        reason = "; ".join(
            f"{name}: expected HTTP {expected}, got {actual}: {detail}"
            for name, actual, expected, detail in failures
        )
        backend_artifact = next(
            (
                artifact
                for artifact in backend_artifacts
                if artifact.get("path") == "main.py"
            ),
            backend_artifacts[0],
        )
        for index, (name, actual, expected, detail) in enumerate(failures, start=1):
            actual_text = "no response" if actual is None else str(actual)
            queries.record_bug(
                graph,
                f"{task_id}:http-check:{index}",
                f"{name} returned {actual_text}, expected {expected}",
                "medium",
                backend_artifact["id"],
                "open",
            )
        queries.fail_task(graph, task_id, reason)
        return []

    if queries.complete_task(graph, task_id) is None:
        raise ValueError(f"Could not complete tester task: {task_id}")
    return []
