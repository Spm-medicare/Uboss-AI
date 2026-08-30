"""The resolver — §39's flow, from a requirement to a route, with the evidence kept.

    Agent requirement → Search Skill Registry → Deterministic compatibility gates
    → Reuse | Configure | Compose | Create private Skill Draft

Five endings, and `blocked` is one of them: *"Block/route change when no safe choice exists"* is a
decision this module is required to be able to reach, not a failure to reach one.

**Order of precedence, and why it is this order.** Reuse before compose, compose before configure,
configure before create, create before blocked — each step is the cheapest honest answer available
at that point. Reuse asks nothing of anyone. Compose asks the caller to accept a set. Configure
asks them to supply something named. Create asks them to build. Blocked asks them to change the
work. Offering a later one when an earlier one was available wastes somebody's afternoon; offering
an earlier one when it was not is the failure this whole module exists to prevent.

**A refused candidate is still recorded.** Every candidate the search returned goes into the
decision with the gates that judged it, passes included. "Nothing matched" and "four things
matched and every one was refused, here is each reason" are different answers, and the second is
the one somebody can act on.

**Similarity never overrides a hard gate.** The search's top-ranked hit is selected only if it
passes every gate; otherwise a lower-ranked candidate that passes wins. The rank is recorded
either way, so a decision that overrode the ranking shows that it did.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uboss.core.context import SecurityContext
from uboss.core.permissions import Action
from uboss.modules.agents import gates, search
from uboss.modules.agents.gates import Outcome, Requirement, Verdict
from uboss.modules.agents.models import ResolverRoute, SkillResolverDecision
from uboss.modules.audit import service as audit
from uboss.modules.identity import guard

#: What a caller is told when the requirement itself is the problem. E01's own instruction is to
#: *"resolve from authoritative context or ask one focused question"*, and this is that question.
SCOPE_QUESTION = (
    "Name the department, the industry or the layer this skill is for. Without one of them the "
    "requirement matches four hundred catalogue skills, and a search that returned the first "
    "twenty would be picking for you."
)


@dataclass(frozen=True, slots=True)
class Resolution:
    """What was decided, and everything it was decided from."""

    route: ResolverRoute
    rationale: str
    verdicts: tuple[Verdict, ...]
    #: `reuse` and `configure` choose one. `compose` chooses the set in `composed_of`.
    selected_skill_id: str | None = None
    composed_of: tuple[str, ...] = ()
    #: Which declared capability each passing candidate covers. Empty when none were declared.
    coverage: dict[str, list[str]] | None = None
    #: The gates that could not run. Shared across candidates, so recorded once.
    unevaluated: tuple[gates.GateResult, ...] = ()


def _gate_json(result: gates.GateResult) -> dict[str, Any]:
    return {
        "gate": result.gate,
        "name": result.name,
        "outcome": str(result.outcome),
        "reason": result.reason,
        "catalogue_gate_id": result.catalogue_gate_id,
        "failure_state": result.failure_state,
        "configurable": result.configurable,
        "missing": list(result.missing),
    }


def _candidate_json(
    verdict: Verdict,
    hit: search.Hit,
    *,
    covers: list[str],
    selected: bool,
) -> dict[str, Any]:
    """One candidate as it goes into the record.

    `exclusions` is carried verbatim because it is the field that stops a plausible hit from being
    the wrong skill, and no gate decides it — a person does, from this text.

    `covers` and `selected` are stored on the candidate rather than as a separate list, so the row
    describes itself: reading it back needs no second structure to be kept in step with this one.
    """
    candidate = verdict.candidate
    return {
        "skill_id": candidate.skill_id,
        "catalogue_id": candidate.catalogue_id,
        "name": candidate.name,
        "layer": candidate.layer,
        "department": candidate.department,
        "industry": candidate.industry,
        "autonomy": candidate.autonomy,
        "status": candidate.status,
        "exclusions": candidate.exclusions,
        "rank": hit.rank,
        "text_match": hit.text_match,
        "passed": verdict.passed,
        "covers": covers,
        "selected": selected,
        "gates": [
            _gate_json(result)
            for result in verdict.results
            if result.outcome is not Outcome.UNEVALUATED
        ],
    }


def _requirement_json(requirement: Requirement) -> dict[str, Any]:
    return {
        "need": requirement.need,
        "autonomy_ceiling": requirement.autonomy_ceiling,
        "department": requirement.department,
        "industry": requirement.industry,
        "layer": requirement.layer,
        "archetype_id": requirement.archetype_id,
        "available_inputs": list(requirement.available_inputs),
        "evidence_required": requirement.evidence_required,
        "capabilities": list(requirement.capabilities),
    }


def _blocked_on_scope(wording: dict[str, str]) -> Resolution:
    """E01, before anything is searched.

    Searching an ambiguous requirement and presenting the top twenty would be answering a question
    nobody asked. The gate's own remedy is one focused question, so that is what comes back.
    """
    failure_state = wording.get("E01")
    scope = gates.GateResult(
        gate="scope",
        name="Scope determinism",
        outcome=Outcome.FAILED,
        reason=SCOPE_QUESTION,
        catalogue_gate_id="E01" if failure_state else None,
        failure_state=failure_state,
    )
    return Resolution(
        route=ResolverRoute.BLOCKED,
        rationale=f"{failure_state or 'Scope is ambiguous'}. {SCOPE_QUESTION}",
        verdicts=(),
        unevaluated=(scope,),
    )


def _compose_set(
    coverage: dict[str, list[str]], passing: list[Verdict]
) -> tuple[str, ...] | None:
    """The smallest set of passing candidates that covers every declared capability.

    Greedy by coverage: take the candidate covering the most still-uncovered capabilities, repeat.
    A set of two where one would do is not wrong so much as harder to review, and review is what a
    composition has to survive.

    Returns nothing when some capability is covered by no passing candidate — that gap is what
    makes `create` the honest route rather than a composition with a hole in it.
    """
    uncovered = {name for name, covering in coverage.items() if covering}
    if len(uncovered) != len(coverage) or not coverage:
        return None

    remaining = dict(coverage)
    chosen: list[str] = []
    order = [verdict.candidate.skill_id for verdict in passing]
    while remaining:
        best: str | None = None
        best_count = 0
        for skill_id in order:
            count = sum(1 for covering in remaining.values() if skill_id in covering)
            if count > best_count:
                best, best_count = skill_id, count
        if best is None:
            return None
        chosen.append(best)
        remaining = {
            name: covering for name, covering in remaining.items() if best not in covering
        }
    return tuple(chosen)


def decide(
    hits: list[search.Hit],
    requirement: Requirement,
    *,
    tenant_id: str,
    wording: dict[str, str],
) -> Resolution:
    """Search results in, route out. No database, so the decision itself is testable on its own."""
    if not requirement.states_a_scope():
        return _blocked_on_scope(wording)

    verdicts = tuple(
        gates.evaluate(hit.as_candidate(), requirement, tenant_id=tenant_id, wording=wording)
        for hit in hits
    )
    unevaluated = gates.unevaluated()
    passing = [verdict for verdict in verdicts if verdict.passed]

    if not verdicts:
        return Resolution(
            route=ResolverRoute.CREATE,
            rationale=(
                "Nothing in the registry matches this requirement. Start a private Skill Draft."
            ),
            verdicts=verdicts,
            unevaluated=unevaluated,
        )

    coverage: dict[str, list[str]] | None = None
    if requirement.capabilities:
        coverage = gates.covered_capabilities(
            [verdict.candidate for verdict in passing], requirement
        )

    #  Reuse — one candidate that passes every gate and, where capabilities were declared, covers
    #  all of them on its own.
    for verdict in passing:
        if coverage is not None:
            covers_all = all(
                verdict.candidate.skill_id in covering for covering in coverage.values()
            )
            if not covers_all:
                continue
        return Resolution(
            route=ResolverRoute.REUSE,
            rationale=(
                f"{verdict.candidate.name} passes every gate that could be evaluated. "
                f"Read its exclusions before accepting it."
            ),
            verdicts=verdicts,
            selected_skill_id=verdict.candidate.skill_id,
            coverage=coverage,
            unevaluated=unevaluated,
        )

    #  Compose — no single skill covers the requirement, but a set of gate-passing ones does.
    if coverage is not None:
        composed = _compose_set(coverage, passing)
        if composed and len(composed) > 1:
            return Resolution(
                route=ResolverRoute.COMPOSE,
                rationale=(
                    f"No single skill covers all {len(coverage)} capabilities. "
                    f"{len(composed)} together do, and each passes every gate that could be "
                    "evaluated."
                ),
                verdicts=verdicts,
                composed_of=composed,
                coverage=coverage,
                unevaluated=unevaluated,
            )

    #  Configure — a candidate whose only refusals name something the caller can supply.
    for verdict in verdicts:
        if not verdict.only_configurable_failures:
            continue
        missing = tuple(
            item for result in verdict.failures for item in result.missing
        )
        listed = "; ".join(missing) if missing else "the inputs it names"
        return Resolution(
            route=ResolverRoute.CONFIGURE,
            rationale=(
                f"{verdict.candidate.name} fits once its mandatory inputs are supplied: {listed}."
            ),
            verdicts=verdicts,
            selected_skill_id=verdict.candidate.skill_id,
            coverage=coverage,
            unevaluated=unevaluated,
        )

    #  Create — candidates passed their gates but nothing covers what was asked for.
    if passing:
        uncovered = (
            [name for name, covering in (coverage or {}).items() if not covering]
            if coverage
            else []
        )
        gap = (
            "No skill covers " + "; ".join(uncovered) + "."
            if uncovered
            else "No candidate covers the requirement on its own or in combination."
        )
        return Resolution(
            route=ResolverRoute.CREATE,
            rationale=f"{gap} Start a private Skill Draft for the gap.",
            verdicts=verdicts,
            coverage=coverage,
            unevaluated=unevaluated,
        )

    #  Blocked — candidates exist and every one is refused by a gate no configuration clears.
    first = verdicts[0].failures[0]
    quoted = f"{first.failure_state}. " if first.failure_state else ""
    return Resolution(
        route=ResolverRoute.BLOCKED,
        rationale=(
            f"{len(verdicts)} candidates were found and every one was refused. "
            f"{quoted}{verdicts[0].candidate.name}: {first.reason}"
        ),
        verdicts=verdicts,
        unevaluated=unevaluated,
    )


async def resolve(
    session: AsyncSession,
    context: SecurityContext,
    requirement: Requirement,
    *,
    source_type: str | None = None,
    source_id: uuid.UUID | None = None,
    limit: int = search.DEFAULT_LIMIT,
) -> tuple[Resolution, SkillResolverDecision]:
    """Search, gate, decide and write the decision down. One transaction; the caller commits.

    Resolving is part of designing, so it is authorised as `edit_draft` rather than `view`: it
    leaves a permanent record in the workspace, and a read-only role should not be able to.
    """
    await guard.authorise(session, context, Action.EDIT_DRAFT)

    wording = await search.gate_wording(session)
    hits = (
        await search.search(
            session,
            need=requirement.need,
            layer=requirement.layer,
            department=requirement.department,
            industry=requirement.industry,
            archetype_id=requirement.archetype_id,
            limit=limit,
        )
        if requirement.states_a_scope()
        else []
    )

    resolution = decide(hits, requirement, tenant_id=str(context.tenant_id), wording=wording)

    by_id = {verdict.candidate.skill_id: verdict for verdict in resolution.verdicts}
    chosen = set(resolution.composed_of) | (
        {resolution.selected_skill_id} if resolution.selected_skill_id else set()
    )
    covers: dict[str, list[str]] = {}
    for capability, covering in (resolution.coverage or {}).items():
        for skill_id in covering:
            covers.setdefault(skill_id, []).append(capability)

    decision = SkillResolverDecision(
        tenant_id=context.tenant_id,
        requested_by_membership_id=context.membership_id,
        requirement=_requirement_json(requirement),
        source_type=source_type,
        source_id=source_id,
        route=str(resolution.route),
        rationale=resolution.rationale,
        selected_skill_id=(
            uuid.UUID(resolution.selected_skill_id) if resolution.selected_skill_id else None
        ),
        candidates=[
            _candidate_json(
                by_id[skill_id],
                hit,
                covers=covers.get(skill_id, []),
                selected=skill_id in chosen,
            )
            for hit, skill_id in ((hit, hit.as_candidate().skill_id) for hit in hits)
            if skill_id in by_id
        ],
        unevaluated_gates=[_gate_json(result) for result in resolution.unevaluated],
    )
    session.add(decision)
    await session.flush()

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="skill.resolve",
        resource_type="skill_resolver_decision",
        resource_id=decision.id,
        actor=context,
        detail={
            "route": str(resolution.route),
            "candidates": len(resolution.verdicts),
            "refused": sum(1 for verdict in resolution.verdicts if not verdict.passed),
            "selected_skill_id": resolution.selected_skill_id,
            "unevaluated_gates": [result.gate for result in resolution.unevaluated],
        },
    )
    return resolution, decision


async def decision_by_id(
    session: AsyncSession, context: SecurityContext, decision_id: uuid.UUID
) -> SkillResolverDecision | None:
    """One recorded decision. Row-level security keeps it inside the workspace that made it."""
    await guard.authorise(session, context, Action.VIEW)
    return (
        await session.execute(
            select(SkillResolverDecision).where(SkillResolverDecision.id == decision_id)
        )
    ).scalar_one_or_none()


async def recent_decisions(
    session: AsyncSession, context: SecurityContext, *, limit: int = 50
) -> list[SkillResolverDecision]:
    """This workspace's decisions, newest first — the evidence trail as a list."""
    await guard.authorise(session, context, Action.VIEW)
    rows = (
        await session.execute(
            select(SkillResolverDecision)
            .order_by(SkillResolverDecision.created_at.desc())
            .limit(max(1, min(limit, 200)))
        )
    ).scalars()
    return list(rows)
