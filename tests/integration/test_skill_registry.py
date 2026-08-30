"""The Skill Registry — the seed, its boundary, and the import that maintains it.

PLAN §39 keeps the catalogue as *"a client-owned seed asset"*. Two things about it have to hold
and neither is obvious from reading the schema:

* the 400 rows are **shared** — one copy, readable by every tenant, writable by none;
* a tenant's own Skill Draft is **private**, and cannot publish itself.

The import is tested against the real workbook when it is present, and skipped with a stated
reason when it is not — a suite that silently passed without the catalogue would be proving
nothing about the thing it is named after.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.conftest import Workspace
from uboss.db.base import build_sessionmaker
from uboss.modules.agents.models import (
    Skill,
    SkillExactnessGate,
    SkillRule,
)
from uboss.modules.agents.seed import catalogue_counts, import_catalogue

pytestmark = pytest.mark.anyio

#: The approved workbook, where a developer's checkout keeps it.
WORKBOOK = Path(
    r"C:\Users\Adminb\Desktop\Uboss Ai\Universal_Enterprise_Skill_Catalog_IF_THEN (1).xlsx"
)

#: What the approved sheet contains. Asserted rather than counted from the file, so a workbook
#: that lost half its rows fails the test instead of redefining what "complete" means.
EXPECTED = {"archetypes": 12, "gates": 12, "skills": 400, "rules": 2400}


needs_workbook = pytest.mark.skipif(
    not WORKBOOK.exists(),
    reason=(
        "The approved Skill Catalogue workbook is not on this machine. These tests import the "
        "real 400 skills and 2,400 rules; running them against a fixture would prove nothing "
        "about the catalogue."
    ),
)


@needs_workbook
async def test_the_whole_catalogue_imports_with_nothing_skipped(
    owner_session: AsyncSession,
) -> None:
    """400 skills, 2,400 rules, 12 archetypes, 12 gates — and no row reported as unusable.

    A skipped row means the sheet and the importer disagree, which is a thing somebody has to
    decide about rather than a number to watch drift.
    """
    report = await import_catalogue(owner_session, WORKBOOK)

    assert report.skipped == []
    assert report.archetypes == EXPECTED["archetypes"]
    assert report.gates == EXPECTED["gates"]
    assert report.total_skills == EXPECTED["skills"]
    assert report.total_rules == EXPECTED["rules"]
    await owner_session.rollback()


@needs_workbook
async def test_importing_twice_does_not_double_anything(
    owner_session: AsyncSession,
) -> None:
    """Matched on the catalogue's own ids.

    The seed is re-imported every time the workbook is corrected. An importer that appended would
    leave two `U-001`s and no way to tell which one a search returned.
    """
    first = await import_catalogue(owner_session, WORKBOOK)
    second = await import_catalogue(owner_session, WORKBOOK)

    assert first.skills_created == EXPECTED["skills"]
    assert second.skills_created == 0
    assert second.skills_updated == EXPECTED["skills"]
    assert second.rules_created == 0

    counts = await catalogue_counts(owner_session)
    assert counts == EXPECTED
    await owner_session.rollback()


@needs_workbook
async def test_every_gate_carries_the_failure_state_the_sheet_gives_it(
    owner_session: AsyncSession,
) -> None:
    """§39's *"deterministic compatibility gates"*, in the catalogue's own words.

    The resolver quotes these verbatim, so a refusal reads the same on screen as it does in the
    approved sheet — rather than a message somebody invented alongside it.
    """
    await import_catalogue(owner_session, WORKBOOK)

    gates = list(
        (
            await owner_session.execute(
                select(SkillExactnessGate).order_by(SkillExactnessGate.position)
            )
        )
        .scalars()
        .all()
    )
    assert [gate.id for gate in gates] == [f"E{n:02d}" for n in range(1, 13)]
    assert all(gate.failure_state for gate in gates)
    #  The one everybody quotes, checked exactly.
    scope = next(gate for gate in gates if gate.id == "E01")
    assert "ambiguous scope" in scope.failure_state
    await owner_session.rollback()


@needs_workbook
async def test_every_rule_belongs_to_a_skill_that_exists(
    owner_session: AsyncSession,
) -> None:
    """The two sheets have to agree.

    A rule pointing at a skill the catalogue does not contain is reported by the importer rather
    than dropped, and this proves there are none in the approved workbook.
    """
    await import_catalogue(owner_session, WORKBOOK)

    orphans = (
        await owner_session.execute(
            select(func.count())
            .select_from(SkillRule)
            .outerjoin(Skill, Skill.id == SkillRule.skill_id)
            .where(Skill.id.is_(None))
        )
    ).scalar_one()
    assert orphans == 0

    #  And every skill has at least one rule: a skill with none is a skill the registry can
    #  return but never gate, which is the failure mode §39 exists to prevent.
    without_rules = (
        await owner_session.execute(
            select(func.count())
            .select_from(Skill)
            .where(
                Skill.catalogue_id.is_not(None),
                ~select(SkillRule.id)
                .where(SkillRule.skill_id == Skill.id)
                .exists(),
            )
        )
    ).scalar_one()
    assert without_rules == 0
    await owner_session.rollback()


@needs_workbook
async def test_autonomy_is_stored_as_a_code_the_resolver_can_compare(
    owner_session: AsyncSession,
) -> None:
    """The sheet writes "A1 — Read / analyze"; only the code is kept.

    A ceiling has to be comparable. Storing the prose would mean the resolver parsing a sentence
    every time it asked whether a skill may write.
    """
    await import_catalogue(owner_session, WORKBOOK)

    levels = {
        value
        for (value,) in (
            await owner_session.execute(
                select(Skill.autonomy).where(Skill.catalogue_id.is_not(None)).distinct()
            )
        ).all()
    }
    assert levels <= {"A1", "A2", "A3", "A4"}
    await owner_session.rollback()


# ------------------------------------------------------------------- the boundary


async def test_the_catalogue_is_readable_by_every_tenant(
    owner_engine: AsyncEngine,
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
) -> None:
    """One copy, shared. Copying 400 rows per tenant would mean 400 copies of a correction.

    Seeded here with one row rather than the whole workbook: this is testing the boundary, and a
    boundary test that needed 400 rows to run would be a slower test proving the same thing.
    """
    left, right = two_workspaces
    catalogue_id = f"T-{uuid.uuid4().hex[:6]}"

    async with build_sessionmaker(owner_engine)() as owner:
        owner.add(
            Skill(
                tenant_id=None,
                catalogue_id=catalogue_id,
                name="A shared catalogue skill",
                layer="Universal Department",
            )
        )
        await owner.commit()

    try:
        async with build_sessionmaker(app_engine)() as session:
            for workspace in (left, right):
                await session.execute(
                    text("SELECT set_config('app.tenant_id', :t, true)"),
                    {"t": str(workspace.tenant_id)},
                )
                visible = (
                    await session.execute(
                        select(func.count())
                        .select_from(Skill)
                        .where(Skill.catalogue_id == catalogue_id)
                    )
                ).scalar_one()
                #  The same row, from both organisations.
                assert visible == 1
            await session.rollback()
    finally:
        #  Removed as the owner, because the application role cannot touch the catalogue — which
        #  is the very thing the next test asserts.
        async with build_sessionmaker(owner_engine)() as owner:
            await owner.execute(
                text("DELETE FROM skills WHERE catalogue_id = :c"), {"c": catalogue_id}
            )
            await owner.commit()


async def test_the_application_role_cannot_write_the_catalogue(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """The seed is corrected by a migration or the import script, never by the product.

    The write policy has no catalogue branch at all, so an insert with no tenant fails the row
    check rather than succeeding quietly into shared reference data.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(left.tenant_id)}
        )

        with pytest.raises(DBAPIError):
            await session.execute(
                text(
                    "INSERT INTO skills (tenant_id, catalogue_id, name, layer) "
                    "VALUES (NULL, 'U-999', 'Sneaked in', 'Universal Department')"
                )
            )
        await session.rollback()


