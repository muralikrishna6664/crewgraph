"""Generic agent runner."""

import json
from dataclasses import dataclass

from agents.llm import LLMResponse, call


@dataclass
class Agent:
    """An agent that sends its role, skills, and context to the configured LLM."""

    name: str
    role: str
    skills: list[str]
    system_prompt: str

    def run(self, context: str | dict[str, object]) -> LLMResponse:
        """Run the agent with text or JSON-encoded context."""
        user = context if isinstance(context, str) else json.dumps(context)
        return call(self.system_prompt, user)
