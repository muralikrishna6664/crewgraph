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
