"""Federated sign-in — the checks that decide whether "signed in as" means anything.

`verify_id_token` is the whole security boundary of this feature. A token that reaches it has come
from the browser, and everything downstream trusts what it says. So it is tested directly, with a
key generated here and tokens signed here — a verifier only ever exercised against a live provider
is a verifier nobody has seen refuse anything.

Six ways a token can be wrong, one test each. Every one of them is something an attacker would
actually try:

* signed with a key the provider does not publish
* signed with the right key but then tampered with
* issued for a different application
* issued by somebody else
* replayed from a different sign-in attempt
* expired
"""

from __future__ import annotations

import time
import uuid

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.conftest import Workspace
from uboss.core.errors import ValidationFailed
from uboss.core.settings import Settings
from uboss.db.base import build_sessionmaker
from uboss.modules.identity import oauth
from uboss.modules.identity.models import FederatedIdentity

pytestmark = pytest.mark.anyio

AUDIENCE = "uboss-test-client"
ISSUER = "https://accounts.google.com"
NONCE = "the-nonce-this-server-minted"


@pytest.fixture(scope="module")
def signing_key() -> rsa.RSAPrivateKey:
    """A key pair for this suite. Generated rather than checked in — a test key in a repository
    is a key somebody eventually uses somewhere else."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def jwks(signing_key: rsa.RSAPrivateKey) -> list[dict[str, object]]:
    """The public half, in the shape a provider publishes it."""
    import json

    from jwt.algorithms import RSAAlgorithm

    published = json.loads(RSAAlgorithm.to_jwk(signing_key.public_key()))
    published["kid"] = "test-key"
    published["alg"] = "RS256"
    return [published]


def mint(
    signing_key: rsa.RSAPrivateKey, **overrides: object
) -> str:
    """A well-formed token, with any claim overridden."""
    import jwt

    now = int(time.time())
    claims: dict[str, object] = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "provider-subject-1",
        "email": "asha@example.test",
        "email_verified": True,
        "name": "Asha Menon",
        "nonce": NONCE,
        "iat": now,
        "exp": now + 300,
    }
    claims.update(overrides)
    return jwt.encode(claims, signing_key, algorithm="RS256", headers={"kid": "test-key"})


def verify(token: str, jwks: list[dict[str, object]], **overrides: object) -> dict[str, object]:
    arguments: dict[str, object] = {
        "keys": jwks,
        "audience": AUDIENCE,
        "issuers": (ISSUER,),
        "nonce": NONCE,
    }
    arguments.update(overrides)
    return oauth.verify_id_token(token, **arguments)  # type: ignore[arg-type]


# ------------------------------------------------------------------ the verifier


def test_a_well_formed_token_is_accepted(
    signing_key: rsa.RSAPrivateKey, jwks: list[dict[str, object]]
) -> None:
    """The other five tests prove things fail. Without this one they could all pass on a verifier
    that refused everything."""
    claims = verify(mint(signing_key), jwks)
    assert claims["sub"] == "provider-subject-1"
    assert claims["email"] == "asha@example.test"


def test_a_token_signed_with_an_unpublished_key_is_refused(
    jwks: list[dict[str, object]],
) -> None:
    """Anybody can generate a key pair. Only the provider's published one counts."""
    impostor = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(ValidationFailed):
        verify(mint(impostor), jwks)


def test_a_tampered_token_is_refused(
    signing_key: rsa.RSAPrivateKey, jwks: list[dict[str, object]]
) -> None:
    """The payload is base64, not encryption — anybody can read and edit it.

    What stops them is the signature over it, and this is the test that proves the signature is
    actually checked rather than the claims merely decoded.
    """
    import base64
    import json

    token = mint(signing_key)
    header, payload, signature = token.split(".")
    decoded = json.loads(base64.urlsafe_b64decode(payload + "=="))
    decoded["sub"] = "somebody-elses-subject"
    forged = (
        base64.urlsafe_b64encode(json.dumps(decoded).encode()).decode().rstrip("=")
    )

    with pytest.raises(ValidationFailed):
        verify(f"{header}.{forged}.{signature}", jwks)


def test_a_token_for_another_application_is_refused(
    signing_key: rsa.RSAPrivateKey, jwks: list[dict[str, object]]
) -> None:
    """A real Google token, correctly signed, issued for somebody else's client id.

    Without the audience check this is how one application's users sign into another's.
    """
    with pytest.raises(ValidationFailed):
        verify(mint(signing_key, aud="a-different-application"), jwks)


def test_a_token_from_another_issuer_is_refused(
    signing_key: rsa.RSAPrivateKey, jwks: list[dict[str, object]]
) -> None:
    with pytest.raises(ValidationFailed):
        verify(mint(signing_key, iss="https://accounts.example.test"), jwks)


def test_a_token_from_a_different_sign_in_attempt_is_refused(
    signing_key: rsa.RSAPrivateKey, jwks: list[dict[str, object]]
) -> None:
    """The nonce binds a token to the attempt this server started.

    Without it a token obtained elsewhere for the same client could be replayed here — which is
    login-CSRF, where somebody gets you signed into *their* account without noticing.
    """
    with pytest.raises(ValidationFailed):
        verify(mint(signing_key, nonce="a-nonce-from-somewhere-else"), jwks)


def test_an_expired_token_is_refused(
    signing_key: rsa.RSAPrivateKey, jwks: list[dict[str, object]]
) -> None:
    now = int(time.time())
    with pytest.raises(ValidationFailed):
        verify(mint(signing_key, exp=now - 10, iat=now - 300), jwks)


