"""What the Agent API accepts and returns — Form 4, and `PLAN.md` §9's form groups.

The same rule the Job and the Objective follow: the approved workbook's lists are published as
**suggestions**, because every one of them ends in `Other` and a value outside the list is
something the sheet itself allows. Only the sets the sheet prints as fixed rows are closed —
Form 4's six error situations, and §9's six access choices.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from uboss.modules.agents.agent_models import (
    AgentAudience,
    AgentStatus,
    Direction,
    SharePrincipal,
    Situation,
)

#  Imported rather than retyped: two copies of one approved list is one copy that drifts.
from uboss.modules.jobs.schemas import (
    INPUT_TYPES,
    OUTPUT_FORMATS,
    PERMISSIONS,
    TIME_UNITS,
)
from uboss.modules.objectives.schemas import APPROVALS, FREQUENCIES, TRIGGERS, WORK_PLACES

#: Form 4 section A allows twelve numbered rows. Past forty, nobody reviews a design properly and
#: the honest answer is two agents — the same reasoning as the Job's step ceiling.
MAX_STEPS = 40
MAX_IO_SCHEMAS = 20
MAX_KNOWLEDGE_SOURCES = 20
MAX_TOOLS = 20
MAX_SKILLS = 20
MAX_SHARES = 100

#: Form 4's six situations, with the sheet's own words for each — so a screen labels them exactly
#: as the approved form does rather than paraphrasing.
SITUATION_LABELS: dict[str, str] = {
    Situation.MANDATORY_INPUT_MISSING: "Mandatory input missing",
    Situation.INFORMATION_UNCLEAR: "Information is unclear",
    Situation.INFORMATION_CONFLICTS: "Information conflicts",
    Situation.TOOL_OR_SYSTEM_FAILS: "Tool or system fails",
    Situation.APPROVAL_REJECTED: "Approval is rejected",
    Situation.PROHIBITED_ACTION_REQUESTED: "Prohibited action requested",
}


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ------------------------------------------------------------------------------ the parts


class AgentStepInput(_Payload):
    """One row of Form 4 section A. All nine columns, in the sheet's own order."""

    position: int = Field(ge=1, le=MAX_STEPS)
    job_step_id: uuid.UUID | None = None
    input_used: str | None = Field(default=None, max_length=4000)
    input_source: str | None = Field(default=None, max_length=4000)
    tool_system: str | None = Field(default=None, max_length=4000)
    agent_action: str | None = Field(default=None, max_length=4000)
    output: str | None = Field(default=None, max_length=4000)
    output_destination: str | None = Field(default=None, max_length=4000)
    approval: str | None = Field(default=None, max_length=120)
    #: The sheet's "Agent Must Never Do". §9 group 2's prohibited actions, per step.
    must_never_do: str | None = Field(default=None, max_length=4000)


class AgentStepRead(BaseModel):
    id: uuid.UUID
    position: int
    job_step_id: uuid.UUID | None
    input_used: str | None
    input_source: str | None
    tool_system: str | None
    agent_action: str | None
    output: str | None
    output_destination: str | None
    approval: str | None
    must_never_do: str | None


class EscalationRuleInput(_Payload):
    """Form 4 section B. The situation is one of six; the answer is the caller's own."""

    situation: Situation
    required_action: str = Field(min_length=1, max_length=2000)
    escalate_to_membership_id: uuid.UUID | None = None
    escalate_to_label: str | None = Field(default=None, max_length=200)


class EscalationRuleRead(BaseModel):
    id: uuid.UUID
    situation: Situation
    #: The sheet's wording, so a screen never has to invent a label for a printed row.
    label: str
    required_action: str
    escalate_to_membership_id: uuid.UUID | None
    escalate_to_label: str | None


class IoSchemaInput(_Payload):
    """One input or output shape. §9 group 4 says *"multiple"*, so these are a list."""

    position: int = Field(ge=1, le=MAX_IO_SCHEMAS)
    direction: Direction
    name: str = Field(min_length=1, max_length=200)
    format: str | None = Field(default=None, max_length=60)
    #: JSON Schema. An object or nothing — a bare string stored as "the schema" would validate
    #: here and fail everywhere it was used.
    json_schema: dict[str, Any] | None = None
    required: bool = True
    description: str | None = Field(default=None, max_length=2000)


class IoSchemaRead(BaseModel):
    id: uuid.UUID
    position: int
    direction: Direction
    name: str
    format: str | None
    json_schema: dict[str, Any] | None
    required: bool
    description: str | None


