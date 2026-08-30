"""Test fixtures.

**Two engines, and the difference between them is the whole point of the security suite.**

`owner_engine` connects as `uboss_owner` — the role that runs migrations. It sets up and tears
down. `app_engine` connects as `uboss_app`, the role every API request runs as, which is bound by
row-level security. A cross-tenant test that connects as the owner proves nothing: FORCE is off
(DECISIONS 22), so the owner sees everything by design.

Every run builds a throwaway database from the migrations and drops it afterwards. Nothing here
touches the development database — a suite that can damage real data is a suite people stop
running.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from uboss.core.runtime import configure_event_loop
from pydantic import SecretStr

from uboss.core.settings import Settings
from uboss.db.base import build_sessionmaker

#  Before pytest-asyncio creates its loop. Windows defaults to one the database driver cannot
#  use — see uboss.core.runtime. Called at import so it is in place before any fixture runs.
configure_event_loop()

TEST_DATABASE = "uboss_test"


def _admin_url() -> str:
    """A connection to `postgres`, for creating and dropping the test database."""
    url = os.environ.get("UBOSS_TEST_ADMIN_URL")
    if url:
        return url
    base = os.environ.get("UBOSS_MIGRATION_DATABASE_URL")
    if not base:
        pytest.exit(
            "Set UBOSS_MIGRATION_DATABASE_URL (or UBOSS_TEST_ADMIN_URL) before running tests.",
            returncode=2,
        )
    return base.rsplit("/", 1)[0] + "/postgres"


def _swap_database(url: str, name: str) -> str:
    return url.rsplit("/", 1)[0] + "/" + name


def _owner_test_url() -> str:
    return _swap_database(os.environ["UBOSS_MIGRATION_DATABASE_URL"], TEST_DATABASE)


def _app_test_url() -> str:
    return _swap_database(os.environ["UBOSS_DATABASE_URL"], TEST_DATABASE)


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def database() -> AsyncIterator[None]:
    """Build a throwaway database from the migrations, and drop it afterwards.

    Built by running alembic rather than by `create_all`. `create_all` produces the tables the
    models describe and **none of the row-level security policies, triggers or grants**, which
    are exactly what the security suite exists to test. A schema built a different way from
    production is a schema that proves nothing about production.
    """
    from alembic import command
    from alembic.config import Config

    admin = create_async_engine(_admin_url(), isolation_level="AUTOCOMMIT")
    async with admin.connect() as connection:
        await connection.execute(text(f"DROP DATABASE IF EXISTS {TEST_DATABASE} WITH (FORCE)"))
        await connection.execute(text(f"CREATE DATABASE {TEST_DATABASE} OWNER uboss_owner"))
    await admin.dispose()

    #  The grants the application role needs. These live in the compose init script for the
    #  development database, which only runs on a fresh volume — so they are repeated here rather
    #  than assumed. Migration 0006 revokes `users` again on top of this.
    owner = create_async_engine(_owner_test_url(), isolation_level="AUTOCOMMIT")
    async with owner.connect() as connection:
        await connection.execute(text("REVOKE ALL ON SCHEMA public FROM PUBLIC"))
        await connection.execute(text("GRANT USAGE ON SCHEMA public TO uboss_app"))
        await connection.execute(
            text(
                "ALTER DEFAULT PRIVILEGES FOR ROLE uboss_owner IN SCHEMA public "
                "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO uboss_app"
            )
        )
        await connection.execute(
            text(
                "ALTER DEFAULT PRIVILEGES FOR ROLE uboss_owner IN SCHEMA public "
                "GRANT USAGE, SELECT ON SEQUENCES TO uboss_app"
            )
        )
        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS btree_gist"))
    await owner.dispose()

    backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + "/backend"
    config = Config(backend + "/alembic.ini")
    config.set_main_option("script_location", backend + "/migrations")

    previous = os.environ.get("UBOSS_MIGRATION_DATABASE_URL")
    os.environ["UBOSS_MIGRATION_DATABASE_URL"] = _owner_test_url()
    try:
        #  In a worker thread, because alembic env.py calls `asyncio.run` and this fixture is
        #  already inside pytest own loop. The thread has no running loop, so it works there.
        await asyncio.to_thread(command.upgrade, config, "head")
    finally:
        if previous is not None:
            os.environ["UBOSS_MIGRATION_DATABASE_URL"] = previous

    yield

    admin = create_async_engine(_admin_url(), isolation_level="AUTOCOMMIT")
    async with admin.connect() as connection:
        await connection.execute(text(f"DROP DATABASE IF EXISTS {TEST_DATABASE} WITH (FORCE)"))
    await admin.dispose()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def owner_engine(database: None) -> AsyncIterator[AsyncEngine]:
    """Connects as `uboss_owner`. Setup and teardown only — never the subject of a test."""
    engine = create_async_engine(_owner_test_url())
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def app_engine(database: None) -> AsyncIterator[AsyncEngine]:
    """Connects as `uboss_app` — the role every API request runs as.

    Bound by row-level security. The security suite uses this and nothing else, because a check
    run as the owner would pass whatever the policies said.
    """
    engine = create_async_engine(_app_test_url())
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(loop_scope="session")
async def owner_session(owner_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with build_sessionmaker(owner_engine)() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture(loop_scope="session")
async def app_session(app_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """A session as the application role, with **no tenant bound**.

    Deliberately unbound. A test that wants a tenant binds it explicitly, so every test says out
    loud which boundary it is inside — and a test that forgets sees nothing, which is the
    fail-closed default the product relies on.
    """
    async with build_sessionmaker(app_engine)() as session:
        yield session
        await session.rollback()


@dataclass(frozen=True, slots=True)
class Workspace:
    """A tenant with one member holding one role, ready to act."""

    tenant_id: uuid.UUID
    slug: str
    user_id: uuid.UUID
    membership_id: uuid.UUID
    role_id: uuid.UUID


async def _make_workspace(session: AsyncSession, slug: str, *, actions: list[str]) -> Workspace:
    """Create a tenant, a person, and a role granting `actions`.

    Written with the owner connection because provisioning is an operator action — the
    application role deliberately cannot create a tenant (DECISIONS 17).
    """
    tenant_id = (
        await session.execute(
            text("INSERT INTO tenants (slug, name) VALUES (:slug, :name) RETURNING id"),
            {"slug": slug, "name": slug.title()},
        )
    ).scalar_one()

    user_id = (
        await session.execute(
            text(
                "INSERT INTO users (email, password_hash, status) "
                "VALUES (:email, 'x', 'active') RETURNING id"
            ),
            {"email": f"person@{slug}.test"},
        )
    ).scalar_one()

    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
    )

    membership_id = (
        await session.execute(
            text(
                "INSERT INTO memberships (tenant_id, user_id, display_name, status) "
                "VALUES (:t, :u, :name, 'active') RETURNING id"
            ),
            {"t": tenant_id, "u": user_id, "name": f"Person at {slug}"},
        )
    ).scalar_one()

    role_id = (
        await session.execute(
            text(
                "INSERT INTO roles (tenant_id, key, name, is_system, is_draft) "
                "VALUES (:t, 'tester', 'Tester', true, true) RETURNING id"
            ),
            {"t": tenant_id},
        )
    ).scalar_one()

    for action in actions:
        await session.execute(
            text("INSERT INTO role_permissions (tenant_id, role_id, action) VALUES (:t, :r, :a)"),
            {"t": tenant_id, "r": role_id, "a": action},
        )

    await session.execute(
        text(
            "INSERT INTO membership_roles (tenant_id, membership_id, role_id) VALUES (:t, :m, :r)"
        ),
        {"t": tenant_id, "m": membership_id, "r": role_id},
    )
    await session.flush()

    return Workspace(
        tenant_id=tenant_id,
        slug=slug,
        user_id=user_id,
        membership_id=membership_id,
        role_id=role_id,
    )


@pytest_asyncio.fixture(loop_scope="session")
async def two_workspaces(
    owner_engine: AsyncEngine,
) -> AsyncIterator[tuple[Workspace, Workspace]]:
    """Two unrelated organisations, cleaned up afterwards.

    Two rather than one, because the question every security test asks is whether one can reach
    the other. A suite with a single tenant cannot fail the test that matters most.
    """
    suffix = uuid.uuid4().hex[:8]
    async with build_sessionmaker(owner_engine)() as session:
        left = await _make_workspace(
            session, f"left{suffix}", actions=["view", "comment", "edit_draft", "publish"]
        )
        right = await _make_workspace(session, f"right{suffix}", actions=["view"])
        await session.commit()

    yield left, right

    async with build_sessionmaker(owner_engine)() as session:
        #  `audit_events` refuses DELETE — the append-only trigger, which is exactly what
        #  test_the_audit_trail_cannot_be_rewritten proves. Cleaning up after a test therefore
        #  has to lift it, and the lift is the narrowest possible: this session, this throwaway
        #  database, restored immediately afterwards.
        #
        #  The alternative — leaving the rows — does not work: the tenant foreign key is
        #  RESTRICT, so the organisation could never be deleted and every run would leak two.
        await session.execute(
            text("ALTER TABLE audit_events DISABLE TRIGGER audit_events_append_only")
        )
        await session.execute(
            text("ALTER TABLE org_revisions DISABLE TRIGGER org_revisions_append_only")
        )
        await session.execute(
            text(
                "ALTER TABLE objective_versions "
                "DISABLE TRIGGER objective_versions_append_only"
            )
        )
        await session.execute(
            text(
                "ALTER TABLE objective_analysis_events "
                "DISABLE TRIGGER objective_analysis_events_append_only"
            )
        )
        await session.execute(
            text("ALTER TABLE job_versions DISABLE TRIGGER job_versions_append_only")
        )
        for workspace in (left, right):
            await session.execute(
                text("SELECT set_config('app.tenant_id', :t, true)"),
                {"t": str(workspace.tenant_id)},
            )
            #  Ordered so a child is removed before its parent. Anything added to the schema and
            #  forgotten here shows up immediately as a foreign-key violation on the tenant
            #  delete — noisy, and better than a suite that leaks an organisation per run.
            for table in (
                #  Jobs before objectives: a job references the objective it serves, and a
                #  published job version is RESTRICT against its job.
                "job_schedules",
                "job_versions",
                "job_inputs",
                "job_assignment_rules",
                "job_step_dependencies",
                "job_steps",
                "jobs",
                #  Objectives before the hierarchy: a published version is RESTRICT against its
                #  objective, so the version has to go first, and the append-only trigger on it
                #  is lifted alongside the other two below.
                "objective_versions",
                "objective_step_dependencies",
                "objective_steps",
                "objective_analysis_events",
                "objective_proposals",
                "objective_current_steps",
                #  The hierarchy, deepest first. `org_revisions` is append-only like
                #  `audit_events`, so its trigger is lifted alongside that one below.
                "org_revisions",
                "reporting_edges",
                "position_assignments",
                "positions",
                "files",
                "audit_events",
                "outbox_events",
                "idempotency_records",
                "resource_grants",
                "scope_policy_restrictions",
                "scope_policies",
                "sessions",
                "membership_roles",
                "role_permissions",
                "roles",
                "memberships",
            ):
                await session.execute(
                    text(f"DELETE FROM {table} WHERE tenant_id = :t"),
                    {"t": workspace.tenant_id},
                )
            await session.execute(
                text("DELETE FROM objectives WHERE tenant_id = :t"),
                {"t": workspace.tenant_id},
            )

            #  `org_units` is a tree whose parent key is RESTRICT, so it empties from the
            #  leaves upward — one statement per level. A test tree is never deep, and the
            #  alternative (CASCADE) would mean deleting a division silently took its
            #  departments in production too.
            while True:
                removed = await session.execute(
                    text(
                        "DELETE FROM org_units u WHERE u.tenant_id = :t AND NOT EXISTS "
                        "(SELECT 1 FROM org_units c WHERE c.parent_id = u.id)"
                    ),
                    {"t": workspace.tenant_id},
                )
                if removed.rowcount == 0:
                    break

            await session.execute(text("DELETE FROM users WHERE id = :u"), {"u": workspace.user_id})
            await session.execute(
                text("DELETE FROM tenants WHERE id = :t"), {"t": workspace.tenant_id}
            )
        await session.execute(
            text("ALTER TABLE audit_events ENABLE TRIGGER audit_events_append_only")
        )
        await session.execute(
            text("ALTER TABLE org_revisions ENABLE TRIGGER org_revisions_append_only")
        )
        await session.execute(
            text(
                "ALTER TABLE objective_versions ENABLE TRIGGER objective_versions_append_only"
            )
        )
        await session.execute(
            text(
                "ALTER TABLE objective_analysis_events "
                "ENABLE TRIGGER objective_analysis_events_append_only"
            )
        )
        await session.execute(
            text("ALTER TABLE job_versions ENABLE TRIGGER job_versions_append_only")
        )
        await session.commit()


@pytest_asyncio.fixture(loop_scope="session")
async def colleague(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> AsyncIterator[uuid.UUID]:
    """A second person in the left workspace, and their membership id.

    Created with the **owner** connection, because `uboss_app` cannot write to `users` — migration
    0006 took that privilege away and the reason has not changed. A test that could add a user as
    the application role would be testing a boundary that is not there.

    Separation of duty needs two people, so a suite with only one cannot test it at all.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        user_id = (
            await session.execute(
                text(
                    "INSERT INTO users (email, password_hash, status) "
                    "VALUES (:email, 'x', 'active') RETURNING id"
                ),
                {"email": f"colleague-{uuid.uuid4().hex[:8]}@test"},
            )
        ).scalar_one()
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": str(left.tenant_id)},
        )
        membership_id = (
            await session.execute(
                text(
                    "INSERT INTO memberships (tenant_id, user_id, display_name, status) "
                    "VALUES (:t, :u, 'The Approver', 'active') RETURNING id"
                ),
                {"t": left.tenant_id, "u": user_id},
            )
        ).scalar_one()
        #  The same role as the first person, so both hold identical permissions and the only
        #  thing separating them is who they are — which is the thing under test.
        await session.execute(
            text(
                "INSERT INTO membership_roles (tenant_id, membership_id, role_id) "
                "VALUES (:t, :m, :r)"
            ),
            {"t": left.tenant_id, "m": membership_id, "r": left.role_id},
        )
        await session.commit()

    yield membership_id

    #  Removed before `two_workspaces` tears the tenant down, or its foreign key would refuse.
    async with build_sessionmaker(owner_engine)() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": str(left.tenant_id)},
        )
        await session.execute(
            text("DELETE FROM membership_roles WHERE membership_id = :m"),
            {"m": membership_id},
        )
        await session.execute(
            text("DELETE FROM memberships WHERE id = :m"), {"m": membership_id}
        )
        await session.execute(text("DELETE FROM users WHERE id = :u"), {"u": user_id})
        await session.commit()


@pytest.fixture(scope="session")
def settings_for_tests() -> Settings:
    """Settings as the suite sees them.

    Deliberately built without an Anthropic key, whatever the developer has in their `.env`.
    "No model configured" is a supported state the product must handle, and a suite that only
    ever runs with a key would never exercise it — nor would it be reproducible, since the answer
    would depend on whose machine it ran on.
    """
    return Settings(anthropic_api_key=SecretStr(""))
