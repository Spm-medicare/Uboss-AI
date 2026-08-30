"""The import, step by step, over HTTP.

One route per step of PLAN §5, and they are separate routes for a reason: each one is a place a
person stops and looks. Collapsing upload → map → preview → apply into a single "import this file"
call would remove the review the plan is built around, and the review is the only thing standing
between a spreadsheet and somebody's live organisation.

Nothing here writes to `org_units` except `apply`, and `apply` is the only route that can.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status

from uboss.core import idempotency
from uboss.core.dependencies import CurrentContext, SessionDep, SettingsDep, StorageDep
from uboss.core.errors import ValidationFailed
from uboss.core.idempotency import require_idempotency_key
from uboss.modules.hierarchy import import_service
from uboss.modules.hierarchy.import_schemas import (
    ImportApply,
    ImportMappingUpdate,
    ImportPreview,
    ImportSummary,
)

router = APIRouter(prefix="/hierarchy/imports", tags=["hierarchy"])

#: Read fully into memory, so this is the real ceiling for an import. Well under the file-size
#: limit in settings: a 10 MB spreadsheet is roughly 100,000 rows, and the row cap in `parsing`
#: refuses at a fifth of that.
MAX_IMPORT_BYTES = 10 * 1024 * 1024


@router.post("", status_code=status.HTTP_201_CREATED, summary="Upload a structure file")
async def upload(
    context: CurrentContext,
    session: SessionDep,
    settings: SettingsDep,
    storage: StorageDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    file: Annotated[UploadFile, File(description="A .csv or .xlsx of the structure.")],
    sheet_name: Annotated[str | None, Form()] = None,
) -> ImportSummary:
    """PLAN §5 steps 1 and 2 — quarantine, then parse deterministically.

    Nothing is created in the live tree. The file is stored `pending` and stays that way: an
    import source is never served back to a browser, so it never needs to leave quarantine.

    The response says which columns were understood and which were not. The ones that were not
    are what step 3 may ask a model about.
    """
    data = await file.read()
    if len(data) > MAX_IMPORT_BYTES:
        raise ValidationFailed(
            f"That file is larger than {MAX_IMPORT_BYTES // (1024 * 1024)} MB. Split it and "
            "import in parts."
        )

    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="hierarchy.import.upload",
        #  The bytes are not in the fingerprint: hashing 10 MB on every retry to notice a file
        #  changed is expensive, and the key already names the operation. The client derives it
        #  from the file it picked.
        payload={"filename": file.filename or "", "sheet_name": sheet_name},
    ) as execution:
        if execution.is_replay:
            return ImportSummary.model_validate(execution.replay_body)

        record = await import_service.start(
            session,
            storage,
            settings,
            context,
            data=data,
            filename=file.filename or "import.csv",
            sheet_name=sheet_name,
        )
        summary = _summary(record)
        execution.complete_json(
            status_code=status.HTTP_201_CREATED, body=summary.model_dump(mode="json")
        )
        return summary


@router.post("/{import_id}/propose", summary="Ask a model about the unmatched columns")
async def propose(
    import_id: uuid.UUID,
    context: CurrentContext,
    session: SessionDep,
    settings: SettingsDep,
    storage: StorageDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> ImportSummary:
    """PLAN §5 step 3 — *"Claude proposes only ambiguous column mappings."*

    Only the headings the deterministic pass could not place, and only headings: the model never
    sees the tree, is never asked what to create, and its answer is a suggestion until a person
    accepts it.

    Returns 200 whether or not a model was reachable. `proposal.consulted` says which happened,
    so the screen can state it rather than leaving a person to infer it from an empty list.
    """
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="hierarchy.import.propose",
        payload={"import_id": str(import_id)},
    ) as execution:
        if execution.is_replay:
            return ImportSummary.model_validate(execution.replay_body)

        record = await import_service.propose_mapping(
            session, storage, settings, context, import_id
        )
        summary = _summary(record)
        execution.complete_json(status_code=200, body=summary.model_dump(mode="json"))
        return summary


@router.put("/{import_id}/mapping", summary="Confirm what the columns mean")
async def set_mapping(
    import_id: uuid.UUID,
    body: ImportMappingUpdate,
    context: CurrentContext,
    session: SessionDep,
    settings: SettingsDep,
    storage: StorageDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> ImportSummary:
    """PLAN §5 step 4 — the person's decision, and the only one that counts.

    Every row is restaged against the confirmed mapping, so what the preview shows is produced by
    the same code that will apply it. Anything not mapped becomes an ignored column, stated
    rather than silently dropped.
    """
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="hierarchy.import.mapping",
        payload={"import_id": str(import_id), **body.model_dump(mode="json")},
    ) as execution:
        if execution.is_replay:
            return ImportSummary.model_validate(execution.replay_body)

        record = await import_service.set_mapping(
            session,
            storage,
            settings,
            context,
            import_id,
            mapping=body.mapping,
            expected_version=body.expected_version,
        )
        summary = _summary(record)
        execution.complete_json(status_code=200, body=summary.model_dump(mode="json"))
        return summary


@router.get("/{import_id}", summary="The staged rows and the tree they would build")
async def preview(
    import_id: uuid.UUID,
    context: CurrentContext,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> ImportPreview:
    """PLAN §5 step 5 — row errors, warnings, and the proposed tree.

    The tree is derived from the staged rows on every read rather than stored. Two copies of one
    fact drift, and the copy on screen is the one somebody would act on.
    """
    result = await import_service.preview(session, context, import_id, limit=limit)
    return ImportPreview.model_validate(result, from_attributes=True)


@router.post("/{import_id}/apply", summary="Apply the import")
async def apply(
    import_id: uuid.UUID,
    body: ImportApply,
    context: CurrentContext,
    session: SessionDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> ImportSummary:
    """PLAN §5 step 7 — *"Backend applies atomically and records source/mapping/audit."*

    One transaction: either the whole staged tree exists afterwards or none of it does. A
    half-applied org chart is worse than a failed one, because nobody can tell which half is real.

    Refused while any row has an error. An import applied with known bad rows puts known bad data
    into the thing every permission scope reads from.
    """
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="hierarchy.import.apply",
        payload={"import_id": str(import_id), **body.model_dump(mode="json")},
    ) as execution:
        if execution.is_replay:
            return ImportSummary.model_validate(execution.replay_body)

        record = await import_service.apply(
            session, context, import_id, expected_version=body.expected_version
        )
        summary = _summary(record)
        execution.complete_json(status_code=200, body=summary.model_dump(mode="json"))
        return summary


def _summary(record: Any) -> ImportSummary:
    return ImportSummary.model_validate(record, from_attributes=True)
