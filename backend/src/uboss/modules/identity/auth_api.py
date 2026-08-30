"""Federated sign-in and account recovery over HTTP.

Kept out of `api.py` because these routes answer to a different rule than the rest of the auth
surface: **they run before there is a session, and two of them run before there is an account
this system will admit to.** That makes what they *say* as much a part of the design as what they
do, and it is easier to keep straight in a file that only holds them.

Three things every route here obeys:

* **An unconfigured capability is a supported state, said plainly.** No mail provider and no OAuth
  credentials are facts about the deployment, not about the person, so there is nothing to protect
  by being vague — and a screen that knows can stop offering a button that would fail.
* **An account's existence is never revealed.** The reset request answers identically for an
  address that has an account, one that does not, and one that is suspended.
* **Creating a workspace is one named door, not a privilege.** `/auth/sign-up` is the only route
  in the system that brings a tenant into existence, and it does it by calling migration 0027's
  `SECURITY DEFINER` function. `uboss_app` still cannot insert a `tenants` or `users` row. See
  `identity/signup.py` for why that shape was chosen over granting the privilege.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from uboss.core import rate_limit
from uboss.core.dependencies import RedisDep, SessionDep, SettingsDep
from uboss.core.errors import ValidationFailed
from uboss.core.idempotency import require_idempotency_key
from uboss.core.logging import get_logger
from uboss.modules.identity import challenges, oauth, recovery, signup
from uboss.modules.identity import service as identity
from uboss.modules.identity.api import client_binding, create_session_response

#  The two response shapes come from `schemas`, where they are declared — importing them via
#  `api` would work but would make this file depend on that one for something it does not own.
from uboss.modules.identity.schemas import ChooseWorkspaceResponse, SignInResponse

log = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OAuthProvider(BaseModel):
    """One federated provider and whether this deployment can actually complete it."""

    name: str
    #: True only when both a client id and a secret are set. The screen renders every provider
    #: the product supports and disables the ones this is false for, rather than hiding them —
    #: an absent button looks like a product that never offered it, and a disabled one with a
    #: reason tells an administrator exactly what is missing.
    configured: bool


class SignInMethods(BaseModel):
    """What this deployment can actually do, so the screen offers only that.

    `password` is always true — it is the built-in path. The rest are computed from whether
    credentials exist, which is why a screen reading this can never render a button that would
    fail at the far end.
    """

    password: bool = True
    #: Every provider the product supports, each flagged with whether it is usable here.
    oauth_providers: list[OAuthProvider]
    #: False when no mail provider is configured — a reset link cannot be delivered, and the
    #: forgot-password screen says so rather than claiming an email is on its way.
    can_send_email: bool


class OAuthStart(BaseModel):
    """Where to send the browser. The verifier stays on the server and is never in this response."""

    url: str


class ForgotPassword(_Payload):
    email: str = Field(min_length=1, max_length=320)


class ForgotPasswordAnswer(BaseModel):
    """Deliberately the same for every address.

    `delivery` describes the **system**, not the account: `unavailable` means no mail provider is
    configured, which is equally true whether or not that address is registered.
    """

    delivery: recovery.Delivery


class ResetPassword(_Payload):
    token: str = Field(min_length=1, max_length=512)
    password: str = Field(min_length=1, max_length=1024)


class AcceptInvite(_Payload):
    token: str = Field(min_length=1, max_length=512)
    password: str = Field(min_length=1, max_length=1024)
    display_name: str | None = Field(default=None, max_length=200)


@router.get("/providers", summary="Which sign-in methods this deployment supports")
async def sign_in_methods(settings: SettingsDep) -> SignInMethods:
    """Read by the sign-in screen before it draws anything.

    Unauthenticated on purpose — it has to be, because it is what the sign-in page asks first —
    and it reveals nothing beyond how this deployment is configured, which anybody who reaches
    the page can see from the buttons anyway.
    """
    return SignInMethods(
        oauth_providers=[
            OAuthProvider(name=name, configured=name in settings.enabled_oauth_providers)
            for name in settings.supported_oauth_providers
        ],
        can_send_email=settings.mail_is_configured,
    )


@router.get("/oauth/{provider}/start", summary="Begin a federated sign-in")
async def oauth_start(
    provider: str,
    settings: SettingsDep,
    redis: RedisDep,
    next_path: Annotated[str, Field(max_length=200)] = "/dashboard",
) -> OAuthStart:
    """Mint the state and PKCE challenge, and hand back the provider's URL.

    The browser is not redirected from here: the client navigates, which keeps this a plain JSON
    API and lets the screen show a failure — an unconfigured provider, a Redis that is down — as
    a message rather than as a broken redirect.
    """
    authorisation = await oauth.start(redis, settings, provider, next_path=next_path)
    return OAuthStart(url=authorisation.url)


class OAuthCallback(_Payload):
    """What the browser brings back from the provider."""

    code: str = Field(min_length=1, max_length=4096)
    state: str = Field(min_length=1, max_length=512)


@router.post("/oauth/{provider}/callback", summary="Finish a federated sign-in")
async def oauth_callback(
    provider: str,
    body: OAuthCallback,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    redis: RedisDep,
) -> SignInResponse | ChooseWorkspaceResponse:
    """Verify the provider's token, find the linked account, and sign them in.

    **Returns exactly what the password route returns**, and by the same code — `signed_in` with a
    cookie, or `choose_workspace` with a single-use challenge when the person belongs to more than
    one organisation. Two sign-in paths that produced two shapes of session would be two places to
    get session handling wrong.

    The account must already exist and already be linked. A provider assertion names a person,
    not a workspace, so there is nothing here to create one from — `oauth.find_user` refuses and
    says what to do instead.
    """
    parked = await oauth.consume_state(redis, body.state)
    if parked.get("provider") != provider:
        #  The state was minted for a different provider. One message, because naming the provider
        #  it was for would confirm that a guessed state had existed.
        raise ValidationFailed(
            "That sign-in attempt has expired or was already used. Start again."
        )

    claims = await oauth.exchange(
        settings, provider, body.code, parked["verifier"], parked["nonce"]
    )
    #  Already a `Credential`, read through the same narrow function the password path uses.
    account, _identity = await oauth.find_user(session, provider, claims)

    workspaces = await identity.workspaces_for(session, account)
    if not workspaces:
        await identity.record_authenticated_sign_in_denial(
            session,
            user=account,
            ip_address=request.client.host if request.client else None,
            denial_reason="no active workspace",
        )
        #  The refusal evidence must survive the rollback the error handler performs.
        await session.commit()
        raise identity.SignInRefused()

    if len(workspaces) > 1:
        challenge = await challenges.issue(
            redis,
            user_id=account.id,
            allowed_workspaces=[tenant.slug for _membership, tenant in workspaces],
            client_binding=client_binding(request, settings),
            ttl_seconds=settings.workspace_challenge_seconds,
        )
        await session.commit()
        return ChooseWorkspaceResponse(
            challenge=challenge,
            workspaces=identity.summarise_workspaces(workspaces),
        )

    membership, tenant = workspaces[0]
    await identity.record_completed_sign_in(session, account=account, now=datetime.now(UTC))
    return await create_session_response(
        response=response,
        request=request,
        session=session,
        settings=settings,
        user=account,
        membership=membership,
        tenant=tenant,
    )


class SignUp(_Payload):
    """Everything a new workspace needs, and nothing it does not.

    No workspace *slug* — it is derived from the name, because a person setting up an account
    should not have to invent a URL segment, and one they typed would be one they got wrong.
    """

    email: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=1024)
    display_name: str = Field(min_length=1, max_length=200)
    workspace_name: str = Field(min_length=1, max_length=200)


@router.post(
    "/sign-up",
    status_code=status.HTTP_201_CREATED,
    summary="Create an account and its workspace",
)
async def sign_up(
    body: SignUp,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    redis: RedisDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> SignInResponse:
    """Create the workspace and sign them into it.

    **Signed in immediately, and only because they just proved they own the password.** There is
    no email confirmation step yet: confirming an address needs a mail provider, which is not
    configured, and a screen that said "check your inbox" on a system that cannot send would be
    the plainest possible version of reporting a success that did not happen. When mail is
    configured this is where verification belongs.

    Rate-limited on the same limiter the sign-in path uses. Creating workspaces is exactly the
    operation somebody would automate, and the limiter already exists.
    """
    ip = request.client.host if request.client else None
    await rate_limit.enforce_sign_in(redis, settings=settings, email=body.email, ip_address=ip)

    created = await signup.create_workspace(
        session,
        email=body.email,
        password=body.password,
        display_name=body.display_name,
        workspace_name=body.workspace_name,
        ip_address=ip,
    )

    #  Read back through the same path the password sign-in uses, so the session this issues is
    #  identical to one issued any other way.
    account = await identity.authenticate(
        session, email=body.email, password=body.password
    )
    workspaces = await identity.workspaces_for(session, account)
    membership, tenant = workspaces[0]
    await identity.record_completed_sign_in(session, account=account, now=datetime.now(UTC))

    log.info("workspace_created_and_signed_in", tenant_id=str(created.tenant_id))
    return await create_session_response(
        response=response,
        request=request,
        session=session,
        settings=settings,
        user=account,
        membership=membership,
        tenant=tenant,
    )


@router.post(
    "/password/forgot",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ask for a password reset link",
)
async def forgot_password(
    body: ForgotPassword,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    redis: RedisDep,
) -> ForgotPasswordAnswer:
    """Answers identically whether or not the address has an account.

    `202` rather than `200` for the same reason: it says *accepted*, which is true in every case,
    rather than *done*, which would be a claim about an account.
    """
    answer = await recovery.request_reset(
        session,
        redis,
        settings,
        email=body.email,
        ip_address=request.client.host if request.client else None,
    )
    await session.commit()
    return ForgotPasswordAnswer(delivery=answer.delivery)


@router.post("/password/reset", summary="Set a new password from a reset link")
async def reset_password(
    body: ResetPassword,
    request: Request,
    session: SessionDep,
    redis: RedisDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, str]:
    """Consumes the token, sets the password, and signs the account out everywhere.

    No idempotency replay here beyond the required header: the token is single-use, so a genuine
    retry finds it already consumed and is told to ask for a new link — which is the correct
    answer, not an error to paper over.
    """
    user = await recovery.complete_reset(
        session,
        redis,
        token=body.token,
        new_password=body.password,
        ip_address=request.client.host if request.client else None,
    )
    await session.commit()
    return {"status": "reset", "email": user.email}


@router.post("/invite/accept", summary="Set the first password on an invited account")
async def accept_invite(
    body: AcceptInvite,
    request: Request,
    session: SessionDep,
    redis: RedisDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, str]:
    """Not registration. The account and its membership already exist.

    Somebody with the authority created them; this is the invited person choosing a password.
    Nothing here creates a workspace — that is decision `0B.3`.
    """
    user = await recovery.accept_invite(
        session,
        redis,
        token=body.token,
        password=body.password,
        display_name=body.display_name,
        ip_address=request.client.host if request.client else None,
    )
    await session.commit()
    return {"status": "accepted", "email": user.email}
