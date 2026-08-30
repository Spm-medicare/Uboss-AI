"""The safe import, and the rule it exists to hold.

PLAN §5: *"Claude never writes the live hierarchy directly."* These prove that in the only way
that matters — by exercising the path a real upload takes and checking that nothing reaches
`org_units` until somebody applies it, and that when it does, it arrives whole or not at all.

The parsing tests need no database at all, which is the point of keeping that module pure: the
same function decides what the person sees in the preview and what gets written.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.conftest import Workspace
from uboss.core.context import SecurityContext
from uboss.core.errors import ValidationFailed
from uboss.db.base import build_sessionmaker
from uboss.modules.hierarchy import import_service, parsing
from uboss.modules.hierarchy import service as hierarchy
from uboss.modules.hierarchy.import_models import ImportStatus
from uboss.modules.identity.models import Membership
from uboss.modules.identity.service import access_for

pytestmark = pytest.mark.anyio


CLEAN = b"""Department,Parent,Position,Email,Code
Acme,,,,ACME
Operations,Acme,Head of Operations,,OPS
Operations,Acme,Analyst,,OPS
Support,Operations,Support Lead,,SUP
"""

MESSY = b"""Team,Belongs to,Job title,Widget owner
Acme,,,
Field Services,Acme,Regional Manager,Priya
"""


# ------------------------------------------------------------------ parsing, no database


def test_a_recognised_header_needs_no_model() -> None:
    """The deterministic pass is first and usually final.

    A file with ordinary headings reaches no model at all: faster, cheaper, and the same answer
    every time. The model is for what is left over, and often there is nothing left over.
    """
    sheet = parsing.read_csv(CLEAN)
    mapping, ambiguous = parsing.match_columns(sheet.columns)

    assert mapping["Department"] == "unit_name"
    assert mapping["Parent"] == "parent_name"
    assert mapping["Position"] == "position_title"
    assert mapping["Code"] == "unit_ref"
    assert ambiguous == []


def test_an_unrecognised_header_is_ambiguous_not_guessed() -> None:
    """"Widget owner" is nobody's field. Guessing is how a column silently becomes the wrong one."""
    sheet = parsing.read_csv(MESSY)
    mapping, ambiguous = parsing.match_columns(sheet.columns)

    assert mapping["Team"] == "unit_name"
    assert ambiguous == ["Widget owner"]


def test_two_columns_cannot_claim_one_field() -> None:
    """A spreadsheet with two "Code" columns is real, and picking one is a coin toss."""
    sheet = parsing.read_csv(b"Department,Code,Code\nAcme,A,B\n")
    mapping, ambiguous = parsing.match_columns(sheet.columns)

    assert list(mapping.values()).count("unit_ref") == 1
    assert len(ambiguous) == 1


def test_a_row_that_contradicts_an_earlier_one_is_an_error() -> None:
    """The same department under two different parents cannot both be true.

    Applied, it would produce one of the two and quietly discard the other — and nobody would
    know which.
    """
    sheet = parsing.read_csv(
        b"Department,Parent\nAcme,\nOperations,Acme\nOperations,Somewhere else\n"
    )
    mapping, _ = parsing.match_columns(sheet.columns)
    staged = parsing.stage(sheet, mapping)

    conflicting = [row for row in staged if row.errors]
    assert len(conflicting) == 1
    assert "Somewhere else" in conflicting[0].errors[0]


def test_one_code_on_two_different_departments_is_an_error() -> None:
    """PLAN §5's "duplicate identifiers", caught before the database has to refuse them."""
    sheet = parsing.read_csv(b"Department,Code\nOne,SAME\nTwo,SAME\n")
    mapping, _ = parsing.match_columns(sheet.columns)
    staged = parsing.stage(sheet, mapping)

    assert not staged[0].errors
    #  Named back as they were typed, and pointing at the row to look at.
    assert "“One”" in staged[1].errors[0]
    assert "row 2" in staged[1].errors[0]


