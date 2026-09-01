"""What the Copilot may never do, derived rather than listed.

`PLAN.md` §12 is the sentence this file enforces:

> It cannot publish, approve, grant access or perform destructive/high-risk actions on the user's
> behalf.

and `UI_SPEC.md` §18 says the same from the other side:

> Publish, approval, permission grant, destructive and high-risk actions remain explicit UI
> decisions.

## Why the forbidden set is derived from `HIGH_RISK_ACTIONS`

A hand-written list here would be a second copy of a decision that already exists, and copies
drift — this project has found that three times: `unsavedSince` existed twice and was missing
from the screen that lost the most data, `is_editable` disagreed across four modules, and an
approved dropdown list was bound to the wrong column for months on end.

So the set is `HIGH_RISK_ACTIONS` — the list `core/permissions.py` already keeps, which step-up
already keys off — **plus `APPROVE`**, which §12 names separately and which is deliberately not
high-risk for a person: approving is ordinary work for whoever holds the permission, and the reason
the Copilot must not do it is different. A person approves; a suggestion does not.

The property that matters: **a new high-risk action is forbidden to the Copilot automatically.**
Nobody has to remember this file exists.

## What the Copilot may do

Search, explain, draft and propose — §12's own four verbs. It reads through the same guard and the
same row-level security every other reader uses, and it writes nothing at all. A proposal it makes
is carried out by the person, through the ordinary route, with the ordinary permission check and
the ordinary step-up. The Copilot is never a second path to a write.
"""

from __future__ import annotations

from dataclasses import dataclass

from uboss.core.permissions import HIGH_RISK_ACTIONS, Action

#: Everything the Copilot is refused, whatever permission the person holds.
#:
#: Derived, not written down: `HIGH_RISK_ACTIONS` is the existing answer to *"what needs a proved
#: password"*, and §12's list is that set plus approving. A high-risk action added later is
#: forbidden here without anybody editing this file.
FORBIDDEN: frozenset[Action] = HIGH_RISK_ACTIONS | {Action.APPROVE}

#: What it may do — §12's four verbs. Listed for the reader rather than used as a gate: reading is
#: authorised by `Action.VIEW` through the same guard as every other reader, and writing is not
#: authorised at all.
PERMITTED_VERBS = ("search", "explain", "draft", "propose")


@dataclass(frozen=True, slots=True)
class Refusal:
    """Why the Copilot will not do something, in words a person can act on."""

    action: Action
    #: What the person should do instead. Never "ask an administrator" — the point is that *they*
    #: may well be allowed; the Copilot is what is not.
    message: str


def refusal_for(action: Action) -> Refusal | None:
    """Whether the Copilot is refused this action, and what to say.

    The message says who may do it rather than that it cannot be done. A person who holds
    `publish` and is told "you cannot publish" has been told something false; what is true is that
    this is a decision they make themselves, on the screen, with their password.
    """
    if action not in FORBIDDEN:
        return None

    match action:
        case Action.PUBLISH:
            return Refusal(
                action,
                "Publishing is a decision you make yourself. I have prepared what I can; "
                "open the publish screen and check the summary before you send it.",
            )
        case Action.APPROVE:
            return Refusal(
                action,
                "An approval has to be given by a person. I can show you what is waiting and "
                "what it says; the decision and its reason are yours.",
            )
        case Action.MANAGE_ACCESS:
            return Refusal(
                action,
                "Granting access is a decision you make yourself, on the access screen, with "
                "your password. I can tell you who has what today.",
            )
        case Action.INTEGRATE:
            return Refusal(
                action,
                "Connecting an outside system is a decision you make yourself. I can tell you "
                "what a job or agent says it needs.",
            )
        case Action.ADMINISTER:
            return Refusal(
                action,
                "Changing the organisation's structure or settings is a decision you make "
                "yourself. I can show you how it stands now.",
            )
        case Action.ASSIGN:
            return Refusal(
                action,
                "Putting somebody into a seat, or taking them out, is a decision you make "
                "yourself. I can tell you who holds what.",
            )
        case _:
            #  A high-risk action added later, with no sentence written for it yet. Refused
            #  anyway — failing closed is the rule, and a generic sentence is better than a
            #  capability nobody meant to grant.
            return Refusal(
                action,
                "That is a decision a person makes, not something I can do for you.",
            )
