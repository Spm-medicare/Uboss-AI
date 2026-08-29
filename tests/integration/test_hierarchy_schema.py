"""What the hierarchy schema refuses.

PLAN §5 asks the product to *"detect cycles, orphan managers and duplicate identifiers"* and to
keep *"effective-dated assignments"* straight. Each of those is enforced by the database, and
these tests exist to say so — because the reason they are in the database rather than in the
service is that Gate 2.3 applies an imported tree in bulk, and a rule the service enforces is a
rule a bulk path can be written around.

Every test here writes as the **owner**, which is the strongest case: if a constraint holds
against the role that owns the schema, it holds against the application role too.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import Workspace

pytestmark = pytest.mark.anyio


async def _bind(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
    )


async def _unit(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    name: str,
    parent: uuid.UUID | None = None,
    unit_type: str = "department",
    external_ref: str | None = None,
) -> uuid.UUID:
    return (
        await session.execute(
            text(
                "INSERT INTO org_units (tenant_id, parent_id, name, unit_type, external_ref) "
                "VALUES (:t, :p, :n, :ty, :ref) RETURNING id"
            ),
            {"t": tenant_id, "p": parent, "n": name, "ty": unit_type, "ref": external_ref},
        )
    ).scalar_one()


async def _position(
    session: AsyncSession, tenant_id: uuid.UUID, unit: uuid.UUID, title: str
) -> uuid.UUID:
    return (
        await session.execute(
            text(
                "INSERT INTO positions (tenant_id, org_unit_id, title) "
                "VALUES (:t, :u, :title) RETURNING id"
            ),
            {"t": tenant_id, "u": unit, "title": title},
        )
    ).scalar_one()


async def test_a_unit_cannot_become_its_own_ancestor(
    owner_session: AsyncSession, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """A cycle makes every scope query non-terminating, so the write is refused outright."""
    left, _ = two_workspaces
    await _bind(owner_session, left.tenant_id)

    root = await _unit(owner_session, left.tenant_id, name="Acme", unit_type="company")
    ops = await _unit(owner_session, left.tenant_id, name="Operations", parent=root)
    team = await _unit(owner_session, left.tenant_id, name="Support", parent=ops)
    await owner_session.flush()

    with pytest.raises(DBAPIError):
        await owner_session.execute(
            text("UPDATE org_units SET parent_id = :child WHERE id = :root"),
            {"child": team, "root": root},
        )
    await owner_session.rollback()


async def test_a_tenant_has_one_root(
    owner_session: AsyncSession, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Two roots is two trees, and every scope query would have to decide which it meant."""
    left, _ = two_workspaces
    await _bind(owner_session, left.tenant_id)

    await _unit(owner_session, left.tenant_id, name="Acme", unit_type="company")
    await owner_session.flush()

    with pytest.raises(IntegrityError):
        await _unit(owner_session, left.tenant_id, name="Also Acme", unit_type="company")
    await owner_session.rollback()


