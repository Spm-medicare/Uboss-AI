"""Federated sign-in — the OIDC half of `PLAN.md`'s *"managed provider with MFA now"*.

Three providers, one code path. Google, Microsoft and Apple all speak OpenID Connect, so what
differs between them is three URLs and one quirk each — not three implementations.

## What this refuses to do

**It never trusts an email address to find an account.** The identity is the provider's `sub`,
which is stable; an address is not, and a provider that let one be re-registered would let
somebody inherit an account. `federated_identities` is unique on `(provider, subject)` for exactly
that reason, and this module looks a person up by that pair and nothing else.

**It never creates a user.** Sign-in with Google gets you into an account that already exists and
has already been linked. Creating one would be self-service registration, which is `0B.3` —
company onboarding — and that decision has not been taken. A person whose Google account is not
linked is told to sign in with their password and link it, not silently given a new identity.

**It never accepts a token it did not ask for.** The `state` is single-use, browser-bound and
short-lived, and the PKCE verifier never leaves the server. An authorisation response arriving
without a matching state is discarded — that is the whole defence against a login-CSRF, where an
attacker gets you signed into *their* account without noticing.

## What is not built, and why the screen says so

An unconfigured provider is a **supported state**. `settings.enabled_oauth_providers` is computed
from whether credentials are present, `GET /auth/providers` publishes it, and the sign-in screen
offers only what is there. A button that cannot complete a sign-in is a control that does not do
what it says.

The id-token signature is verified against the provider's published JWKS. That verification has
been exercised against locally generated keys; it has **not** been exercised against a live
Google, Microsoft or Apple tenant, because no credentials exist for one yet. That is stated here
rather than discovered later.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import httpx
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uboss.core.errors import DependencyUnavailable, ValidationFailed
from uboss.core.logging import get_logger
from uboss.core.settings import Settings
from uboss.modules.identity import credentials
from uboss.modules.identity.models import FederatedIdentity

log = get_logger(__name__)

#: Where a pending authorisation is parked between the redirect out and the redirect back.
STATE_PREFIX = "uboss:auth:oauth:"

#: How long somebody has to complete a provider's sign-in page. Long enough for a password
#: manager, a second factor and a moment of confusion; short enough that an intercepted state is
#: worthless by the time it is used.
STATE_TTL_SECONDS = 600

#: How long a fetched JWKS is reused. Providers rotate keys, and a cache that outlived a rotation
#: would reject every real token until it expired.
JWKS_TTL_SECONDS = 3600


@dataclass(frozen=True, slots=True)
class Provider:
    """One OIDC provider's three URLs and its scope string."""

    name: str
    authorize_url: str
    token_url: str
    jwks_url: str
    issuers: tuple[str, ...]
    scope: str
    #: Apple returns the person's name **once**, in a form POST on the first authorisation, and
    #: never again. Providers that need `response_mode=form_post` say so here.
    form_post: bool = False


def providers(settings: Settings) -> dict[str, Provider]:
    """The three, with the Microsoft tenant segment filled in from configuration."""
    tenant = settings.microsoft_tenant.strip() or "common"
    #  S106 flags every `token_url=` below as a hardcoded credential. It reads the argument name,
    #  not the value: these are the providers' published OAuth endpoints, which are public and
    #  documented. Silenced per line rather than per file so a real one would still be caught.
    return {
        "google": Provider(
            name="google",
            authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
            token_url="https://oauth2.googleapis.com/token",  # noqa: S106
            jwks_url="https://www.googleapis.com/oauth2/v3/certs",
            issuers=("https://accounts.google.com", "accounts.google.com"),
            scope="openid email profile",
        ),
        "microsoft": Provider(
            name="microsoft",
            authorize_url=(
                f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"
            ),
            token_url=f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
            jwks_url=f"https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys",
            #: Microsoft's issuer carries the *directory* id, which differs per customer, so it
            #: cannot be pinned to a constant here. The audience check below is what binds a token
            #: to this application; the issuer prefix is checked rather than the whole string.
            issuers=("https://login.microsoftonline.com/",),
            scope="openid email profile",
        ),
        "apple": Provider(
            name="apple",
            authorize_url="https://appleid.apple.com/auth/authorize",
            token_url="https://appleid.apple.com/auth/token",  # noqa: S106
            jwks_url="https://appleid.apple.com/auth/keys",
            issuers=("https://appleid.apple.com",),
            scope="openid email name",
            #  Apple only returns the name on a form POST, and only the first time.
            form_post=True,
        ),
    }


