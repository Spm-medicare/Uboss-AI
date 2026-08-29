"""Short-lived, single-use proof for choosing one of several workspaces."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid
from dataclasses import dataclass

from redis.asyncio import Redis
from redis.exceptions import RedisError

from uboss.core.errors import DependencyUnavailable
from uboss.core.logging import get_logger

log = get_logger(__name__)

KEY_PREFIX = "uboss:auth:workspace:"


@dataclass(frozen=True, slots=True)
class WorkspaceClaim:
    user_id: uuid.UUID
    allowed_workspaces: frozenset[str]


def _key(raw: str) -> str:
    return f"{KEY_PREFIX}{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"


async def issue(
    client: Redis,
    *,
    user_id: uuid.UUID,
    allowed_workspaces: list[str],
    client_binding: str,
    ttl_seconds: int,
) -> str:
    """Mint a proof stored hashed in Redis; return the raw value once."""
    payload = json.dumps(
        {
            "user_id": str(user_id),
            "allowed_workspaces": sorted(set(allowed_workspaces)),
            "client_binding": client_binding,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    try:
        # Collision retry is defensive; 256 random bits make it practically unreachable.
        for _attempt in range(3):
            raw = secrets.token_urlsafe(32)
            stored = await client.set(_key(raw), payload, ex=ttl_seconds, nx=True)
            if stored:
                return raw
    except RedisError as exc:
        log.warning("workspace_challenge_unavailable", error_type=type(exc).__name__)
        raise DependencyUnavailable(
            "Workspace selection is temporarily unavailable. Try signing in again shortly."
        ) from exc
    raise DependencyUnavailable(
        "Workspace selection is temporarily unavailable. Try signing in again shortly."
    )


async def consume(
    client: Redis, *, raw: str, expected_client_binding: str
) -> WorkspaceClaim | None:
    """Consume exactly once and return a valid browser-bound claim."""
    try:
        encoded = await client.getdel(_key(raw))
    except RedisError as exc:
        log.warning("workspace_challenge_unavailable", error_type=type(exc).__name__)
        raise DependencyUnavailable(
            "Workspace selection is temporarily unavailable. Try signing in again shortly."
        ) from exc
    if not isinstance(encoded, str):
        return None

    try:
        data = json.loads(encoded)
        user_id = uuid.UUID(str(data["user_id"]))
        allowed = frozenset(str(item) for item in data["allowed_workspaces"])
        binding = str(data["client_binding"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        log.warning("workspace_challenge_corrupt")
        return None

    if not hmac.compare_digest(binding, expected_client_binding) or not allowed:
        return None
    return WorkspaceClaim(user_id=user_id, allowed_workspaces=allowed)