class KnowledgeSourceInput(_Payload):
    """§9 group 6: knowledge sources **and retention**, which is why the days sit here."""

    position: int = Field(ge=1, le=MAX_KNOWLEDGE_SOURCES)
    name: str = Field(min_length=1, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    #: Null means the tenant's own retention policy decides.
    retention_days: int | None = Field(default=None, ge=1, le=36500)
    contains_personal_data: bool = False


class KnowledgeSourceRead(BaseModel):
    id: uuid.UUID
    position: int
    name: str
    location: str | None
    description: str | None
    retention_days: int | None
    contains_personal_data: bool


class ToolInput(_Payload):
    """A tool and the explicit scopes it needs.

    There is no `granted` field here on purpose. §9: *"Tool suggestions never grant access."*
    Saving a form proposes a tool; granting it is a separate act by somebody with the authority,
    and letting a draft save set the flag would be exactly the shortcut the sentence forbids.
    """

    position: int = Field(ge=1, le=MAX_TOOLS)
    tool: str = Field(min_length=1, max_length=200)
    #: Non-empty. A tool with no scope is a tool with every scope.
    scopes: list[str] = Field(min_length=1, max_length=20)
    purpose: str | None = Field(default=None, max_length=2000)


class ToolRead(BaseModel):
    id: uuid.UUID
    position: int
    tool: str
    scopes: list[str]
    purpose: str | None
    #: False until somebody with the authority grants it. A screen shows this as a suggestion.
    granted: bool
    granted_by_membership_id: uuid.UUID | None
    granted_at: datetime | None


class ToolGrant(_Payload):
    """Granting or withdrawing one tool's access. A separate request, and a separate permission."""

    granted: bool
    expected_version: int


class SkillInput(_Payload):
    """A skill this Agent uses, and the resolver decision that chose it."""

    position: int = Field(ge=1, le=MAX_SKILLS)
    skill_id: uuid.UUID
    #: The 5.2 decision that produced this choice. Optional in the schema, offered first by the
    #: screen — this is what makes "why this skill" answerable from the record.
    resolver_decision_id: uuid.UUID | None = None
    notes: str | None = Field(default=None, max_length=2000)


class SkillRead(BaseModel):
    id: uuid.UUID
    position: int
    skill_id: uuid.UUID
    name: str
    catalogue_id: str | None
    autonomy: str
    #: What the skill is **not** for. Carried onto the card because it is what stops a plausible
    #: choice from being the wrong one, and no gate decides it — a person does.
    exclusions: str | None
    resolver_decision_id: uuid.UUID | None
    route: str | None
    notes: str | None


class ShareInput(_Payload):
    """One principal the Agent is shared with."""

    principal_type: SharePrincipal
    principal_id: uuid.UUID | None = None
    label: str | None = Field(default=None, max_length=200)


class ShareRead(BaseModel):
    id: uuid.UUID
    principal_type: SharePrincipal
    principal_id: uuid.UUID | None
    label: str | None


# ------------------------------------------------------------------------------ the agent


class AgentCreate(_Payload):
    """A name is enough to start.

    Naming a job carries its objective, department and published version across rather than asking
    for them again — Form 4 is *"generated from Forms 2 and 3"*, and retyping is how two records
    of one fact start to disagree.
    """

    name: str = Field(min_length=1, max_length=200)
    job_id: uuid.UUID | None = None
    objective_id: uuid.UUID | None = None


class AgentUpdate(_Payload):
    """Save the draft. Every collection is replaced wholesale when sent, left alone when not."""

    expected_version: int

    #  Group 1.
    name: str | None = Field(default=None, min_length=1, max_length=200)
    objective_id: uuid.UUID | None = None
    job_id: uuid.UUID | None = None
    #: The approved, immutable version this Agent runs. Not the draft.
    job_version_id: uuid.UUID | None = None
    trigger: str | None = Field(default=None, max_length=120)
    frequency: str | None = Field(default=None, max_length=60)
    completion_time_value: int | None = Field(default=None, ge=1)
    completion_time_unit: str | None = Field(default=None, max_length=20)

    #  Group 2.
    purpose: str | None = Field(default=None, max_length=8000)
    instructions: str | None = Field(default=None, max_length=20000)
    boundaries: str | None = Field(default=None, max_length=8000)
    prohibited_actions: str | None = Field(default=None, max_length=8000)

    #  Group 3.
    owner_membership_id: uuid.UUID | None = None
    visibility: AgentAudience | None = None
    shares: list[ShareInput] | None = Field(default=None, max_length=MAX_SHARES)

    #  Group 4.
    io_schemas: list[IoSchemaInput] | None = Field(default=None, max_length=MAX_IO_SCHEMAS)

    #  Group 5 — a policy key the gateway resolves, never a model name.
    model_policy_key: str | None = Field(default=None, max_length=60)

    #  Group 6.
    knowledge_sources: list[KnowledgeSourceInput] | None = Field(
        default=None, max_length=MAX_KNOWLEDGE_SOURCES
    )

    #  Group 7.
    tools: list[ToolInput] | None = Field(default=None, max_length=MAX_TOOLS)

    #  Group 8.
    main_approver_membership_id: uuid.UUID | None = None
    main_approver_label: str | None = Field(default=None, max_length=200)
    escalation_membership_id: uuid.UUID | None = None
    escalation_label: str | None = Field(default=None, max_length=200)
    escalation_rules: list[EscalationRuleInput] | None = Field(default=None, max_length=6)

    #  Group 9.
    cost_cap_minor_units: int | None = Field(default=None, ge=0)
    cost_cap_currency: str | None = Field(default=None, min_length=3, max_length=3)
    token_cap: int | None = Field(default=None, ge=1)
    time_limit_seconds: int | None = Field(default=None, ge=1)
    max_concurrency: int | None = Field(default=None, ge=1)
    max_retries: int | None = Field(default=None, ge=0)

    #  Form 4 section A, and the skills the design uses.
    steps: list[AgentStepInput] | None = Field(default=None, max_length=MAX_STEPS)
    skills: list[SkillInput] | None = Field(default=None, max_length=MAX_SKILLS)


class AgentRead(BaseModel):
    """One Agent in full — every group, so a form renders from one request."""

    id: uuid.UUID
    version: int
    status: AgentStatus
    #: Whether this draft still accepts edits. Sent rather than derived on the client, because a
    #: screen that worked out for itself which statuses are editable is a second copy of a rule
    #: the service already owns — and the copy on screen is the one people would trust.
    is_editable: bool
    name: str

    objective_id: uuid.UUID | None
    objective_name: str | None
    job_id: uuid.UUID | None
    job_name: str | None
    job_version_id: uuid.UUID | None
    #: The version number a person recognises, not the row id.
    job_version_no: int | None
    trigger: str | None
    frequency: str | None
    completion_time_value: int | None
    completion_time_unit: str | None

    purpose: str | None
    instructions: str | None
    boundaries: str | None
    prohibited_actions: str | None

    owner_membership_id: uuid.UUID | None
    owner_name: str | None
    visibility: AgentAudience
    shares: list[ShareRead]

    io_schemas: list[IoSchemaRead]
    model_policy_key: str | None
    knowledge_sources: list[KnowledgeSourceRead]
    tools: list[ToolRead]

    main_approver_membership_id: uuid.UUID | None
    main_approver_name: str | None
    main_approver_label: str | None
    escalation_membership_id: uuid.UUID | None
    escalation_name: str | None
    escalation_label: str | None
    escalation_rules: list[EscalationRuleRead]

    cost_cap_minor_units: int | None
    cost_cap_currency: str | None
    token_cap: int | None
    time_limit_seconds: int | None
    max_concurrency: int | None
    max_retries: int | None

    steps: list[AgentStepRead]
    skills: list[SkillRead]

    #: Which of Form 4's six situations still have no answer. Not a validation error while the
    #: form is a draft — a checklist, so the screen can show what is left rather than refusing a
    #: save. 5.4 turns this into a publish gate.
    situations_unanswered: list[Situation]

    created_at: datetime
    updated_at: datetime


class AgentCard(BaseModel):
    """One Agent as a list shows it."""

    id: uuid.UUID
    name: str
    status: AgentStatus
    owner_name: str | None
    job_name: str | None
    visibility: AgentAudience
    step_count: int
    skill_count: int
    updated_at: datetime


class AgentList(BaseModel):
    """`is_empty` separates "no agents yet" from "none match that filter" — different words."""

    agents: list[AgentCard]
    is_empty: bool


class AgentWorkbookLists(BaseModel):
    """Form 4's suggested values, served rather than kept in the frontend.

    A second copy of an approved list is a copy that drifts. These are suggestions, not validation
    — every one of them ends in `Other`. The two closed sets are separate: `situations` is what
    the sheet prints as fixed rows, and `visibility` is §9's six access choices.
    """

    triggers: list[str] = Field(default_factory=lambda: list(TRIGGERS))
    frequencies: list[str] = Field(default_factory=lambda: list(FREQUENCIES))
    time_units: list[str] = Field(default_factory=lambda: list(TIME_UNITS))
    approvals: list[str] = Field(default_factory=lambda: list(APPROVALS))
    input_types: list[str] = Field(default_factory=lambda: list(INPUT_TYPES))
    output_formats: list[str] = Field(default_factory=lambda: list(OUTPUT_FORMATS))
    #: The workbook's "Permission" list — the vocabulary a tool scope is chosen from.
    permissions: list[str] = Field(default_factory=lambda: list(PERMISSIONS))
    #: The workbook's "Where" list, for a knowledge source's location.
    locations: list[str] = Field(default_factory=lambda: list(WORK_PLACES))
    #: Closed. Form 4 prints all six.
    situations: list[dict[str, str]] = Field(
        default_factory=lambda: [
            {"value": value, "label": label} for value, label in SITUATION_LABELS.items()
        ]
    )
    #: Closed. §9's six access choices.
    visibility: list[str] = Field(default_factory=lambda: [v.value for v in AgentAudience])
