"""What the analysis and the graph return.

The timeline is the part worth reading carefully. `AnalysisRead.stages` covers all six whether or
not they have run, so the screen draws a stage that has not started as *not started* rather than
as missing — which is what makes an honest timeline cheap enough to actually build.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from uboss.modules.objectives.proposal_models import (
    ProposalStatus,
    Stage,
    StageState,
    StepKind,
    StepSource,
)


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StepCreate(_Payload):
    kind: StepKind
    title: str = Field(min_length=1, max_length=300)
    detail: str | None = None
    responsible_role: str | None = Field(default=None, max_length=200)
    #: Insert after this step. Absent puts it at the end.
    after_step_id: uuid.UUID | None = None


class StepUpdate(_Payload):
    kind: StepKind | None = None
    title: str | None = Field(default=None, min_length=1, max_length=300)
    detail: str | None = None
    responsible_role: str | None = Field(default=None, max_length=200)
    rationale: str | None = None
    expected_version: int = Field(ge=1)


class StepDelete(_Payload):
    expected_version: int = Field(ge=1)


class StepMerge(_Payload):
    into_step_id: uuid.UUID


class PlanReorder(_Payload):
    """The whole order, not a move.

    "Step X to position 4" needs the client and the server to agree on what the other positions
    were, and after a concurrent edit they do not.
    """

    order: list[uuid.UUID]


class StepDependencies(_Payload):
    depends_on: list[uuid.UUID]


class StepRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    position: int
    kind: StepKind
    title: str
    detail: str | None
    responsible_role: str | None
    #: Which of the current-process steps this replaces. Null where the plan introduces work that
    #: did not exist before.
    replaces_current_step: int | None
    #: Why it is there, in the model's own words. Shown beside the step so a reviewer sees the
    #: reasoning and not only the conclusion.
    rationale: str | None
    source: StepSource
    #: True when the model proposed it and a person changed it. `source == "ai" and edited` is
    #: PLAN §7's "compare AI/human changes", as a flag.
    edited: bool
    version: int
    depends_on: list[uuid.UUID] = Field(default_factory=list)


class StageRead(BaseModel):
    """One of the six, whether or not it has run."""

    stage: Stage
    state: StageState | None
    detail: str | None = None
    at: datetime | None = None


class AnalysisRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: ProposalStatus
    stage: Stage | None
    model: str | None
    input_tokens: int
    output_tokens: int
    latency_ms: int
    failure_detail: str | None
    started_at: datetime
    finished_at: datetime | None
    #: All six, in order. A stage with a null `state` has not started.
    stages: list[StageRead] = Field(default_factory=list)
    #: The model's note, when it had one — usually that the current process was too thin to plan
    #: from. Worth showing: it is the difference between "no plan" and "no plan, and here is why".
    note: str | None = None


class PlanRead(BaseModel):
    """The execution graph, and where it came from."""

    objective_id: uuid.UUID
    steps: list[StepRead]
    #: The most recent analysis, if there has been one.
    analysis: AnalysisRead | None = None
    #: True when there is no plan yet — distinct from a plan somebody emptied, which reads the
    #: same on screen and means something different.
    never_analysed: bool
    #: How many steps the model proposed and a person has since changed. §7's comparison, as a
    #: number a reviewer can act on.
    ai_steps: int = 0
    edited_ai_steps: int = 0
    human_steps: int = 0
