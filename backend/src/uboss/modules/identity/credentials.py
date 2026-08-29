"""The only way the application reaches the credentials table.

`users` holds an address and an Argon2 hash for every person in every organisation, and it
carries no `tenant_id`, so row-level security cannot protect it. Migration 0006 therefore took
the table away from the application role entirely: `uboss_app` has no privilege on it and can
only call the five `SECURITY DEFINER` functions this module wraps.

**What that prevents.** Enumeration. No call here returns more than one row, and there is no
call that returns a list. An injection elsewhere in the application cannot dump the table,
because the role has no rights on it to abuse.

**What it does not prevent, stated plainly.** Argon2 verification happens in Python, so a hash
for the one account being named still reaches this process. The protection is that you must
already know the exact address or id to get it.

Every function in this module is a thin call. Deliberately: the moment one of them grows a
filter or a second query, the narrow surface stops being narrow. New behaviour goes in a new
database function, in a migration, where it is reviewed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class Credential:
    """One person's sign-in identity. Never serialised to a client.

    Frozen, and never passed further than the authentication service — a hash that travels is a
    hash that ends up in a log line.
    """

    id: uuid.UUID
    email: str
    password_hash: str | None
    status: str
    failed_sign_in_count: int = 0
    locked_until: datetime | None = None

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    def is_locked(self, now: datetime) -> bool:
        return self.locked_until is not None and self.locked_until > now


async def find_by_email(session: AsyncSession, email: str) -> Credential | None:
    """The sign-in path's entry point.

    Returns nothing when the address matches no account. The caller must still run a password
    verification in that case — returning early is what makes "no such account" measurably
    faster than "wrong password".
    """
    row = (
        await session.execute(
            text(
                "SELECT id, email, password_hash, status, failed_sign_in_count, locked_until "
                "FROM auth_find_by_email(:email)"
            ),
            {"email": email},
        )
    ).first()
    if row is None:
        return None
    return Credential(
        id=row.id,
        email=row.email,
        password_hash=row.password_hash,
        status=row.status,
        failed_sign_in_count=row.failed_sign_in_count,
        locked_until=row.locked_until,
    )


async def find_by_id(session: AsyncSession, user_id: uuid.UUID) -> Credential | None:
    """For the workspace challenge and for step-up, which already hold a verified identity."""
    row = (
        await session.execute(
            text(
                "SELECT id, email, password_hash, status FROM auth_find_by_id(:user_id)"
            ),
            {"user_id": str(user_id)},
        )
    ).first()
    if row is None:
        return None
    return Credential(
        id=row.id,
        email=row.email,
        password_hash=row.password_hash,
        status=row.status,
    )


async def record_failure(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    max_attempts: int,
    lockout: timedelta,
) -> None:
    """Count a failed attempt, and close the account if there have been too many.

    The threshold and the window are passed in rather than baked into the function: they are
    policy, and policy belongs with the application.
    """
    await session.execute(
        text("SELECT auth_record_failure(:user_id, :max_attempts, :lockout)"),
        {
            "user_id": str(user_id),
            "max_attempts": max_attempts,
            "lockout": f"{int(lockout.total_seconds())} seconds",
        },
    )


async def record_verified(
    session: AsyncSession, user_id: uuid.UUID, *, new_hash: str | None = None
) -> None:
    """A password has just been proved: reset the counters, optionally take a fresher hash.

    `new_hash` is only ever supplied when Argon2's cost has been raised since the stored hash was
    written. Passing None leaves it alone.
    """
    await session.execute(
        text("SELECT auth_record_verified(:user_id, :new_hash)"),
        {"user_id": str(user_id), "new_hash": new_hash},
    )


async def record_sign_in(session: AsyncSession, user_id: uuid.UUID) -> None:
    """A session now exists.

    Separate from `record_verified` because proving a password is not the same as signing in —
    the workspace chooser sits between them, and someone who never picks a workspace has not
    signed in.
    """
    await session.execute(
        text("SELECT auth_record_sign_in(:user_id)"), {"user_id": str(user_id)}
    )