def test_one_department_listed_twice_may_repeat_its_code() -> None:
    """A spreadsheet lists a department once per position. That is not a duplicate identifier.

    Reading it as one is how an ordinary two-person team makes an import fail with a message
    nobody can act on — which is exactly what the first version of this rule did.
    """
    sheet = parsing.read_csv(b"Department,Code,Position\nOps,OPS,Lead\nOps,OPS,Analyst\n")
    mapping, _ = parsing.match_columns(sheet.columns)
    staged = parsing.stage(sheet, mapping)

    assert [row.errors for row in staged] == [[], []]


def test_an_unmapped_department_name_is_refused_outright() -> None:
    """Without it there is nothing to build a tree from, so this is not a warning."""
    sheet = parsing.read_csv(b"Something,Else\na,b\n")
    with pytest.raises(ValidationFailed):
        parsing.stage(sheet, {})


def test_a_blank_header_becomes_a_named_column_rather_than_being_dropped() -> None:
    """Dropping it would shift every cell after it into the wrong column.

    That is the worst kind of silent failure: the import succeeds and the data is wrong.
    """
    sheet = parsing.read_csv(b"Department,,Position\nAcme,x,Lead\n")

    assert sheet.columns == ["Department", "Column 2", "Position"]
    assert sheet.rows[0][1]["Column 2"] == "x"


# ---------------------------------------------------------------- the import, end to end


async def _context(session: AsyncSession, workspace: Workspace) -> SecurityContext:
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(workspace.tenant_id)}
    )
    for action in ("administer", "assign"):
        await session.execute(
            text(
                "INSERT INTO role_permissions (tenant_id, role_id, action) "
                "VALUES (:t, :r, :a) ON CONFLICT DO NOTHING"
            ),
            {"t": workspace.tenant_id, "r": workspace.role_id, "a": action},
        )
    await session.flush()

    membership = await session.get(Membership, workspace.membership_id)
    assert membership is not None
    roles, granted, ceiling = await access_for(session, membership)
    now = hierarchy._now()
    return SecurityContext(
        tenant_id=workspace.tenant_id,
        user_id=workspace.user_id,
        membership_id=workspace.membership_id,
        session_id=uuid.uuid4(),
        email="person@test",
        display_name=membership.display_name,
        roles=roles,
        granted_actions=granted,
        org_node_id=membership.org_node_id,
        policy_grants=ceiling,
        step_up_at=now,
        step_up_expires_at=now + timedelta(minutes=10),
    )


class _NoStorage:
    """Stands in for object storage.

    The import's correctness has nothing to do with where the bytes went — it parses what it was
    handed. Using a stub keeps these tests from needing MinIO, and the storage path has its own
    tests in `test_files.py`.
    """

    async def put(self, key: str, data: bytes, *, content_type: str) -> object:
        from uboss.modules.files.storage import StoredObject

        import hashlib

        return StoredObject(
            key=key, size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest()
        )


async def test_an_upload_creates_nothing_in_the_live_tree(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace], settings_for_tests: object
) -> None:
    """The whole point of staging. Steps 1 and 2 touch `hierarchy_imports` and nothing else."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)

        record = await import_service.start(
            session,
            _NoStorage(),  # type: ignore[arg-type]
            settings_for_tests,  # type: ignore[arg-type]
            context,
            data=CLEAN,
            filename="structure.csv",
        )

        assert record.status in (ImportStatus.VALIDATED, ImportStatus.MAPPED)
        assert record.row_count == 4
        assert record.error_count == 0
        assert record.ignored_columns == []

        tree = await hierarchy.read_tree(session, context)
        assert tree.is_empty
        await session.rollback()


async def test_applying_builds_the_tree_and_records_where_it_came_from(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace], settings_for_tests: object
) -> None:
    """Step 7 — atomic, with the source and mapping recorded.

    §5 requires the applied import to record both. "Why does this department exist" has to be
    answerable a month later, and the answer is a revision pointing at a file and a mapping.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)

        record = await import_service.start(
            session,
            _NoStorage(),  # type: ignore[arg-type]
            settings_for_tests,  # type: ignore[arg-type]
            context,
            data=CLEAN,
            filename="structure.csv",
        )
        await import_service.apply(
            session, context, record.id, expected_version=record.version
        )
        await session.flush()

        tree = await hierarchy.read_tree(session, context)
        names = {unit.name for unit in tree.units}
        assert names == {"Acme", "Operations", "Support"}

        acme = next(unit for unit in tree.units if unit.name == "Acme")
        operations = next(unit for unit in tree.units if unit.name == "Operations")
        support = next(unit for unit in tree.units if unit.name == "Support")
        assert acme.parent_id is None
        assert operations.parent_id == acme.id
        assert support.parent_id == operations.id

        #  Three positions, and every one of them vacant: no email column was mapped, so nobody
        #  was matched. Vacant is the truth, and the tree says so rather than inventing holders.
        seats = [position for unit in tree.units for position in unit.positions]
        assert len(seats) == 3
        assert all(seat.holder is None for seat in seats)

        page = await hierarchy.revisions(session, context)
        imported = page.revisions[0]
        assert imported.change_type == "hierarchy.imported"
        assert "structure.csv" in imported.summary or "departments" in imported.summary
        await session.rollback()


