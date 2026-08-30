"""The seven steps of PLAN §5's safe import, and the rule they exist to hold.

    1. Upload into quarantine and scan/validate.
    2. Parse sheets and columns deterministically.
    3. Claude proposes only ambiguous column mappings.
    4. User reviews mapping and ignored columns.
    5. Show row errors, warnings and proposed tree.
    6. User edits and confirms change summary.
    7. Backend applies atomically and records source/mapping/audit.

    Claude never writes the live hierarchy directly.

Everything here serves that last line. The model is asked about column *headings* and nothing
else — never about the rows, never about the tree, never about what to create. Its answer is a
suggestion attached to an import, and it does not become a mapping until a person accepts it.

**Deterministic first, model second, and usually never.** `match_columns` decides every heading
it recognises. Only what is left goes to the model, so a file with ordinary headings is imported
with no model call at all — which is faster, cheaper, and produces the same answer every time.

**The apply is one transaction.** A half-applied org chart is worse than a failed one: nobody can
tell which half is real. Either the whole staged tree exists afterwards or none of it does.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from uboss.core.context import SecurityContext
from uboss.core.errors import Conflict, NotFound, ValidationFailed
from uboss.core.permissions import Action
from uboss.core.settings import Settings
from uboss.modules.ai_gateway import service as ai
from uboss.modules.ai_gateway.contract import ModelUnavailableError, Task, TaskKind
from uboss.modules.files import service as files
from uboss.modules.files.models import Classification
from uboss.modules.files.storage import Storage
from uboss.modules.hierarchy import parsing
from uboss.modules.hierarchy import service as hierarchy
from uboss.modules.hierarchy.import_models import (
    HierarchyImport,
    HierarchyImportRow,
    ImportStatus,
    MappingSource,
)
from uboss.modules.hierarchy.models import OrgUnit, Position, PositionAssignment
from uboss.modules.identity import guard

#: What the model is told, in full. Short on purpose: a long prompt for a small task is a long
#: prompt to keep true as the field list changes.
MAPPING_INSTRUCTIONS = """\
You map spreadsheet column headings to fields in an organisation-structure importer.

You are given headings that an exact-match pass could not place, the fields still unclaimed, and
two example values per heading. Return one entry per heading you are confident about.

Rules:
- Only use field names from the list you are given. Never invent one.
- One field per heading, and never a field that is already taken.
- If a heading does not clearly mean one of the fields, leave it out. An omission is reviewed as
  "ignored"; a wrong guess silently reshapes somebody's organisation.