async def test_a_private_skill_is_invisible_to_another_tenant(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """A Skill Draft belongs to one organisation. The catalogue is shared; a draft is not."""
    left, right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(left.tenant_id)}
        )
        session.add(
            Skill(
                tenant_id=left.tenant_id,
                catalogue_id=None,
                name="Our own quoting check",
                layer="Universal Department",
                status="draft",
            )
        )
        await session.flush()

        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(right.tenant_id)}
        )
        theirs = (
            await session.execute(
                select(func.count())
                .select_from(Skill)
                .where(Skill.tenant_id.is_not(None))
            )
        ).scalar_one()
        assert theirs == 0
        await session.rollback()


async def test_a_skill_is_either_catalogue_or_private_and_never_both(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """A row with both a tenant and a catalogue id is one nobody could classify."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(left.tenant_id)}
        )
        session.add(
            Skill(
                tenant_id=left.tenant_id,
                catalogue_id="U-001",
                name="Both at once",
                layer="Universal Department",
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()


async def test_a_private_skill_cannot_publish_itself(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """PLAN §39: *"Skills cannot self-publish."*

    Held by the schema rather than by whichever service happens to write the row, so a future
    importer or a bulk path cannot get around it either.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(left.tenant_id)}
        )
        session.add(
            Skill(
                tenant_id=left.tenant_id,
                catalogue_id=None,
                name="Straight to published",
                layer="Universal Department",
                status="published",
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()


async def test_the_model_registry_lists_every_table_in_the_database(
    owner_session: AsyncSession,
) -> None:
    """`db/registry.py` exists because four modules had drifted off `env.py`'s import list.

    Its own comment said an omission "would generate a DROP for a live table", so this compares
    what SQLAlchemy knows against what is actually there. A new module that forgets the registry
    fails here rather than in a migration somebody runs against production.
    """
    from uboss.db.registry import metadata

    known = {table.name for table in metadata().sorted_tables}  # type: ignore[attr-defined]
    live = {
        name
        for (name,) in (
            await owner_session.execute(
                text(
                    "SELECT tablename FROM pg_tables "
                    "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
                )
            )
        ).all()
    }

    missing = live - known
    assert not missing, f"models not imported by db/registry.py: {sorted(missing)}"