# ------------------------------------------------------------------ the account


async def test_an_unlinked_provider_account_does_not_create_a_user(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Signing in with Google gets you into an account that already exists.

    Creating one would be self-service registration — decision `0B.3`, which has not been taken.
    The refusal names what to do instead, which is a sentence somebody can act on.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, left)
        claims = oauth.Claims(
            subject="nobody-here",
            email="stranger@example.test",
            email_verified=True,
            display_name="A Stranger",
        )
        with pytest.raises(ValidationFailed) as refused:
            await oauth.find_user(session, "google", claims)
        assert "Sign in with your password" in str(refused.value)
        assert "create a workspace" in str(refused.value)
        await session.rollback()


async def test_a_linked_account_is_found_by_subject_and_not_by_email(
    owner_engine: AsyncEngine,
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
) -> None:
    """The identity is the provider's `sub`.

    An address can be changed and re-registered; matching on one would let somebody who acquires
    an old address inherit the account it used to belong to. So the lookup is by subject, and a
    provider asserting a *different* address for the same subject still finds the same person.
    """
    left, _ = two_workspaces
    subject = f"google-{uuid.uuid4().hex[:8]}"

    async with build_sessionmaker(owner_engine)() as owner:
        user_id = (
            await owner.execute(
                text("SELECT user_id FROM memberships WHERE id = :m"),
                {"m": left.membership_id},
            )
        ).scalar_one()
        owner.add(
            FederatedIdentity(
                user_id=user_id,
                provider="google",
                subject=subject,
                email="old-address@example.test",
                email_verified=True,
            )
        )
        await owner.commit()

    try:
        async with build_sessionmaker(app_engine)() as session:
            await _bind(session, left)
            #  A different address, the same subject.
            claims = oauth.Claims(
                subject=subject,
                email="new-address@example.test",
                email_verified=True,
                display_name="Asha Menon",
            )
            user, identity = await oauth.find_user(session, "google", claims)
            assert user.id == user_id
            #  The asserted address is kept current so an administrator can see it — but it was
            #  not what found the account.
            assert identity.email == "new-address@example.test"
            await session.rollback()
    finally:
        async with build_sessionmaker(owner_engine)() as owner:
            await owner.execute(
                text("DELETE FROM federated_identities WHERE subject = :s"), {"s": subject}
            )
            await owner.commit()


async def test_one_provider_account_cannot_be_linked_to_two_people(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Two accounts claiming the same Google subject is the account takeover the unique
    constraint exists to make impossible."""
    from sqlalchemy.exc import IntegrityError

    left, right = two_workspaces
    subject = f"google-{uuid.uuid4().hex[:8]}"

    async with build_sessionmaker(owner_engine)() as owner:
        ids = [
            (
                await owner.execute(
                    text("SELECT user_id FROM memberships WHERE id = :m"), {"m": membership}
                )
            ).scalar_one()
            for membership in (left.membership_id, right.membership_id)
        ]
        for user_id in ids:
            owner.add(
                FederatedIdentity(user_id=user_id, provider="google", subject=subject)
            )
        with pytest.raises(IntegrityError):
            await owner.flush()
        await owner.rollback()


# ------------------------------------------------------------------ what is configured


def test_no_provider_is_offered_without_credentials() -> None:
    """An unconfigured provider is a supported state, and the screen never sees it.

    `GET /auth/providers` publishes this tuple, and the sign-in page draws only what is in it — so
    a button that could not complete a sign-in is not something the interface can render.
    """
    settings = Settings(
        database_url="postgresql+psycopg://x:y@localhost/z",  # type: ignore[arg-type]
        auth_signing_key="x" * 32,  # type: ignore[arg-type]
    )
    assert settings.enabled_oauth_providers == ()
    assert settings.mail_is_configured is False


def test_a_provider_with_only_half_its_credentials_is_not_offered() -> None:
    """A client id with no secret cannot complete a token exchange.

    Half-configured is the state a deployment is actually in halfway through being set up, and
    offering the button then would fail at the far end rather than here.
    """
    settings = Settings(
        database_url="postgresql+psycopg://x:y@localhost/z",  # type: ignore[arg-type]
        auth_signing_key="x" * 32,  # type: ignore[arg-type]
        google_client_id="an-id-with-no-secret",
    )
    assert settings.enabled_oauth_providers == ()


def test_a_fully_configured_provider_is_offered() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://x:y@localhost/z",  # type: ignore[arg-type]
        auth_signing_key="x" * 32,  # type: ignore[arg-type]
        google_client_id="an-id",
        google_client_secret="a-secret",  # type: ignore[arg-type]
    )
    assert settings.enabled_oauth_providers == ("google",)


def test_the_redirect_uri_comes_from_configuration_and_not_a_request() -> None:
    """It is registered with the provider, so a value taken from a `Host` header — which is
    attacker-controlled — would be a way to redirect an authorisation somewhere else."""
    settings = Settings(
        database_url="postgresql+psycopg://x:y@localhost/z",  # type: ignore[arg-type]
        auth_signing_key="x" * 32,  # type: ignore[arg-type]
        public_base_url="https://app.example.test/",
    )
    assert (
        oauth.redirect_uri(settings, "google")
        == "https://app.example.test/auth/callback/google"
    )


async def _bind(session: AsyncSession, workspace: Workspace) -> None:
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(workspace.tenant_id)}
    )
