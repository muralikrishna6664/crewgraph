import pytest


@pytest.fixture(autouse=True)
def disable_auth_for_tests_unless_overridden(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "false")