async def test_an_import_with_errors_cannot_be_applied(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace], settings_for_tests: object
) -> None:
    """Known bad rows would put known bad data into what every permission scope reads from."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)

        record = await import_service.start(
            session,
            _NoStorage(),  # type: ignore[arg-type]
            settings_for_tests,  # type: ignore[arg-type]
            context,
            data=b"Department,Code\nOne,SAME\nTwo,SAME\n",
            filename="dupes.csv",
        )
        assert record.error_count == 1

        with pytest.raises(ValidationFailed):
            await import_service.apply(
                session, context, record.id, expected_version=record.version
            )

        tree = await hierarchy.read_tree(session, context)
        assert tree.is_empty
        await session.rollback()


async def test_no_model_configured_is_stated_not_hidden(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace], settings_for_tests: object
) -> None:
    """Step 3, with no key configured.

    `consulted: false` and a reason. The screen has to be able to say "no model was consulted" in
    those words — an empty suggestion list looks identical to a model that had no ideas, and they
    are different facts.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)

        record = await import_service.start(
            session,
            _NoStorage(),  # type: ignore[arg-type]
            settings_for_tests,  # type: ignore[arg-type]
            context,
            data=MESSY,
            filename="messy.csv",
        )
        assert record.ignored_columns == ["Widget owner"]

        record = await import_service.propose_mapping(
            session,
            _NoStorage(),  # type: ignore[arg-type]
            settings_for_tests,  # type: ignore[arg-type]
            context,
            record.id,
        )

        assert record.proposal is not None
        assert record.proposal["consulted"] is False
        assert record.proposal["reason"]
        assert record.proposal["suggestions"] == []
        await session.rollback()


async def test_confirming_a_mapping_restages_every_row(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace], settings_for_tests: object
) -> None:
    """Step 4. The preview and the apply come from the same code, so they cannot disagree.

    Mapping "Widget owner" to the person's name changes what every row means, and the staged
    rows have to change with it.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)

        record = await import_service.start(
            session,
            _NoStorage(),  # type: ignore[arg-type]
            settings_for_tests,  # type: ignore[arg-type]
            context,
            data=MESSY,
            filename="messy.csv",
        )

        record = await import_service.set_mapping(
            session,
            _NoStorage(),  # type: ignore[arg-type]
            settings_for_tests,  # type: ignore[arg-type]
            context,
            record.id,
            mapping={
                "Team": "unit_name",
                "Belongs to": "parent_name",
                "Job title": "position_title",
                "Widget owner": "person_name",
            },
            expected_version=record.version,
        )

        assert record.ignored_columns == []
        assert record.column_mapping["Widget owner"]["source"] == "chosen"

        preview = await import_service.preview(session, context, record.id)
        field_services = next(
            unit for unit in preview.proposed_tree if unit["name"] == "Field Services"
        )
        assert field_services["positions"][0]["person_name"] == "Priya"
        await session.rollback()