def client_credentials(settings: Settings, provider: str) -> tuple[str, str]:
    """This provider's client id and secret, or a refusal naming what is missing."""
    pairs = {
        "google": (settings.google_client_id, settings.google_client_secret),
        "microsoft": (settings.microsoft_client_id, settings.microsoft_client_secret),
        "apple": (settings.apple_client_id, settings.apple_client_secret),
    }
    if provider not in pairs:
        raise ValidationFailed("That sign-in provider is not one this system knows.")
    client_id, secret = pairs[provider]
    if not client_id.strip() or not secret.get_secret_value().strip():
        #  Said plainly. This is a fact about the deployment, not about the person signing in, so
        #  there is nothing to protect by being vague.
        raise ValidationFailed(
            f"Signing in with {provider.title()} is not set up on this system yet."
        )
    return client_id.strip(), secret.get_secret_value().strip()


def redirect_uri(settings: Settings, provider: str) -> str:
    """Where the provider sends the browser back.

    Built from `public_base_url` rather than from the request, because the redirect URI is
    registered with the provider and a value taken from a `Host` header would be attacker-chosen.
    """
    return f"{settings.public_base_url.rstrip('/')}/auth/callback/{provider}"


# ---------------------------------------------------------------------------- starting


@dataclass(frozen=True, slots=True)
class Authorisation:
    """Where to send the browser, and the state that will prove it came back."""

    url: str
    state: str


