"""Storing a file, and deciding who may have it back.

`storage.py` moves bytes. This module decides.

Three rules it exists to hold, each of which is easy to leave out and impossible to notice
missing until it matters:

* **A key is checked against the caller's tenant before every read.** Object storage has no idea
  what a tenant is — hand it a key and it hands back the bytes. Row-level security protects the
  *metadata*; this protects the object.
* **A file is not served until it has been scanned clean.** `pending` and `failed` both refuse. A
  file nobody could check is not a file to hand over.
* **The digest is computed from what was stored**, never taken from the client. A client-supplied
  hash describes what the client believed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uboss.core.context import SecurityContext
from uboss.core.errors import NotFound, UbossError, ValidationFailed, as_field_error
from uboss.core.settings import Settings
from uboss.modules.audit import service as audit
from uboss.modules.audit.models import AuditOutcome
from uboss.modules.files.models import Classification, File, ScanState
from uboss.modules.files.storage import Storage, key_for, owns


class FileNotReady(UbossError):
    """Uploaded, but not yet cleared for download.

    A 409 rather than a 404: the file exists and the caller may well be entitled to it. Saying so
    is safe — they uploaded it, or they can see its metadata — and telling them to wait is more
    useful than pretending it is not there.
    """

    status_code = 409
    code = "file_not_ready"


@dataclass(frozen=True, slots=True)
class Upload:
    """What was accepted."""

    file_id: uuid.UUID
    sha256: str
    size_bytes: int
    scan_state: str


async def store(
    session: AsyncSession,
    storage: Storage,
    settings: Settings,
    context: SecurityContext,
    *,
    data: bytes,
    original_name: str,
    content_type: str,
    classification: Classification = Classification.INTERNAL,
    owner_type: str | None = None,
    owner_id: uuid.UUID | None = None,
) -> Upload:
    """Write the bytes, then the row.

    **Bytes first, row second.** If the row fails, an object is left behind with nothing pointing
    at it — wasted space, cleaned up by a lifecycle rule. The other order fails worse: a row that
    promises a file which does not exist, and a download that 500s for ever.

    The key is generated, never derived from `original_name`. A filename arrives from a browser
    and may contain `../`, a null byte, or Unicode a storage backend normalises into somebody
    else's key.
    """
    if len(data) > settings.max_upload_bytes:
        raise ValidationFailed(
            f"That file is larger than the {settings.max_upload_bytes // (1024 * 1024)} MB limit.",
            field_errors=as_field_error("file", "Too large.", "too_large"),
        )
    if not data:
        raise ValidationFailed(
            "That file is empty.",
            field_errors=as_field_error("file", "Empty file.", "empty"),
        )

    key = key_for(context.tenant_id)
    stored = await storage.put(key, data, content_type=content_type)

    row = File(
        tenant_id=context.tenant_id,
        storage_key=stored.key,
        #  Kept for display and download, never for addressing. Truncated rather than rejected:
        #  a long filename is not a reason to refuse someone's work.
        original_name=original_name[:400],
        content_type=content_type[:200],
        size_bytes=stored.size_bytes,
        sha256=stored.sha256,
        classification=classification,
        #  Every upload starts here. Nothing moves it until a scanner does, and until then
        #  `download_url` refuses — which is the honest default while no scanner is configured.
        scan_state=ScanState.PENDING,
        uploaded_by_membership_id=context.membership_id,
        owner_type=owner_type,
        owner_id=owner_id,
    )
    session.add(row)
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="file.uploaded",
        resource_type="file",
        resource_id=row.id,
        actor=context,
        detail={
            "name": row.original_name,
            "size_bytes": row.size_bytes,
            "sha256": row.sha256,
            "classification": row.classification,
        },
    )

    return Upload(
        file_id=row.id,
        sha256=stored.sha256,
        size_bytes=stored.size_bytes,
        scan_state=row.scan_state,
    )


async def find(
    session: AsyncSession, context: SecurityContext, file_id: uuid.UUID
) -> File:
    """The file's metadata, or a 404.

    Row-level security already limits this to the caller's tenant, so a file in another
    organisation simply is not here. The `tenant_id` in the predicate says so out loud as well.
    """
    row = (
        await session.execute(
            select(File).where(
                File.id == file_id, File.tenant_id == context.tenant_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFound("No such file.")
    return row


async def download_url(
    session: AsyncSession,
    storage: Storage,
    context: SecurityContext,
    file_id: uuid.UUID,
) -> str:
    """A short-lived link to the bytes, if the caller may have them.

    Three checks, and the middle one is the one that would be easy to leave out:

    1. The metadata is in this tenant — row-level security, plus the predicate in `find`.
    2. **The key is in this tenant's prefix.** Belt and braces. If a row ever pointed at another
       organisation's object — a bug, a bad import, a restored backup — the first check would
       pass and the bytes would be handed over. Object storage cannot make this check itself.
    3. The file has been scanned clean.
    """
    row = await find(session, context, file_id)

    if not owns(row.storage_key, context.tenant_id):
        #  Not a 403. A caller cannot cause this, so telling them anything about it is pointless;
        #  what matters is that an operator sees it, which the audit row does.
        await audit.record(
            session,
            tenant_id=context.tenant_id,
            action="file.key_outside_tenant",
            resource_type="file",
            resource_id=row.id,
            outcome=AuditOutcome.FAILED,
            actor=context,
            denial_reason="the stored key is not inside this tenant's prefix",
        )
        raise NotFound("No such file.")

    if not row.is_downloadable:
        raise FileNotReady(
            "This file is still being checked. Try again shortly."
            if row.scan_state == ScanState.PENDING
            else "This file cannot be downloaded."
        )

    return await storage.signed_url(row.storage_key)


async def record_scan_result(
    session: AsyncSession,
    context: SecurityContext,
    file_id: uuid.UUID,
    *,
    state: ScanState,
    detail: str | None = None,
) -> None:
    """What the scanner found.

    Separate from upload because scanning is asynchronous and, today, absent. Nothing calls this
    yet: no scanner is configured, so every file stays `pending` and stays undownloadable. That
    is visible rather than a silent allow — the alternative, defaulting to `clean`, would serve
    unscanned files while the code claimed otherwise.
    """
    row = await find(session, context, file_id)
    row.scan_state = state
    row.scan_detail = detail
    row.scanned_at = datetime.now(UTC)

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action=f"file.scan.{state}",
        resource_type="file",
        resource_id=row.id,
        outcome=(
            AuditOutcome.SUCCEEDED
            if state == ScanState.CLEAN
            else AuditOutcome.FAILED
        ),
        actor=context,
        detail={"scan_detail": detail} if detail else {},
    )
