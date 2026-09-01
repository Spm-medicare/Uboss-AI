"""What the registry search and the resolver accept and return.

Everything a screen shows about a decision comes from here, and everything here comes from a row
or from a gate that ran. There is no confidence percentage, no "success rate" and no match score
dressed up as certainty — `text_match` is Postgres's `ts_rank_cd` value reported as it comes, and
it is labelled as what it is. CLAUDE.md forbids displaying a value the backend did not return, and
a number invented here would satisfy the letter of that while breaking it.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from uboss.modules.agents.gates import AUTONOMY_ORDER
from uboss.modules.agents.models import ResolverRoute


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SkillCard(BaseModel):
    """A skill as a search result shows it.

    `exclusions` is on the card rather than behind a link on purpose: it is what the skill is
    *not* for, and it is the field that stops a plausible hit from being the wrong choice. Hiding
    it one click away would mean most people never read it.
    """

    id: uuid.UUID
    catalogue_id: str | None
    name: str
    layer: str
    department: str | None
    industry: str | None
    archetype_id: str | None
    purpose: str | None
    positive_trigger: str | None
    exclusions: str | None
    minimum_inputs: str | None
    autonomy: str
    status: str
    #: True for one of the 400 shared rows; false for this workspace's own draft.
    is_catalogue: bool
    rank: int
    #: `ts_rank_cd`. A relative ordering value, not a confidence.
    text_match: float


class SkillSearchResult(BaseModel):
    """`is_empty` separates "nothing matches" from "this filter matches nothing" for the screen."""

    results: list[SkillCard]
    total: int
    is_empty: bool


class GateOutcome(BaseModel):
    """One gate's verdict, with the catalogue's own words where it has them."""

    gate: str
    name: str
    #: `passed`, `failed` or `unevaluated`. Unevaluated is not a pass.
    outcome: str
    reason: str
    #: The exactness gate this refusal quotes, when one of the twelve says exactly this.
    catalogue_gate_id: str | None = None
    failure_state: str | None = None
    #: True when supplying something would clear it — the difference between Configure and Block.
    configurable: bool = False
    #: For minimum inputs: what is still needed, in the catalogue's words, ready as a checklist.
    missing: list[str] = Field(default_factory=list)


class CandidateOutcome(BaseModel):
    """A candidate and every gate that judged it — refusals and passes both."""

    skill_id: uuid.UUID
    catalogue_id: str | None
    name: str
    layer: str
    department: str | None
    industry: str | None
    autonomy: str
    status: str
    exclusions: str | None
    rank: int
    text_match: float
    passed: bool
    gates: list[GateOutcome]


class RequirementIn(_Payload):
    """The requirement, stated rather than inferred.

    E01 refuses an ambiguous scope, so a scope this API guessed at would defeat the gate meant to
    catch it. `department`, `industry` and `layer` are individually optional and collectively not:
    a requirement naming none of them comes back blocked, with the one question to answer.
    """

    need: str = Field(min_length=1, max_length=2000)
    autonomy_ceiling: str = Field(default="A1", pattern="^A[1-4]$")
    department: str | None = Field(default=None, max_length=200)
    industry: str | None = Field(default=None, max_length=200)
    layer: str | None = Field(default=None, max_length=40)
    archetype_id: str | None = Field(default=None, max_length=8)
    #: In the catalogue's own vocabulary. The gate publishes the list to tick, so this is chosen
    #: from `minimum_inputs` rather than typed from memory.
    available_inputs: list[str] = Field(default_factory=list, max_length=100)
    evidence_required: bool = False
    #: Two or more with no single skill covering them is what makes Compose the honest route.
    capabilities: list[str] = Field(default_factory=list, max_length=20)
    #: Where the requirement came from, when it came from somewhere — a job step, usually.
    source_type: str | None = Field(default=None, max_length=40)
    source_id: uuid.UUID | None = None


class ResolutionRead(BaseModel):
    """The route, why, and everything it was decided from.

    `unevaluated_gates` is not decoration. Those are gates that could not run because what they
    read is not modelled yet, and a resolution carrying any of them is offered for confirmation
    rather than applied — which is what `requires_confirmation` says out loud.
    """

    decision_id: uuid.UUID
    route: ResolverRoute
    rationale: str
    selected_skill_id: uuid.UUID | None
    composed_of: list[uuid.UUID]
    candidates: list[CandidateOutcome]
    #: Which passing candidates cover each declared capability. Empty when none were declared.
    coverage: dict[str, list[uuid.UUID]]
    unevaluated_gates: list[GateOutcome]
    requires_confirmation: bool
    created_at: datetime


class DecisionCard(BaseModel):
    """One past decision, as a list shows it."""

    id: uuid.UUID
    route: ResolverRoute
    rationale: str
    selected_skill_id: uuid.UUID | None
    need: str
    candidates: int
    refused: int
    created_at: datetime


class DecisionList(BaseModel):
    decisions: list[DecisionCard]
    is_empty: bool


class RegistryLists(BaseModel):
    """The registry's own vocabulary, served rather than copied into the frontend.

    A second copy of an approved list is a copy that drifts. The layers, departments, industries
    and archetypes here are the distinct values actually present in the catalogue — so a filter
    can never offer a value that matches nothing.
    """

    layers: list[str]
    departments: list[str]
    industries: list[str]
    archetypes: list[dict[str, str]]
    #: How many skills the shared catalogue holds, and how many this workspace has added. Served
    #: because the screen states both, and a stated number that nothing counted is a number that
    #: was true of one seed and of nothing since.
    catalogue_skills: int = 0
    workspace_skills: int = 0
    autonomy: list[str] = Field(default_factory=lambda: list(AUTONOMY_ORDER))
