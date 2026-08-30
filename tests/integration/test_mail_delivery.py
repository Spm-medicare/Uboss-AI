"""Getting the mail out — the half that was a placeholder until now.

The outbox has recorded reset requests since Gate 1 and nothing delivered them, so
`mail_is_configured` was false and the screen said so. `notifications.mail` and
`notifications.publishers` are what make it true, and these are the checks that keep them honest.

**The whole point of the sender is the TLS rule.** `smtplib` will happily put a live
password-reset token on a plaintext socket if nothing stops it, and an SMTP server that quietly
stops offering `STARTTLS` is the attack: every reset link that passes through it is readable. So
that is the first test, driven against a real socket that answers `EHLO` and offers nothing.

**A publisher that returns means delivered.** The relay marks the row on a return, so a publisher
that swallows an error marks a mail as sent that never left the building. That is the second test.

No live provider is involved. A test that needed real credentials is a test that runs on one
machine.
"""

from __future__ import annotations

import asyncio
import socket
import threading
import uuid

import pytest
from pydantic import SecretStr

from uboss.core.settings import Settings
from uboss.modules.audit.relay import Event, PublisherMissing
from uboss.modules.notifications import mail, publishers

pytestmark = pytest.mark.anyio


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "smtp_host": "127.0.0.1",
        "smtp_port": 2525,
        "smtp_username": "postmaster@example.test",
        "smtp_password": SecretStr("app-password"),
        "mail_from_name": "UBOSS AI",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _event(event_type: str, payload: dict[str, object]) -> Event:
    return Event(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        event_type=event_type,
        subject_type="user",
        subject_id=uuid.uuid4(),
        payload=payload,
        attempts=1,
        correlation_id="test-correlation",
    )


class _PlaintextServer:
    """An SMTP server that greets and offers no `STARTTLS`.

    Deliberately not a real one. It answers `EHLO` with a capability list that has no `STARTTLS`
    in it and then does nothing else, which is exactly the situation the sender has to refuse —
    a downgrade, whether by a misconfigured relay or somebody sitting in the middle.
    """

    def __init__(self) -> None:
        self._sock = socket.socket()
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(1)
        self.port: int = self._sock.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def __enter__(self) -> _PlaintextServer:
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._sock.close()

    def _serve(self) -> None:
        try:
            conn, _ = self._sock.accept()
        except OSError:
            return
        with conn:
            conn.sendall(b"220 plaintext.example.test ESMTP\r\n")
            try:
                conn.recv(1024)  # EHLO
                #  No STARTTLS in the list. Everything else a server normally offers.
                conn.sendall(b"250-plaintext.example.test\r\n250-SIZE 35882577\r\n250 8BITMIME\r\n")
                conn.recv(1024)
            except OSError:
                return


async def test_the_sender_refuses_a_server_that_will_not_do_starttls() -> None:
    """**The one that matters.**

    A password-reset link on a plaintext socket is the whole compromise. `starttls()` raises when
    the server does not offer it, and nothing in `_send_blocking` catches that — so the send
    fails, the relay records the reason against the row, and an operator finds out. The
    alternative is a system that silently downgrades and looks like it is working.
    """
    with _PlaintextServer() as server:
        settings = _settings(smtp_port=server.port)
        with pytest.raises(Exception) as refused:
            await mail.send(
                mail.Message(to="somebody@example.test", subject="Reset", body="link"),
                settings,
            )

    #  Not asserting the exact class: `smtplib` raises `SMTPNotSupportedError` for a server that
    #  omits the capability and an `SMTPException` for one that offers it and then fails. Both
    #  are correct refusals, and pinning one would make this test fail on a *better* refusal.
    assert "starttls" in str(refused.value).lower() or "tls" in str(refused.value).lower()


async def test_an_unconfigured_deployment_refuses_rather_than_pretending() -> None:
    """No credentials means the send raises, not returns.

    Returning would mark the outbox row published — a reset recorded as sent by a system that
    cannot send at all, which is the exact failure the `delivery: unavailable` answer exists to
    prevent on the screen.
    """
    settings = Settings(smtp_host="", smtp_username="", smtp_password=SecretStr(""))
    assert not settings.mail_is_configured

    with pytest.raises(RuntimeError) as refused:
        await mail.send(
            mail.Message(to="somebody@example.test", subject="Reset", body="link"), settings
        )
    assert "cannot send mail" in str(refused.value)


def test_the_sender_address_falls_back_to_the_account_it_authenticates_as() -> None:
    """Sending as an address the account is not authorised for is the commonest silent refusal."""
    assert _settings().mail_sender == "postmaster@example.test"
    assert (
        _settings(mail_from_address="noreply@example.test").mail_sender
        == "noreply@example.test"
    )


def test_a_host_without_credentials_is_not_configured() -> None:
    """All three, or none.

    A deployment with a host and no credentials would queue events that could never be delivered
    while the screen told people to check their inbox.
    """
    assert not Settings(
        smtp_host="smtp.example.test", smtp_username="", smtp_password=SecretStr("")
    ).mail_is_configured
    assert not Settings(
        smtp_host="", smtp_username="a@b.c", smtp_password=SecretStr("p")
    ).mail_is_configured
    assert _settings().mail_is_configured


async def test_every_event_the_product_queues_has_a_publisher() -> None:
    """An event type nothing listens for is dead-lettered on its first attempt.

    That is the relay's design and it is the right one — but it means adding an event type
    without adding a publisher produces a notification nobody knows was never sent. This is the
    check that turns that into a test failure instead.
    """
    registry = publishers.build(_settings())
    assert "identity.password_reset_requested" in registry.registered
    assert "identity.invite_issued" in registry.registered

    with pytest.raises(PublisherMissing):
        registry.publisher_for("identity.something_nobody_wired_up")


async def test_a_failing_provider_propagates_out_of_the_publisher() -> None:
    """The relay treats a return as proof of delivery.

    So a publisher that catches its own errors turns the outbox into a table of events marked
    sent that were never sent. Nothing is listening on this port; the connection error has to
    come back out.
    """
    #  Port 1 is reserved and nothing binds it, so the connection is refused immediately rather
    #  than hanging for the socket timeout.
    registry = publishers.build(_settings(smtp_port=1))
    publisher = registry.publisher_for("identity.password_reset_requested")

    with pytest.raises(OSError):
        await asyncio.wait_for(
            publisher(
                _event(
                    "identity.password_reset_requested",
                    {
                        "email": "somebody@example.test",
                        "reset_url": "https://uboss.example/reset-password?token=abc",
                        "expires_in_minutes": 30,
                    },
                )
            ),
            timeout=30,
        )


def test_the_reset_mail_says_that_nothing_has_changed_if_it_was_not_you() -> None:
    """The sentence that separates this mail from the phishing mail imitating it.

    A reset mail that says "click here to secure your account" is indistinguishable from an
    attack. One that says the password has *not* changed gives the recipient something true to
    check the link against.
    """
    body = publishers._reset_body(
        reset_url="https://uboss.example/reset-password?token=abc",
        minutes=30,
        product="UBOSS AI",
    )
    assert "https://uboss.example/reset-password?token=abc" in body
    assert "30 minutes" in body
    assert "If this was not you" in body
    assert "has not been\nchanged" in body
    #  No password is ever mailed. 1.2.6 states it as a rule that does not bend, and the body is
    #  the only place it could be broken.
    assert "password is" not in body.lower().replace("password has not been", "")
