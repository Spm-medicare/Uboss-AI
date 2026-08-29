"""Server-side idempotency for retryable tenant business commands.

An idempotency table without acquisition logic is only a table. This module owns the protocol:

1. validate the client key;
2. fingerprint canonical JSON and scope the key by tenant + server operation name;
3. acquire a transaction-scoped PostgreSQL advisory lock without waiting;
4. replay a completed matching response, reject changed input, or reserve a new record;
5. persist the successful JSON response in the same transaction as the business mutation.

If the business command raises, the reservation and business writes roll back together. A
concurrent duplicate cannot enter the command because it cannot acquire the advisory lock.

Do not use this for sign-in, password, token, secret, file-streaming or very large-response
endpoints. Those need purpose-built replay behavior and must not persist credential material.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Header
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from uboss.core.errors import (
    IdempotencyKeyReused,
    OperationInProgress,
    UnsafeReplayResponse,
    ValidationFailed,
    as_field_error,
)
from uboss.modules.audit.models import IdempotencyRecord

IDEMPOTENCY_HEADER = "Idempotency-Key"
DEFAULT_RETENTION = timedelta(hours=24)
MAX_RESPONSE_BYTES = 256 * 1024

# UUID/ULID-like values and namespaced client keys are accepted. Whitespace and opaque Unicode
# are refused so logs, proxies and databases cannot disagree about where a key starts or ends.
KEY_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,199}")

# A replay table is not a credential store. Refuse rather than redact: returning a redacted replay
# would differ from the first response and break the idempotency contract.
PROHIBITED_RESPONSE_KEYS = frozenset(
    {
        "password",
        "password_hash",
        "current_password",
        "new_password",
        "token",
        "raw_token",
        "token_hash",
        "access_token",
        "refresh_token",
        "api_key",
        "secret",
        "authorization",
        "cookie",
        "set_cookie",
        "session_cookie",
    }
)


def require_idempotency_key(
    value: str | None = Header(default=None, alias=IDEMPOTENCY_HEADER),
) -> str:
    """FastAPI dependency for commands that require a client idempotency key."""
    if value is None:
        raise ValidationFailed(
            f"{IDEMPOTENCY_HEADER} is required for this operation.",
            field_errors=as_field_error(
                "header.Idempotency-Key",
                "Provide one stable key for this logical operation and reuse it only for retries.",
                "required",
            ),
        )
    key = value.strip()
    if KEY_PATTERN.fullmatch(key) is None:
        raise ValidationFailed(
            f"{IDEMPOTENCY_HEADER} is not valid.",
            field_errors=as_field_error(
                "header.Idempotency-Key",
                "Use 8-200 ASCII letters, numbers, dots, underscores, colons or hyphens.",
                "invalid",
            ),
        )
    return key


def fingerprint_json(payload: Any) -> str:
    """Return SHA-256 for a deterministic JSON representation.

    Pydantic request models should be passed as ``model_dump(mode="json")`` so dates, UUIDs and
    enums have already become JSON values. NaN and infinity are refused because JSON systems do
    not agree on their meaning.
    """
    try:
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("Idempotency payload must be canonical JSON data.") from exc
    return hashlib.sha256(canonical).hexdigest()


def _advisory_lock_id(tenant_id: uuid.UUID, operation: str, key: str) -> int:
    digest = hashlib.sha256(f"{tenant_id}\0{operation}\0{key}".encode()).digest()
    # PostgreSQL advisory locks take a signed bigint. The stable hash is only a lock namespace;
    # the table's unique key remains the correctness check if a rare hash collision occurs.
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


def _contains_prohibited_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in PROHIBITED_RESPONSE_KEYS or _contains_prohibited_key(child):
                return True
    elif isinstance(value, list):
        return any(_contains_prohibited_key(item) for item in value)
    return False


@dataclass(slots=True)
class IdempotencyExecution:
    """The acquired command or a completed response ready to replay."""

    record: IdempotencyRecord
    is_replay: bool
    _completed: bool

    @property
    def replay_status(self) -> int:
        if not self.is_replay or self.record.response_status is None:
            raise RuntimeError("No completed response is available to replay.")
        return self.record.response_status

    @property
    def replay_body(self) -> dict[str, Any] | None:
        if not self.is_replay:
            raise RuntimeError("No completed response is available to replay.")
        return self.record.response_body

    def complete_json(self, *, status_code: int, body: dict[str, Any] | None) -> None:
        """Attach an eligible successful JSON response to the current transaction."""
        if self.is_replay:
            raise RuntimeError("A replay cannot be completed again.")
        if not 200 <= status_code < 300:
            raise ValueError("Only successful responses may be stored for replay.")
        if _contains_prohibited_key(body):
            raise UnsafeReplayResponse(
                "This endpoint returned credential-like data and cannot use stored replay."
            )
        encoded = json.dumps(
            body,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(encoded) > MAX_RESPONSE_BYTES:
            raise ValueError("Idempotency replay response exceeds the 256 KiB limit.")

        self.record.response_status = status_code
        self.record.response_body = body
        self._completed = True


@asynccontextmanager
async def execute(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    key: str,
    operation: str,
    payload: Any,
    retention: timedelta = DEFAULT_RETENTION,
) -> AsyncIterator[IdempotencyExecution]:
    """Acquire or replay one idempotent business command.

    The caller must keep the business mutation inside this context and call ``complete_json``
    before a successful exit. Otherwise an exception is raised so an incomplete reservation can
    never commit accidentally.
    """
    if not operation or len(operation) > 200:
        raise ValueError("Operation must be a stable server name of 1-200 characters.")
    if KEY_PATTERN.fullmatch(key) is None:
        raise ValueError("Idempotency key was not validated.")
    if retention <= timedelta(0):
        raise ValueError("Idempotency retention must be positive.")

    fingerprint = fingerprint_json(payload)
    lock_id = _advisory_lock_id(tenant_id, operation, key)
    acquired = bool(
        (
            await session.execute(
                text("SELECT pg_try_advisory_xact_lock(:lock_id)"),
                {"lock_id": lock_id},
            )
        ).scalar_one()
    )
    if not acquired:
        raise OperationInProgress(
            "This operation is already running. Retry with the same idempotency key."
        )

    now = datetime.now(UTC)
    record = (
        await session.execute(
            select(IdempotencyRecord).where(
                IdempotencyRecord.tenant_id == tenant_id,
                IdempotencyRecord.key == key,
                IdempotencyRecord.operation == operation,
            )
        )
    ).scalar_one_or_none()

    if record is not None and record.expires_at <= now:
        await session.delete(record)
        await session.flush()
        record = None

    if record is not None:
        if record.request_fingerprint != fingerprint:
            raise IdempotencyKeyReused(
                "This idempotency key was already used for different request data."
            )
        if record.response_status is None:
            raise OperationInProgress(
                "This operation has no completed replay yet. Retry with the same key."
            )
        execution = IdempotencyExecution(record=record, is_replay=True, _completed=True)
    else:
        record = IdempotencyRecord(
            tenant_id=tenant_id,
            key=key,
            operation=operation,
            request_fingerprint=fingerprint,
            response_status=None,
            response_body=None,
            expires_at=now + retention,
        )
        session.add(record)
        await session.flush()
        execution = IdempotencyExecution(record=record, is_replay=False, _completed=False)

    try:
        yield execution
    except BaseException:
        raise
    else:
        if not execution._completed:
            raise RuntimeError(
                "Idempotent command exited without completing its replay response."
            )


async def delete_expired_for_tenant(
    session: AsyncSession, *, tenant_id: uuid.UUID, now: datetime | None = None
) -> None:
    """Delete expired keys inside the caller's already-bound tenant transaction."""
    await session.execute(
        delete(IdempotencyRecord).where(
            IdempotencyRecord.tenant_id == tenant_id,
            IdempotencyRecord.expires_at <= (now or datetime.now(UTC)),
        )
    )
