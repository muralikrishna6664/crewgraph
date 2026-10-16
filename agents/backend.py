"""Backend implementation agent."""

from agents.runner import Agent


class BackendAgent(Agent):
    """Generate backend files and an API contract for dependent tasks."""

    def __init__(self) -> None:
        super().__init__(
            name="backend",
            role="Build the REST API and publish its API contract",
            skills=["backend"],
            system_prompt=(
                "Generate task files. Implement the backend requested in the task. "
                "Always produce API_CONTRACT.md documenting routes, request bodies, "
                "and responses for frontend tasks. Return JSON with a files object "
                "mapping safe relative paths to complete file contents."
            ),
        )
