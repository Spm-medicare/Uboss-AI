"""Single-use token storage for invite setup and account recovery.

This module deliberately does not expose an HTTP route. Issuing a secure token is only half of
an invite/reset journey: the product also needs an authorised issuer, audited notification
delivery and, for a password reset, cross-tenant session revocation. Callers may use these
primitives once those boundaries exist; until then the API must not claim that it sent a link.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from dataclasses import dataclass
from enum import StrEnum

from redis.asyncio import Redis
from redis.exceptions import RedisError

from uboss.core.errors import DependencyUnavailable
from uboss.core.logging import get_logger

log = get_logger(__name__)
KEY_PREFIX = "uboss:auth:action:"


class ActionTokenPurpose(StrEnum):
    INVITE_SETUP = "invite_setup"
    PASSWORD_RESET = "password_reset"  # noqa: S105 - purpose label, not a credential


@dataclass(frozen=True, slots=True)
class ActionTokenClaim:
    purpose: ActionTokenPurpose
    user_id: uuid.UUID
    tenant_id: uuid.UUID | None
    membership_id: uuid.UUID | None


def _key(raw: str) -> str:
    return f"{KEY_PREFIX}{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"


async def issue(
    client: Redis,
    *,
    purpose: ActionTokenPurpose,
    user_id: uuid.UUID,
    ttl_seconds: int,
    tenant_id: uuid.UUID | None = None,
    membership_id: uuid.UUID | None = None,
) -> str:
    """Store a hashed 256-bit token and return its raw value exactly once.

    Invite setup is membership-specific. A reset is identity-wide and therefore carries no
    tenant/membership identifiers; its eventual consumer must revoke sessions in every tenant.
    """
    if purpose is ActionTokenPurpose.INVITE_SETUP and (
        tenant_id is None or membership_id is None
    ):
        raise ValueError("Invite setup tokens require a tenant and membership.")
    if purpose is ActionTokenPurpose.PASSWORD_RESET and (
        tenant_id is not None or membership_id is not None
    ):
        raise ValueError("Password reset tokens must be identity-wide.")

    payload = json.dumps(
        {
            "purpose": purpose.value,
            "user_id": str(user_id),
            "tenant_id": str(tenant_id) if tenant_id else None,
            "membership_id": str(membership_id) if membership_id else None,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    try:
        for _attempt in range(3):
            raw = secrets.token_urlsafe(32)
            if await client.set(_key(raw), payload, ex=ttl_seconds, nx=True):
                return raw
    except RedisError as exc:
        log.warning("identity_action_token_unavailable", error_type=type(exc).__name__)
        raise DependencyUnavailable(
            "Secure account links are temporarily unavailable. Try again shortly."
        ) from exc
    raise DependencyUnavailable(
        "Secure account links are temporarily unavailable. Try again shortly."
    )


async def consume(
    client: Redis,
    *,
    raw: str,
    expected_purpose: ActionTokenPurpose,
) -> ActionTokenClaim | None:
    """Atomically consume a token, returning a claim only when its purpose matches.

    A wrong-purpose presentation burns the token. This is fail-closed: a reset token presented
    to an invite endpoint must never remain usable after crossing an unexpected code path.
    """
    try:
        encoded = await client.getdel(_key(raw))
    except RedisError as exc:
        log.warning("identity_action_token_unavailable", error_type=type(exc).__name__)
        raise DependencyUnavailable(
            "Secure account links are temporarily unavailable. Try again shortly."
        ) from exc
    if not isinstance(encoded, str):
        return None

    try:
        data = json.loads(encoded)
        purpose = ActionTokenPurpose(str(data["purpose"]))
        user_id = uuid.UUID(str(data["user_id"]))
        tenant_id = uuid.UUID(str(data["tenant_id"])) if data["tenant_id"] else None
        membership_id = (
            uuid.UUID(str(data["membership_id"])) if data["membership_id"] else None
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        log.warning("identity_action_token_corrupt")
        return None

    if purpose is not expected_purpose:
        return None
    if purpose is ActionTokenPurpose.INVITE_SETUP and (
        tenant_id is None or membership_id is None
    ):
        return None
    if purpose is ActionTokenPurpose.PASSWORD_RESET and (
        tenant_id is not None or membership_id is not None
    ):
        return None
    return ActionTokenClaim(
        purpose=purpose,
        user_id=user_id,
        tenant_id=tenant_id,
        membership_id=membership_id,
    )