async def start(
    redis: Redis, settings: Settings, provider_name: str, *, next_path: str = "/dashboard"
) -> Authorisation:
    """Begin a sign-in and park what is needed to finish it.

    The PKCE verifier is generated here and **never sent to the browser** — only its hash goes to
    the provider. That is what stops an intercepted authorisation code from being exchanged by
    anybody but this server.
    """
    definition = providers(settings)[provider_name]
    client_id, _ = client_credentials(settings, provider_name)

    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    nonce = secrets.token_urlsafe(16)

    #  Only a path, never a URL. `next` comes from the browser, and an absolute value here would
    #  make this an open redirect somebody could use to bounce a person off this domain.
    safe_next = (
        next_path
        if next_path.startswith("/") and not next_path.startswith("//")
        else "/dashboard"
    )

    try:
        await redis.setex(
            f"{STATE_PREFIX}{state}",
            STATE_TTL_SECONDS,
            json.dumps(
                {
                    "provider": provider_name,
                    "verifier": verifier,
                    "nonce": nonce,
                    "next": safe_next,
                }
            ),
        )
    except RedisError as cause:  # pragma: no cover — exercised by the dependency-down test
        raise DependencyUnavailable(
            "Sign-in is temporarily unavailable. Try again shortly."
        ) from cause

    query = {
        "client_id": client_id,
        "redirect_uri": redirect_uri(settings, provider_name),
        "response_type": "code",
        "scope": definition.scope,
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if definition.form_post:
        query["response_mode"] = "form_post"
    return Authorisation(url=f"{definition.authorize_url}?{urlencode(query)}", state=state)


async def consume_state(redis: Redis, state: str) -> dict[str, Any]:
    """Take the parked state, once.

    Deleted on read rather than after a successful exchange: a state that survived a failed
    attempt could be replayed, and a person who needs to try again can start a new sign-in.
    """
    try:
        raw = await redis.getdel(f"{STATE_PREFIX}{state}")
    except RedisError as cause:  # pragma: no cover
        raise DependencyUnavailable(
            "Sign-in is temporarily unavailable. Try again shortly."
        ) from cause
    if raw is None:
        #  Expired, already used, or never issued by this server. One message for all three —
        #  telling them apart would tell somebody probing which states had existed.
        raise ValidationFailed(
            "That sign-in attempt has expired or was already used. Start again."
        )
    parsed: dict[str, Any] = json.loads(raw)
    return parsed


# ---------------------------------------------------------------------------- finishing


@dataclass(frozen=True, slots=True)
class Claims:
    """What the provider asserted, after the token was verified."""

    subject: str
    email: str | None
    email_verified: bool
    display_name: str | None


async def exchange(
    settings: Settings, provider_name: str, code: str, verifier: str, nonce: str
) -> Claims:
    """Trade the authorisation code for an id token, and verify it before believing a word.

    Four checks, and all four matter: the signature against the provider's published key, the
    audience against this application's client id, the issuer against the provider's own, and the
    nonce against the one this server generated. Skipping any of them turns "signed in as" into
    "claims to be".
    """
    definition = providers(settings)[provider_name]
    client_id, client_secret = client_credentials(settings, provider_name)

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            definition.token_url,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri(settings, provider_name),
                "client_id": client_id,
                "client_secret": client_secret,
                "code_verifier": verifier,
            },
            headers={"Accept": "application/json"},
        )
        if response.status_code >= 400:
            #  The provider's own body is not returned to the browser: it can carry the client
            #  secret back in an error message, and it is not a sentence anybody can act on.
            log.warning(
                "oauth_token_exchange_failed",
                provider=provider_name,
                status=response.status_code,
            )
            raise ValidationFailed(
                f"{provider_name.title()} did not complete the sign-in. Try again."
            )
        token = response.json()

        id_token = token.get("id_token")
        if not id_token:
            raise ValidationFailed(
                f"{provider_name.title()} did not return an identity token."
            )
        keys = await _jwks(client, definition.jwks_url)

    claims = verify_id_token(
        id_token, keys=keys, audience=client_id, issuers=definition.issuers, nonce=nonce
    )
    return Claims(
        subject=str(claims["sub"]),
        email=claims.get("email"),
        email_verified=bool(claims.get("email_verified", False)),
        display_name=claims.get("name") or claims.get("given_name"),
    )


_JWKS_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}


async def _jwks(client: httpx.AsyncClient, url: str) -> list[dict[str, Any]]:
    """The provider's signing keys, cached for an hour.

    Cached because a fetch per sign-in is a dependency on somebody else's uptime in the middle of
    a login; only for an hour because providers rotate, and a stale cache would reject every real
    token until it expired.
    """
    cached = _JWKS_CACHE.get(url)
    now = time.time()
    if cached and cached[0] > now:
        return cached[1]

    response = await client.get(url, timeout=10.0)
    response.raise_for_status()
    keys: list[dict[str, Any]] = response.json().get("keys", [])
    _JWKS_CACHE[url] = (now + JWKS_TTL_SECONDS, keys)
    return keys


