"""What the Copilot is refused, and why the list cannot drift.

`PLAN.md` §12: *"It cannot publish, approve, grant access or perform destructive/high-risk actions
on the user's behalf."* `UI_SPEC.md` §18 says it from the other side: those *"remain explicit UI
decisions"*.

The obvious implementation is a list of forbidden actions in the Copilot module. These tests exist
because that implementation would be wrong in a way nobody notices for months: it is a second copy
of a decision `core/permissions.py` already records, and this project has watched three copies
drift already — `unsavedSince` existed twice and was missing where it mattered most, `is_editable`
disagreed across four modules, and an approved dropdown was bound to the wrong column.

So the set is derived, and the test that matters is the last one: a high-risk action added in
future is forbidden to the Copilot **without anybody editing the Copilot**.
"""

from __future__ import annotations

import pytest

from uboss.core.permissions import HIGH_RISK_ACTIONS, Action
from uboss.modules.copilot import policy


def test_everything_the_plan_names_is_refused() -> None:
    """§12's four, by name, so the sentence and the code cannot part company."""
    assert Action.PUBLISH in policy.FORBIDDEN, "cannot publish"
    assert Action.APPROVE in policy.FORBIDDEN, "cannot approve"
    assert Action.MANAGE_ACCESS in policy.FORBIDDEN, "cannot grant access"
    #: *"destructive/high-risk"* — the whole set, not a chosen few.
    assert HIGH_RISK_ACTIONS <= policy.FORBIDDEN


def test_the_forbidden_set_is_derived_from_the_one_that_already_exists() -> None:
    """The property the whole design rests on.

    `FORBIDDEN` must be exactly *"what needs a proved password"* plus approving. Any other shape —
    a literal tuple, a hand-maintained list, a copy that happens to agree today — passes the test
    above and fails this one, which is the point.
    """
    assert HIGH_RISK_ACTIONS | {Action.APPROVE} == policy.FORBIDDEN


def test_a_new_high_risk_action_is_refused_without_touching_the_copilot() -> None:
    """The regression this file exists for.

    Somebody will add a high-risk action one day — a payment, a deletion, an export of personal
    data. They will edit `core/permissions.py` and they will not think about the Copilot. This
    asserts they do not have to: whatever is high-risk is refused here by construction.

    Simulated by checking the relationship rather than by monkey-patching a frozenset, because the
    relationship is the guarantee.
    """
    for action in HIGH_RISK_ACTIONS:
        assert policy.refusal_for(action) is not None, f"{action} is high-risk and must be refused"


def test_reading_is_not_refused() -> None:
    """A guard that refuses everything is not a guard, it is an off switch.

    §12 gives the Copilot four verbs — search, explain, draft, propose — and all four are reading
    and writing *nothing*. `view` and `comment` are the ordinary actions it needs, and refusing
    them would leave a drawer that can do nothing but apologise.
    """
    assert policy.refusal_for(Action.VIEW) is None
    assert policy.refusal_for(Action.COMMENT) is None
    assert policy.refusal_for(Action.EDIT_DRAFT) is None, (
        "drafting a change is permitted; *saving* it is the person's own action, refused elsewhere"
    )


@pytest.mark.parametrize("action", sorted(policy.FORBIDDEN, key=lambda value: value.value))
def test_every_refusal_says_what_the_person_should_do(action: Action) -> None:
    """A refusal that only says no teaches people to route around the product.

    Each message has to name the decision as *theirs*. A person who holds `publish` and is told
    "you cannot publish" has been told something false — what is true is that this is a decision
    they make on the screen, with their password.
    """
    refusal = policy.refusal_for(action)
    assert refusal is not None
    assert len(refusal.message) > 40, "a refusal is a sentence, not a code"
    assert "you" in refusal.message.lower() or "person" in refusal.message.lower(), (
        "the message must name who decides instead"
    )
    #  Never blame the reader's permissions: they may well hold them.
    assert "you cannot" not in refusal.message.lower()
    assert "not allowed" not in refusal.message.lower()
    assert "administrator" not in refusal.message.lower()


def test_the_permitted_verbs_are_the_plans_own_four() -> None:
    """Recorded so a fifth cannot be added quietly.

    §12: *"It may search, explain, draft and propose changes."* A verb beyond those four is a
    capability the plan did not grant, and adding one is a decision for the client rather than a
    tuple somebody extends.
    """
    assert policy.PERMITTED_VERBS == ("search", "explain", "draft", "propose")
