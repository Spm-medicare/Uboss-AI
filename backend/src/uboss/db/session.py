"""One database session per request, and the dependency that hands it out.

A single session for the whole request, shared by every dependency and the route body. That is
what makes "the audit row commits with the change" true: two sessions would be two transactions,
and two transactions can disagree about what happened.

The session starts **unbound** — no tenant. `current_context` in `core.dependencies` binds the
tenant onto it while resolving the caller's session cookie, before the route body runs. A route
that takes this dependency without also requiring authentication therefore gets a session with
no tenant bound, and row-level security returns nothing to it. That is the fail-closed default:
forgetting to authenticate a route makes it useless, not dangerous.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _factory(request: Request) -> async_sessionmaker[AsyncSession]:
    """The sessionmaker built at start-up and stored on the app.

    Read from app state rather than a module global so that a test, or a second app in the same
    process, cannot accidentally share one engine.
    """
    factory: async_sessionmaker[AsyncSession] = request.app.state.sessionmaker
    return factory


async def db_session(request: Request) -> AsyncIterator[AsyncSession]:
    """The request's session and transaction.

    Commits when the route returns, rolls back on any exception. A half-applied change is never
    left behind for the next request to find — and because the audit and outbox rows are written
    into this same transaction, they are rolled back with it.
    """
    async with _factory(request)() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
