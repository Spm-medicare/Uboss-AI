"""The Skill Factory — a private skill, from a gap the resolver found to a version it can select.

`PLAN.md` §39's flow ends in three arrows that had nowhere to land:

    … → Reuse | Configure | Compose | Create private Skill Draft
      → Sandbox tests → Human approval → Versioned active Skill

The resolver has returned the *Create* route since 5.2 and says *"Start a private Skill Draft for
the gap"*. This is the other end of that sentence.

## The fields are the workbook's own

`docs/product/SKILL_REGISTRY.md` lists what the Factory collects, and every line of it is a column
the 400 catalogue rows already have — purpose, positive triggers, exclusions, minimum inputs,
IF-THEN decisions, output, validation gate, autonomy, source authority. That is not a coincidence
and it is the point: **a private skill is judged by the same gates as a catalogue skill.** A field
the resolver reads and the Factory does not collect would produce a draft that can never be
selected, and the completeness gates below exist to make that impossible rather than to be tidy.

The clearest case is `source_ids`. The `evidence` gate refuses a skill with no source authority —
E06 *"UNVERIFIED — no trace"* — so a skill published without one would pass approval and then be
refused by every resolution for the rest of its life. It is a submit gate here for that reason, and
the refusal says so.

## Nothing approves itself

§39: *"No Skill or Agent can approve/promote itself."* Four checks, the same four the Objective, the
Job, the Agent and the Supervisor use: the caller holds `publish` and has proved it recently, they
are the named approver, they are not the person who submitted it, and the version they read is the
version they approve. The database also refuses a published private skill that names no approver
(`ck_skills_published_was_approved`) and, since 0043, one that names no version.

## What a save costs

Saving a draft clears every test result. A pass recorded against yesterday's rules says nothing
about today's, and choosing which edits "do not count" is exactly the judgement that lets a stale
pass through — so none of them do. The Agent's tests already work this way, and the Supervisor's
simulations do too.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from uboss.core.context import SecurityContext
from uboss.core.errors import Conflict, NotFound, ValidationFailed
from uboss.core.permissions import Action
from uboss.modules.agents.agent_models import SandboxTestStatus
from uboss.modules.agents.factory_schemas import (
    DraftCard,
    DraftListRead,
    DraftRead,
    RuleRead,
    SkillTestRead,
)
from uboss.modules.agents.models import (
    Autonomy,
    Skill,
    SkillRule,
    SkillStatus,
    SkillTest,
    SkillTestKind,
    SkillVersion,
)
from uboss.modules.audit import service as audit
from uboss.modules.identity import guard
from uboss.modules.identity.models import Membership

#: What a draft has to say before anybody is asked to approve it, and why each one matters.
#:
#: Every entry is a field the resolver's gates read. That is the whole selection rule: a skill
#: missing one of these can be approved and then never selected, which is worse than a refusal
#: because nobody finds out for months.
REQUIRED: tuple[tuple[str, str], ...] = (
    ("name", "Give it a name somebody searching would recognise."),
    ("purpose", "Say what it is for, in one or two sentences."),
    (
        "positive_trigger",
        "Say when it applies. The resolver matches on this, so a skill without one is a skill "
        "nobody finds.",
    ),
    (
        "exclusions",
        "Say what it is *not* for. This is the line that stops a plausible match being the wrong "
        "skill, and it is shown on every candidate card.",
    ),
    (
        "minimum_inputs",
        "Say what it cannot start without. The minimum-inputs gate refuses a skill that would "
        "begin work on a half-filled request.",
    ),
    ("primary_if", "The main decision: under what condition."),
    ("primary_then", "The main decision: and then what."),
    ("output", "Say what it produces, so the next step knows what it is receiving."),
    (
        "validation_gate",
        "Say how its output is checked. Without one, nothing downstream can tell a good result "
        "from a confident one.",
    ),
    (
        "source_ids",
        "Name where its authority comes from — a standard, a policy, a procedure. The evidence "
        "gate refuses a skill with no trace, so one published without this would be refused by "
        "every resolution afterwards.",
    ),
)


#: A private skill's layer. The catalogue's own two — *Universal Department* and *Industry
#: Overlay* — describe where a shared skill sits in the workbook, and a tenant's own skill is
#: neither. Migration 0043 widened the constraint to admit this third value rather than have every
#: private skill wear a classification from a sheet it did not come from.
WORKSPACE_LAYER = "Workspace"


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class Gap:
    """One thing standing between a draft and an approval request."""

    field: str
    remedy: str


@dataclass(frozen=True, slots=True)
class TestState:
    kind: str
    status: str
    sample_situation: str | None
    expected_result: str | None
    actual_result: str | None
    run_at: datetime | None
    run_by_name: str | None


@dataclass(slots=True)
class DraftSummary:
    """What this draft is, and what it is waiting for."""

    skill_id: uuid.UUID
    name: str
    status: str
    version: int
    owner_name: str | None
    approver_name: str | None
    submitted_by_name: str | None
    rule_count: int
    tests_passed: int
    tests_total: int
    published_version_no: int | None
    gaps: list[Gap] = field(default_factory=list)
    next_action: str = ""
    can_submit: bool = False
    can_approve: bool = False


async def _skill(session: AsyncSession, context: SecurityContext, skill_id: uuid.UUID) -> Skill:
    """This tenant's own skill, or a refusal that does not say which.

    A catalogue row is found by the same query and then refused as *not found*: the 400 are shared
    reference data and the Factory has no business editing them. `NotFound` rather than a refusal
    naming the row, because a message distinguishing "not yours" from "does not exist" tells an
    outsider which ids are real.
    """
    row = (
        await session.execute(
            select(Skill).where(Skill.id == skill_id, Skill.tenant_id == context.tenant_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFound("No such skill draft.")
    return row


async def _name(session: AsyncSession, membership_id: uuid.UUID | None) -> str | None:
    if membership_id is None:
        return None
    membership = await session.get(Membership, membership_id)
    return membership.display_name if membership else None


def _clean(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text[:limit] if text else None


async def create(
    session: AsyncSession,
    context: SecurityContext,
    *,
    name: str,
    purpose: str | None = None,
    layer: str = WORKSPACE_LAYER,
    department: str | None = None,
    industry: str | None = None,
    archetype_id: str | None = None,
) -> Skill:
    """Start a private skill draft.

    A name is all that is required to begin — the rest is what the submit gate asks for. A form
    that demanded ten fields before it would save anything would send people to a text file, and
    `REQUIRED` is checked when it matters rather than when it is inconvenient.

    `layer` defaults to `Workspace` rather than to one of the catalogue's own layers: this skill
    belongs to one organisation, and saying so is more useful than borrowing a classification from
    a sheet it did not come from.
    """
    await guard.authorise(session, context, Action.EDIT_DRAFT)

    if not name.strip():
        raise ValidationFailed("Give the skill a name.")
    if context.membership_id is None:
        raise ValidationFailed("Only a member of this workspace can own a skill.")

    skill = Skill(
        tenant_id=context.tenant_id,
        catalogue_id=None,
        name=name.strip()[:300],
        layer=layer,
        department=_clean(department, 200),
        industry=_clean(industry, 200),
        archetype_id=archetype_id,
        purpose=_clean(purpose, 8000),
        status=SkillStatus.DRAFT,
        autonomy=Autonomy.READ,
        owner_membership_id=context.membership_id,
    )
    session.add(skill)
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="skill.draft_created",
        resource_type="skill",
        resource_id=skill.id,
        actor=context,
        detail={"name": skill.name},
    )
    return skill


#: The text fields a draft may carry, with the limit each is trimmed to. Listed rather than
#: inferred from the model, so widening what the Factory writes is a deliberate edit.
EDITABLE_FIELDS: dict[str, int] = {
    "name": 300,
    "department": 200,
    "industry": 200,
    "purpose": 8000,
    "positive_trigger": 4000,
    "exclusions": 4000,
    "minimum_inputs": 4000,
    "primary_if": 4000,
    "primary_then": 4000,
    "output": 4000,
    "validation_gate": 4000,
    "source_ids": 2000,
}


async def update(
    session: AsyncSession,
    context: SecurityContext,
    skill_id: uuid.UUID,
    *,
    expected_version: int,
    changes: dict[str, Any],
    rules: list[dict[str, Any]] | None = None,
) -> Skill:
    """Save the draft, and clear every test result.

    The clearing is not optional and not selective — see the module docstring. `rules` replaces the
    IF-THEN set wholesale when sent and leaves it alone when not, the same contract every other
    builder's collections keep.
    """
    skill = await _skill(session, context, skill_id)
    await guard.authorise(session, context, Action.EDIT_DRAFT)

    if not skill.is_editable:
        raise ValidationFailed(
            f"This skill is {str(skill.status).replace('_', ' ')}, so its design is not being "
            "edited. Withdraw it first if it needs changing."
        )
    if skill.version != expected_version:
        raise Conflict("Somebody else changed this skill. Reload it and try again.")

    for name, limit in EDITABLE_FIELDS.items():
        if name not in changes:
            continue
        value = _clean(changes[name], limit)
        if name == "name" and not value:
            raise ValidationFailed("Give the skill a name.")
        setattr(skill, name, value)

    if "archetype_id" in changes:
        skill.archetype_id = changes["archetype_id"] or None
    if changes.get("autonomy"):
        skill.autonomy = Autonomy(changes["autonomy"])

    if rules is not None:
        await _replace_rules(session, skill, rules)

    #  Results belong to the design they were recorded against.
    cleared = await _clear_results(session, context, skill.id)
    skill.version += 1

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="skill.draft_saved",
        resource_type="skill",
        resource_id=skill.id,
        actor=context,
        #  Which fields, never their values: the values are in the row, and an audit trail that
        #  copies them is a second place personal or commercial text lives.
        detail={
            "fields": sorted(name for name in changes if name in EDITABLE_FIELDS),
            "rules_replaced": rules is not None,
            "test_results_cleared": cleared,
        },
    )
    return skill


async def _replace_rules(
    session: AsyncSession, skill: Skill, rules: list[dict[str, Any]]
) -> None:
    """The IF-THEN set, replaced wholesale.

    Positions are assigned here rather than trusted from the caller: a set with two rules at
    position 3 is a list nobody can order, and the order is what a reviewer reads.
    """
    if len(rules) > 60:
        raise ValidationFailed(
            "Sixty rules is more than anybody reviews properly. Split the skill."
        )
    await session.execute(delete(SkillRule).where(SkillRule.skill_id == skill.id))
    for position, rule in enumerate(rules, start=1):
        if_clause = str(rule.get("if_clause") or "").strip()
        then_clause = str(rule.get("then_clause") or "").strip()
        if not if_clause or not then_clause:
            raise ValidationFailed(
                f"Rule {position} needs both halves: what the condition is, and what happens."
            )
        session.add(
            SkillRule(
                skill_id=skill.id,
                catalogue_id=None,
                condition_type=str(rule.get("condition_type") or "primary decision")[:60],
                if_clause=if_clause[:4000],
                then_clause=then_clause[:4000],
                priority=str(rule.get("priority") or "High")[:20],
                evidence_required=_clean(rule.get("evidence_required"), 2000),
                failure_state=_clean(rule.get("failure_state"), 120),
                human_gate=_clean(rule.get("human_gate"), 30),
                source_ids=_clean(rule.get("source_ids"), 2000),
                position=position,
            )
        )
    await session.flush()


async def _clear_results(
    session: AsyncSession, context: SecurityContext, skill_id: uuid.UUID
) -> int:
    """Reset every recorded result. Returns how many were cleared, for the audit row."""
    tests = list(
        (
            await session.execute(
                select(SkillTest).where(
                    SkillTest.tenant_id == context.tenant_id, SkillTest.skill_id == skill_id
                )
            )
        )
        .scalars()
        .all()
    )
    cleared = 0
    for test in tests:
        if test.status == SandboxTestStatus.NOT_RUN:
            continue
        test.status = SandboxTestStatus.NOT_RUN
        test.actual_result = None
        test.run_by_membership_id = None
        test.run_at = None
        cleared += 1
    if cleared:
        await session.flush()
    return cleared


async def set_test(
    session: AsyncSession,
    context: SecurityContext,
    skill_id: uuid.UUID,
    *,
    kind: str,
    sample_situation: str | None,
    expected_result: str | None,
) -> SkillTest:
    """Write down one of the six tests — the situation and what should happen.

    Separate from recording its result, because they are separate acts by (often) separate people:
    designing a test is part of designing the skill, and running it is evidence about a design that
    already exists. Writing a test also clears its own previous result, for the same reason a save
    does.
    """
    skill = await _skill(session, context, skill_id)
    await guard.authorise(session, context, Action.EDIT_DRAFT)
    if not skill.is_editable:
        raise ValidationFailed(
            "This skill is not being edited, so its tests cannot be rewritten now."
        )

    test = await _test(session, context, skill_id, kind)
    if test is None:
        test = SkillTest(
            tenant_id=context.tenant_id, skill_id=skill_id, kind=SkillTestKind(kind).value
        )
        session.add(test)

    test.sample_situation = _clean(sample_situation, 4000)
    test.expected_result = _clean(expected_result, 4000)
    #  A rewritten test has not been run. Keeping the old result would attach yesterday's outcome
    #  to today's question.
    test.status = SandboxTestStatus.NOT_RUN
    test.actual_result = None
    test.run_by_membership_id = None
    test.run_at = None
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="skill.test_written",
        resource_type="skill",
        resource_id=skill_id,
        actor=context,
        detail={"kind": test.kind},
    )
    return test


async def record_result(
    session: AsyncSession,
    context: SecurityContext,
    skill_id: uuid.UUID,
    *,
    kind: str,
    status: str,
    observed: str,
) -> SkillTest:
    """Record what happened when somebody ran a test.

    There is no sandbox runtime for a skill, so this is a person's own account of it — which is why
    it carries their name and the time, and why an observation is required. A `pass` with nothing
    to show for it is a claim nobody can check, and migration 0043 refuses one at the table as
    well.
    """
    skill = await _skill(session, context, skill_id)
    await guard.authorise(session, context, Action.EDIT_DRAFT)
    if not skill.is_editable:
        raise ValidationFailed(
            "This skill has been submitted, so results cannot be changed. Withdraw it first."
        )

    test = await _test(session, context, skill_id, kind)
    if test is None:
        raise ValidationFailed(
            "Write the test down first — the situation and what should happen — then record what "
            "it did."
        )
    if not observed.strip():
        raise ValidationFailed(
            "Say what actually happened. A result with no observation is not evidence of anything."
        )

    outcome = SandboxTestStatus(status)
    if outcome == SandboxTestStatus.NOT_RUN:
        raise ValidationFailed(
            "Recording a result means saying what happened, not that it did not."
        )

    test.status = outcome.value
    test.actual_result = observed.strip()[:4000]
    test.run_by_membership_id = context.membership_id
    test.run_at = _now()
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="skill.test_result",
        resource_type="skill",
        resource_id=skill_id,
        actor=context,
        detail={"kind": test.kind, "status": test.status},
    )
    return test


async def _test(
    session: AsyncSession, context: SecurityContext, skill_id: uuid.UUID, kind: str
) -> SkillTest | None:
    return (
        await session.execute(
            select(SkillTest).where(
                SkillTest.tenant_id == context.tenant_id,
                SkillTest.skill_id == skill_id,
                SkillTest.kind == SkillTestKind(kind).value,
            )
        )
    ).scalar_one_or_none()


async def list_drafts(session: AsyncSession, context: SecurityContext) -> DraftListRead:
    """This workspace's own skills, newest change first.

    Archived rows are included and labelled rather than filtered out: *"we never had one"* and
    *"we retired it"* are different answers, and somebody about to write a new skill needs the
    second one. The catalogue's 400 are not here — they are found by the registry search, which is
    where a shared read belongs.
    """
    rows = list(
        (
            await session.execute(
                select(Skill)
                .where(Skill.tenant_id == context.tenant_id)
                .order_by(Skill.updated_at.desc())
            )
        )
        .scalars()
        .all()
    )

    cards: list[DraftCard] = []
    for skill in rows:
        rule_count = len(
            (
                await session.execute(select(SkillRule.id).where(SkillRule.skill_id == skill.id))
            )
            .scalars()
            .all()
        )
        passed = len(
            [
                test
                for test in (
                    await session.execute(
                        select(SkillTest).where(
                            SkillTest.tenant_id == context.tenant_id,
                            SkillTest.skill_id == skill.id,
                        )
                    )
                )
                .scalars()
                .all()
                if test.status == SandboxTestStatus.PASS
            ]
        )
        cards.append(
            DraftCard(
                id=skill.id,
                name=skill.name,
                status=SkillStatus(skill.status),
                owner_name=await _name(session, skill.owner_membership_id),
                rule_count=rule_count,
                tests_passed=passed,
                updated_at=skill.updated_at,
            )
        )

    return DraftListRead(drafts=cards, is_empty=not cards)


async def read(
    session: AsyncSession, context: SecurityContext, skill_id: uuid.UUID
) -> DraftRead:
    """One private skill, with its rules in order and all six tests.

    Tests are returned for every kind, including the ones nobody has written yet, each with its
    status. A panel showing only what exists would make five missing tests look like five tests
    that are fine.
    """
    skill = await _skill(session, context, skill_id)

    rules = list(
        (
            await session.execute(
                select(SkillRule)
                .where(SkillRule.skill_id == skill.id)
                .order_by(SkillRule.position)
            )
        )
        .scalars()
        .all()
    )
    written = {
        test.kind: test
        for test in (
            await session.execute(
                select(SkillTest).where(
                    SkillTest.tenant_id == context.tenant_id, SkillTest.skill_id == skill.id
                )
            )
        )
        .scalars()
        .all()
    }

    version_no: int | None = None
    if skill.published_version_id is not None:
        version_no = (
            await session.execute(
                select(SkillVersion.version_no).where(
                    SkillVersion.tenant_id == context.tenant_id,
                    SkillVersion.id == skill.published_version_id,
                )
            )
        ).scalar_one_or_none()

    tests: list[SkillTestRead] = []
    for kind in SkillTestKind:
        test = written.get(kind.value)
        tests.append(
            SkillTestRead(
                kind=kind,
                status=test.status if test else SandboxTestStatus.NOT_RUN.value,
                sample_situation=test.sample_situation if test else None,
                expected_result=test.expected_result if test else None,
                actual_result=test.actual_result if test else None,
                run_at=test.run_at if test else None,
                run_by_name=(
                    await _name(session, test.run_by_membership_id) if test else None
                ),
            )
        )

    return DraftRead(
        id=skill.id,
        name=skill.name,
        status=SkillStatus(skill.status),
        version=skill.version,
        layer=skill.layer,
        department=skill.department,
        industry=skill.industry,
        archetype_id=skill.archetype_id,
        purpose=skill.purpose,
        positive_trigger=skill.positive_trigger,
        exclusions=skill.exclusions,
        minimum_inputs=skill.minimum_inputs,
        primary_if=skill.primary_if,
        primary_then=skill.primary_then,
        output=skill.output,
        validation_gate=skill.validation_gate,
        autonomy=skill.autonomy,
        source_ids=skill.source_ids,
        owner_name=await _name(session, skill.owner_membership_id),
        approver_name=await _name(session, skill.approver_membership_id),
        approver_membership_id=skill.approver_membership_id,
        submitted_by_name=await _name(session, skill.submitted_by_membership_id),
        approved_by_name=await _name(session, skill.approved_by_membership_id),
        approved_at=skill.approved_at,
        published_version_no=version_no,
        rules=[
            RuleRead(
                id=rule.id,
                position=rule.position,
                condition_type=rule.condition_type,
                if_clause=rule.if_clause,
                then_clause=rule.then_clause,
                priority=rule.priority,
                evidence_required=rule.evidence_required,
                failure_state=rule.failure_state,
                human_gate=rule.human_gate,
                source_ids=rule.source_ids,
            )
            for rule in rules
        ],
        tests=tests,
        is_editable=skill.is_editable,
        created_at=skill.created_at,
        updated_at=skill.updated_at,
    )
