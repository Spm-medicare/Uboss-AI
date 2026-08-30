"""What the Job API accepts and returns.

The workbook's lists are published here as suggestions, the same as the Objective's: every one of
them ends in `Other`, so a value outside the list is something the approved sheet allows. Only the
lists that are genuinely closed — the WHO types, the AI-access levels — are enums.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from uboss.modules.jobs.models import (
    AiAccess,
    InputRequirement,
    JobStatus,
    StepMode,
    WhoType,
)
from uboss.modules.objectives.models import Visibility

#  From the workbook's "Dropdown Lists" sheet. The four Form 2 shares are imported rather than
#  retyped: two copies of one approved list is one copy that drifts.
from uboss.modules.objectives.schemas import (
    APPROVALS,
    DEPARTMENTS,
    FREQUENCIES,
    TRIGGERS,
    WORK_PLACES,
)

#: The workbook's "Time Unit" list.
TIME_UNITS: tuple[str, ...] = ("Minutes", "Hours", "Days")

#: "Input Type".
INPUT_TYPES: tuple[str, ...] = (
    "Text / Form",
    "Email",
    "Excel",
    "Word",
    "PDF",
    "Image",
    "System Data",
    "Physical Record",
    "Approval",
    "Policy / SOP",
    "API Data",
    "Other",
)

#: "Method" — the verbs a step's HOW column uses. This is the list that makes Form 3 different
#: from Form 2: it describes the action, not the outcome.
METHODS: tuple[str, ...] = (
    "Open",
    "Read",
    "Search",
    "Download",
    "Upload",
    "Copy",
    "Enter",
    "Extract",
    "Check",
    "Compare",
    "Calculate",
    "Classify",
    "Draft",
    "Create",
    "Update",
    "Send",
    "Notify",
    "Monitor",
    "Physically Inspect",
    "Ask Someone",
    "Approve",
    "Other",
)

#: "Approval Timing" — when in the step the sign-off happens.
APPROVAL_TIMINGS: tuple[str, ...] = (
    "No approval",
    "Before this step",
    "After this step",
    "Only for exceptions",
    "Always",
)

#: "Missing Action" — the step's `if_missing_or_wrong`.
MISSING_ACTIONS: tuple[str, ...] = (
    "Ask the user",
    "Send for human review",
    "Stop and report",
    "Continue with flagged draft",
    "Use approved fallback",
    "Other",
)

#: "Failure Action" — the job's own policy when the whole thing fails.
FAILURE_ACTIONS: tuple[str, ...] = (
    "Retry",
    "Use approved manual method",
    "Escalate",
    "Stop and report",
    "Other",
)

#: "Output Format".
OUTPUT_FORMATS: tuple[str, ...] = (
    "Text",
    "Table",
    "Excel",
    "Word",
    "PDF",
    "Email",
    "System Record",
    "Status",
    "Alert",
    "Dashboard",
    "Physical Output",
    "Other",
)


class JobWorkbookLists(BaseModel):
    """The suggested values, served so the frontend keeps no second copy to drift."""

    departments: list[str] = Field(default_factory=lambda: list(DEPARTMENTS))
    triggers: list[str] = Field(default_factory=lambda: list(TRIGGERS))
    frequencies: list[str] = Field(default_factory=lambda: list(FREQUENCIES))
    work_places: list[str] = Field(default_factory=lambda: list(WORK_PLACES))
    approvals: list[str] = Field(default_factory=lambda: list(APPROVALS))
    time_units: list[str] = Field(default_factory=lambda: list(TIME_UNITS))
    input_types: list[str] = Field(default_factory=lambda: list(INPUT_TYPES))
    methods: list[str] = Field(default_factory=lambda: list(METHODS))
    approval_timings: list[str] = Field(default_factory=lambda: list(APPROVAL_TIMINGS))
    missing_actions: list[str] = Field(default_factory=lambda: list(MISSING_ACTIONS))
    failure_actions: list[str] = Field(default_factory=lambda: list(FAILURE_ACTIONS))
    output_formats: list[str] = Field(default_factory=lambda: list(OUTPUT_FORMATS))


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class JobStepInput(BaseModel):
    """One row of Form 3's step table — all sixteen columns.

    Every field is optional. Somebody describes their own method a piece at a time, and refusing
    a half-written row would mean refusing to autosave, which is how work gets lost.
    """

    model_config = ConfigDict(extra="forbid")

    who_person: str | None = Field(default=None, max_length=200)
    who_role: str | None = Field(default=None, max_length=200)
    when_trigger: str | None = Field(default=None, max_length=200)
    when_frequency: str | None = Field(default=None, max_length=200)
    what_exact_work: str | None = None
    input_exact: str | None = None
    input_found_where: str | None = Field(default=None, max_length=200)
    how_exact_method: str | None = None
    where_performed: str | None = Field(default=None, max_length=200)
    rule_formula_check: str | None = None
    output: str | None = None
    output_destination: str | None = Field(default=None, max_length=200)
    approval: str | None = Field(default=None, max_length=200)
    if_missing_or_wrong: str | None = Field(default=None, max_length=300)
    time_taken: str | None = Field(default=None, max_length=100)
    mode: StepMode = StepMode.HUMAN


class AssignmentRuleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    who_type: WhoType
    target_id: uuid.UUID | None = None
    target_label: str | None = Field(default=None, max_length=300)
    condition_note: str | None = None
    all_must_act: bool = False


class JobInputDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    input_type: str = Field(min_length=1, max_length=60)
    source: str | None = Field(default=None, max_length=300)
    requirement: InputRequirement = InputRequirement.OPTIONAL
    condition_note: str | None = None
    validation_note: str | None = None
    classification: str = Field(default="internal", max_length=40)
    retention_note: str | None = Field(default=None, max_length=300)
    #: Defaults to `none`. The safe answer should be the one somebody chooses, not the one that
    #: happens when they do not.
    ai_access: AiAccess = AiAccess.NONE


class JobCreate(_Payload):
    """Only a name is needed to start, as with an Objective."""

    name: str = Field(min_length=1, max_length=300)
    objective_id: uuid.UUID | None = None
    department: str | None = Field(default=None, max_length=200)


class JobUpdate(_Payload):
    """A draft save — autosave and Save Draft alike."""

    name: str | None = Field(default=None, min_length=1, max_length=300)
    objective_id: uuid.UUID | None = None
    objective_step_id: uuid.UUID | None = None
    department: str | None = Field(default=None, max_length=200)
    external_ref: str | None = Field(default=None, max_length=120)
    owner_membership_id: uuid.UUID | None = None
    current_person: str | None = Field(default=None, max_length=200)
    current_role: str | None = Field(default=None, max_length=200)
    trigger: str | None = Field(default=None, max_length=200)
    frequency: str | None = Field(default=None, max_length=200)
    high_level_work: str | None = None
    start_requirement: str | None = None
    completion_evidence: str | None = None
    normal_completion_time: str | None = Field(default=None, max_length=60)
    time_unit: str | None = Field(default=None, max_length=40)

    purpose: str | None = None
    expected_output: str | None = None
    quality_checks: str | None = None
    sla_note: str | None = Field(default=None, max_length=300)
    retry_policy: str | None = None
    failure_action: str | None = Field(default=None, max_length=200)
    escalation_to: str | None = Field(default=None, max_length=200)
    visibility: Visibility | None = None
    approver_membership_id: uuid.UUID | None = None

    #: Each collection is replaced wholesale when sent. They are edited as lists — rows are
    #: reordered and removed — and a diff computed on the client would be a second implementation
    #: of what the server already does.
    steps: list[JobStepInput] | None = None
    assignment_rules: list[AssignmentRuleInput] | None = None
    inputs: list[JobInputDefinition] | None = None

    expected_version: int = Field(ge=1)


# ---------------------------------------------------------------------------- reading


class JobStepRead(JobStepInput):
    id: uuid.UUID
    position: int
    depends_on: list[uuid.UUID] = Field(default_factory=list)


class AssignmentRuleRead(AssignmentRuleInput):
    id: uuid.UUID
    position: int


class JobInputRead(JobInputDefinition):
    id: uuid.UUID
    position: int


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: JobStatus
    name: str
    objective_id: uuid.UUID | None
    objective_name: str | None = None
    objective_step_id: uuid.UUID | None
    department: str | None
    external_ref: str | None
    owner_membership_id: uuid.UUID | None
    owner_name: str | None = None
    current_person: str | None
    current_role: str | None
    trigger: str | None
    frequency: str | None
    high_level_work: str | None
    start_requirement: str | None
    completion_evidence: str | None
    normal_completion_time: str | None
    time_unit: str | None

    purpose: str | None
    expected_output: str | None
    quality_checks: str | None
    sla_note: str | None
    retry_policy: str | None
    failure_action: str | None
    escalation_to: str | None
    visibility: Visibility
    approver_membership_id: uuid.UUID | None
    approver_name: str | None = None

    steps: list[JobStepRead] = Field(default_factory=list)
    assignment_rules: list[AssignmentRuleRead] = Field(default_factory=list)
    inputs: list[JobInputRead] = Field(default_factory=list)

    published_version_id: uuid.UUID | None
    archived_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime
    is_editable: bool


class JobCard(BaseModel):
    """A row in the list."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    status: JobStatus
    department: str | None
    owner_name: str | None = None
    objective_name: str | None = None
    trigger: str | None
    frequency: str | None
    step_count: int = 0
    updated_at: datetime


class JobList(BaseModel):
    jobs: list[JobCard]
    is_empty: bool
