"""What each outbox event turns into when it leaves the building.

The relay (`audit.relay`) knows how to claim, retry and dead-letter; it does not know what an
event *means*. This is where meaning lives: one function per event type, each rendering the
message and handing it to `mail.send`.

**Registration is what makes an event deliverable.** An event with no publisher here is
dead-lettered immediately with a message naming the type nothing is listening for — deliberate,
because a notification silently discarded is one nobody knows was never sent. So adding an event
type without adding it here fails loudly on the first event, which is the moment it is cheapest
to notice.

**The mail bodies are here rather than in a template file.** There are two of them, both under
twenty lines, and both are security-sensitive text that has to be read alongside the code that
decides who receives it. A template directory would put the words somewhere the reviewer of the
routing does not look.
"""

from __future__ import annotations

from uboss.core.logging import get_logger
from uboss.core.settings import Settings
from uboss.modules.audit.relay import Event, Registry
from uboss.modules.notifications import mail

log = get_logger(__name__)


def _reset_body(*, reset_url: str, minutes: int, product: str) -> str:
    """The password-reset mail.

    Written to survive being read suspiciously. It says what was asked for, does not say the
    address has an account beyond the fact it was typed into the form, gives the expiry, and
    ends with the sentence that matters most: **if this was not you, nothing has changed.** A
    reset mail that instead says "click here to secure your account" is indistinguishable from
    the phishing mail imitating it.
    """
    return (
        f"Somebody asked to reset the {product} password for this address.\n"
        f"\n"
        f"Choose a new password here:\n"
        f"{reset_url}\n"
        f"\n"
        f"The link works once and expires in {minutes} minutes.\n"
        f"\n"
        f"If this was not you, you do not need to do anything. Your password has not been\n"
        f"changed and nobody has been given access to your account.\n"
    )


def _invite_body(*, invite_url: str, minutes: int, workspace: str, inviter: str) -> str:
    """The invitation mail.

    Names the workspace and the person who sent it, because "you have been invited" from an
    unfamiliar product with neither is the shape of every credential-harvesting mail ever sent.
    """
    return (
        f"{inviter} invited you to the {workspace} workspace.\n"
        f"\n"
        f"Set your password and sign in here:\n"
        f"{invite_url}\n"
        f"\n"
        f"The link works once and expires in {minutes} minutes. If you were not expecting this,\n"
        f"you can ignore it — no account is created until you set a password.\n"
    )


def build(settings: Settings) -> Registry:
    """The registry the relay runs with.

    Takes `settings` rather than reading them at module scope so a test can build a registry
    against a stub configuration without touching the environment.
    """
    registry = Registry()

    async def password_reset(event: Event) -> None:
        payload = event.payload
        await mail.send(
            mail.Message(
                to=payload["email"],
                subject=f"Reset your {settings.mail_from_name} password",
                body=_reset_body(
                    reset_url=payload["reset_url"],
                    minutes=payload["expires_in_minutes"],
                    product=settings.mail_from_name,
                ),
            ),
            settings,
        )

    async def invite_issued(event: Event) -> None:
        payload = event.payload
        await mail.send(
            mail.Message(
                to=payload["email"],
                subject=f"You have been invited to {payload['workspace_name']}",
                body=_invite_body(
                    invite_url=payload["invite_url"],
                    minutes=payload["expires_in_minutes"],
                    workspace=payload["workspace_name"],
                    inviter=payload["invited_by"],
                ),
            ),
            settings,
        )

    registry.register("identity.password_reset_requested", password_reset)
    registry.register("identity.invite_issued", invite_issued)
    return registry
