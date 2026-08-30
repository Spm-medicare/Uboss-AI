"""Forgetting a password, and the two rules that make the answer safe to give.

**The answer never depends on whether the account exists.** Not the message, not the shape, not
the status code. A "no such account" here is an address-enumeration oracle handed to anybody with
the form, and the whole design of `recovery.request_reset` exists to avoid producing one.

**A reset ends every session, everywhere.** Somebody resetting a password usually believes their
account is compromised. Leaving the attacker's session alive would make the reset theatre, and it
would be theatre nobody could see through — the screen would say it worked.

The delivery half is not asserted here beyond "an event was queued": whether the mail leaves the
building is `notifications.mail`'s job and `test_mail_delivery.py`'s.
"""

from __future__ import annotations

import uuid

import pytest
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from uboss.core.errors import ValidationFailed
from uboss.core.settings import Settings
from uboss.modules.identity import credentials, passwords, recovery, signup

pytestmark = pytest.mark.anyio

PASSWORD = "a-passphrase-long-enough-to-pass"
REPLACEMENT = "a-different-passphrase-entirely"


#  Function-scoped on purpose. A `redis.asyncio` client binds its connection pool to whichever
#  loop first used it, and every test here runs on its own — so one shared client works for the
#  first test and raises "attached to a different loop" for the rest.
@pytest.fixture
def redis(settings_for_tests: Settings) -> Redis:
    """A real Redis, because the token store is the thing under test.

    A fake would prove the code calls a method; this proves the token can be minted, found once,
    and not found twice — which is the property the whole flow rests on.

    **Synchronous, and never closed.** `Redis.from_url` connects lazily, so building it outside a
    loop is safe; closing it inside an async teardown is not, because the teardown may run on a
    loop that has already been closed. That raises "Event loop is closed" during teardown — a
    fixture fault that reads exactly like a product one. The connections go when the process
    does, which for a test run is moments later.
    """
    client: Redis = Redis.from_url(settings_for_tests.redis_url, decode_responses=True)
    return client


async def _founder(session: AsyncSession) -> tuple[str, signup.SignedUp]:
    email = f"founder-{uuid.uuid4().hex[:10]}@example.test"
    created = await signup.create_workspace(
        session,
        email=email,
        password=PASSWORD,
        display_name="Priya Raman",
        workspace_name=f"Northwind {uuid.uuid4().hex[:8]}",
    )
    return email, created


async def test_a_known_and_an_unknown_address_get_the_same_answer(
    app_session: AsyncSession, redis: Redis, settings_for_tests: Settings
) -> None:
    """The one property this route exists to have."""
    email, _ = await _founder(app_session)

    known = await recovery.request_reset(
        app_session, redis, settings=settings_for_tests, email=email
    )
    unknown = await recovery.request_reset(
        app_session,
        redis,
        settings=settings_for_tests,
        email=f"nobody-{uuid.uuid4().hex[:10]}@example.test",
    )

    assert known == unknown, "the answer must not vary with whether the account exists"


async def test_a_reset_link_is_queued_only_for_an_account_that_exists(
    app_session: AsyncSession, redis: Redis, settings_for_tests: Settings
) -> None:
    """Identical *answers*, different *actions*.

    The caller cannot tell the difference; the outbox can. Sending a reset link to an address
    with no account would be mailing a stranger about an account they do not have.
    """
    email, created = await _founder(app_session)

    before = (
        await app_session.execute(
            text(
                "SELECT count(*) FROM outbox_events "
                "WHERE event_type = 'identity.password_reset_requested' AND tenant_id = :tenant"
            ),
            {"tenant": str(created.tenant_id)},
        )
    ).scalar_one()

    await recovery.request_reset(
        app_session, redis, settings=settings_for_tests, email=email
    )
    await recovery.request_reset(
        app_session,
        redis,
        settings=settings_for_tests,
        email=f"nobody-{uuid.uuid4().hex[:10]}@example.test",
    )

    after = (
        await app_session.execute(
            text(
                "SELECT count(*) FROM outbox_events "
                "WHERE event_type = 'identity.password_reset_requested' AND tenant_id = :tenant"
            ),
            {"tenant": str(created.tenant_id)},
        )
    ).scalar_one()

    assert after == before + 1, "one event for the real account, none for the unknown address"


