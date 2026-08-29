"""Optimistic concurrency: two people editing the same thing, and neither one losing.

PLAN §28: "Optimistic concurrency prevents silent overwrite." PLAN §30: "A Draft is mutable with
optimistic concurrency."

The failure this prevents has no error message of its own, which is what makes it dangerous. Two
people open the same draft. One saves. The other saves. The second write lands on top and the
first person's work is gone — no exception, no warning, nothing in a log. They find out days
later, if at all.

The fix is to make the update say what it expected to find:

    UPDATE ... SET ... WHERE id = :id AND version = :expected

Zero rows changed means someone else got there first. The caller is told to re-read and decide,
which is the only honest answer: the server cannot know whether the two edits conflict or
complement.

**Retrying a conflict is never automatic.** A client that re-sends its stale write with a fresh
version has simply performed the silent overwrite by hand.
"""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import Update, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

from uboss.core.errors import Conflict

#: The header a client sends the version it read in. `If-Match` is the HTTP-native way to say
#: "only if it still looks like this", and using it means a cache or a proxy on the path
#: understands the intent rather than seeing an opaque body field.
VERSION_HEADER = "If-Match"


class VersionConflict(Conflict):
    """Someone else changed the record between the caller's read and their write.

    A 409, not a 500: nothing is broken. The caller re-reads, sees what changed, and decides.
    """

    code = "version_conflict"

    def __init__(self, what: str = "This record") -> None:
        super().__init__(
            f"{what} was changed by someone else while you were editing. "
            "Reload to see their changes, then apply yours."
        )


def guarded_update(
    model: type[DeclarativeBase],
    *,
    row_id: Any,
    tenant_id: Any,
    expected_version: int,
    values: dict[str, Any],
) -> Update:
    """Build an `UPDATE` that only lands if the row is still the version the caller read.

    The version is incremented here rather than by the caller. A caller that had to remember
    would eventually forget, and a row whose version stops moving is a row that has silently
    stopped being protected.

    `tenant_id` is in the predicate as well as being enforced by row-level security. Belt and
    braces: RLS refuses the row, this makes the statement say what it means.
    """
    return (
        update(model)
        .where(
            model.id == row_id,  # type: ignore[attr-defined]
            model.tenant_id == tenant_id,  # type: ignore[attr-defined]
            model.version == expected_version,  # type: ignore[attr-defined]
        )
        .values(**values, version=expected_version + 1)
    )


async def apply_guarded_update(
    session: AsyncSession,
    model: type[DeclarativeBase],
    *,
    row_id: Any,
    tenant_id: Any,
    expected_version: int,
    values: dict[str, Any],
    what: str = "This record",
) -> None:
    """Run the guarded update, and refuse if it matched nothing.

    Zero rows means one of two things — the row moved on, or it never existed for this tenant —
    and the caller is told the first. That is deliberate: distinguishing them would tell someone
    that a record they cannot see exists.
    """
    #  `CursorResult` is what an UPDATE actually returns; the base `Result` protocol has no
    #  rowcount, so the narrowing is explicit rather than ignored.
    result = cast(
        "CursorResult[Any]",
        await session.execute(
            guarded_update(
                model,
                row_id=row_id,
                tenant_id=tenant_id,
                expected_version=expected_version,
                values=values,
            )
        ),
    )
    if result.rowcount == 0:
        raise VersionConflict(what)
