"""The database engine, the session, and the tenant boundary that travels with it.

Two independent boundaries protect a tenant's rows, and neither substitutes for the other:

1. **The application** checks that the caller holds the permission for what they asked to do.
2. **PostgreSQL row-level security** refuses rows belonging to any other tenant, whatever the
   application believes.

This module owns the second one. Every session that will touch tenant data must first be given
its tenant through `bind_tenant`, which sets a transaction-local setting the RLS policies read.
Transaction-local matters: a value that outlived its transaction would leak into whichever
request picked the connection up next from the pool.
"""

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from sqlalchemy import MetaData, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from uboss.core.settings import Settings

#: One naming convention for every constraint, so a migration's generated names are stable and a
#: failure message names something a person can find.
NAMING = MetaData(
    naming_convention={
        "ix": "ix_%(column_0_N_label)s",
        "uq": "uq_%(table_name)s_%(column_0_N_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)


class Base(DeclarativeBase):
    metadata = NAMING


def build_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url.get_secret_value(),
        pool_size=settings.database_pool_size,
        max_overflow=5,
        pool_pre_ping=True,
        # Nothing is committed that the caller did not ask to commit.
        future=True,
        echo=False,
    )


def build_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        engine,
        expire_on_commit=False,
        autoflush=False,
    )


async def bind_tenant(session: AsyncSession, tenant_id: UUID) -> None:
    """Tell PostgreSQL which tenant this transaction belongs to.

    `set_config(..., true)` is **transaction-local**. When the transaction ends the setting is
    gone, so a pooled connection cannot carry one request's tenant into the next.

    The value is bound as a parameter rather than interpolated: a tenant id arrives from a
    verified token, but a query that concatenates one is a query that will eventually
    concatenate something else.
    """
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": str(tenant_id)},
    )


async def bind_session_lookup(session: AsyncSession, token_hash: str) -> None:
    """Allow exactly one session row to be read, before its tenant is known.

    Finding the session is what *establishes* the tenant, so the tenant cannot already be bound.
    The `sessions` policy therefore also matches on the token hash — which the caller can only
    supply if they already hold the token, so this reveals nothing they did not have.

    Bound for one transaction only, and never alongside a tenant: the two paths are separate.
    """
    await session.execute(
        text("SELECT set_config('app.session_token_hash', :token_hash, true)"),
        {"token_hash": token_hash},
    )


async def bind_verified_user(session: AsyncSession, user_id: UUID) -> None:
    """Allow one person's own memberships to be listed, across tenants.

    Used only by the sign-in path, after the password has been checked, so that someone who
    belongs to two organisations can be shown both and pick one. The `memberships` policy's
    alternative branch matches on this; the *write* policies do not, so a verified user id gets
    a list of workspaces and nothing more.

    Never set on an ordinary request — those bind a tenant instead.
    """
    await session.execute(
        text("SELECT set_config('app.user_id', :user_id, true)"),
        {"user_id": str(user_id)},
    )


async def session_scope(
    factory: async_sessionmaker[AsyncSession], tenant_id: UUID | None = None
) -> AsyncIterator[AsyncSession]:
    """One session for one unit of work, with the tenant bound before anything is read.

    Commits on success, rolls back on any exception. A half-applied change is never left behind
    for the next request to find.
    """
    async with factory() as session:
        try:
            if tenant_id is not None:
                await bind_tenant(session, tenant_id)
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def healthcheck(session: AsyncSession) -> dict[str, Any]:
    """A real query, not a ping.

    A connection can be open while the database refuses work, so this asks it to answer
    something and reports what came back.
    """
    row = await session.execute(text("SELECT current_database(), version()"))
    database, version = row.one()
    return {"database": database, "server": version.split(",")[0]}
