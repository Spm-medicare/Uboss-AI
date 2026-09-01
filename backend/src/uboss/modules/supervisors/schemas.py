"""What the Supervisor API accepts and returns.

**The two scopes are two fields, and they are edited by two different calls.** `supervised` is
part of the design and goes through `PUT /supervisors/{id}`; handlers do not, because changing who
may control a Supervisor is `manage_access` and changing what it watches is `edit_draft`. Putting
both in one payload would have made the stricter permission decide the looser one — the shape of
the contract is what keeps §10's independence real at the API as well as in the schema.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time

from pydantic import BaseModel, ConfigDict, Field

from uboss.modules.supervisors.models import (
    HandlerRole,
    OnFailure,
    SimulationStatus,
    SupervisorKind,
    SupervisorStatus,
)

#: Past these, nobody reviews the thing properly. The same reasoning as every other ceiling here.
MAX_SUPERVISED = 100
MAX_DEPENDENCIES = 200
MAX_QUALITY_GATES = 30
MAX_ESCALATIONS = 30
MAX_NOTIFICATIONS = 30
MAX_SIMULATIONS = 30


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ------------------------------------------------------------------ scope 1


class SupervisedInput(_Payload):
    """One row of scope 1 — whose Agents are watched."""

    position: int = Field(ge=1, le=MAX_SUPERVISED)
    membership_id: uuid.UUID
    #: Null means every Agent that person owns, now and later.
    agent_id: uuid.UUID | None = None
    #: Pinning a version means watching what was approved rather than whatever the draft became.
    agent_version_id: uuid.UUID | None = None


class SupervisedRead(BaseModel):
    id: uuid.UUID
    position: int
    membership_id: uuid.UUID
    person_name: str | None
    agent_id: uuid.UUID | None
    agent_name: str | None
    agent_version_id: uuid.UUID | None


# ------------------------------------------------------------------ scope 2


class HandlerInput(_Payload):
    """One row of scope 2. Sent to its own route — see the module docstring."""

    membership_id: uuid.UUID
    role: HandlerRole
    expected_version: int


class HandlerRead(BaseModel):
    id: uuid.UUID
    membership_id: uuid.UUID
    person_name: str | None
    role: HandlerRole
    granted_by_membership_id: uuid.UUID | None
    granted_at: datetime


# ------------------------------------------------------------------ groups 5 to 9


class DependencyInput(_Payload):
    """Both sides are positions in the supervised list, so a dependency can only link two things
    this Supervisor watches."""

    supervised_position: int = Field(ge=1, le=MAX_SUPERVISED)
    depends_on_position: int = Field(ge=1, le=MAX_SUPERVISED)


class DependencyRead(BaseModel):
    id: uuid.UUID
    supervised_id: uuid.UUID
    depends_on_id: uuid.UUID


class QualityGateInput(_Payload):
    position: int = Field(ge=1, le=MAX_QUALITY_GATES)
    name: str = Field(min_length=1, max_length=200)
    condition: str = Field(min_length=1, max_length=4000)
    evidence: str | None = Field(default=None, max_length=4000)
    on_failure: OnFailure = OnFailure.ESCALATE


class QualityGateRead(BaseModel):
    id: uuid.UUID
    position: int
    name: str
    condition: str
    evidence: str | None
    on_failure: OnFailure


class EscalationInput(_Payload):
    position: int = Field(ge=1, le=MAX_ESCALATIONS)
    situation: str = Field(min_length=1, max_length=200)
    required_action: str = Field(min_length=1, max_length=4000)
    escalate_to_membership_id: uuid.UUID | None = None
    escalate_to_label: str | None = Field(default=None, max_length=200)
    #: Null means immediately.
    after_minutes: int | None = Field(default=None, ge=0)


class EscalationRead(BaseModel):
    id: uuid.UUID
    position: int
    situation: str
    required_action: str
    escalate_to_membership_id: uuid.UUID | None
    escalate_to_name: str | None
    escalate_to_label: str | None
    after_minutes: int | None


class NotificationInput(_Payload):
    position: int = Field(ge=1, le=MAX_NOTIFICATIONS)
    event: str = Field(min_length=1, max_length=200)
    channel: str | None = Field(default=None, max_length=60)
    to_handlers: bool = True
    recipient_membership_id: uuid.UUID | None = None
    recipient_label: str | None = Field(default=None, max_length=200)


class NotificationRead(BaseModel):
    id: uuid.UUID
    position: int
    event: str
    channel: str | None
    to_handlers: bool
    recipient_membership_id: uuid.UUID | None
    recipient_name: str | None
    recipient_label: str | None


class SupervisorScheduleWrite(_Payload):
    """The Job's schedule fields, because the Job's pure module reads them.

    Prefixed `Supervisor…` because FastAPI names an OpenAPI component after the class, and the
    Job already has a `ScheduleWrite`. Two classes sharing a name make the generator fully qualify
    **both**, which breaks whichever frontend alias pointed at the other one —
    `test_the_contract_has_no_fully_qualified_schema_names` caught exactly this.
    """

    expected_version: int
    auto_run: bool = False
    timezone: str = Field(min_length=1, max_length=64)
    frequency: str = Field(max_length=20)
    interval: int = Field(default=1, ge=1)
    at_time: time
    weekdays: list[int] = Field(default_factory=list, max_length=7)
    monthday: int | None = Field(default=None, ge=1, le=31)
    dst_policy: str = "shift"
    ambiguous_policy: str = "first"
    skip_dates: list[str] = Field(default_factory=list, max_length=200)
    weekdays_only: bool = False
    missed_run_policy: str = "skip"
    overlap_policy: str = "queue"


class SupervisorScheduleRead(BaseModel):
    id: uuid.UUID
    auto_run: bool
    timezone: str
    frequency: str
    interval: int
    at_time: time
    weekdays: list[int]
    monthday: int | None
    dst_policy: str
    ambiguous_policy: str
    skip_dates: list[str]
    weekdays_only: bool
    missed_run_policy: str
    overlap_policy: str
    version: int


# ------------------------------------------------------------------ the supervisor


class SupervisorCreate(_Payload):
    """A name and a kind. A department Supervisor names its department; a personal one cannot."""

    name: str = Field(min_length=1, max_length=200)
    kind: SupervisorKind = SupervisorKind.PERSONAL
    org_node_id: uuid.UUID | None = None
    objective_id: uuid.UUID | None = None


class SupervisorUpdate(_Payload):
    """Save the draft. Every collection is replaced wholesale when sent, left alone when not.

    There is no `handlers` field, deliberately — see the module docstring.
    """

    expected_version: int

    name: str | None = Field(default=None, min_length=1, max_length=200)
    objective_id: uuid.UUID | None = None
    purpose: str | None = Field(default=None, max_length=8000)

    #  Group 4 and 5.
    trigger: str | None = Field(default=None, max_length=120)
    routing_policy: str | None = Field(default=None, max_length=4000)
    max_concurrency: int | None = Field(default=None, ge=1)

    #  Group 7.
    cost_cap_minor_units: int | None = Field(default=None, ge=0)
    cost_cap_currency: str | None = Field(default=None, min_length=3, max_length=3)
    token_cap: int | None = Field(default=None, ge=1)
    sla_minutes: int | None = Field(default=None, ge=1)
    deadline_minutes: int | None = Field(default=None, ge=1)
    max_retries: int | None = Field(default=None, ge=0)
    retry_backoff_seconds: int | None = Field(default=None, ge=0)

    #  Group 8.
    approver_membership_id: uuid.UUID | None = None
    approver_label: str | None = Field(default=None, max_length=200)
    escalation_membership_id: uuid.UUID | None = None
    escalation_label: str | None = Field(default=None, max_length=200)

    supervised: list[SupervisedInput] | None = Field(default=None, max_length=MAX_SUPERVISED)
    dependencies: list[DependencyInput] | None = Field(
        default=None, max_length=MAX_DEPENDENCIES
    )
    quality_gates: list[QualityGateInput] | None = Field(
        default=None, max_length=MAX_QUALITY_GATES
    )
    escalations: list[EscalationInput] | None = Field(default=None, max_length=MAX_ESCALATIONS)
    notifications: list[NotificationInput] | None = Field(
        default=None, max_length=MAX_NOTIFICATIONS
    )


class SupervisorRead(BaseModel):
    """One Supervisor in full, so a form renders from one request."""

    id: uuid.UUID
    version: int
    status: SupervisorStatus
    #: Whether this draft still accepts edits. Sent rather than derived on the client — a screen
    #: working out for itself which statuses are editable is a second copy of a service rule.
    is_editable: bool
    name: str
    kind: SupervisorKind

    owner_membership_id: uuid.UUID
    owner_name: str | None
    org_node_id: uuid.UUID | None
    org_node_name: str | None
    objective_id: uuid.UUID | None
    objective_name: str | None
    purpose: str | None

    trigger: str | None
    routing_policy: str | None
    max_concurrency: int | None

    cost_cap_minor_units: int | None
    cost_cap_currency: str | None
    token_cap: int | None
    sla_minutes: int | None
    deadline_minutes: int | None
    max_retries: int | None
    retry_backoff_seconds: int | None

    approver_membership_id: uuid.UUID | None
    approver_name: str | None
    approver_label: str | None
    escalation_membership_id: uuid.UUID | None
    escalation_name: str | None
    escalation_label: str | None

    supervised: list[SupervisedRead]
    handlers: list[HandlerRead]
    dependencies: list[DependencyRead]
    quality_gates: list[QualityGateRead]
    escalations: list[EscalationRead]
    notifications: list[NotificationRead]
    schedule: SupervisorScheduleRead | None

    #: What the caller may do on *this* Supervisor, after both boundaries. The screen disables
    #: what it must rather than working the answer out itself.
    my_role: HandlerRole | None
    my_actions: list[str]

    created_at: datetime
    updated_at: datetime


class SupervisorCard(BaseModel):
    id: uuid.UUID
    name: str
    kind: SupervisorKind
    status: SupervisorStatus
    owner_name: str | None
    #: The department a department Supervisor watches, and null for a personal one. §10 makes the
    #: department part of a Supervisor's identity, and two department Supervisors are otherwise
    #: told apart only by whatever their names happen to say.
    department_name: str | None = None
    supervised_count: int
    handler_count: int
    updated_at: datetime


class SupervisorList(BaseModel):
    """`is_empty` separates "none yet" from "none match that filter" — different words."""

    supervisors: list[SupervisorCard]
    is_empty: bool


class SupervisorLists(BaseModel):
    """The closed vocabularies a screen needs, served rather than copied into the frontend."""

    kinds: list[str] = Field(default_factory=lambda: [k.value for k in SupervisorKind])
    handler_roles: list[str] = Field(default_factory=lambda: [r.value for r in HandlerRole])
    on_failure: list[str] = Field(default_factory=lambda: [o.value for o in OnFailure])
    simulation_statuses: list[str] = Field(
        default_factory=lambda: [s.value for s in SimulationStatus]
    )
