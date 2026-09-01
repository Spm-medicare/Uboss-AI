"""Retention, breach cases and the processor register — §5, §6 and §7.

## What this module does not do

**It does not delete anything.** §5 asks for policy, preview, approval and reconciliation evidence,
and every one of those is a record of a decision. The disposal itself reaches into whichever
subsystem holds the data — rows, files, indexes, caches, backups, a provider's own store — and a
function that swept all of them on one API call would be the least reviewable code in this product.

So a run carries the counts and the evidence somebody recorded, and the disposal remains an
authorised, evidenced act. That is a smaller claim than a green tick, and it is the true one. The
alternative — a scheduled job that reported *"deleted 214 rows"* with nothing anybody could check —
is exactly the shape `CLAUDE.md` forbids: *"Never display a value the backend did not return."*

The same applies to a breach notification. §6: an Agent *"may draft; it cannot decide legal
notification or send without authorised approval."* Nothing here sends anything.

## Approval is by somebody else

A retention run is prepared by one person and approved by another — migration 0045 refuses
otherwise. A disposal proposed and approved by the same person is a disposal nobody reviewed, and
this is the one control in §5 that cannot be recovered after the fact.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from uboss.core.context import SecurityContext
from uboss.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from uboss.core.logging import correlation_id
from uboss.core.permissions import Action
from uboss.modules.audit import service as audit
from uboss.modules.identity import guard
from uboss.modules.privacy.retention_models import BreachAction as BreachActionRow
from uboss.modules.privacy.retention_models import (
    BreachActionKind,
    BreachCase,
    BreachSeverity,
    BreachState,
    Disposal,
    Processor,
    ProcessorRole,
    ProcessorState,
    RetentionPolicy,
    RetentionRun,
    RunState,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _text(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned[:limit] if cleaned else None


# ── §5 policies ────────────────────────────────────────────────────────────────────────────


async def list_policies(
    session: AsyncSession, context: SecurityContext
) -> list[RetentionPolicy]:
    """Every policy, soonest review first — the ordering the register uses, for the same reason."""
    await guard.authorise(session, context, Action.VIEW)
    rows = (
        await session.execute(
            select(RetentionPolicy)
            .where(
                RetentionPolicy.tenant_id == context.tenant_id,
                RetentionPolicy.archived_at.is_(None),
            )
            .order_by(RetentionPolicy.review_due.asc().nullslast(), RetentionPolicy.name)
        )
    ).scalars()
    return list(rows.all())


async def create_policy(
    session: AsyncSession,
    context: SecurityContext,
    *,
    name: str,
    data_category: str,
    trigger: str,
    disposal: Disposal,
    purpose: str | None = None,
    jurisdiction: str | None = None,
    lifecycle_state: str | None = None,
    processing_activity_id: uuid.UUID | None = None,
    period_days: int | None = None,
    exception_note: str | None = None,
    backup_behaviour: str | None = None,
    approval_required: bool = True,
    owner_membership_id: uuid.UUID | None = None,
    review_due: date | None = None,
) -> RetentionPolicy:
    """Write down what is kept, for how long, and what happens then.

    `period_days` is optional and has no default. §5 wants a period where there is one; *"decided
    case by case"* is a real answer for some categories, and a number nobody chose would be worse
    than an empty field somebody can see is empty.
    """
    await guard.authorise(session, context, Action.ADMINISTER)

    for label, value in (
        ("a name", name),
        ("what it covers", data_category),
        ("a trigger", trigger),
    ):
        if not value.strip():
            raise ValidationFailed(f"A retention policy needs {label}.")
    if period_days is not None and period_days < 0:
        raise ValidationFailed("A retention period cannot be negative.")

    policy = RetentionPolicy(
        tenant_id=context.tenant_id,
        name=name.strip()[:200],
        data_category=data_category.strip()[:200],
        purpose=_text(purpose, 4000),
        jurisdiction=_text(jurisdiction, 120),
        lifecycle_state=_text(lifecycle_state, 120),
        processing_activity_id=processing_activity_id,
        trigger=trigger.strip(),
        period_days=period_days,
        disposal=disposal.value,
        exception_note=_text(exception_note, 4000),
        backup_behaviour=_text(backup_behaviour, 4000),
        approval_required=approval_required,
        owner_membership_id=owner_membership_id,
        review_due=review_due,
    )
    session.add(policy)
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="privacy.retention_policy_created",
        resource_type="retention_policy",
        resource_id=policy.id,
        actor=context,
        detail={
            "name": policy.name,
            "disposal": policy.disposal,
            "period_days": policy.period_days,
        },
    )
    return policy


async def _policy(
    session: AsyncSession, context: SecurityContext, policy_id: uuid.UUID
) -> RetentionPolicy:
    row = (
        await session.execute(
            select(RetentionPolicy).where(
                RetentionPolicy.tenant_id == context.tenant_id,
                RetentionPolicy.id == policy_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFound("No such retention policy.")
    return row


# ── §5 runs ────────────────────────────────────────────────────────────────────────────────


async def prepare_run(
    session: AsyncSession,
    context: SecurityContext,
    policy_id: uuid.UUID,
    *,
    candidates: int,
    excluded: int,
    evidence: str,
) -> RetentionRun:
    """A preview: what this policy would dispose of, and what is being held back.

    The counts come from whoever ran the search, because this module does not perform it — see the
    module docstring. What it does is make the numbers reviewable: a preview with no evidence is a
    number nobody can check, and `evidence` is required for that reason.
    """
    policy = await _policy(session, context, policy_id)
    await guard.authorise(session, context, Action.ADMINISTER)

    if candidates < 0 or excluded < 0:
        raise ValidationFailed("A count cannot be negative.")
    if not evidence.strip():
        raise ValidationFailed(
            "Record what was searched and what was excluded. A count with no evidence behind it "
            "is not a preview, it is a number."
        )

    run = RetentionRun(
        tenant_id=context.tenant_id,
        policy_id=policy.id,
        state=RunState.PREVIEW,
        candidates=candidates,
        excluded=excluded,
        evidence=evidence.strip(),
        prepared_by_membership_id=context.membership_id,
        correlation_id=correlation_id.get(),
    )
    session.add(run)
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="privacy.retention_previewed",
        resource_type="retention_run",
        resource_id=run.id,
        actor=context,
        detail={
            "policy_id": str(policy.id),
            "candidates": candidates,
            "excluded": excluded,
        },
    )
    return run


async def approve_run(
    session: AsyncSession, context: SecurityContext, run_id: uuid.UUID
) -> RetentionRun:
    """Approve a preview — by somebody who did not prepare it.

    §5: *"Execution requires preview and approval where configured."* The refusal here is a
    sentence; migration 0045's constraint is the same rule for every other code path.

    A proved password as well. This is the act that turns a plan to delete personal data into an
    authorised one, and `administer` is already a step-up action.
    """
    run = await _run(session, context, run_id)
    await guard.authorise(session, context, Action.ADMINISTER)

    if not context.has_stepped_up():
        raise PermissionDenied(
            "Confirm your identity before approving a disposal.", code="step_up_required"
        )
    if run.state != RunState.PREVIEW:
        raise ValidationFailed("Only a preview can be approved.")
    if run.prepared_by_membership_id == context.membership_id:
        raise PermissionDenied(
            "You prepared this preview, so the approval is not yours to give. Somebody else has to "
            "approve a disposal."
        )

    run.state = RunState.APPROVED
    run.approved_by_membership_id = context.membership_id
    run.approved_at = _now()
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="privacy.retention_approved",
        resource_type="retention_run",
        resource_id=run.id,
        actor=context,
        detail={
            "policy_id": str(run.policy_id),
            "prepared_by_membership_id": str(run.prepared_by_membership_id),
        },
    )
    return run


async def record_execution(
    session: AsyncSession,
    context: SecurityContext,
    run_id: uuid.UUID,
    *,
    disposed: int,
    failed: int,
    reconciled: int,
    evidence: str,
) -> RetentionRun:
    """Record what an approved disposal actually did — §5's reconciliation.

    Only after approval, and the numbers have to add up against the preview: more disposed than
    there were candidates means the run did something nobody previewed, which is the one arithmetic
    check worth refusing on.
    """
    run = await _run(session, context, run_id)
    await guard.authorise(session, context, Action.ADMINISTER)

    if run.state != RunState.APPROVED:
        raise ValidationFailed(
            "A disposal is recorded against an approved run. This one is "
            f"{str(run.state).replace('_', ' ')}."
        )
    if min(disposed, failed, reconciled) < 0:
        raise ValidationFailed("A count cannot be negative.")
    if run.candidates is not None and disposed > run.candidates:
        raise ValidationFailed(
            f"More was disposed of ({disposed}) than the preview found ({run.candidates}). "
            "Something happened that nobody previewed — record it as a failure and investigate."
        )
    if not evidence.strip():
        raise ValidationFailed("Record what was done and how it was reconciled.")

    run.state = RunState.EXECUTED
    run.disposed = disposed
    run.failed = failed
    run.reconciled = reconciled
    run.executed_at = _now()
    #  Appended rather than replaced: the preview's evidence is part of the record of what was
    #  approved, and overwriting it would leave the approval standing on nothing.
    run.evidence = f"{run.evidence}\n\n— execution —\n{evidence.strip()}"
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="privacy.retention_executed",
        resource_type="retention_run",
        resource_id=run.id,
        actor=context,
        detail={
            "policy_id": str(run.policy_id),
            "disposed": disposed,
            "failed": failed,
            "reconciled": reconciled,
        },
    )
    return run


async def cancel_run(
    session: AsyncSession, context: SecurityContext, run_id: uuid.UUID, *, reason: str
) -> RetentionRun:
    """Decide against a preview, with a reason.

    The row stays: a plan somebody rejected is a fact about what was considered.
    """
    run = await _run(session, context, run_id)
    await guard.authorise(session, context, Action.ADMINISTER)

    if run.state not in (RunState.PREVIEW, RunState.APPROVED):
        raise ValidationFailed("Only a preview or an approved run can be cancelled.")
    if not reason.strip():
        raise ValidationFailed("Say why it is being cancelled.")

    run.state = RunState.CANCELLED
    run.evidence = f"{run.evidence}\n\n— cancelled —\n{reason.strip()}"
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="privacy.retention_cancelled",
        resource_type="retention_run",
        resource_id=run.id,
        actor=context,
        detail={"policy_id": str(run.policy_id)},
    )
    return run


async def list_runs(
    session: AsyncSession, context: SecurityContext, *, policy_id: uuid.UUID | None = None
) -> list[RetentionRun]:
    await guard.authorise(session, context, Action.VIEW)
    statement = select(RetentionRun).where(RetentionRun.tenant_id == context.tenant_id)
    if policy_id is not None:
        statement = statement.where(RetentionRun.policy_id == policy_id)
    rows = (
        await session.execute(statement.order_by(RetentionRun.prepared_at.desc()))
    ).scalars()
    return list(rows.all())


async def _run(
    session: AsyncSession, context: SecurityContext, run_id: uuid.UUID
) -> RetentionRun:
    row = (
        await session.execute(
            select(RetentionRun).where(
                RetentionRun.tenant_id == context.tenant_id, RetentionRun.id == run_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFound("No such retention run.")
    return row


# ── §6 breach cases ────────────────────────────────────────────────────────────────────────


async def _reference(session: AsyncSession, tenant_id: uuid.UUID) -> str:
    """`PDB-0003`. Sequential per workspace, under an advisory lock."""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"pdb:{tenant_id}"},
    )
    used = (
        await session.execute(
            select(func.count()).select_from(BreachCase).where(BreachCase.tenant_id == tenant_id)
        )
    ).scalar_one()
    return f"PDB-{used + 1:04d}"


async def _step(
    session: AsyncSession,
    context: SecurityContext,
    case: BreachCase,
    kind: BreachActionKind,
    detail: str,
) -> None:
    session.add(
        BreachActionRow(
            tenant_id=context.tenant_id,
            case_id=case.id,
            kind=kind.value,
            detail=detail.strip()[:4000],
            actor_membership_id=context.membership_id,
            correlation_id=correlation_id.get(),
        )
    )
    await session.flush()


async def open_case(
    session: AsyncSession,
    context: SecurityContext,
    *,
    summary: str,
    awareness_at: datetime | None = None,
    detected_at: datetime | None = None,
    severity: BreachSeverity = BreachSeverity.UNKNOWN,
    affected_systems: str | None = None,
    data_categories: str | None = None,
) -> BreachCase:
    """Open a case the moment personal data may be involved.

    §6: *"Any suspected personal-data impact opens a restricted breach case."* Suspected — so the
    bar for opening one is low and the severity starts at `unknown`, which is the honest first
    answer. `awareness_at` defaults to now because that is what it means: when somebody realised.
    """
    await guard.authorise(session, context, Action.ADMINISTER)
    if not summary.strip():
        raise ValidationFailed("Say in one line what appears to have happened.")

    case = BreachCase(
        tenant_id=context.tenant_id,
        reference=await _reference(session, context.tenant_id),
        summary=summary.strip()[:300],
        state=BreachState.OPEN,
        severity=severity.value,
        detected_at=detected_at,
        awareness_at=awareness_at or _now(),
        reported_by_membership_id=context.membership_id,
        affected_systems=_text(affected_systems, 4000),
        data_categories=_text(data_categories, 4000),
    )
    session.add(case)
    await session.flush()

    await _step(session, context, case, BreachActionKind.OPENED, case.summary)
    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="privacy.breach_opened",
        resource_type="breach_case",
        resource_id=case.id,
        actor=context,
        detail={"reference": case.reference, "severity": case.severity},
    )
    return case


#: What may be updated as a case develops, and the length each is trimmed to.
CASE_FIELDS: dict[str, int] = {
    "affected_systems": 4000,
    "affected_regions": 300,
    "data_categories": 4000,
    "impact": 8000,
    "containment": 8000,
    "remediation": 8000,
    "postmortem": 8000,
}


async def update_case(
    session: AsyncSession,
    context: SecurityContext,
    case_id: uuid.UUID,
    *,
    expected_version: int,
    changes: dict[str, object],
    note: str,
) -> BreachCase:
    """Record what has been learned. Every update leaves a step in the trail.

    `note` is required: a case that changed with nothing said about why is a case somebody will have
    to reconstruct from column diffs during the argument about what was known when.
    """
    case = await _case(session, context, case_id)
    await guard.authorise(session, context, Action.ADMINISTER)

    if case.version != expected_version:
        raise Conflict("Somebody else updated this case. Reload it and try again.")
    if not case.is_open:
        raise ValidationFailed("This case is closed.")
    if not note.strip():
        raise ValidationFailed("Say what changed and how it is known.")

    changed: list[str] = []
    for field, limit in CASE_FIELDS.items():
        if field not in changes:
            continue
        sent = changes[field]
        value = _text(sent if sent is None or isinstance(sent, str) else str(sent), limit)
        if getattr(case, field) != value:
            setattr(case, field, value)
            changed.append(field)

    if changes.get("severity"):
        chosen = BreachSeverity(str(changes["severity"])).value
        if case.severity != chosen:
            case.severity = chosen
            changed.append("severity")
    if changes.get("state"):
        chosen = BreachState(str(changes["state"])).value
        if chosen == BreachState.CLOSED:
            raise ValidationFailed("Close a case through the closing step, which needs a reason.")
        if case.state != chosen:
            case.state = chosen
            changed.append("state")
    if "estimated_principals" in changes:
        estimate = changes["estimated_principals"]
        #  Its own name, not the `value` the loop above used for strings. Two types through one
        #  local is how a reader stops being able to tell what a line means, and mypy said so.
        counted = None if estimate is None else int(str(estimate))
        if counted is not None and counted < 0:
            raise ValidationFailed("An estimate cannot be negative.")
        if case.estimated_principals != counted:
            case.estimated_principals = counted
            changed.append("estimated_principals")
    if changes.get("commander_membership_id"):
        case.commander_membership_id = uuid.UUID(str(changes["commander_membership_id"]))
        changed.append("commander_membership_id")

    case.version += 1
    await session.flush()

    await _step(session, context, case, BreachActionKind.ASSESSED, note)
    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="privacy.breach_updated",
        resource_type="breach_case",
        resource_id=case.id,
        actor=context,
        detail={"reference": case.reference, "fields": changed},
    )
    return case


async def decide_notification(
    session: AsyncSession,
    context: SecurityContext,
    case_id: uuid.UUID,
    *,
    expected_version: int,
    authority_required: bool,
    principals_required: bool,
    reason: str,
) -> BreachCase:
    """Decide whether the authority and the affected people have to be told.

    §6 is unambiguous about who decides: *"Privacy/Legal approves applicability, exact timing and
    wording. An Agent may draft; it cannot decide legal notification or send without authorised
    approval."*

    So this is a person's decision, with a proved password, and the reason is required — the
    decision *not* to notify is the one somebody will be asked to justify.
    """
    case = await _case(session, context, case_id)
    await guard.authorise(session, context, Action.ADMINISTER)

    if not context.has_stepped_up():
        raise PermissionDenied(
            "Confirm your identity before deciding a breach notification.",
            code="step_up_required",
        )
    if case.version != expected_version:
        raise Conflict("Somebody else updated this case. Reload it and try again.")
    if not reason.strip():
        raise ValidationFailed(
            "Give the reasoning. A decision not to notify is the one that will be questioned."
        )

    case.authority_notification_required = authority_required
    case.principal_notification_required = principals_required
    case.notification_decided_by_membership_id = context.membership_id
    case.notification_decided_at = _now()
    case.notification_reason = reason.strip()
    if case.state == BreachState.OPEN:
        case.state = BreachState.ASSESSING
    case.version += 1
    await session.flush()

    await _step(
        session,
        context,
        case,
        BreachActionKind.NOTIFICATION_DECIDED,
        (
            f"authority: {authority_required}; affected people: {principals_required}. "
            f"{reason.strip()}"
        ),
    )
    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="privacy.breach_notification_decided",
        resource_type="breach_case",
        resource_id=case.id,
        actor=context,
        detail={
            "reference": case.reference,
            "authority_required": authority_required,
            "principals_required": principals_required,
        },
    )
    return case


async def record_notification(
    session: AsyncSession,
    context: SecurityContext,
    case_id: uuid.UUID,
    *,
    expected_version: int,
    audience: str,
    evidence: str,
) -> BreachCase:
    """Record that a notification was sent, and what proves it.

    Recorded, not sent: nothing in this product notifies a regulator. §6 wants *"send/delivery
    evidence"*, which is what this is.

    Refused unless somebody has decided a notification was required — the table refuses it too. A
    notification sent with no decision behind it is a notification nobody authorised.
    """
    case = await _case(session, context, case_id)
    await guard.authorise(session, context, Action.ADMINISTER)

    if case.version != expected_version:
        raise Conflict("Somebody else updated this case. Reload it and try again.")
    if case.notification_decided_at is None:
        raise ValidationFailed(
            "Nobody has decided whether a notification is required. Record that decision first — "
            "it is Privacy or Legal's to make, not this system's."
        )
    if not evidence.strip():
        raise ValidationFailed("Record what was sent, to whom, and what proves delivery.")

    if audience == "authority":
        if not case.authority_notification_required:
            raise ValidationFailed(
                "The decision on record is that the authority does not need to be notified. "
                "Change the decision first, with its reasoning."
            )
        case.authority_notified_at = _now()
        kind = BreachActionKind.AUTHORITY_NOTIFIED
    elif audience == "principals":
        if not case.principal_notification_required:
            raise ValidationFailed(
                "The decision on record is that the affected people do not need to be notified. "
                "Change the decision first, with its reasoning."
            )
        case.principals_notified_at = _now()
        kind = BreachActionKind.PRINCIPALS_NOTIFIED
    else:
        raise ValidationFailed("A notification goes to the authority or to the affected people.")

    if case.state in (BreachState.OPEN, BreachState.ASSESSING, BreachState.CONTAINED):
        case.state = BreachState.NOTIFYING
    case.version += 1
    await session.flush()

    await _step(session, context, case, kind, evidence)
    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="privacy.breach_notification_recorded",
        resource_type="breach_case",
        resource_id=case.id,
        actor=context,
        detail={"reference": case.reference, "audience": audience},
    )
    return case


async def close_case(
    session: AsyncSession,
    context: SecurityContext,
    case_id: uuid.UUID,
    *,
    expected_version: int,
    reason: str,
) -> BreachCase:
    """Close a case, with the reason and the person. Both are required by the table as well."""
    case = await _case(session, context, case_id)
    await guard.authorise(session, context, Action.ADMINISTER)

    if case.version != expected_version:
        raise Conflict("Somebody else updated this case. Reload it and try again.")
    if not case.is_open:
        raise ValidationFailed("This case is already closed.")
    if not reason.strip():
        raise ValidationFailed("Say what was concluded, and why the case can be closed.")

    case.state = BreachState.CLOSED
    case.closed_by_membership_id = context.membership_id
    case.closed_at = _now()
    case.closure_reason = reason.strip()
    case.version += 1
    await session.flush()

    await _step(session, context, case, BreachActionKind.CLOSED, reason)
    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="privacy.breach_closed",
        resource_type="breach_case",
        resource_id=case.id,
        actor=context,
        detail={"reference": case.reference},
    )
    return case


async def list_cases(session: AsyncSession, context: SecurityContext) -> list[BreachCase]:
    """Open cases first, then by awareness. A closed case is history; an open one is work."""
    await guard.authorise(session, context, Action.ADMINISTER)
    rows = (
        await session.execute(
            select(BreachCase)
            .where(BreachCase.tenant_id == context.tenant_id)
            .order_by(BreachCase.closed_at.asc().nullsfirst(), BreachCase.awareness_at.desc())
        )
    ).scalars()
    return list(rows.all())


async def case_trail(
    session: AsyncSession, context: SecurityContext, case_id: uuid.UUID
) -> list[BreachActionRow]:
    case = await _case(session, context, case_id)
    await guard.authorise(session, context, Action.ADMINISTER)
    rows = (
        await session.execute(
            select(BreachActionRow)
            .where(
                BreachActionRow.tenant_id == context.tenant_id,
                BreachActionRow.case_id == case.id,
            )
            .order_by(BreachActionRow.occurred_at)
        )
    ).scalars()
    return list(rows.all())


async def _case(
    session: AsyncSession, context: SecurityContext, case_id: uuid.UUID
) -> BreachCase:
    row = (
        await session.execute(
            select(BreachCase).where(
                BreachCase.tenant_id == context.tenant_id, BreachCase.id == case_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFound("No such breach case.")
    return row


# ── §7 processors ──────────────────────────────────────────────────────────────────────────


async def list_processors(session: AsyncSession, context: SecurityContext) -> list[Processor]:
    """The register, active first.

    A retired provider stays: §7 wants its exit evidence readable afterwards.
    """
    await guard.authorise(session, context, Action.VIEW)
    rows = (
        await session.execute(
            select(Processor)
            .where(Processor.tenant_id == context.tenant_id)
            .order_by(Processor.retired_at.asc().nullsfirst(), Processor.name)
        )
    ).scalars()
    return list(rows.all())


async def register_processor(
    session: AsyncSession,
    context: SecurityContext,
    *,
    name: str,
    service: str,
    purpose: str,
    processing_role: ProcessorRole,
    data_categories: str,
    region: str | None = None,
    transfer_rule: str | None = None,
    safeguards: str | None = None,
    deletion_support: str | None = None,
) -> Processor:
    """Propose a provider. It is not active, and nothing may be sent to it yet.

    §7: *"New/materially changed subprocessors require risk review, contract approval and configured
    customer-notice/change workflow before personal data is sent."* So a new row starts `proposed`
    and the state is the workflow.
    """
    await guard.authorise(session, context, Action.ADMINISTER)

    for label, value in (
        ("a name", name),
        ("what it does", service),
        ("what it is for", purpose),
        ("which data it sees", data_categories),
    ):
        if not value.strip():
            raise ValidationFailed(f"A processor record needs {label}.")

    processor = Processor(
        tenant_id=context.tenant_id,
        name=name.strip()[:200],
        service=service.strip(),
        purpose=purpose.strip(),
        processing_role=processing_role.value,
        state=ProcessorState.PROPOSED,
        data_categories=data_categories.strip(),
        region=_text(region, 120),
        transfer_rule=_text(transfer_rule, 4000),
        safeguards=_text(safeguards, 4000),
        deletion_support=_text(deletion_support, 4000),
    )
    session.add(processor)
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="privacy.processor_proposed",
        resource_type="processor",
        resource_id=processor.id,
        actor=context,
        detail={"name": processor.name, "role": processor.processing_role},
    )
    return processor


async def approve_processor(
    session: AsyncSession,
    context: SecurityContext,
    processor_id: uuid.UUID,
    *,
    expected_version: int,
    contract_version: str,
    security_review: str,
    effective_from: date | None = None,
) -> Processor:
    """Record the review and the contract, and make the provider usable.

    Both are required, and migration 0045 refuses an `active` processor without them. §7's sentence
    is *"before personal data is sent"* — a provider marked active with no contract on record is
    personal data leaving under no agreement.
    """
    processor = await _processor(session, context, processor_id)
    await guard.authorise(session, context, Action.ADMINISTER)

    if not context.has_stepped_up():
        raise PermissionDenied(
            "Confirm your identity before approving a processor.", code="step_up_required"
        )
    if processor.version != expected_version:
        raise Conflict("Somebody else changed this record. Reload it and try again.")
    if processor.retired_at is not None:
        raise ValidationFailed("This provider has been retired.")
    if not contract_version.strip():
        raise ValidationFailed(
            "Record the contract or DPA version. Without it there is nothing to point at when "
            "somebody asks under what agreement the data is being processed."
        )
    if not security_review.strip():
        raise ValidationFailed("Record what the security review found.")

    processor.state = ProcessorState.ACTIVE
    processor.contract_version = contract_version.strip()[:120]
    processor.security_review = security_review.strip()
    processor.reviewed_by_membership_id = context.membership_id
    processor.reviewed_at = _now()
    processor.effective_from = effective_from or date.today()
    processor.version += 1
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="privacy.processor_approved",
        resource_type="processor",
        resource_id=processor.id,
        actor=context,
        detail={"name": processor.name, "contract_version": processor.contract_version},
    )
    return processor


async def retire_processor(
    session: AsyncSession,
    context: SecurityContext,
    processor_id: uuid.UUID,
    *,
    expected_version: int,
    exit_evidence: str,
) -> Processor:
    """End the relationship, with the evidence §7 asks for.

    *"Provider termination requires export, deletion confirmation and credential/key revocation
    evidence."* All three go in the note, and the table refuses a retirement without one — a
    provider marked retired with nothing recorded may still hold the data.
    """
    processor = await _processor(session, context, processor_id)
    await guard.authorise(session, context, Action.ADMINISTER)

    if processor.version != expected_version:
        raise Conflict("Somebody else changed this record. Reload it and try again.")
    if processor.retired_at is not None:
        raise ValidationFailed("This provider is already retired.")
    if not exit_evidence.strip():
        raise ValidationFailed(
            "Record the export, the deletion confirmation and the revoked credentials. A provider "
            "marked retired with nothing recorded may still hold the data."
        )

    processor.state = ProcessorState.RETIRED
    processor.retired_at = _now()
    processor.exit_evidence = exit_evidence.strip()
    processor.version += 1
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="privacy.processor_retired",
        resource_type="processor",
        resource_id=processor.id,
        actor=context,
        detail={"name": processor.name},
    )
    return processor


async def _processor(
    session: AsyncSession, context: SecurityContext, processor_id: uuid.UUID
) -> Processor:
    row = (
        await session.execute(
            select(Processor).where(
                Processor.tenant_id == context.tenant_id, Processor.id == processor_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFound("No such processor.")
    return row
