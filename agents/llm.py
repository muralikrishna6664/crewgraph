"""Small environment-configured LLM client."""

import json
import os
import re
from typing import NamedTuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class LLMResponse(NamedTuple):
    """Text returned by a model and its input and output token counts."""

    text: str
    input_tokens: int
    output_tokens: int


MOCK_DAG = {
    "tasks": [
        {
            "id": "todo-api",
            "title": "Build the to-do REST API",
            "skill": "backend",
            "depends_on": [],
        },
        {
            "id": "todo-page",
            "title": "Build the to-do web page",
            "skill": "frontend",
            "depends_on": ["todo-api"],
        },
        {
            "id": "todo-tests",
            "title": "Test the to-do app",
            "skill": "tester",
            "depends_on": ["todo-api", "todo-page"],
        },
        {
            "id": "todo-security",
            "title": "Scan the generated app for security issues",
            "skill": "security",
            "depends_on": ["todo-api", "todo-page", "todo-tests"],
        },
    ]
}

MOCK_API_CONTRACT = {
    "endpoints": [
        {"method": "GET", "path": "/todos", "expected_status": 200},
        {
            "method": "POST",
            "path": "/todos",
            "expected_status": 201,
            "json": {"title": "Buy milk"},
            "capture_id": True,
        },
        {
            "method": "DELETE",
            "path": "/todos/{id}",
            "expected_status": 204,
            "use_captured_id": True,
        },
        {
            "method": "POST",
            "path": "/todos",
            "expected_status": 422,
            "json": {"title": ""},
            "invalid": True,
        },
    ]
}


def _estimate_tokens(text: str) -> int:
    """Estimate tokens for mock responses without requiring a tokenizer."""
    return len(re.findall(r"\w+|[^\w\s]", text))


