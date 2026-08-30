"""What the publish screen shows and what approving sends.

PLAN §7: *"Publish shows owners, steps, schedules, permissions, cost, warnings and approval
route."* Everything below is computed on read, so a summary can never describe a version of the
objective that no longer exists.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field

from uboss.modules.objectives.models import ObjectiveStatus


class PublishAction(BaseModel):
    """The version the person was looking at when they decided.

    On approval this is not decoration: it is the difference between approving what you read and
    approving whatever it has become since.
    """

    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)


class WarningRead(BaseModel):
    """Something the approver should see. Never a blocker."""

    code: str
    message: str


class PublishSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    objective_id: uuid.UUID
    title: str
    status: ObjectiveStatus
    owner_name: str | None
    approver_name: str | None
    submitted_by_name: str | None
    department: str | None
    expected_result: str | None

    step_count: int
    human_steps: int
    agent_steps: int
    hybrid_steps: int
    approval_steps: int
    output_steps: int

    ai_proposed: int
    ai_edited: int
    human_added: int

    #: What the last successful analysis actually cost. Null when none has run — never an
    #: estimate, which is a number somebody would quote.
    analysis_model: str | None
    analysis_tokens: int

    warnings: list[WarningRead] = Field(default_factory=list)
    #: Whose turn it is, in a sentence. Written by the server so two screens cannot each conclude
    #: it is the other person's turn.
    next_action: str
    can_submit: bool
    can_approve: bool
    version: int


class VersionRead(BaseModel):
    """A published version — immutable, and evidence."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version_no: int
    title: str
    published_at: str
    approved_by_name: str | None = None
    published_by_name: str | None = None
    step_count: int = 0
