"""Files — 1.6.1.

Exit check: **a file uploaded in one tenant is unreachable from another, including by direct
key.** "Including by direct key" is the part worth testing. Row-level security protects the
metadata row; object storage has no idea what a tenant is, so if a wrong key ever reaches it, it
hands over the bytes.

These run against MinIO, the same S3 API a deployment uses — there is no local branch in the
code to test around.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.conftest import Workspace
from uboss.core.context import SecurityContext
from uboss.core.errors import NotFound, ValidationFailed
from uboss.core.settings import Settings, get_settings
from uboss.db.base import build_sessionmaker
from uboss.modules.files import service as files
from uboss.modules.files.models import File, ScanState
from uboss.modules.files.storage import Storage, key_for, owns


def _context(workspace: Workspace) -> SecurityContext:
    return SecurityContext(
        tenant_id=workspace.tenant_id,
        user_id=workspace.user_id,
        membership_id=workspace.membership_id,
        session_id=uuid.uuid4(),
        email="person@test",
        display_name="Person",
        roles=("tester",),
    )


@pytest.fixture(scope="session")
def settings() -> Settings:
    return get_settings()


@pytest_asyncio.fixture(loop_scope="session")
async def storage(settings: Settings) -> AsyncIterator[Storage]:
    store = Storage(settings)
    await store.ensure_bucket()
    yield store


async def _bind(session: AsyncSession, tenant_id: Any) -> None:
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
    )


# ── keys ─────────────────────────────────────────────────────────────────────────────────


async def test_a_key_is_always_inside_its_tenants_prefix() -> None:
    tenant = uuid.uuid4()
    other = uuid.uuid4()
    key = key_for(tenant)

    assert key.startswith(f"t/{tenant}/")
    assert owns(key, tenant)
    assert not owns(key, other)


async def test_a_key_never_contains_the_filename() -> None:
    """A filename arrives from a browser and may contain anything — `../` included."""
    key = key_for(uuid.uuid4())
    assert ".." not in key
    assert key.count("/") == 2


async def test_the_database_refuses_a_row_whose_key_is_not_tenant_prefixed(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """The `CHECK` is what stops a bug from planting one tenant's key on another's row.

    Row-level security cannot make this check — a policy cannot see inside a string.
    """
    left, right = two_workspaces

    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, left.tenant_id)
        with pytest.raises(Exception) as raised:
            await session.execute(
                text(
                    "INSERT INTO files (tenant_id, storage_key, original_name, content_type, "
                    "size_bytes, sha256) VALUES (:t, :k, 'x.txt', 'text/plain', 1, 'abc')"
                ),
                #  A key belonging to the *other* organisation.
                {"t": left.tenant_id, "k": f"t/{right.tenant_id}/{uuid.uuid4()}"},
            )
        assert "key_is_tenant_prefixed" in str(raised.value).lower()
        await session.rollback()


# ── the exit check ───────────────────────────────────────────────────────────────────────


async def test_a_file_from_one_tenant_is_unreachable_from_another(
    app_engine: AsyncEngine,
    storage: Storage,
    settings: Settings,
    two_workspaces: tuple[Workspace, Workspace],
) -> None:
    """1.6.1's exit check, both halves.

    By metadata: the row is not visible to the other organisation.
    **By direct key:** even holding the exact storage key, the other organisation is refused —
    which is the half that object storage cannot enforce for itself.
    """
    left, right = two_workspaces
    left_context = _context(left)
    right_context = _context(right)

    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, left.tenant_id)
        upload = await files.store(
            session,
            storage,
            settings,
            left_context,
            data=b"one organisation's private numbers",
            original_name="private.txt",
            content_type="text/plain",
        )
        stored_key = (
            await session.execute(
                text("SELECT storage_key FROM files WHERE id = :id"),
                {"id": upload.file_id},
            )
        ).scalar_one()
        await session.commit()

    #  By metadata.
    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, right.tenant_id)
        with pytest.raises(NotFound):
            await files.find(session, right_context, upload.file_id)

        visible = (
            await session.execute(text("SELECT count(*) FROM files"))
        ).scalar_one()
        assert visible == 0, "the other organisation could see the file's metadata"

    #  By direct key. The other organisation holds the exact storage key — the worst case, and
    #  the one object storage cannot defend against, because it has no idea what a tenant is.
    assert not owns(stored_key, right.tenant_id)

    #  And the database will not let a row in that organisation point at it, so there is no way
    #  to reach it through the service either. Attempted with raw SQL: an invalid ORM object
    #  would stay in the session and fail again during cleanup.
    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, right.tenant_id)
        with pytest.raises(Exception) as raised:
            await session.execute(
                text(
                    "INSERT INTO files (tenant_id, storage_key, original_name, "
                    "content_type, size_bytes, sha256, scan_state) "
                    "VALUES (:t, :k, 'stolen.txt', 'text/plain', 1, :h, 'clean')"
                ),
                {"t": right.tenant_id, "k": stored_key, "h": "x" * 64},
            )
        assert "key_is_tenant_prefixed" in str(raised.value).lower()
        await session.rollback()


async def test_the_service_refuses_a_key_outside_the_callers_tenant(
    app_engine: AsyncEngine,
    storage: Storage,
    settings: Settings,
    two_workspaces: tuple[Workspace, Workspace],
) -> None:
    """The belt-and-braces check, exercised on its own.

    The row is edited to point outside the tenant *after* it was created, which is the shape a
    restored backup or a bad import would take. `download_url` refuses and records why.
    """
    left, right = two_workspaces
    left_context = _context(left)

    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, left.tenant_id)
        upload = await files.store(
            session,
            storage,
            settings,
            left_context,
            data=b"contents",
            original_name="ok.txt",
            content_type="text/plain",
        )
        row = await files.find(session, left_context, upload.file_id)
        row.scan_state = ScanState.CLEAN
        #  Bypasses the database CHECK by not flushing the change — the service check is what is
        #  under test, and it runs on the object in memory.
        row.storage_key = f"t/{right.tenant_id}/{uuid.uuid4()}"

        with pytest.raises(NotFound):
            await files.download_url(session, storage, left_context, upload.file_id)

        await session.rollback()


# ── the scan gate ────────────────────────────────────────────────────────────────────────


async def test_a_file_is_not_downloadable_until_it_has_been_scanned(
    app_engine: AsyncEngine,
    storage: Storage,
    settings: Settings,
    two_workspaces: tuple[Workspace, Workspace],
) -> None:
    """A file nobody could check is not a file to hand over.

    No scanner is configured, so every upload stays `pending` — and that is visible rather than
    a silent allow.
    """
    left, _right = two_workspaces
    context = _context(left)

    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, left.tenant_id)
        upload = await files.store(
            session,
            storage,
            settings,
            context,
            data=b"contents",
            original_name="report.txt",
            content_type="text/plain",
        )
        assert upload.scan_state == ScanState.PENDING

        with pytest.raises(files.FileNotReady):
            await files.download_url(session, storage, context, upload.file_id)

        #  Cleared, and now it is served.
        await files.record_scan_result(
            session, context, upload.file_id, state=ScanState.CLEAN
        )
        url = await files.download_url(session, storage, context, upload.file_id)
        assert url.startswith("http")
        assert "X-Amz-Signature" in url or "Signature" in url

        await session.rollback()


@pytest.mark.parametrize("state", [ScanState.PENDING, ScanState.INFECTED, ScanState.FAILED])
async def test_only_a_clean_file_is_served(
    app_engine: AsyncEngine,
    storage: Storage,
    settings: Settings,
    two_workspaces: tuple[Workspace, Workspace],
    state: ScanState,
) -> None:
    """`failed` refuses too. A scan that could not decide is not a pass."""
    left, _right = two_workspaces
    context = _context(left)

    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, left.tenant_id)
        upload = await files.store(
            session,
            storage,
            settings,
            context,
            data=b"contents",
            original_name="x.txt",
            content_type="text/plain",
        )
        await files.record_scan_result(session, context, upload.file_id, state=state)

        with pytest.raises(files.FileNotReady):
            await files.download_url(session, storage, context, upload.file_id)
        await session.rollback()


# ── what was stored ──────────────────────────────────────────────────────────────────────


async def test_the_digest_describes_what_was_actually_stored(
    app_engine: AsyncEngine,
    storage: Storage,
    settings: Settings,
    two_workspaces: tuple[Workspace, Workspace],
) -> None:
    """Computed from the bytes, never taken from the client."""
    import hashlib

    left, _right = two_workspaces
    context = _context(left)
    data = b"the exact bytes that were written"

    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, left.tenant_id)
        upload = await files.store(
            session,
            storage,
            settings,
            context,
            data=data,
            original_name="x.txt",
            content_type="text/plain",
        )
        assert upload.sha256 == hashlib.sha256(data).hexdigest()
        assert upload.size_bytes == len(data)

        row = await files.find(session, context, upload.file_id)
        fetched = await storage.get(row.storage_key)
        assert fetched == data
        assert hashlib.sha256(fetched).hexdigest() == upload.sha256

        await session.rollback()


async def test_an_oversized_or_empty_upload_is_refused(
    app_engine: AsyncEngine,
    storage: Storage,
    settings: Settings,
    two_workspaces: tuple[Workspace, Workspace],
) -> None:
    """Checked before anything is written, so a rejected upload leaves no object behind."""
    left, _right = two_workspaces
    context = _context(left)

    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, left.tenant_id)

        with pytest.raises(ValidationFailed):
            await files.store(
                session,
                storage,
                settings,
                context,
                data=b"",
                original_name="empty.txt",
                content_type="text/plain",
            )

        with pytest.raises(ValidationFailed):
            await files.store(
                session,
                storage,
                settings,
                context,
                data=b"x" * (settings.max_upload_bytes + 1),
                original_name="huge.bin",
                content_type="application/octet-stream",
            )
        await session.rollback()


async def test_an_upload_is_recorded_in_the_audit_trail(
    app_engine: AsyncEngine,
    storage: Storage,
    settings: Settings,
    two_workspaces: tuple[Workspace, Workspace],
) -> None:
    left, _right = two_workspaces
    context = _context(left)

    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, left.tenant_id)
        upload = await files.store(
            session,
            storage,
            settings,
            context,
            data=b"contents",
            original_name="minutes.txt",
            content_type="text/plain",
        )
        await session.flush()

        row = (
            await session.execute(
                text(
                    "SELECT action, resource_id, detail FROM audit_events "
                    "WHERE action = 'file.uploaded'"
                )
            )
        ).one()
        assert row.resource_id == upload.file_id
        assert row.detail["sha256"] == upload.sha256
        assert row.detail["name"] == "minutes.txt"
        await session.rollback()
