"""Redis-backed abuse limits for anonymous identity endpoints.

All buckets are created for every supplied email, whether or not an account exists. Redis keys
hold only keyed hashes, not raw email addresses or IP addresses, so operational key inspection
does not become another identity directory.
"""

from __future__ import annotations

import hashlib
import hmac
import math
from dataclasses import dataclass

from redis.asyncio import Redis
from redis.exceptions import RedisError

from uboss.core.errors import DependencyUnavailable, RateLimited
from uboss.core.logging import get_logger
from uboss.core.settings import Settings

log = get_logger(__name__)

_INCREMENT_SCRIPT = """
local value = redis.call('INCR', KEYS[1])
if value == 1 then
  redis.call('PEXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('PTTL', KEYS[1])
return {value, ttl}
"""


@dataclass(frozen=True, slots=True)
class Limit:
    namespace: str
    maximum: int
    window_seconds: int
    material: str


def _digest(secret: str, material: str) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        material.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def client_binding(secret: str, *, ip_address: str | None, user_agent: str | None) -> str:
    """Bind a short-lived workspace challenge to the browser that requested it."""
    return _digest(secret, f"client\0{ip_address or 'unknown'}\0{user_agent or 'unknown'}")


async def _increment(client: Redis, *, key: str, window_seconds: int) -> tuple[int, int]:
    result = await client.eval(_INCREMENT_SCRIPT, 1, key, window_seconds * 1000)
    if not isinstance(result, list) or len(result) != 2:
        raise RedisError("Unexpected rate-limit script result")
    return int(result[0]), max(1, math.ceil(int(result[1]) / 1000))


async def _enforce(client: Redis, *, secret: str, limits: tuple[Limit, ...]) -> None:
    exceeded_retry_after: list[int] = []
    try:
        for limit in limits:
            key = f"uboss:rate:{limit.namespace}:{_digest(secret, limit.material)}"
            count, retry_after = await _increment(
                client,
                key=key,
                window_seconds=limit.window_seconds,
            )
            if count > limit.maximum:
                exceeded_retry_after.append(retry_after)
    except RedisError as exc:
        log.warning("identity_rate_limit_unavailable", error_type=type(exc).__name__)
        raise DependencyUnavailable(
            "Identity verification is temporarily unavailable. Try again shortly."
        ) from exc

    if exceeded_retry_after:
        raise RateLimited(
            "Too many identity verification attempts. Wait before trying again.",
            retry_after_seconds=max(exceeded_retry_after),
        )


async def enforce_sign_in(
    client: Redis,
    *,
    settings: Settings,
    email: str,
    ip_address: str | None,
) -> None:
    secret = settings.auth_signing_key.get_secret_value()
    ip = ip_address or "unknown"
    normalized_email = email.strip().lower()
    await _enforce(
        client,
        secret=secret,
        limits=(
            Limit("signin-ip", settings.sign_in_ip_limit, settings.sign_in_ip_window_seconds, ip),
            Limit(
                "signin-account",
                settings.sign_in_account_limit,
                settings.sign_in_account_window_seconds,
                normalized_email,
            ),
            Limit(
                "signin-pair",
                settings.sign_in_pair_limit,
                settings.sign_in_pair_window_seconds,
                f"{ip}\0{normalized_email}",
            ),
        ),
    )


async def enforce_workspace_selection(
    client: Redis,
    *,
    settings: Settings,
    ip_address: str | None,
) -> None:
    # A separate bucket prevents challenge guessing without consuming the password buckets.
    await _enforce(
        client,
        secret=settings.auth_signing_key.get_secret_value(),
        limits=(
            Limit(
                "workspace-ip",
                settings.sign_in_ip_limit,
                settings.sign_in_ip_window_seconds,
                ip_address or "unknown",
            ),
        ),
    )


async def enforce_step_up(
    client: Redis,
    *,
    settings: Settings,
    membership_id: str,
    ip_address: str | None,
) -> None:
    """Limit password re-checks separately from anonymous sign-in attempts.

    A stolen session must not become an unlimited online password oracle. Membership and IP
    buckets cover both a single-session attack and one source trying many sessions.
    """
    await _enforce(
        client,
        secret=settings.auth_signing_key.get_secret_value(),
        limits=(
            Limit(
                "stepup-ip",
                settings.step_up_ip_limit,
                settings.step_up_window_seconds,
                ip_address or "unknown",
            ),
            Limit(
                "stepup-membership",
                settings.step_up_membership_limit,
                settings.step_up_window_seconds,
                membership_id,
            ),
        ),
    )