def verify_id_token(
    id_token: str,
    *,
    keys: list[dict[str, Any]],
    audience: str,
    issuers: tuple[str, ...],
    nonce: str,
    now: int | None = None,
) -> dict[str, Any]:
    """Verify an OIDC id token and return its claims.

    Separated from `exchange` and given no network of its own so it can be tested directly — with
    a locally generated key, a token this code signs, and then the same token tampered with. A
    verifier only exercised through a live provider is a verifier nobody has seen fail.
    """
    #  Imported here rather than at module scope so the rest of this module — the provider
    #  registry, the state handling — stays importable in a build without the JWT extras.
    import jwt

    try:
        header = jwt.get_unverified_header(id_token)
    except jwt.PyJWTError as cause:
        raise ValidationFailed("That identity token could not be read.") from cause

    key_id = header.get("kid")
    match = next((key for key in keys if key.get("kid") == key_id), None)
    if match is None:
        raise ValidationFailed(
            "That identity token was signed with a key this provider does not publish."
        )

    try:
        signing_key = jwt.PyJWK.from_dict(match).key
        claims: dict[str, Any] = jwt.decode(
            id_token,
            signing_key,
            algorithms=[header.get("alg", "RS256")],
            audience=audience,
            options={"require": ["exp", "iat", "sub", "aud", "iss"]},
        )
    except jwt.PyJWTError as cause:
        #  One message for a bad signature, a wrong audience and an expired token alike. Which of
        #  the three failed is in the log, not in the response.
        log.warning("oauth_id_token_rejected", reason=str(cause))
        raise ValidationFailed("That identity token was not accepted.") from cause

    issuer = str(claims.get("iss", ""))
    if not any(issuer == known or issuer.startswith(known) for known in issuers):
        raise ValidationFailed("That identity token came from an unexpected issuer.")

    #  The nonce binds the token to *this* sign-in attempt. Without it a token obtained elsewhere
    #  for the same client could be replayed here.
    if claims.get("nonce") != nonce:
        raise ValidationFailed("That identity token belongs to a different sign-in attempt.")

    if now is not None and int(claims.get("exp", 0)) <= now:
        raise ValidationFailed("That identity token has expired.")

    return claims


# ---------------------------------------------------------------------------- the account


async def find_user(
    session: AsyncSession, provider: str, claims: Claims
) -> tuple[credentials.Credential, FederatedIdentity]:
    """The account this provider's subject is linked to.

    **Looked up by `(provider, subject)` and nothing else.** Not by email: an address can be
    changed and re-registered, and matching on one would let somebody who acquires an old address
    inherit the account it used to belong to.

    **The account is read through `auth_find_by_id`, never through `users`.** The application
    role has no privilege on that table — migration 0006 withheld it deliberately — so a
    `select(User)` here fails in production and, worse, would have to be *granted* to pass. The
    narrow function is the only door, and this path uses the same one the password sign-in does.

    **No account is created here.** `/auth/sign-up` creates accounts, and it takes a workspace
    name; a provider assertion carries no such thing. Somebody whose provider account is not
    linked is told what to do about it, which is a sentence they can act on rather than a silent
    second identity nobody asked for.
    """
    identity = (
        await session.execute(
            select(FederatedIdentity).where(
                FederatedIdentity.provider == provider,
                FederatedIdentity.subject == claims.subject,
            )
        )
    ).scalar_one_or_none()

    if identity is None:
        raise ValidationFailed(
            f"No account here is linked to that {provider.title()} sign-in. Sign in with your "
            "password and link it from your account settings, or create a workspace first."
        )

    account = await credentials.find_by_id(session, identity.user_id)
    if account is None or not account.is_active:
        #  The same sentence a suspended account gets from the password path. Which of the two it
        #  was is in the audit trail.
        raise ValidationFailed("That account cannot sign in. Ask an administrator.")

    #  Kept current so an administrator can see what the provider is asserting now, and so a
    #  changed address is visible rather than silently diverging.
    identity.email = claims.email
    identity.email_verified = claims.email_verified
    if claims.display_name:
        identity.display_name = claims.display_name
    identity.last_sign_in_at = datetime.now(UTC)
    return account, identity


async def link(
    session: AsyncSession, user_id: uuid.UUID, provider: str, claims: Claims
) -> FederatedIdentity:
    """Attach a provider to an account that is already signed in.

    Deliberately requires an existing session: linking is something a person does *to their own
    account*, and doing it from the sign-in screen would be registration by another name.
    """
    existing = (
        await session.execute(
            select(FederatedIdentity).where(
                FederatedIdentity.provider == provider,
                FederatedIdentity.subject == claims.subject,
            )
        )
    ).scalar_one_or_none()
    if existing is not None and existing.user_id != user_id:
        raise ValidationFailed(
            f"That {provider.title()} account is already linked to somebody else here."
        )

    identity = existing or FederatedIdentity(
        user_id=user_id, provider=provider, subject=claims.subject
    )
    identity.email = claims.email
    identity.email_verified = claims.email_verified
    identity.display_name = claims.display_name
    if existing is None:
        session.add(identity)
    return identity
