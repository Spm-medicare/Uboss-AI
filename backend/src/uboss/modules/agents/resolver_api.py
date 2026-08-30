"""The Skill Registry over HTTP — search, resolve, and the decisions that were recorded.

§39: *"Skill Registry is internal to Agent Builder and is not a sidebar module."* That is a rule
about the interface, and 5.5 keeps it. These routes exist so the Agent Builder has something to
call; nothing here adds a menu.

Searching is `view`. Resolving is `edit_draft` — it leaves a permanent record in the workspace,
and a read-only role should not be able to write one. Resolving carries an `Idempotency-Key` like
every other mutating request here: a retried resolve returns the decision it already made rather
than recording a second one that says the same thing.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from uboss.core import idempotency
from uboss.core.dependencies import CurrentContext, SessionDep
from uboss.core.errors import NotFound
from uboss.core.idempotency import require_idempotency_key
from uboss.core.permissions import Action
from uboss.modules.agents import resolver, search
from uboss.modules.agents.gates import Requirement
from uboss.modules.agents.models import ResolverRoute, SkillResolverDecision
from uboss.modules.agents.resolver_schemas import (
    CandidateOutcome,
    DecisionCard,
    DecisionList,
    GateOutcome,
    RegistryLists,
    RequirementIn,
    ResolutionRead,
    SkillCard,
    SkillSearchResult,
)
from uboss.modules.identity import guard

router = APIRouter(prefix="/skills", tags=["skills"])

#: The routes a person is asked to confirm when a gate could not run. `create` and `blocked` need
#: no confirmation — neither of them applies a skill to anything.
NEEDS_CONFIRMATION = (ResolverRoute.REUSE, ResolverRoute.CONFIGURE, ResolverRoute.COMPOSE)


def _read_decision(decision: SkillResolverDecision) -> ResolutionRead:
    """A stored decision, read back exactly as it was written.

    The gate results come out of the row rather than being recomputed. The catalogue is corrected
    over time, and re-running today's gates against last quarter's decision would produce today's
    answer and present it as history.
    """
    candidates = [
        CandidateOutcome(
            skill_id=uuid.UUID(entry["skill_id"]),
            catalogue_id=entry.get("catalogue_id"),
            name=entry["name"],
            layer=entry["layer"],
            department=entry.get("department"),
            industry=entry.get("industry"),
            autonomy=entry["autonomy"],
            status=entry["status"],
            exclusions=entry.get("exclusions"),
            rank=entry["rank"],
            text_match=entry["text_match"],
            passed=entry["passed"],
            gates=[GateOutcome(**gate) for gate in entry.get("gates", [])],
        )
        for entry in decision.candidates
    ]
    unevaluated = [GateOutcome(**gate) for gate in decision.unevaluated_gates]
    route = ResolverRoute(decision.route)
    #  Both are rebuilt from the candidates, which carry what they cover and whether they were
    #  chosen. One structure to keep true rather than three that can disagree.
    composed = [
        uuid.UUID(entry["skill_id"])
        for entry in decision.candidates
        if entry.get("selected") and route is ResolverRoute.COMPOSE
    ]
    coverage: dict[str, list[uuid.UUID]] = {}
    for entry in decision.candidates:
        for capability in entry.get("covers", []):
            coverage.setdefault(capability, []).append(uuid.UUID(entry["skill_id"]))
    return ResolutionRead(
        decision_id=decision.id,
        route=route,
        rationale=decision.rationale,
        selected_skill_id=decision.selected_skill_id,
        composed_of=composed,
        candidates=candidates,
        coverage=coverage,
        unevaluated_gates=unevaluated,
        requires_confirmation=bool(unevaluated) and route in NEEDS_CONFIRMATION,
        created_at=decision.created_at,
    )


@router.get("", summary="Search the Skill Registry")
async def search_registry(
    context: CurrentContext,
    session: SessionDep,
    q: Annotated[str, Query(max_length=2000)] = "",
    layer: Annotated[str | None, Query(max_length=40)] = None,
    department: Annotated[str | None, Query(max_length=200)] = None,
    industry: Annotated[str | None, Query(max_length=200)] = None,
    archetype_id: Annotated[str | None, Query(max_length=8)] = None,
    limit: Annotated[int, Query(ge=1, le=search.MAX_LIMIT)] = search.DEFAULT_LIMIT,
) -> SkillSearchResult:
    """Ranked candidates — the shared catalogue and this workspace's own drafts together.

    This ranks; it does not decide. A result here has passed no gate, which is why the card
    carries the skill's exclusions and its autonomy rather than a tick.
    """
    await guard.authorise(session, context, Action.VIEW)
    hits = await search.search(
        session,
        need=q,
        layer=layer,
        department=department,
        industry=industry,
        archetype_id=archetype_id,
        limit=limit,
    )
    cards = [
        SkillCard(
            id=hit.skill.id,
            catalogue_id=hit.skill.catalogue_id,
            name=hit.skill.name,
            layer=hit.skill.layer,
            department=hit.skill.department,
            industry=hit.skill.industry,
            archetype_id=hit.skill.archetype_id,
            purpose=hit.skill.purpose,
            positive_trigger=hit.skill.positive_trigger,
            exclusions=hit.skill.exclusions,
            minimum_inputs=hit.skill.minimum_inputs,
            autonomy=hit.skill.autonomy,
            status=hit.skill.status,
            is_catalogue=hit.skill.is_catalogue,
            rank=hit.rank,
            text_match=hit.text_match,
        )
        for hit in hits
    ]
    return SkillSearchResult(results=cards, total=len(cards), is_empty=not cards)


@router.get("/lists", summary="The registry's own vocabulary, for the filters")
async def registry_lists(context: CurrentContext, session: SessionDep) -> RegistryLists:
    """Read from the rows, so a filter can never offer a value that matches nothing."""
    await guard.authorise(session, context, Action.VIEW)
    layers, departments, industries, archetypes = await search.registry_lists(session)
    return RegistryLists(
        layers=layers,
        departments=departments,
        industries=industries,
        archetypes=[{"id": code, "name": name} for code, name in archetypes],
    )


@router.get("/resolutions", summary="Decisions this workspace has recorded")
async def list_resolutions(
    context: CurrentContext,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> DecisionList:
    """The evidence trail. Newest first, because the question is usually about the last one."""
    decisions = await resolver.recent_decisions(session, context, limit=limit)
    cards = [
        DecisionCard(
            id=decision.id,
            route=ResolverRoute(decision.route),
            rationale=decision.rationale,
            selected_skill_id=decision.selected_skill_id,
            need=str(decision.requirement.get("need", "")),
            candidates=len(decision.candidates),
            refused=sum(1 for entry in decision.candidates if not entry.get("passed")),
            created_at=decision.created_at,
        )
        for decision in decisions
    ]
    return DecisionList(decisions=cards, is_empty=not cards)


@router.get("/resolutions/{decision_id}", summary="One recorded decision, in full")
async def read_resolution(
    decision_id: uuid.UUID, context: CurrentContext, session: SessionDep
) -> ResolutionRead:
    """Every candidate and every gate, as they stood when the decision was made."""
    decision = await resolver.decision_by_id(session, context, decision_id)
    if decision is None:
        raise NotFound("That decision does not exist.")
    return _read_decision(decision)


@router.post(
    "/resolve",
    status_code=status.HTTP_201_CREATED,
    summary="Resolve a requirement to a route",
)
async def resolve_requirement(
    body: RequirementIn,
    context: CurrentContext,
    session: SessionDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> ResolutionRead:
    """§39's flow, end to end, with the evidence written down before the answer comes back.

    A requirement naming no department, industry or layer comes back `blocked` with E01's own
    words and the one question to answer — not a list of twenty guesses.
    """
    async with idempotency.execute(
        session,
        tenant_id=context.tenant_id,
        key=idempotency_key,
        operation="skill.resolve",
        payload=body.model_dump(mode="json"),
    ) as execution:
        if execution.is_replay:
            return ResolutionRead.model_validate(execution.replay_body)

        requirement = Requirement(
            need=body.need,
            autonomy_ceiling=body.autonomy_ceiling,
            department=body.department,
            industry=body.industry,
            layer=body.layer,
            archetype_id=body.archetype_id,
            available_inputs=tuple(body.available_inputs),
            evidence_required=body.evidence_required,
            capabilities=tuple(body.capabilities),
        )
        resolution, decision = await resolver.resolve(
            session,
            context,
            requirement,
            source_type=body.source_type,
            source_id=body.source_id,
        )

        result = ResolutionRead(
            decision_id=decision.id,
            route=resolution.route,
            rationale=resolution.rationale,
            selected_skill_id=decision.selected_skill_id,
            composed_of=[uuid.UUID(value) for value in resolution.composed_of],
            candidates=[
                CandidateOutcome(
                    skill_id=uuid.UUID(entry["skill_id"]),
                    catalogue_id=entry.get("catalogue_id"),
                    name=entry["name"],
                    layer=entry["layer"],
                    department=entry.get("department"),
                    industry=entry.get("industry"),
                    autonomy=entry["autonomy"],
                    status=entry["status"],
                    exclusions=entry.get("exclusions"),
                    rank=entry["rank"],
                    text_match=entry["text_match"],
                    passed=entry["passed"],
                    gates=[GateOutcome(**gate) for gate in entry.get("gates", [])],
                )
                for entry in decision.candidates
            ],
            coverage={
                name: [uuid.UUID(value) for value in ids]
                for name, ids in (resolution.coverage or {}).items()
            },
            unevaluated_gates=[
                GateOutcome(
                    gate=result.gate,
                    name=result.name,
                    outcome=str(result.outcome),
                    reason=result.reason,
                    catalogue_gate_id=result.catalogue_gate_id,
                    failure_state=result.failure_state,
                    configurable=result.configurable,
                    missing=list(result.missing),
                )
                for result in resolution.unevaluated
            ],
            requires_confirmation=(
                bool(resolution.unevaluated) and resolution.route in NEEDS_CONFIRMATION
            ),
            created_at=decision.created_at,
        )
        execution.complete_json(
            status_code=status.HTTP_201_CREATED, body=result.model_dump(mode="json")
        )
        return result


@router.get("/{skill_id}", summary="One skill, in full")
async def read_skill(
    skill_id: uuid.UUID, context: CurrentContext, session: SessionDep
) -> SkillCard:
    """Declared last so `/lists` and `/resolutions` are not swallowed by the path parameter."""
    await guard.authorise(session, context, Action.VIEW)
    skill = await search.by_id(session, skill_id)
    if skill is None:
        raise NotFound("That skill does not exist.")
    return SkillCard(
        id=skill.id,
        catalogue_id=skill.catalogue_id,
        name=skill.name,
        layer=skill.layer,
        department=skill.department,
        industry=skill.industry,
        archetype_id=skill.archetype_id,
        purpose=skill.purpose,
        positive_trigger=skill.positive_trigger,
        exclusions=skill.exclusions,
        minimum_inputs=skill.minimum_inputs,
        autonomy=skill.autonomy,
        status=skill.status,
        is_catalogue=skill.is_catalogue,
        rank=1,
        text_match=0.0,
    )
