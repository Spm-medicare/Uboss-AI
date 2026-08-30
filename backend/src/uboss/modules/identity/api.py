"""Sign in, sign out, and "who am I".

The session lives in an http-only cookie, not in a response body. That is the point: JavaScript
never sees the token, so a script injected into the page cannot take it. It also means the
client has no token to store, mishandle, or accidentally log.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from uboss.core import idempotency, rate_limit
from uboss.core.dependencies import CurrentContext, RedisDep, SessionDep, SettingsDep
from uboss.core.errors import NotAuthenticated, StepUpFailed, problem
from uboss.core.idempotency import require_idempotency_key
from uboss.core.logging import get_logger
from uboss.core.settings import Settings
from uboss.modules.audit import service as audit
from uboss.modules.identity import challenges, tokens
from uboss.modules.identity import service as identity
from uboss.modules.identity.credentials import Credential
from uboss.modules.identity.models import Membership, Session
from uboss.modules.identity.schemas import (
    ChooseWorkspaceResponse,
    CurrentUser,
    PasswordStepUpRequest,
    SessionSummary,
    SignInRequest,
    SignInResponse,
    StepUpResponse,
    WorkspaceSelectionRequest,
)
from uboss.modules.tenancy.models import Tenant

log = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["identity"])


def _client_ip(request: Request) -> str | None:
    """The caller's address, as the server observed it.

    `X-Forwarded-For` is deliberately not read here. It is trivially forged, and the only safe
    way to use it is for the proxy in front of this API to overwrite it — at which point the
    proxy, not this code, decides what is true. Until that proxy is configured and documented,
    reading the header would record an attacker-chosen address in the audit trail.
    """
    return request.client.host if request.client else None


def client_binding(request: Request, settings: Settings) -> str:
    return rate_limit.client_binding(
        settings.auth_signing_key.get_secret_value(),
        ip_address=_client_ip(request),
        user_agent=request.headers.get("User-Agent"),
    )


async def create_session_response(
    *,
    response: Response,
    request: Request,
    session: AsyncSession,
    settings: Settings,
    user: Credential,
    membership: Membership,
    tenant: Tenant,
) -> SignInResponse:
    minted, row, context = await identity.start_session(
        session,
        settings,
        user=user,
        membership=membership,
        tenant=tenant,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("User-Agent"),
    )
    await session.commit()

    secure = settings.environment != "local"
    response.set_cookie(
        tokens.cookie_name(secure),
        minted.raw,
        **tokens.cookie_settings(  # type: ignore[arg-type]
            secure=secure,
            max_age_seconds=settings.refresh_token_days * 24 * 3600,
        ),
    )
    return SignInResponse(
        user=identity.describe(
            context, membership=membership, tenant=tenant, session_row=row
        )
    )


@router.post(
    "/sign-in",
    summary="Sign in",
    responses={
        200: {"description": "Signed in, or asked to choose a workspace."},
        401: {"description": "The credentials did not match an account."},
    },
)
async def sign_in(
    body: SignInRequest,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    redis: RedisDep,
) -> SignInResponse | ChooseWorkspaceResponse:
    """Exchange an email and password for a session cookie.

    Returns one of two things, both with 200:

    * `signed_in` — a cookie is set and the person is in.
    * `choose_workspace` — the password was right, but they belong to more than one
      organisation. Nothing failed, so this is not an error; the client submits the returned
      single-use challenge and never sends the password again.

    Every failure returns the same 401 with the same wording, whatever went wrong.
    """
    ip = _client_ip(request)
    await rate_limit.enforce_sign_in(
        redis,
        settings=settings,
        email=body.email,
        ip_address=ip,
    )

    try:
        user = await identity.authenticate(
            session, email=body.email, password=body.password
        )
    except NotAuthenticated:
        #  Recorded before the refusal is raised, and committed — an attack that fails must
        #  still leave a trail. `authenticate` already looked the account up; this re-reads it
        #  on the same session so the trail can name the organisations involved.
        await identity.record_failed_attempt_by_email(
            session, email=body.email, ip_address=ip
        )
        await session.commit()
        log.info("sign_in_failed", email_domain=body.email.rsplit("@", 1)[-1])
        raise

    workspaces = await identity.workspaces_for(session, user)

    if not workspaces:
        await identity.record_authenticated_sign_in_denial(
            session,
            user=user,
            ip_address=ip,
            denial_reason="no active workspace",
        )
        # The request dependency rolls back exceptions, but denial evidence must survive.
        await session.commit()
        raise identity.SignInRefused()

    await identity.record_verified_password(session, user, body.password)

    if len(workspaces) > 1:
        challenge = await challenges.issue(
            redis,
            user_id=user.id,
            allowed_workspaces=[tenant.slug for _membership, tenant in workspaces],
            client_binding=client_binding(request, settings),
            ttl_seconds=settings.workspace_challenge_seconds,
        )
        return ChooseWorkspaceResponse(
            challenge=challenge,
            workspaces=identity.summarise_workspaces(workspaces)
        )

    membership, tenant = workspaces[0]
    await identity.record_completed_sign_in(
        session,
        account=user,
        now=datetime.now(UTC),
    )
    return await create_session_response(
        response=response,
        request=request,
        session=session,
        settings=settings,
        user=user,
        membership=membership,
        tenant=tenant,
    )


@router.post(
    "/select-workspace",
    summary="Complete sign-in by choosing a workspace",
    responses={
        200: {"description": "Signed in to the selected workspace."},
        401: {"description": "The challenge was not accepted."},
    },
)
async def select_workspace(
    body: WorkspaceSelectionRequest,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    redis: RedisDep,
) -> SignInResponse:
    ip = _client_ip(request)
    await rate_limit.enforce_workspace_selection(
        redis,
        settings=settings,
        ip_address=ip,
    )
    claim = await challenges.consume(
        redis,
        raw=body.challenge,
        expected_client_binding=client_binding(request, settings),
    )
    if claim is None or body.workspace not in claim.allowed_workspaces:
        raise identity.SignInRefused()

    user = await identity.user_for_workspace_challenge(
        session,
        user_id=claim.user_id,
    )
    if user is None:
        raise identity.SignInRefused()

    workspaces = await identity.workspaces_for(session, user)
    chosen = next(
        (pair for pair in workspaces if pair[1].slug == body.workspace),
        None,
    )
    if chosen is None:
        await identity.record_authenticated_sign_in_denial(
            session,
            user=user,
            ip_address=ip,
            denial_reason="workspace challenge no longer authorized",
        )
        await session.commit()
        raise identity.SignInRefused()

    membership, tenant = chosen
    await identity.record_completed_sign_in(
        session,
        account=user,
        now=datetime.now(UTC),
    )
    return await create_session_response(
        response=response,
        request=request,
        session=session,
        settings=settings,
        user=user,
        membership=membership,
        tenant=tenant,
    )


@router.post("/sign-out", status_code=status.HTTP_204_NO_CONTENT, summary="Sign out")
async def sign_out(
    response: Response,
    context: CurrentContext,
    session: SessionDep,
    settings: SettingsDep,
) -> None:
    """End this session now.

    The row is marked revoked as well as the cookie being cleared. Clearing the cookie alone
    would leave a token that still works if it was copied anywhere — which is exactly the case
    where signing out matters.
    """
    await identity.end_session(session, context=context, session_id=context.session_id)
    secure = settings.environment != "local"
    response.delete_cookie(tokens.cookie_name(secure), path="/")


@router.post(
    "/step-up/password",
    response_model=StepUpResponse,
    summary="Confirm the current identity before a high-risk action",
    responses={
        200: {"description": "A short step-up window is now active."},
        401: {"description": "The credential proof was not accepted."},
        429: {"description": "Too many verification attempts."},
    },
)
async def password_step_up(
    body: PasswordStepUpRequest,
    request: Request,
    response: Response,
    context: CurrentContext,
    session: SessionDep,
    settings: SettingsDep,
    redis: RedisDep,
) -> StepUpResponse | Response:
    """Re-check the current account's password without creating a new session.

    This does not grant a permission. It only supplies the recent proof that a separately
    authorised high-risk route requires.
    """
    ip = _client_ip(request)
    await rate_limit.enforce_step_up(
        redis,
        settings=settings,
        membership_id=str(context.membership_id),
        ip_address=ip,
    )
    expires_at = await identity.prove_password_for_step_up(
        session,
        settings,
        context=context,
        password=body.password,
        ip_address=ip,
    )
    # A denial is evidence too. Commit it before raising because the request dependency rolls
    # back uncommitted work when an exception leaves the route.
    await session.commit()
    if expires_at is None:
        refusal = StepUpFailed("That password was not accepted.")
        denied = JSONResponse(
            status_code=refusal.status_code,
            content=problem(refusal),
            headers=refusal.headers,
        )
        # `current_context` may have rotated the session token before the password check. This
        # route commits denial evidence, so that rotation commits too; preserve its cookie on
        # the deliberate 401 response or the browser would retain only the short-grace token.
        denied.raw_headers.extend(
            (name, value)
            for name, value in response.raw_headers
            if name.lower() == b"set-cookie"
        )
        return denied
    return StepUpResponse(expires_at=expires_at)


@router.get("/me", summary="Who is signed in")
async def me(context: CurrentContext, session: SessionDep) -> CurrentUser:
    """The signed-in person, their workspace and what they may do.

    `actions` exists so menus can hide what a person cannot use. It is never the check: every
    route re-resolves permissions on the server, because a list sent to a browser is a list the
    browser can edit.
    """
    loaded = (
        await session.execute(
            select(Membership, Tenant, Session)
            .join(Tenant, Tenant.id == Membership.tenant_id)
            .join(Session, Session.membership_id == Membership.id)
            .where(
                Membership.id == context.membership_id,
                Session.id == context.session_id,
            )
        )
    ).first()
    if loaded is None:
        raise NotAuthenticated("Your session has ended. Sign in again.")

    membership, tenant, session_row = loaded
    return identity.describe(
        context, membership=membership, tenant=tenant, session_row=session_row
    )


@router.get("/sessions", summary="Where this account is signed in")
async def list_sessions(
    context: CurrentContext, session: SessionDep, settings: SettingsDep
) -> list[SessionSummary]:
    """Every live session for this person, in this workspace.

    Scoped to the caller's own `user_id` as well as the tenant. An administrator ending someone
    else's session is a separate, audited action — not a side effect of viewing a list.
    """
    now = datetime.now(UTC)
    rows = (
        await session.execute(
            select(Session)
            .where(
                Session.tenant_id == context.tenant_id,
                Session.user_id == context.user_id,
                Session.revoked_at.is_(None),
                Session.expires_at > now,
                Session.last_seen_at
                > now - timedelta(minutes=settings.session_idle_minutes),
            )
            .order_by(Session.last_seen_at.desc())
        )
    ).scalars().all()

    return [
        SessionSummary(
            id=row.id,
            created_at=row.created_at,
            last_seen_at=row.last_seen_at,
            expires_at=row.expires_at,
            ip_address=str(row.ip_address) if row.ip_address else None,
            user_agent=row.user_agent,
            is_current=row.id == context.session_id,
        )
        for row in rows
    ]


@router.delete(
    "/sessions/{session_id}",
    summary="End another session",
    responses={
        409: {"description": "The same key was used for a different request, or one is running."},
    },
)
async def revoke_session(
    session_id: uuid.UUID,
    context: CurrentContext,
    session: SessionDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, str]:
    """End one of this person's own sessions — the "sign out everywhere else" control.

    The update is filtered by `user_id` as well as tenant, so this cannot reach a colleague's
    session even with a valid id from the same workspace.

    **Idempotent.** Revoking a session is naturally repeatable — the second revoke changes
    nothing — but the *audit row* is not: without this, a retry after a dropped connection would
    record the same revocation twice and an investigation would see two events where one
    happened. The key is derived from the session being ended, so a retry reuses it and replays
    the first answer.

    Returns a small body rather than 204 so there is something to replay. A stored replay of "no
    content" cannot be told apart from a request that never ran.
    """
    payload = {"session_id": str(session_id)}
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="identity.session.revoke",
        payload=payload,
    ) as execution:
        if execution.is_replay:
            return cast(dict[str, str], execution.replay_body)

        await session.execute(
            update(Session)
            .where(
                Session.id == session_id,
                Session.tenant_id == context.tenant_id,
                Session.user_id == context.user_id,
            )
            .values(revoked_at=datetime.now(UTC))
        )
        await audit.record(
            session,
            tenant_id=context.tenant_id,
            action="identity.session.revoked",
            resource_type="session",
            resource_id=session_id,
            actor=context,
        )
        body = {"status": "revoked", "session_id": str(session_id)}
        execution.complete_json(status_code=200, body=body)
        return body