async def test_the_queued_event_carries_a_link_built_from_the_configured_base_url(
    app_session: AsyncSession, redis: Redis, settings_for_tests: Settings
) -> None:
    """Never from a request header.

    `Host` is attacker-controlled. A reset link built from one is a reset link that can be
    pointed at somebody else's server, and the person clicking it hands over a live token.
    """
    email, created = await _founder(app_session)
    await recovery.request_reset(
        app_session, redis, settings=settings_for_tests, email=email
    )

    payload = (
        await app_session.execute(
            text(
                "SELECT payload FROM outbox_events "
                "WHERE event_type = 'identity.password_reset_requested' AND tenant_id = :tenant "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"tenant": str(created.tenant_id)},
        )
    ).scalar_one()

    assert payload["email"] == email
    assert payload["reset_url"].startswith(settings_for_tests.public_base_url.rstrip("/"))
    assert "token=" in payload["reset_url"]
    assert payload["expires_in_minutes"] == settings_for_tests.password_reset_token_minutes


async def test_a_reset_replaces_the_password_and_the_token_works_once(
    app_session: AsyncSession, redis: Redis, settings_for_tests: Settings
) -> None:
    """Both halves in one test, because they are one guarantee.

    A token that can be replayed is a token an attacker can use after the person has already
    reset — so "the password changed" and "the token is spent" have to be true together.
    """
    email, created = await _founder(app_session)
    await recovery.request_reset(
        app_session, redis, settings=settings_for_tests, email=email
    )
    payload = (
        await app_session.execute(
            text(
                "SELECT payload FROM outbox_events "
                "WHERE event_type = 'identity.password_reset_requested' AND tenant_id = :tenant "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"tenant": str(created.tenant_id)},
        )
    ).scalar_one()
    token = payload["reset_url"].split("token=", 1)[1]

    before = await credentials.find_by_id(app_session, created.user_id)
    assert before is not None

    await recovery.complete_reset(
        app_session, redis, token=token, new_password=REPLACEMENT
    )

    after = await credentials.find_by_id(app_session, created.user_id)
    assert after is not None
    assert after.password_hash != before.password_hash
    assert passwords.verify_password(after.password_hash, REPLACEMENT)
    assert not passwords.verify_password(after.password_hash, PASSWORD)

    with pytest.raises(ValidationFailed):
        await recovery.complete_reset(
            app_session, redis, token=token, new_password="yet-another-passphrase"
        )


async def test_a_reset_refuses_a_password_the_sign_in_rules_would_refuse(
    app_session: AsyncSession, redis: Redis, settings_for_tests: Settings
) -> None:
    """A reset is not a way around the strength rule.

    It is the obvious place to relax one — the person is already locked out and frustrated — and
    that is exactly why it is checked here.
    """
    email, created = await _founder(app_session)
    await recovery.request_reset(
        app_session, redis, settings=settings_for_tests, email=email
    )
    payload = (
        await app_session.execute(
            text(
                "SELECT payload FROM outbox_events "
                "WHERE event_type = 'identity.password_reset_requested' AND tenant_id = :tenant "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"tenant": str(created.tenant_id)},
        )
    ).scalar_one()

    with pytest.raises(ValidationFailed):
        await recovery.complete_reset(
            app_session,
            redis,
            token=payload["reset_url"].split("token=", 1)[1],
            new_password="short",
        )


async def test_an_unknown_token_is_refused_without_saying_why(
    app_session: AsyncSession, redis: Redis
) -> None:
    """One sentence for expired, spent and never-existed.

    Distinguishing them would tell somebody holding a guessed token whether they had guessed a
    real one, which is the only thing worth learning from this endpoint.
    """
    with pytest.raises(ValidationFailed) as refused:
        await recovery.complete_reset(
            app_session, redis, token="not-a-token-anybody-minted", new_password=REPLACEMENT
        )
    assert "expired or was already used" in str(refused.value)
