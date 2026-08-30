"""Sending mail, over SMTP, for real.

Until now `mail_is_configured` was always false and the recovery screen said so — an honest
answer, but a placeholder one. This module is the thing that makes it true: a deployment that
sets SMTP credentials can send a password-reset link, and the screen stops apologising.

## The three decisions in here

**stdlib `smtplib`, run off the event loop.** `asyncio.to_thread` rather than a new async SMTP
dependency. A password reset is one small message on a path that already tolerates a retry — the
outbox is what provides the durability, so the client only has to be correct, not fast. Blocking
the loop on a network call would matter; a worker thread costs nothing here.

**TLS is not optional and not negotiable.** Port 465 opens an implicit TLS socket; every other
port runs `STARTTLS` and this module *raises* if the server refuses, rather than continuing in
the clear. `smtplib` will happily send a password-reset link over a plaintext socket if you let
it, which is the whole attack: an SMTP server that quietly drops `STARTTLS` support gets every
reset token that passes through it. `starttls()` raises when the server does not offer it, and
nothing here catches that.

**A failure raises.** The relay's contract says a publisher that returns has delivered. Every
`smtplib` error propagates, the relay records it against the row, and the event is retried with
backoff. Swallowing an exception here would mark a reset as sent that never left the building.

## What is deliberately absent

No HTML alternative part, no tracking pixel, no unsubscribe header. A password-reset mail is
transactional, is read once, and is the message most likely to be scrutinised by somebody
deciding whether it is a phishing attempt — so it is plain text that says who it is from, what
was asked for, and what to do if it was not them.
"""

from __future__ import annotations

import asyncio
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from uboss.core.logging import get_logger
from uboss.core.settings import Settings

log = get_logger(__name__)

#: The port that means "wrap the socket in TLS before saying anything". Every other port is
#: assumed to be the submission port and gets `STARTTLS`.
IMPLICIT_TLS_PORT = 465

#: How long to wait on the provider before giving up and letting the relay retry. Well under the
#: relay's five-minute lease, so a stuck connection never outlives the claim that owns it.
TIMEOUT_SECONDS = 20


@dataclass(frozen=True, slots=True)
class Message:
    """One mail, already rendered. Rendering is the caller's job, sending is this module's."""

    to: str
    subject: str
    body: str


def _build(message: Message, settings: Settings) -> EmailMessage:
    """The MIME message, with a real `Message-ID` and a display name.

    `make_msgid` uses the sender's own domain rather than the local hostname — a `Message-ID`
    reading `@some-container-id` is one of the cheapest spam signals there is.
    """
    mail = EmailMessage()
    mail["Subject"] = message.subject
    mail["From"] = formataddr((settings.mail_from_name, settings.mail_sender))
    mail["To"] = message.to
    mail["Message-ID"] = make_msgid(domain=settings.mail_sender.rsplit("@", 1)[-1] or None)
    #  Transactional, and never a reply to anything. Both headers exist so that a mail client
    #  and an auto-responder both treat it as such.
    mail["Auto-Submitted"] = "auto-generated"
    mail.set_content(message.body)
    return mail


def _send_blocking(mail: EmailMessage, settings: Settings) -> None:
    """The actual SMTP conversation. Runs in a worker thread; every error propagates."""
    context = ssl.create_default_context()
    password = settings.smtp_password.get_secret_value()

    if settings.smtp_port == IMPLICIT_TLS_PORT:
        client: smtplib.SMTP = smtplib.SMTP_SSL(
            settings.smtp_host, settings.smtp_port, timeout=TIMEOUT_SECONDS, context=context
        )
    else:
        client = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=TIMEOUT_SECONDS)

    with client:
        client.ehlo()
        if settings.smtp_port != IMPLICIT_TLS_PORT:
            #  Not wrapped in a try. If the server does not offer STARTTLS this raises, the
            #  event is retried and eventually dead-lettered, and an operator finds out. The
            #  alternative — sending anyway — puts a live reset token on the wire in plaintext.
            client.starttls(context=context)
            client.ehlo()
        if settings.smtp_username:
            client.login(settings.smtp_username, password)
        client.send_message(mail)


async def send(message: Message, settings: Settings) -> None:
    """Send one message, or raise.

    Raising is the point: the relay treats a return as proof of delivery, so anything that went
    wrong has to come back out of here.
    """
    if not settings.mail_is_configured:
        raise RuntimeError(
            "No SMTP credentials are configured, so this deployment cannot send mail. "
            "Set UBOSS_SMTP_HOST, UBOSS_SMTP_USERNAME and UBOSS_SMTP_PASSWORD."
        )

    await asyncio.to_thread(_send_blocking, _build(message, settings), settings)
    #  The address is logged at domain granularity only. A log line naming who was sent a
    #  password-reset link is a log line that answers "does this person have an account".
    log.info("mail_sent", domain=message.to.rsplit("@", 1)[-1], subject=message.subject)
