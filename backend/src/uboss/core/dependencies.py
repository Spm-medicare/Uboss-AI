"""The dependencies every protected route declares.

`current_context` is the one place a request stops being anonymous. It reads the session cookie,
resolves it against the database, binds the resulting tenant onto the request's session, and
returns the verified caller. Nothing else in the product decides who is calling.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, cast

from fastapi import Depends, Request, Response
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from uboss.core.context import SecurityContext
from uboss.core.errors import NotAuthenticated, PermissionDenied
from uboss.core.logging import actor_id, tenant_id
from uboss.core.permissions import Action
from uboss.core.settings import Settings, get_settings
from uboss.db.session import db_session
from uboss.modules.identity import service as identity
from uboss.modules.identity import tokens


def settings_dep() -> Settings:
    return get_settings()


SettingsDep = Annotated[Settings, Depends(settings_dep)]
SessionDep = Annotated[AsyncSession, Depends(db_session)]


def redis_dep(request: Request) -> Redis:
    return cast(Redis, request.app.state.redis)


RedisDep = Annotated[Redis, Depends(redis_dep)]


async def current_context(
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
) -> SecurityContext:
    """The verified caller, or a refusal.

    Side effects, in order, and all deliberate:

    1. The tenant is bound onto the request's session, so every statement the route runs after
       this is inside the tenant boundary.
    2. The context is stored on `request.state`, where an error handler or middleware can read
       it without re-resolving.
    3. The tenant and actor are put into the logging context, so every log line for the rest of
       the request names them without any call site passing them.
    """
    secure = settings.environment != "local"
    raw = request.cookies.get(tokens.cookie_name(secure))
    if not raw:
        raise NotAuthenticated("Sign in to continue.")

    context, row, rotated = await identity.resolve_session(session, raw, settings)

    if rotated is not None:
        secure = settings.environment != "local"
        remaining_seconds = max(
            1,
            int((row.expires_at - datetime.now(UTC)).total_seconds()),
        )
        response.set_cookie(
            tokens.cookie_name(secure),
            rotated.raw,
            **tokens.cookie_settings(  # type: ignore[arg-type]
                secure=secure,
                max_age_seconds=remaining_seconds,
            ),
        )

    request.state.security_context = context
    tenant_id.set(str(context.tenant_id))
    actor_id.set(str(context.membership_id))
    return context


CurrentContext = Annotated[SecurityContext, Depends(current_context)]


def requires(action: Action):  # type: ignore[no-untyped-def]
    """Declare the permission a route needs.

    Used as a route dependency:

        @router.post("/objectives", dependencies=[Depends(requires(Action.EDIT_DRAFT))])

    This is the tenant-wide check. A route that acts on one object still re-checks against that
    object's own grants — this catches the caller who has no business on the endpoint at all,
    before any work is done.
    """

    async def check(context: CurrentContext) -> None:
        context.require(action)

    return check


async def require_step_up(context: CurrentContext) -> None:
    """Guard a high-risk route with a recent server-verified credential proof.

    Permission and step-up are deliberately separate checks: proving a password never grants an
    action the caller's role did not already have.
    """
    if not context.has_stepped_up():
        raise PermissionDenied("Confirm your identity before continuing.", code="step_up_required")


StepUpContext = Annotated[SecurityContext, Depends(require_step_up)]