- Confidence is your own estimate between 0 and 1. Below 0.6 will not be shown as a suggestion.
"""

MAPPING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "mappings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "column": {"type": "string"},
                    "field": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "why": {"type": "string"},
                },
                "required": ["column", "field", "confidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["mappings"],
    "additionalProperties": False,
}

#: Below this, a suggestion is not shown. A low-confidence guess a person waves through is worse
#: than no guess, because it arrives wearing the same clothes as a good one.
MIN_CONFIDENCE = 0.6


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class Preview:
    """What a person is shown before deciding — PLAN §5 step 5."""

    import_id: uuid.UUID
    status: str
    source_columns: list[str]
    column_mapping: dict[str, Any]
    ignored_columns: list[str]
    proposal: dict[str, Any] | None
    row_count: int
    error_count: int
    warning_count: int
    #: The tree as it would be, built from the staged rows and nothing else.
    proposed_tree: list[dict[str, Any]]
    #: Every row, with what is wrong with it. Capped for the response; the count is exact.
    rows: list[dict[str, Any]]
    can_apply: bool


# --------------------------------------------------------------------- 1 and 2: upload


async def start(
    session: AsyncSession,
    storage: Storage,
    settings: Settings,
    context: SecurityContext,
    *,
    data: bytes,
    filename: str,
    sheet_name: str | None = None,
) -> HierarchyImport:
    """Take the file, park it, and read it. Nothing is created in the live tree.

    The file is stored as `pending` in `files` and stays there for its whole life. An import
    source is never served back to a browser, so it never needs to leave quarantine — and while
    no malware scanner is configured, `pending` is the honest state rather than a `clean` nobody
    checked.

    Parsing happens on the bytes already in hand, not on a re-download. The reader is read-only
    and values-only: no formula is evaluated and no linked workbook is fetched.
    """
    await guard.authorise(session, context, Action.ADMINISTER)

    sheet = parsing.read(data, filename, sheet_name)
    if not sheet.rows:
        raise ValidationFailed("That file has a header but no rows.")

    upload = await files.store(
        session,
        storage,
        settings,
        context,
        data=data,
        original_name=filename,
        #  Not the browser's content type: this is what the file was read as, which is the fact
        #  worth keeping.
        content_type="text/csv" if filename.lower().endswith(".csv") else "application/xlsx",
        #  An org chart is a list of employees. It is personal data, and saying so here is what
        #  makes the retention and privacy controls in PLAN §19 able to act on it.
        classification=Classification.PERSONAL_DATA,
        owner_type="hierarchy_import",
    )

    mapping, ambiguous = parsing.match_columns(sheet.columns)

    record = HierarchyImport(
        tenant_id=context.tenant_id,
        file_id=upload.file_id,
        status=ImportStatus.PARSED,
        sheet_name=sheet.name,
        source_columns=sheet.columns,
        column_mapping={
            column: {"field": field, "source": MappingSource.EXACT.value}
            for column, field in mapping.items()
        },
        ignored_columns=ambiguous,
        row_count=len(sheet.rows),
        created_by_membership_id=context.membership_id,
    )
    session.add(record)
    await session.flush()

    #  The file now belongs to this import, so a retention sweep can find one from the other.
    file_row = await files.find(session, context, upload.file_id)
    file_row.owner_id = record.id

    await _stage_rows(session, context, record, sheet, mapping)
    return record


# ------------------------------------------------------------------ 3: the model's part


async def propose_mapping(
    session: AsyncSession,
    storage: Storage,
    settings: Settings,
    context: SecurityContext,
    import_id: uuid.UUID,
) -> HierarchyImport:
    """Ask a model about the headings nothing matched — and only those.

    Returns the import unchanged when there is nothing ambiguous, which is the common case: a
    file with ordinary headings never reaches a model at all.

    A failure here is not a failure of the import. `ModelUnavailableError` is recorded on the import
    so the screen can say "no model was consulted" in those words, and the person maps the
    remaining columns by hand. Presenting a deterministic result as a model's work — or the
    reverse — is the thing this must never do.
    """
    await guard.authorise(session, context, Action.ADMINISTER)
    record = await _get(session, import_id)

    if not record.ignored_columns:
        return record

    claimed = {entry["field"] for entry in record.column_mapping.values()}
    available = [
        {"field": item.name, "means": item.description}
        for item in parsing.FIELDS
        if item.name not in claimed
    ]
    if not available:
        return record

    samples = await _samples(session, record, record.ignored_columns)
    task = Task(
        kind=TaskKind.COLUMN_MAPPING,
        instructions=MAPPING_INSTRUCTIONS,
        input=json.dumps(
            {
                "unplaced_headings": [
                    {"heading": column, "examples": samples.get(column, [])}
                    for column in record.ignored_columns
                ],
                "available_fields": available,
            },
            ensure_ascii=False,
        ),
        schema=MAPPING_SCHEMA,
    )

    try:
        completion = await ai.run(session, settings, context, task)
    except ModelUnavailableError as unavailable:
        record.proposal = {
            "consulted": False,
            "reason": str(unavailable),
            "suggestions": [],
        }
        record.version += 1
        await session.flush()
        return record

    suggestions: list[dict[str, Any]] = []
    taken = set(claimed)
    for entry in completion.content.get("mappings", []):
        column = str(entry.get("column", ""))
        field = str(entry.get("field", ""))
        confidence = float(entry.get("confidence", 0))
        #  Every one of these checks has caught a real model answer at some point: a heading it
        #  invented, a field that does not exist, a field already used, or a guess it was not
        #  confident about. None of them is a reason to distrust the model; all of them are
        #  reasons not to let one wrong answer through into somebody's organisation.
        if column not in record.ignored_columns:
            continue
        if field not in parsing.FIELDS_BY_NAME or field in taken:
            continue
        if confidence < MIN_CONFIDENCE:
            continue
        taken.add(field)
        suggestions.append(
            {
                "column": column,
                "field": field,
                "confidence": confidence,
                "why": str(entry.get("why", ""))[:400],
            }
        )

    record.proposal = {
        "consulted": True,
        "model": completion.model,
        "suggestions": suggestions,
        #  Recorded so the review screen can say how many were dropped rather than quietly
        #  showing fewer than the model returned.
        "returned": len(completion.content.get("mappings", [])),
        "at": _now().isoformat(),
    }
    record.version += 1
    await session.flush()
    return record


async def _samples(
    session: AsyncSession, record: HierarchyImport, columns: list[str], limit: int = 2
) -> dict[str, list[str]]:
    """A couple of example values per heading, so the model has something to reason from.

    Two, not twenty. The heading is the question; the values are context. Sending more would put
    more of somebody's employee list into a prompt for no better answer.
    """
    rows = (
        await session.execute(
            select(HierarchyImportRow.raw)
            .where(HierarchyImportRow.import_id == record.id)
            .order_by(HierarchyImportRow.row_number)
            .limit(limit)
        )
    ).scalars()

    samples: dict[str, list[str]] = {column: [] for column in columns}
    for raw in rows:
        for column in columns:
            value = str(raw.get(column, "")).strip()
            if value:
                samples[column].append(value[:80])
    return samples


# ------------------------------------------------------------ 4 and 5: review and edit


async def set_mapping(
    session: AsyncSession,
    storage: Storage,
    settings: Settings,
    context: SecurityContext,
    import_id: uuid.UUID,
    *,
    mapping: dict[str, str],
    expected_version: int,
) -> HierarchyImport:
    """Apply the mapping a person confirmed, and restage every row against it.

    Restaged rather than patched: the same function that produced the preview produces what will
    be applied, so the two cannot drift. A mapping change that only updated the summary would
    show a tree nobody had actually built.

    Everything not in `mapping` becomes an ignored column — stated, so "we ignored six columns"
    is something the person read rather than something they discover afterwards.
    """
    await guard.authorise(session, context, Action.ADMINISTER)
    record = await _get(session, import_id)
    if record.status == ImportStatus.APPLIED:
        raise ValidationFailed("This import has already been applied.")
    if record.version != expected_version:
        raise Conflict("Somebody else changed this import. Reload it and try again.")

    unknown = [field for field in mapping.values() if field not in parsing.FIELDS_BY_NAME]
    if unknown:
        raise ValidationFailed(f"Unknown field: {unknown[0]}.")
    missing = [column for column in mapping if column not in record.source_columns]
    if missing:
        raise ValidationFailed(f"That file has no column called “{missing[0]}”.")
    if len(set(mapping.values())) != len(mapping):
        raise ValidationFailed("Two columns cannot mean the same field.")

    proposed = {
        entry["column"]: entry["field"] for entry in (record.proposal or {}).get("suggestions", [])
    }
    record.column_mapping = {
        column: {
            "field": field,
            #  A model's suggestion a person accepted unchanged is still recorded as proposed.
            #  The audit question is "where did this come from", and "a person clicked past it"
            #  is a different answer from "a person chose it".
            "source": (
                MappingSource.PROPOSED.value
                if proposed.get(column) == field
                else MappingSource.CHOSEN.value
            ),
        }
        for column, field in mapping.items()
    }
    record.ignored_columns = [column for column in record.source_columns if column not in mapping]
    record.status = ImportStatus.MAPPED
    record.version += 1

    sheet = await _reread(session, record)
    await _stage_rows(session, context, record, sheet, mapping)
    return record


async def preview(
    session: AsyncSession, context: SecurityContext, import_id: uuid.UUID, *, limit: int = 200
) -> Preview:
    """Everything a person needs to decide — the mapping, the rows, and the tree it would build.

    The tree is derived from the staged rows here, not stored. Two copies of the same fact drift,
    and the one on screen is the one somebody would act on.
    """
    await guard.authorise(session, context, Action.VIEW)
    record = await _get(session, import_id)

    rows = list(
        (
            await session.execute(
                select(HierarchyImportRow)
                .where(HierarchyImportRow.import_id == import_id)
                .order_by(HierarchyImportRow.row_number)
            )
        )
        .scalars()
        .all()
    )

    return Preview(
        import_id=record.id,
        status=record.status,
        source_columns=record.source_columns,
        column_mapping=record.column_mapping,
        ignored_columns=record.ignored_columns,
        proposal=record.proposal,
        row_count=record.row_count,
        error_count=record.error_count,
        warning_count=record.warning_count,
        proposed_tree=_tree_from(rows),
        rows=[
            {
                "row_number": row.row_number,
                "kind": row.kind,
                "parsed": row.parsed,
                "errors": row.errors,
                "warnings": row.warnings,
            }
            #  Capped for the response, never for the counts above. "12 errors" stays true even
            #  when the list shows the first 200 rows.
            for row in rows[:limit]
        ],
        can_apply=record.can_apply,
    )


def _tree_from(rows: list[HierarchyImportRow]) -> list[dict[str, Any]]:
    """The tree the staged rows describe, flat, with `parent_name` resolved to a name.

    Flat for the same reason the live tree is: the client nests it, one shape serves every view,
    and no depth limit has to be guessed here.
    """
    units: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.errors:
            continue
        name = str(row.parsed.get("unit_name", "")).strip()
        if not name:
            continue
        key = name.lower()
        unit = units.setdefault(
            key,
            {
                "name": name,
                "parent_name": str(row.parsed.get("parent_name", "")) or None,
                "unit_type": row.parsed.get("unit_type") or "department",
                "external_ref": row.parsed.get("unit_ref") or None,
                "positions": [],
            },
        )
        title = str(row.parsed.get("position_title", "")).strip()
        if title:
            unit["positions"].append(
                {
                    "title": title,
                    "person_name": row.parsed.get("person_name") or None,
                    "person_email": row.parsed.get("person_email") or None,
                }
            )
    return list(units.values())


# ------------------------------------------------------------------- 7: apply, atomically


async def apply(
    session: AsyncSession,
    context: SecurityContext,
    import_id: uuid.UUID,
    *,
    expected_version: int,
) -> HierarchyImport:
    """Move the staged tree into the live one, or nothing.

    One transaction. A half-applied org chart is worse than a failed one — nobody can tell which
    half is real, and the fix requires knowing what the file said, which by then nobody does.

    Refused unless the import is validated and has no errors. An import applied with known bad
    rows is an import that put known bad data into the thing every permission scope reads from.
    """
    await guard.authorise(session, context, Action.ADMINISTER)
    record = await _get(session, import_id)

    if record.status == ImportStatus.APPLIED:
        raise ValidationFailed("This import has already been applied.")
    if record.version != expected_version:
        raise Conflict("Somebody else changed this import. Reload it and try again.")
    if record.error_count:
        raise ValidationFailed(
            f"{record.error_count} rows still have errors. Fix the file or the mapping and "
            "upload it again."
        )
    if record.status not in (ImportStatus.MAPPED, ImportStatus.VALIDATED):
        raise ValidationFailed("Review the mapping before applying this import.")

    existing_root = (
        await session.execute(select(OrgUnit.id).where(OrgUnit.parent_id.is_(None)))
    ).scalar_one_or_none()
    if existing_root is not None:
        raise ValidationFailed(
            "This workspace already has a company structure. Importing into an existing tree "
            "arrives with company onboarding; for now, import into an empty workspace."
        )

    rows = list(
        (
            await session.execute(
                select(HierarchyImportRow)
                .where(HierarchyImportRow.import_id == import_id)
                .order_by(HierarchyImportRow.row_number)
            )
        )
        .scalars()
        .all()
    )
    staged = _tree_from(rows)
    if not staged:
        raise ValidationFailed("There is nothing in this import to apply.")

    created = await _write_tree(session, context, record, staged, rows)

    revision = await hierarchy._revise(
        session,
        context,
        change_type="hierarchy.imported",
        entity_type="hierarchy_import",
        entity_id=record.id,
        summary=(
            f"Imported {created['units']} departments and {created['positions']} positions "
            f"from “{created['filename']}”"
        ),
        before=None,
        after={
            "import_id": str(record.id),
            "file_id": str(record.file_id),
            "column_mapping": record.column_mapping,
            "ignored_columns": record.ignored_columns,
            "units": created["units"],
            "positions": created["positions"],
            "assignments": created["assignments"],
        },
    )
    await session.flush()

    record.status = ImportStatus.APPLIED
    record.applied_at = _now()
    record.applied_revision_id = revision.id
    record.version += 1
    await session.flush()
    return record


async def _write_tree(
    session: AsyncSession,
    context: SecurityContext,
    record: HierarchyImport,
    staged: list[dict[str, Any]],
    rows: list[HierarchyImportRow],
) -> dict[str, Any]:
    """Create the units, then the positions, then the assignments — in that order.

    The order is forced by the foreign keys, and by the cycle trigger: a unit's parent has to
    exist before it does. Rows naming a parent that is not in the file are attached to the root,
    which is stated as a warning at staging rather than discovered here.
    """
    by_name = {unit["name"].lower(): unit for unit in staged}

    #  One root. The file may or may not contain the company itself; if every named parent is
    #  also a unit in the file, the one with no parent is the root. If several have no parent,
    #  they are all attached to a company node named for the workspace, because the database
    #  allows exactly one root and the alternative is refusing the import.
    roots = [unit for unit in staged if not unit["parent_name"]]
    root_id: uuid.UUID

    if len(roots) == 1:
        top = roots[0]
        root = OrgUnit(
            tenant_id=context.tenant_id,
            parent_id=None,
            name=top["name"],
            unit_type=top["unit_type"] if top["unit_type"] == "company" else "company",
            external_ref=top["external_ref"],
        )
        session.add(root)
        await session.flush()
        root_id = root.id
        created_ids = {top["name"].lower(): root.id}
    else:
        holder = OrgUnit(
            tenant_id=context.tenant_id,
            parent_id=None,
            name=record.sheet_name or "Company",
            unit_type="company",
        )
        session.add(holder)
        await session.flush()
        root_id = holder.id
        created_ids = {}

    #  Breadth-first by depth, so a parent always exists before its child. A unit whose parent is
    #  not in the file lands under the root — never dropped, because a department that vanished
    #  silently is the failure people find months later.
    remaining = [unit for unit in staged if unit["name"].lower() not in created_ids]
    while remaining:
        progressed = False
        still: list[dict[str, Any]] = []
        for unit in remaining:
            parent_name = (unit["parent_name"] or "").lower()
            parent_id = created_ids.get(parent_name) if parent_name else root_id
            if parent_id is None and parent_name in by_name:
                still.append(unit)
                continue
            node = OrgUnit(
                tenant_id=context.tenant_id,
                parent_id=parent_id or root_id,
                name=unit["name"],
                unit_type=unit["unit_type"],
                external_ref=unit["external_ref"],
            )
            session.add(node)
            await session.flush()
            created_ids[unit["name"].lower()] = node.id
            progressed = True
        if not progressed:
            #  Only reachable if the file describes a loop the staging checks missed. Refusing is
            #  the correct end: the transaction rolls back and nothing was created.
            raise ValidationFailed(
                "The departments in that file refer to each other in a loop. Fix the parent "
                "column and upload it again."
            )
        remaining = still

    #  Resolved one address at a time through `directory_membership_for_email`, because
    #  `uboss_app` cannot read `users` — migration 0006 took that privilege away and the reason
    #  has not changed. The function answers only "is there an active member of *this* tenant
    #  with this address", and returns only the membership id.
    people: dict[str, uuid.UUID | None] = {}

    async def member_for(email: str) -> uuid.UUID | None:
        if email not in people:
            people[email] = (
                await session.execute(
                    text("SELECT directory_membership_for_email(:email)"), {"email": email}
                )
            ).scalar_one_or_none()
        return people[email]

    positions = 0
    assignments = 0
    today = _now().date()

    for row in rows:
        title = str(row.parsed.get("position_title", "")).strip()
        if not title or row.errors:
            continue
        unit_id = created_ids.get(str(row.parsed.get("unit_name", "")).lower())
        if unit_id is None:
            continue

        position = Position(
            tenant_id=context.tenant_id,
            org_unit_id=unit_id,
            title=title,
            location=row.parsed.get("location") or None,
            external_ref=row.parsed.get("position_ref") or None,
        )
        session.add(position)
        await session.flush()
        positions += 1
        row.applied_entity_id = position.id

        email = str(row.parsed.get("person_email", "")).strip().lower()
        member_id = await member_for(email) if email else None
        if member_id is None:
            #  Nobody in this workspace has that address. The position is still created — the
            #  seat is real whether or not the person has an account — and it reads as vacant,
            #  which it is.
            continue

        starts = _parse_date(str(row.parsed.get("effective_from", ""))) or today
        session.add(
            PositionAssignment(
                tenant_id=context.tenant_id,
                position_id=position.id,
                membership_id=member_id,
                effective_from=starts,
            )
        )
        assignments += 1

    await session.flush()

    return {
        "units": len(created_ids) + (0 if len(roots) == 1 else 1),
        "positions": positions,
        "assignments": assignments,
        #  The sheet, not the file name: the file's name is on the `files` row, and a sheet is
        #  what a person picked when a workbook had several.
        "filename": record.sheet_name or "the uploaded file",
    }


def _parse_date(value: str) -> date | None:
    """A date from a spreadsheet cell, or nothing.

    ISO first, then the two orderings people actually type. An unreadable date becomes "today"
    at the call site rather than an error: refusing a whole import over one badly typed start
    date would be the wrong trade, and the warning was already raised at staging.
    """
    text = value.strip()
    if not text:
        return None
    for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:10], pattern).date()
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------- internals


async def _get(session: AsyncSession, import_id: uuid.UUID) -> HierarchyImport:
    record = (
        await session.execute(select(HierarchyImport).where(HierarchyImport.id == import_id))
    ).scalar_one_or_none()
    if record is None:
        raise NotFound("No such import.")
    return record


async def _reread(session: AsyncSession, record: HierarchyImport) -> parsing.Sheet:
    """Rebuild the sheet from the staged rows rather than the file.

    The raw cells were kept for exactly this. Re-downloading and re-parsing would be slower, and
    would let the stored rows and the file disagree if the object were ever replaced.
    """
    rows = list(
        (
            await session.execute(
                select(HierarchyImportRow)
                .where(HierarchyImportRow.import_id == record.id)
                .order_by(HierarchyImportRow.row_number)
            )
        )
        .scalars()
        .all()
    )
    return parsing.Sheet(
        name=record.sheet_name,
        columns=record.source_columns,
        rows=[(row.row_number, {k: str(v) for k, v in row.raw.items()}) for row in rows],
    )


async def _stage_rows(
    session: AsyncSession,
    context: SecurityContext,
    record: HierarchyImport,
    sheet: parsing.Sheet,
    mapping: dict[str, str],
) -> None:
    """Replace the staged rows for this import, and recount.

    Replaced wholesale rather than updated in place: a re-map can change what every row means,
    and a partial update would leave rows staged against a mapping that no longer exists.
    """
    await session.execute(
        delete(HierarchyImportRow).where(HierarchyImportRow.import_id == record.id)
    )

    try:
        staged = parsing.stage(sheet, mapping)
    except ValidationFailed:
        #  A mapping with no department-name column. The import survives so the person can fix
        #  the mapping; it simply has nothing staged against it.
        record.row_count = len(sheet.rows)
        record.error_count = len(sheet.rows)
        record.warning_count = 0
        await session.flush()
        raise

    for row in staged:
        session.add(
            HierarchyImportRow(
                tenant_id=context.tenant_id,
                import_id=record.id,
                row_number=row.row_number,
                raw=dict(row.raw),
                kind=row.kind,
                parsed=row.parsed,
                errors=row.errors,
                warnings=row.warnings,
            )
        )

    record.row_count = len(staged)
    record.error_count = sum(1 for row in staged if row.errors)
    record.warning_count = sum(1 for row in staged if row.warnings)
    if record.status in (ImportStatus.PARSED, ImportStatus.MAPPED):
        record.status = ImportStatus.VALIDATED if record.error_count == 0 else ImportStatus.MAPPED
    await session.flush()