def call(system: str, user: str) -> LLMResponse:
    """Call the configured provider and return text with token usage counts."""
    provider = os.getenv("LLM_PROVIDER", "mock").lower()
    model = os.getenv("LLM_MODEL", "mock-dag")

    if provider == "mock":
        if "Repair generated file" in system:
            fixed_backend = (
                "from fastapi import FastAPI, HTTPException\n"
                "from fastapi.responses import Response\n"
                "from pydantic import BaseModel\n\n"
                "app = FastAPI(title='CrewGraph To-do API')\n"
                "todos = []\n"
                "next_id = 1\n\n"
                "class TodoInput(BaseModel):\n"
                "    title: str\n\n"
                "@app.get('/todos')\n"
                "def list_todos():\n"
                "    return todos\n\n"
                "@app.post('/todos', status_code=201)\n"
                "def create_todo(item: TodoInput):\n"
                "    global next_id\n"
                "    if not item.title.strip():\n"
                "        raise HTTPException(status_code=422, detail='title must not be empty')\n"
                "    todo = {'id': next_id, 'title': item.title, 'completed': False}\n"
                "    next_id += 1\n"
                "    todos.append(todo)\n"
                "    return todo\n\n"
                "@app.delete('/todos/{todo_id}', status_code=204)\n"
                "def delete_todo(todo_id: int):\n"
                "    for index, todo in enumerate(todos):\n"
                "        if todo['id'] == todo_id:\n"
                "            todos.pop(index)\n"
                "            return Response(status_code=204)\n"
                "    raise HTTPException(status_code=404, detail='todo not found')\n"
            )
            return LLMResponse(
                json.dumps({"files": {"main.py": fixed_backend}}),
                _estimate_tokens(f"{system}\n{user}"),
                _estimate_tokens(fixed_backend),
            )

        if "Generate task files" in system:
            try:
                context = json.loads(user)
                task = context["task"]
                skill = task["skill"]
            except (json.JSONDecodeError, KeyError, TypeError) as error:
                raise ValueError("Mock worker requires task context with a skill") from error

            if skill == "backend":
                security_flaw = os.getenv("DEMO_FLAW") == "security"
                files = {
                    "API_CONTRACT.json": json.dumps(MOCK_API_CONTRACT, indent=2),
                    "main.py": (
                        "import os\n"
                        "from fastapi import FastAPI, HTTPException\n"
                        "from fastapi.responses import JSONResponse, Response\n"
                        "from pydantic import BaseModel\n\n"
                        "app = FastAPI(title='CrewGraph To-do API')\n"
                        "todos = []\n"
                        "next_id = 1\n\n"
                        "class TodoInput(BaseModel):\n"
                        "    title: str\n\n"
                        "@app.get('/todos')\n"
                        "def list_todos():\n"
                        "    return todos\n\n"
                        "@app.post('/todos', status_code=201)\n"
                        "def create_todo(item: TodoInput):\n"
                        "    global next_id\n"
                        "    if not item.title.strip() and os.getenv('DEMO_FLAW') != '1':\n"
                        "        raise HTTPException(status_code=422, "
                        "detail='title must not be empty')\n"
                        "    todo = {'id': next_id, 'title': item.title, "
                        "'completed': False}\n"
                        "    next_id += 1\n"
                        "    todos.append(todo)\n"
                        "    if not item.title.strip() and os.getenv('DEMO_FLAW') == '1':\n"
                        "        return JSONResponse(status_code=200, content=todo)\n"
                        "    return todo\n\n"
                        "@app.delete('/todos/{todo_id}', status_code=204)\n"
                        "def delete_todo(todo_id: int):\n"
                        "    for index, todo in enumerate(todos):\n"
                        "        if todo['id'] == todo_id:\n"
                        "            todos.pop(index)\n"
                        "            return Response(status_code=204)\n"
                        "    raise HTTPException(status_code=404, detail='todo not found')\n"
                    ),
                }
                if security_flaw:
                    files["main.py"] = files["main.py"].replace(
                        "from fastapi.responses import JSONResponse, Response\n",
                        "from fastapi.responses import JSONResponse, Response\n"
                        "from fastapi.middleware.cors import CORSMiddleware\n"
                        "SECRET_API_KEY = 'crewgraph-demo-fake-key-123456'\n",
                    ).replace(
                        "app = FastAPI(title='CrewGraph To-do API')\n",
                        "app = FastAPI(title='CrewGraph To-do API')\n"
                        "app.add_middleware(CORSMiddleware, allow_origins=['*'], "
                        "allow_methods=['*'], allow_headers=['*'])\n",
                    )
            elif skill == "frontend":
                context_data = context.get("handoff_context", {})
                artifacts = context_data.get("artifacts", [])
                contracts = [
                    artifact.get("content", "")
                    for artifact in artifacts
                    if artifact.get("kind") == "api_contract"
                    and artifact.get("content")
                ]
                if not contracts:
                    raise ValueError(
                        "Mock frontend requires an API contract from handoff context"
                    )
                files = {
                    "dashboard/index.html": (
                        "<!doctype html>\n"
                        "<html><head><title>To-do</title></head><body>\n"
                        "<h1>To-do list</h1><form id=\"new-todo\">"
                        "<input id=\"title\" required><button>Add</button></form>\n"
                        "<ul id=\"todos\"></ul>\n<script>\n"
                        "const list = document.querySelector('#todos');\n"
                        "async function loadTodos() {\n"
                        "  const response = await fetch('/todos');\n"
                        "  const todos = await response.json();\n"
                        "  list.replaceChildren(...todos.map(todo => {\n"
                        "    const item = document.createElement('li');\n"
                        "    item.textContent = todo.title;\n"
                        "    return item;\n"
                        "  }));\n"
                        "}\n"
                        "document.querySelector('#new-todo').onsubmit = async event => {\n"
                        "  event.preventDefault();\n"
                        "  await fetch('/todos', {method: 'POST', "
                        "headers: {'Content-Type': 'application/json'}, "
                        "body: JSON.stringify({title: document.querySelector('#title').value})});\n"
                        "  await loadTodos();\n"
                        "};\nloadTodos();\n</script></body></html>\n"
                    )
                }
            elif skill == "tester":
                files = {
                    "tests/test_todo_api.py": (
                        "def test_todo_api_contract_has_required_endpoints():\n"
                        "    from pathlib import Path\n"
                        "    contract = Path('API_CONTRACT.md').read_text()\n"
                        "    assert 'GET' in contract\n"
                        "    assert '/todos' in contract\n"
                    )
                }
            else:
                raise ValueError(f"No mock files are configured for skill: {skill}")
            text = json.dumps({"files": files})
        else:
            text = json.dumps(MOCK_DAG)
        return LLMResponse(
            text,
            _estimate_tokens(f"{system}\n{user}"),
            _estimate_tokens(text),
        )

    if provider != "openai":
        raise ValueError(f"Unsupported LLM_PROVIDER: {provider}")

    api_key = os.getenv("LLM_API_KEY")
    if not api_key:
        raise ValueError("LLM_API_KEY is required when LLM_PROVIDER is openai")
    if not os.getenv("LLM_MODEL"):
        raise ValueError("LLM_MODEL is required when LLM_PROVIDER is openai")

    request = Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(
            {
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "response_format": {"type": "json_object"},
            }
        ).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=60) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise RuntimeError(f"OpenAI request failed with HTTP {error.code}") from error
    except URLError as error:
        raise RuntimeError(f"Could not reach OpenAI: {error.reason}") from error

    try:
        text = result["choices"][0]["message"]["content"]
        usage = result["usage"]
        if not isinstance(text, str):
            raise TypeError("completion content is not text")
        return LLMResponse(
            text,
            int(usage["prompt_tokens"]),
            int(usage["completion_tokens"]),
        )
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise RuntimeError("OpenAI returned an invalid chat completion response") from error
