"""What the Objective API accepts and returns.

The workbook's suggested lists are published here as part of the contract. They are *suggestions*,
not validation: every one of them ends in `Other`, so a value outside the list is something the
approved workbook explicitly allows. Sending them to the client means the picker offers what a
team is used to seeing without the server refusing what it is not.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from uboss.modules.objectives.models import (
    AiAssistance,
    ObjectiveStatus,
    Priority,
    Visibility,
)

#  The workbook's "Dropdown Lists" sheet, read from
#  `UBOSS_Complete_Builder_Forms_Organogram (1).xlsx` rather than retyped from memory. Each list
#  ends in "Other" exactly as the sheet does.

DEPARTMENTS: tuple[str, ...] = (
    "Management",
    "Sales",
    "Marketing",
    "Purchase",
    "Production",
    "Quality",
    "Regulatory",
    "Finance",
    "HR",
    "IT",
    "Logistics",
    "Customer Service",
    "Other",
)

WORKLOAD_UNITS: tuple[str, ...] = (
    "Day",
    "Week",
    "Month",
    "Quarter",
    "Year",
    "Transaction",
)

TRIGGERS: tuple[str, ...] = (
    "New request",
    "New email",
    "New record",
    "Scheduled date",
    "Previous step completed",
    "Approval received",
    "System notification",
    "Customer request",
    "Management instruction",
    "Event-based",
    "Other",
)

FREQUENCIES: tuple[str, ...] = (
    "Every transaction",
    "On demand",
    "Hourly",
    "Daily",
    "Weekly",
    "Monthly",
    "Quarterly",
    "Yearly",
    "Event-based",
    "Other",
)

WORK_PLACES: tuple[str, ...] = (
    "Excel",
    "Word",
    "Email",
    "ERP",
    "CRM",
    "HRMS / ATS",
    "Monday.com",
    "Google Drive",
    "SharePoint",
    "Website / Portal",
    "Internal Software",
    "Physical Location",
    "Meeting / Telephone",
    "Other",
)

PROBLEMS: tuple[str, ...] = (
    "No problem",
    "Repetitive work",
    "Manual data entry",
    "Duplicate entry",
    "Missing information",
    "Errors",
    "Delay",
    "Approval delay",
    "Inconsistent method",
    "Manual calculation",
    "System limitation",
    "Compliance risk",
    "Other",
)

APPROVALS: tuple[str, ...] = (
    "No approval",
    "Team Lead",
    "Department Head",
    "Quality",
    "Regulatory",
    "Finance",
    "HR",
    "Management",
    "Other",
)


class WorkbookLists(BaseModel):
    """The suggested values, served so the interface does not keep its own copy.

    A second copy in the frontend is a copy that drifts, and the workbook is the approved source.
    """

    departments: list[str] = Field(default_factory=lambda: list(DEPARTMENTS))
    workload_units: list[str] = Field(default_factory=lambda: list(WORKLOAD_UNITS))
    triggers: list[str] = Field(default_factory=lambda: list(TRIGGERS))
    frequencies: list[str] = Field(default_factory=lambda: list(FREQUENCIES))
    work_places: list[str] = Field(default_factory=lambda: list(WORK_PLACES))
    problems: list[str] = Field(default_factory=lambda: list(PROBLEMS))
    approvals: list[str] = Field(default_factory=lambda: list(APPROVALS))


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CurrentStepInput(BaseModel):
    """One row of the workbook's step table.

    Every field is optional. A person fills this in while describing their own process, and a
    half-written row is a normal intermediate state — refusing it would mean refusing to autosave,
    which is how work gets lost.
    """

    model_config = ConfigDict(extra="forbid")

    who_person: str | None = Field(default=None, max_length=200)
    who_role: str | None = Field(default=None, max_length=200)
    when_trigger: str | None = Field(default=None, max_length=200)
    when_frequency: str | None = Field(default=None, max_length=200)
    what_exact_work: str | None = None
    input_used: str | None = None
    input_received_from: str | None = Field(default=None, max_length=200)
    where_done: str | None = Field(default=None, max_length=200)
    output_produced: str | None = None
    output_sent_to: str | None = Field(default=None, max_length=200)
    time_taken: str | None = Field(default=None, max_length=100)
    current_problem: str | None = Field(default=None, max_length=200)
    approval: str | None = Field(default=None, max_length=200)


class ObjectiveCreate(_Payload):
    """Only the title is required to start.

    PLAN §6's journey begins at "Create/Open Draft", and a form that demanded eight groups before
    it would save anything is a form people fill in somewhere else first.
    """

    title: str = Field(min_length=1, max_length=300)
    department: str | None = Field(default=None, max_length=200)


class ObjectiveUpdate(_Payload):
    """A draft save. Everything optional; what is absent is left alone.

    This is the autosave payload as well as the explicit Save Draft one — PLAN §6 asks for both,
    and they write the same thing. What differs is only how often, and what the screen says.
    """

    title: str | None = Field(default=None, min_length=1, max_length=300)
    department: str | None = Field(default=None, max_length=200)
    owner_membership_id: uuid.UUID | None = None
    expected_result: str | None = None
    workload_count: str | None = Field(default=None, max_length=60)
    workload_unit: str | None = Field(default=None, max_length=40)
    target_date: date | None = None

    description: str | None = None
    priority: Priority | None = None
    baseline: str | None = None
    success_measures: str | None = None
    included_work: str | None = None
    excluded_work: str | None = None
    stakeholders: str | None = None
    geography: str | None = Field(default=None, max_length=200)
    start_date: date | None = None
    urgency: str | None = Field(default=None, max_length=200)
    budget_note: str | None = None
    policy_constraints: str | None = None
    dependencies: str | None = None
    risk_note: str | None = None

    approver_membership_id: uuid.UUID | None = None
    visibility: Visibility | None = None
    handles_sensitive_data: bool | None = None
    sensitive_data_note: str | None = None
    ai_assistance: AiAssistance | None = None
    human_checkpoints: str | None = None

    #: The whole step table, replaced. Sent as a list rather than per-row operations because the
    #: table is edited as a grid: rows are reordered and removed, and a diff computed on the
    #: client would be a second implementation of what the server already does.
    current_steps: list[CurrentStepInput] | None = None

    expected_version: int = Field(ge=1)


class CurrentStepRead(CurrentStepInput):
    id: uuid.UUID
    position: int


class PersonRef(BaseModel):
    """Somebody in this workspace, as a form needs to show them."""

    membership_id: uuid.UUID
    display_name: str
    job_title: str | None = None


class ObjectiveRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: ObjectiveStatus
    title: str
    department: str | None
    owner_membership_id: uuid.UUID | None
    owner_name: str | None = None
    expected_result: str | None
    workload_count: str | None
    workload_unit: str | None
    target_date: date | None

    description: str | None
    priority: Priority
    baseline: str | None
    success_measures: str | None
    included_work: str | None
    excluded_work: str | None
    stakeholders: str | None
    geography: str | None
    start_date: date | None
    urgency: str | None
    budget_note: str | None
    policy_constraints: str | None
    dependencies: str | None
    risk_note: str | None

    approver_membership_id: uuid.UUID | None
    approver_name: str | None = None
    visibility: Visibility
    handles_sensitive_data: bool
    sensitive_data_note: str | None
    ai_assistance: AiAssistance
    human_checkpoints: str | None

    current_steps: list[CurrentStepRead] = Field(default_factory=list)

    published_version_id: uuid.UUID | None
    archived_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime
    #: False once published or while analysing. The interface disables the form rather than
    #: letting somebody type into something that will not save.
    is_editable: bool


class ObjectiveCard(BaseModel):
    """A row in the list — PLAN §7's "Objective cards"."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    status: ObjectiveStatus
    department: str | None
    priority: Priority
    owner_name: str | None = None
    target_date: date | None
    #: How many rows of the current process have been described. A real count, never a
    #: percentage: a completion figure would be inventing a definition of "complete".
    step_count: int = 0
    updated_at: datetime


class ObjectiveList(BaseModel):
    objectives: list[ObjectiveCard]
    #: True when this workspace has no objectives at all, as opposed to none matching a filter.
    #: Two states that look identical on screen and need different words.
    is_empty: bool
