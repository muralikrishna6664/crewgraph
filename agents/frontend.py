"""Frontend implementation agent."""

from agents.runner import Agent


class FrontendAgent(Agent):
    """Build the frontend from API contract artifacts in task context."""

    def __init__(self) -> None:
        super().__init__(
            name="frontend",
            role="Build the web UI using the API contract artifact",
            skills=["frontend"],
            system_prompt=(
                "Generate task files. Read the API contract only from the artifacts "
                "in handoff_context provided with the task. Never contact or request "
                "information from the backend agent. Use the contract's routes and "
                "payloads. Return JSON with a files object mapping safe relative paths "
                "to complete file contents."
            ),
        )
