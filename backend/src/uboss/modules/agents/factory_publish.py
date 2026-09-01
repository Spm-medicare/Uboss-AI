"""Approving a private skill, and the version approval produces.

`PLAN.md` §39's last two arrows: *"→ Sandbox tests → Human approval → Versioned active Skill"*, and
one sentence that decides the shape of this file — *"Skills cannot self-publish."*

## Two gates, and both are the contract's own

**Completeness.** Every field in `factory.REQUIRED` must be answered, because every one of them is
read by a gate the resolver runs. A skill approved without its `source_ids` passes review and is
then refused by *every* resolution afterwards — E06 *"UNVERIFIED — no trace"* — which is a worse
outcome than a refusal, because nobody finds out for months. The gate exists to make that
impossible rather than to be thorough.

**Tests.** All six of `docs/product/SKILL_REGISTRY.md`'s list must exist and read `pass`. A `fail`,
a `blocked` or a `not_run` stops the submission and says which. There is no sandbox runtime for a
skill yet, so a result is recorded by a person — and `run_by`, `run_at` and an observation are what
make that evidence rather than a checkbox. Migration 0043 refuses a decided result carrying none of
them.

Nothing else blocks. A gate this file invented would be a rule nobody approved.

## Nobody approves their own work

The same four checks as the Objective, the Job, the Agent and the Supervisor:

1. `publish` held, and proved recently — approving is a high-risk action, so step-up applies.
2. The caller is the person the draft was sent to.
3. The caller did not submit it.
4. The version they read is the version they approve.

The database refuses the rest: a submitted draft naming no submitter or approver, a published skill
naming no approver, and — since 0043 — a published skill naming no frozen version.

## What the version holds

Everything: the fields, the IF-THEN rules in order, and the six test results as they stood. A
resolver selecting this skill later is selecting what was approved, and the row cannot be edited by
anybody — a trigger refuses `UPDATE` and `DELETE`, and the privilege was never granted.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uboss.core.context import SecurityContext
from uboss.core.errors import Conflict, PermissionDenied, ValidationFailed
from uboss.core.logging import correlation_id
from uboss.core.permissions import Action
from uboss.modules.agents.agent_models import SandboxTestStatus
from uboss.modules.agents.factory import (
    REQUIRED,
    DraftSummary,
    Gap,
    _name,
    _skill,
)
from uboss.modules.agents.models import (
    Skill,
    SkillRule,
    SkillStatus,
    SkillTest,
    SkillTestKind,
    SkillVersion,
)
from uboss.modules.audit import service as audit
from uboss.modules.identity import guard


def _now() -> datetime:
    return datetime.now(UTC)


async def _rules(session: AsyncSession, skill_id: uuid.UUID) -> list[SkillRule]:
    return list(
        (
            await session.execute(
                select(SkillRule)
                .where(SkillRule.skill_id == skill_id)
                .order_by(SkillRule.position)
            )
        )
        .scalars()
        .all()
    )


async def _tests(
    session: AsyncSession, context: SecurityContext, skill_id: uuid.UUID
) -> list[SkillTest]:
    return list(
        (
            await session.execute(
                select(SkillTest)
                .where(
                    SkillTest.tenant_id == context.tenant_id,
                    SkillTest.skill_id == skill_id,
                )
                .order_by(SkillTest.kind)
            )
        )
        .scalars()
        .all()
    )


def _gaps(skill: Skill, rules: list[SkillRule], tests: list[SkillTest]) -> list[Gap]:
    """Everything standing between this draft and an approval request, each with its remedy.

    Returned as a list rather than a boolean because a screen has to say *what* is missing. A
    submit button that is simply disabled teaches people to guess.
    """
    gaps = [
        Gap(field=name, remedy=remedy)
        for name, remedy in REQUIRED
        if not (getattr(skill, name, None) or "").strip()
    ]

    if not rules:
        gaps.append(
            Gap(
                field="rules",
                remedy=(
                    "Write at least one IF-THEN decision. A skill with none has a purpose and no "
                    "method, and there is nothing for a reviewer to check."
                ),
            )
        )

    by_kind = {test.kind: test for test in tests}
    for kind in SkillTestKind:
        test = by_kind.get(kind.value)
        if test is None:
            gaps.append(
                Gap(
                    field=f"test.{kind.value}",
                    remedy=f"Write the {kind.value.replace('_', ' ')} test and run it.",
                )
            )
        elif test.status != SandboxTestStatus.PASS:
            gaps.append(
                Gap(
                    field=f"test.{kind.value}",
                    remedy=(
                        f"The {kind.value.replace('_', ' ')} test reads "
                        f"{str(test.status).replace('_', ' ')}. It has to pass."
                    ),
                )
            )
    return gaps


async def summary(
    session: AsyncSession, context: SecurityContext, skill_id: uuid.UUID
) -> DraftSummary:
    """What this draft is waiting for, and who it is waiting on.

    `can_submit` and `can_approve` are answered here rather than on the screen. The frontend asking
    the same question a second way is how a button comes to offer something the backend refuses —
    which this codebase has already had to fix on three other forms.
    """
    skill = await _skill(session, context, skill_id)
    rules = await _rules(session, skill.id)
    tests = await _tests(session, context, skill.id)
    gaps = _gaps(skill, rules, tests)
    passed = len([test for test in tests if test.status == SandboxTestStatus.PASS])

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

    can_submit = (
        skill.status == SkillStatus.DRAFT
        and not gaps
        and skill.approver_membership_id is not None
    )
    can_approve = (
        skill.status == SkillStatus.READY_TO_PUBLISH
        and Action.PUBLISH in context.granted_actions
        and skill.approver_membership_id == context.membership_id
        and skill.submitted_by_membership_id != context.membership_id
    )

    if skill.status == SkillStatus.PUBLISHED:
        next_action = "This skill is active. Resolutions can select it."
    elif skill.status == SkillStatus.ARCHIVED:
        next_action = "This skill is archived. It is kept as a record and is never selected."
    elif skill.status == SkillStatus.READY_TO_PUBLISH:
        next_action = (
            "Waiting for a decision. The person it was sent to approves it — not the person who "
            "sent it."
        )
    elif gaps:
        next_action = f"{len(gaps)} thing{'s' if len(gaps) != 1 else ''} to finish first."
    elif skill.approver_membership_id is None:
        next_action = "Name who should approve it, then send it."
    else:
        next_action = "Ready to send for approval."

    return DraftSummary(
        skill_id=skill.id,
        name=skill.name,
        status=skill.status,
        version=skill.version,
        owner_name=await _name(session, skill.owner_membership_id),
        approver_name=await _name(session, skill.approver_membership_id),
        submitted_by_name=await _name(session, skill.submitted_by_membership_id),
        rule_count=len(rules),
        tests_passed=passed,
        tests_total=len(SkillTestKind),
        published_version_no=version_no,
        gaps=gaps,
        next_action=next_action,
        can_submit=can_submit,
        can_approve=can_approve,
    )


async def set_approver(
    session: AsyncSession,
    context: SecurityContext,
    skill_id: uuid.UUID,
    approver_membership_id: uuid.UUID,
    *,
    expected_version: int,
) -> Skill:
    """Name who decides.

    A person, never a role: `can_approve` compares the named approver against the signed-in
    membership, so a label could never satisfy it and the approval could never happen.
    """
    skill = await _skill(session, context, skill_id)
    await guard.authorise(session, context, Action.EDIT_DRAFT)

    if not skill.is_editable:
        raise ValidationFailed("This skill has been submitted. Withdraw it to change the approver.")
    if skill.version != expected_version:
        raise Conflict("Somebody else changed this skill. Reload it and try again.")

    skill.approver_membership_id = approver_membership_id
    skill.version += 1
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="skill.approver_named",
        resource_type="skill",
        resource_id=skill.id,
        actor=context,
        detail={"approver_membership_id": str(approver_membership_id)},
    )
    return skill


async def submit(
    session: AsyncSession,
    context: SecurityContext,
    skill_id: uuid.UUID,
    *,
    expected_version: int,
) -> Skill:
    """Send the draft for a decision. Both gates are checked here, not only on the screen."""
    skill = await _skill(session, context, skill_id)
    await guard.authorise(session, context, Action.EDIT_DRAFT)

    if skill.status != SkillStatus.DRAFT:
        raise ValidationFailed(
            f"This skill is {str(skill.status).replace('_', ' ')}, so it is not waiting to be sent."
        )
    if skill.version != expected_version:
        raise Conflict("Somebody else changed this skill. Reload it and try again.")
    if skill.approver_membership_id is None:
        raise ValidationFailed("Name who should approve it — a person, not a role.")

    rules = await _rules(session, skill.id)
    tests = await _tests(session, context, skill.id)
    gaps = _gaps(skill, rules, tests)
    if gaps:
        raise ValidationFailed(gaps[0].remedy)

    skill.status = SkillStatus.READY_TO_PUBLISH
    skill.submitted_by_membership_id = context.membership_id
    skill.submitted_at = _now()
    skill.version += 1
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="skill.submitted",
        resource_type="skill",
        resource_id=skill.id,
        actor=context,
        detail={"approver_membership_id": str(skill.approver_membership_id)},
    )
    return skill


async def withdraw(
    session: AsyncSession,
    context: SecurityContext,
    skill_id: uuid.UUID,
    *,
    expected_version: int,
) -> Skill:
    """Take it back for more work.

    Available to whoever may edit it, not only to the person who sent it: work does not stop
    because somebody is away. What is refused is *approving* it, which is a different act.
    """
    skill = await _skill(session, context, skill_id)
    await guard.authorise(session, context, Action.EDIT_DRAFT)

    if skill.status != SkillStatus.READY_TO_PUBLISH:
        raise ValidationFailed("This skill is not waiting for a decision.")
    if skill.version != expected_version:
        raise Conflict("Somebody else changed this skill. Reload it and try again.")

    skill.status = SkillStatus.DRAFT
    skill.submitted_by_membership_id = None
    skill.submitted_at = None
    skill.version += 1
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="skill.withdrawn",
        resource_type="skill",
        resource_id=skill.id,
        actor=context,
        detail={},
    )
    return skill


def _snapshot(skill: Skill, rules: list[SkillRule], tests: list[SkillTest]) -> dict[str, Any]:
    """The whole skill, frozen.

    Assembled from rows rather than from the request: what is recorded is what the database holds,
    not what somebody sent. Test results are included because *"approved with all six passing"* is
    the claim this row exists to support.
    """
    return {
        "name": skill.name,
        "layer": skill.layer,
        "department": skill.department,
        "industry": skill.industry,
        "archetype_id": skill.archetype_id,
        "purpose": skill.purpose,
        "positive_trigger": skill.positive_trigger,
        "exclusions": skill.exclusions,
        "minimum_inputs": skill.minimum_inputs,
        "primary_if": skill.primary_if,
        "primary_then": skill.primary_then,
        "output": skill.output,
        "validation_gate": skill.validation_gate,
        "autonomy": skill.autonomy,
        "source_ids": skill.source_ids,
        "rules": [
            {
                "position": rule.position,
                "condition_type": rule.condition_type,
                "if_clause": rule.if_clause,
                "then_clause": rule.then_clause,
                "priority": rule.priority,
                "evidence_required": rule.evidence_required,
                "failure_state": rule.failure_state,
                "human_gate": rule.human_gate,
                "source_ids": rule.source_ids,
            }
            for rule in rules
        ],
        "tests": [
            {
                "kind": test.kind,
                "status": test.status,
                "sample_situation": test.sample_situation,
                "expected_result": test.expected_result,
                "actual_result": test.actual_result,
                "run_at": test.run_at.isoformat() if test.run_at else None,
            }
            for test in tests
        ],
    }


async def approve(
    session: AsyncSession,
    context: SecurityContext,
    skill_id: uuid.UUID,
    *,
    expected_version: int,
) -> SkillVersion:
    """Approve the draft and freeze it. §39: *"Skills cannot self-publish."*

    Four checks, in the order that gives the most useful refusal: the permission, then who was
    asked, then who asked, then whether the design moved. Somebody who is not the approver should
    hear that before hearing about a stale version.
    """
    skill = await _skill(session, context, skill_id)
    await guard.authorise(session, context, Action.PUBLISH)

    if not context.has_stepped_up():
        raise PermissionDenied(
            "Confirm your identity before approving.", code="step_up_required"
        )
    if skill.status != SkillStatus.READY_TO_PUBLISH:
        raise ValidationFailed("This skill is not waiting for a decision.")
    if skill.approver_membership_id != context.membership_id:
        raise PermissionDenied("This was sent to somebody else to approve.")
    if skill.submitted_by_membership_id == context.membership_id:
        raise PermissionDenied(
            "You sent this for approval, so the decision is not yours to make. "
            "Somebody else has to approve it."
        )
    if skill.version != expected_version:
        raise Conflict(
            "This skill changed after you opened it. Reload and read it again before approving."
        )

    rules = await _rules(session, skill.id)
    tests = await _tests(session, context, skill.id)
    #  Checked again at the moment of approval. The gates passed when it was sent; a test result
    #  cleared by an edit in between would otherwise be approved unnoticed.
    gaps = _gaps(skill, rules, tests)
    if gaps:
        raise ValidationFailed(
            f"This is no longer complete: {gaps[0].remedy} Send it back for the work."
        )

    version = SkillVersion(
        tenant_id=context.tenant_id,
        skill_id=skill.id,
        snapshot=_snapshot(skill, rules, tests),
        name=skill.name,
        published_by_membership_id=skill.submitted_by_membership_id,
        approved_by_membership_id=context.membership_id,
        correlation_id=correlation_id.get(),
    )
    session.add(version)
    await session.flush()

    skill.status = SkillStatus.PUBLISHED
    skill.published_version_id = version.id
    skill.approved_by_membership_id = context.membership_id
    skill.approved_at = _now()
    skill.version += 1
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="skill.approved",
        resource_type="skill",
        resource_id=skill.id,
        actor=context,
        detail={
            "version_id": str(version.id),
            "version_no": version.version_no,
            "submitted_by_membership_id": str(skill.submitted_by_membership_id),
        },
    )
    return version


async def archive(
    session: AsyncSession,
    context: SecurityContext,
    skill_id: uuid.UUID,
    *,
    expected_version: int,
) -> Skill:
    """Take it out of use, and keep it.

    Archived, never deleted: a skill that was selected by a resolution is part of why something
    happened. The published version stays exactly where it is — the pointer is left alone, so the
    record of what was approved survives the skill being retired.
    """
    skill = await _skill(session, context, skill_id)
    await guard.authorise(session, context, Action.EDIT_DRAFT)

    if skill.status == SkillStatus.ARCHIVED:
        raise ValidationFailed("This skill is already archived.")
    if skill.version != expected_version:
        raise Conflict("Somebody else changed this skill. Reload it and try again.")

    skill.status = SkillStatus.ARCHIVED
    skill.version += 1
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="skill.archived",
        resource_type="skill",
        resource_id=skill.id,
        actor=context,
        detail={},
    )
    return skill
