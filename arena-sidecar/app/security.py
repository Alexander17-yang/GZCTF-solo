from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from datetime import UTC, datetime
from typing import Any


PBKDF2_ITERATIONS = 310_000


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_secret(value: str, *, pepper: str = "", iterations: int = PBKDF2_ITERATIONS) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", (value + pepper).encode("utf-8"), salt, iterations, dklen=32
    )
    return f"pbkdf2_sha256${iterations}${_b64url_encode(salt)}${_b64url_encode(digest)}"


def verify_secret(value: str, encoded: str, *, pepper: str = "") -> bool:
    try:
        algorithm, iterations_text, salt_text, digest_text = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_text)
        if iterations < 100_000 or iterations > 2_000_000:
            return False
        salt = _b64url_decode(salt_text)
        expected = _b64url_decode(digest_text)
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac(
        "sha256", (value + pepper).encode("utf-8"), salt, iterations, dklen=len(expected)
    )
    return hmac.compare_digest(actual, expected)


def issue_token(subject: str, role: str, secret: str, ttl_seconds: int) -> tuple[str, datetime]:
    now = int(time.time())
    expires = now + ttl_seconds
    payload = {
        "sub": subject,
        "role": role,
        "iat": now,
        "exp": expires,
        "nonce": secrets.token_urlsafe(8),
    }
    encoded_payload = _b64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signature = _b64url_encode(
        hmac.new(secret.encode("utf-8"), encoded_payload.encode("ascii"), hashlib.sha256).digest()
    )
    return f"arena1.{encoded_payload}.{signature}", datetime.fromtimestamp(expires, UTC)


def decode_token(token: str, secret: str) -> dict[str, Any] | None:
    try:
        prefix, encoded_payload, signature = token.split(".", 2)
        if prefix != "arena1":
            return None
        expected = _b64url_encode(
            hmac.new(secret.encode("utf-8"), encoded_payload.encode("ascii"), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(signature, expected):
            return None
        payload = json.loads(_b64url_decode(encoded_payload))
        if not isinstance(payload, dict) or int(payload.get("exp", 0)) <= int(time.time()):
            return None
        return payload
    except (ValueError, TypeError, json.JSONDecodeError):
        return None

