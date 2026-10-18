"""Demo-only tenant authentication and signed session tokens."""

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass

_demo_accounts = {
    "acme": "pbkdf2_sha256$210000$Y3Jld2dyYXBoLWFjbWUtc2FsdC12MQ$E54ymUfnEevglEf7LNmACMQd1HcyPviWclazF6jCP-s",
    "globex": "pbkdf2_sha256$210000$Y3Jld2dyYXBoLWdsb2JleC1zYWx0LXYx$f_buNB6I-90M6azWdva0Neg_Vc7vPP4Ih7dKUMvss8o",
}
_session_ttl_seconds = 8 * 60 * 60


@dataclass(frozen=True)
class DemoSession:
    """Authenticated demo identity attached to an HTTP request."""

    username: str
    tenant: str
    expires_at: int


def auth_enabled() -> bool:
    """Return whether demo authentication is enabled by configuration."""
    value = os.getenv("AUTH_ENABLED", "false").strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off", ""}:
        return False
    raise ValueError("AUTH_ENABLED must be a boolean value")


def verify_password(username: str, password: str) -> bool:
    """Check a password against the account's stored PBKDF2 digest."""
    encoded = _demo_accounts.get(username)
    if encoded is None:
        return False
    algorithm, iterations, salt_text, expected_text = encoded.split("$", 3)
    if algorithm != "pbkdf2_sha256":
        raise ValueError("Unsupported stored password hash")
    salt = _decode_base64(salt_text)
    expected = _decode_base64(expected_text)
    actual = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, int(iterations)
    )
    return hmac.compare_digest(actual, expected)


def _decode_base64(value: str) -> bytes:
    """Decode an unpadded URL-safe base64 value."""
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _encode_base64(value: bytes) -> str:
    """Encode bytes as unpadded URL-safe base64."""
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _secret_key() -> bytes:
    """Return the configured signing key or the documented demo-only key."""
    return os.getenv(
        "SECRET_KEY", "crewgraph-demo-only-change-this-secret"
    ).encode("utf-8")


def create_session_token(username: str, now: int | None = None) -> str:
    """Create an expiring HMAC-signed session token for a demo account."""
    if username not in _demo_accounts:
        raise ValueError("Unknown demo account")
    issued_at = int(time.time()) if now is None else now
    payload = json.dumps(
        {
            "username": username,
            "tenant": username,
            "exp": issued_at + _session_ttl_seconds,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    encoded_payload = _encode_base64(payload)
    signature = hmac.new(
        _secret_key(), encoded_payload.encode("ascii"), hashlib.sha256
    ).digest()
    return f"{encoded_payload}.{_encode_base64(signature)}"


def verify_session_token(token: str, now: int | None = None) -> DemoSession | None:
    """Validate a signed token and return its tenant identity when current."""
    try:
        encoded_payload, encoded_signature = token.split(".", 1)
        supplied_signature = _decode_base64(encoded_signature)
        expected_signature = hmac.new(
            _secret_key(), encoded_payload.encode("ascii"), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(supplied_signature, expected_signature):
            return None
        payload = json.loads(_decode_base64(encoded_payload))
        username = payload["username"]
        tenant = payload["tenant"]
        expires_at = payload["exp"]
        if (
            not isinstance(username, str)
            or username not in _demo_accounts
            or tenant != username
            or not isinstance(expires_at, int)
            or expires_at <= (int(time.time()) if now is None else now)
        ):
            return None
    except (ValueError, TypeError, KeyError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return DemoSession(username, tenant, expires_at)