async def test_two_organisations_may_reuse_one_external_reference(
    owner_session: AsyncSession, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Uniqueness is per tenant, never global.

    Two unrelated customers both calling a cost centre `OPS-01` is ordinary. A global unique
    index would make the second one fail, and the message would say nothing that made sense to
    them.
    """
    left, right = two_workspaces

    await _bind(owner_session, left.tenant_id)
    await _unit(
        owner_session, left.tenant_id, name="Acme", unit_type="company", external_ref="OPS-01"
    )
    await _bind(owner_session, right.tenant_id)
    await _unit(
        owner_session, right.tenant_id, name="Globex", unit_type="company", external_ref="OPS-01"
    )
    await owner_session.flush()

    #  And a duplicate inside one of them is still refused.
    with pytest.raises(IntegrityError):
        await _unit(
            owner_session,
            right.tenant_id,
            name="Second",
            parent=None,
            external_ref="OPS-01",
        )
    await owner_session.rollback()


async def test_a_seat_has_one_holder_at_a_time(
    owner_session: AsyncSession, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """PLAN §5's effective dating, enforced rather than assumed.

    Two concurrent requests that each check before writing will both find the seat empty. Only
    the exclusion constraint refuses the second.
    """
    left, _ = two_workspaces
    await _bind(owner_session, left.tenant_id)

    root = await _unit(owner_session, left.tenant_id, name="Acme", unit_type="company")
    seat = await _position(owner_session, left.tenant_id, root, "Regional Manager")

    async def assign(start: date, end: date | None) -> None:
        await owner_session.execute(
            text(
                "INSERT INTO position_assignments "
                "(tenant_id, position_id, membership_id, effective_from, effective_to) "
                "VALUES (:t, :p, :m, :f, :to)"
            ),
            {
                "t": left.tenant_id,
                "p": seat,
                "m": left.membership_id,
                "f": start,
                "to": end,
            },
        )

    await assign(date(2026, 1, 1), date(2026, 6, 1))
    #  Starts the day the last one ended. `effective_to` is exclusive, so these do not overlap —
    #  a handover with no gap and no double-booking.
    await assign(date(2026, 6, 1), None)
    await owner_session.flush()

    with pytest.raises(IntegrityError):
        await assign(date(2026, 9, 1), None)
    await owner_session.rollback()


async def test_a_position_reports_to_one_primary_manager_at_a_time(
    owner_session: AsyncSession, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Two primary lines at once means an approval with two destinations and no rule."""
    left, _ = two_workspaces
    await _bind(owner_session, left.tenant_id)

    root = await _unit(owner_session, left.tenant_id, name="Acme", unit_type="company")
    analyst = await _position(owner_session, left.tenant_id, root, "Analyst")
    manager = await _position(owner_session, left.tenant_id, root, "Manager")
    director = await _position(owner_session, left.tenant_id, root, "Director")

    async def report_to(manager_id: uuid.UUID, kind: str, start: date) -> None:
        await owner_session.execute(
            text(
                "INSERT INTO reporting_edges "
                "(tenant_id, position_id, manager_position_id, kind, effective_from) "
                "VALUES (:t, :p, :m, :k, :f)"
            ),
            {"t": left.tenant_id, "p": analyst, "m": manager_id, "k": kind, "f": start},
        )

    await report_to(manager, "primary", date(2026, 1, 1))
    #  A dotted line alongside the primary one is the whole point of having two kinds. Asserted
    #  before the refusal below, because the rollback that refusal needs would take these
    #  positions with it.
    await report_to(director, "dotted", date(2026, 3, 1))
    await owner_session.flush()

    with pytest.raises(IntegrityError):
        await report_to(director, "primary", date(2026, 3, 1))
    await owner_session.rollback()


async def test_a_reporting_loop_is_refused(
    owner_session: AsyncSession, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Escalation walks this graph. A loop is an approval that never reaches a person."""
    left, _ = two_workspaces
    await _bind(owner_session, left.tenant_id)

    root = await _unit(owner_session, left.tenant_id, name="Acme", unit_type="company")
    a = await _position(owner_session, left.tenant_id, root, "A")
    b = await _position(owner_session, left.tenant_id, root, "B")
    c = await _position(owner_session, left.tenant_id, root, "C")

    async def report_to(child: uuid.UUID, manager: uuid.UUID, kind: str = "primary") -> None:
        await owner_session.execute(
            text(
                "INSERT INTO reporting_edges "
                "(tenant_id, position_id, manager_position_id, kind, effective_from) "
                "VALUES (:t, :p, :m, :k, DATE '2026-01-01')"
            ),
            {"t": left.tenant_id, "p": child, "m": manager, "k": kind},
        )

    await report_to(a, b)
    await report_to(b, c)
    await owner_session.flush()

    #  C reporting to A closes the ring A -> B -> C -> A.
    with pytest.raises(DBAPIError):
        await report_to(c, a)
    await owner_session.rollback()


async def test_revision_numbers_have_no_gaps(
    owner_session: AsyncSession, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """A gap is indistinguishable from a deletion, which is what the history exists to prevent.

    Also: the numbering is per tenant. Two organisations both start at 1, and neither can infer
    how much the other has changed from the number on its own rows.
    """
    left, right = two_workspaces

    async def revise(workspace: Workspace, summary: str) -> None:
        await _bind(owner_session, workspace.tenant_id)
        await owner_session.execute(
            text(
                "INSERT INTO org_revisions "
                "(tenant_id, change_type, entity_type, entity_id, summary) "
                "VALUES (:t, 'unit.created', 'org_unit', gen_random_uuid(), :s)"
            ),
            {"t": workspace.tenant_id, "s": summary},
        )

    await revise(left, "one")
    await revise(right, "one elsewhere")
    await revise(left, "two")
    await revise(left, "three")
    await owner_session.flush()

    await _bind(owner_session, left.tenant_id)
    numbers = list(
        (
            await owner_session.execute(
                text(
                    "SELECT revision_no FROM org_revisions WHERE tenant_id = :t "
                    "ORDER BY revision_no"
                ),
                {"t": left.tenant_id},
            )
        ).scalars()
    )
    assert numbers == [1, 2, 3]

    await _bind(owner_session, right.tenant_id)
    assert (
        await owner_session.execute(
            text("SELECT revision_no FROM org_revisions WHERE tenant_id = :t"),
            {"t": right.tenant_id},
        )
    ).scalar_one() == 1

    #  Left open, this transaction holds a lock the fixture teardown needs to lift the
    #  append-only trigger — and the suite deadlocks rather than failing.
    await owner_session.rollback()


async def test_the_revision_history_cannot_be_rewritten(
    owner_session: AsyncSession, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Append-only, like `audit_events`. A history somebody can edit is not a history."""
    left, _ = two_workspaces
    await _bind(owner_session, left.tenant_id)

    async def write_one() -> None:
        await _bind(owner_session, left.tenant_id)
        await owner_session.execute(
            text(
                "INSERT INTO org_revisions "
                "(tenant_id, change_type, entity_type, entity_id, summary) "
                "VALUES (:t, 'unit.created', 'org_unit', gen_random_uuid(), 'as written')"
            ),
            {"t": left.tenant_id},
        )
        await owner_session.flush()

    #  Written again before the second attempt: the rollback the first refusal needs also
    #  discards the row, and a DELETE that matches nothing never reaches the trigger — the test
    #  would pass while proving nothing.
    await write_one()
    with pytest.raises(DBAPIError):
        await owner_session.execute(
            text("UPDATE org_revisions SET summary = 'rewritten' WHERE tenant_id = :t"),
            {"t": left.tenant_id},
        )
    await owner_session.rollback()

    await write_one()
    with pytest.raises(DBAPIError):
        await owner_session.execute(
            text("DELETE FROM org_revisions WHERE tenant_id = :t"), {"t": left.tenant_id}
        )
    await owner_session.rollback()
