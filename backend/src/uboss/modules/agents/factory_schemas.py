"""What the Skill Factory's routes accept and return.

The read shapes carry the skill's own fields plus the two things a screen cannot work out for
itself: what is still missing, and whether *this* caller may send or approve it. Both are answered
by the backend — a frontend deciding a second way is how a button comes to offer something the
server refuses.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from uboss.modules.agents.models import Autonomy, SkillStatus, SkillTestKind

if TYPE_CHECKING:
    #  Under `TYPE_CHECKING` only: `factory` imports these shapes to build them, so a runtime
    #  import here would be a cycle. The annotation is all that is needed.
    from uboss.modules.agents.factory import DraftSummary


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SkillResultStatus(enum.StrEnum):
    """What a person can record. `not_run` is absent on purpose: it is the state a test starts in
    and returns to when the design changes, never something anybody *records*."""

    PASS = "pass"  # noqa: S105 - the workbook's word, not a credential
    FAIL = "fail"
    BLOCKED = "blocked"


class DraftCreate(_Payload):
    """A name is enough to begin. The rest is what the submit gate asks for."""

    name: str = Field(min_length=1, max_length=300)
    purpose: str | None = Field(default=None, max_length=8000)
    department: str | None = Field(default=None, max_length=200)
    industry: str | None = Field(default=None, max_length=200)
    archetype_id: str | None = Field(default=None, max_length=8)


class RuleInput(_Payload):
    """One IF-THEN decision.

    `failure_state` is the field that makes a rule governance rather than logic: it is what the
    product says when the rule refuses, in the author's own words.
    """

    condition_type: str = Field(default="primary decision", max_length=60)
    if_clause: str = Field(min_length=1, max_length=4000)
    then_clause: str = Field(min_length=1, max_length=4000)
    priority: str = Field(default="High", max_length=20)
    evidence_required: str | None = Field(default=None, max_length=2000)
    failure_state: str | None = Field(default=None, max_length=120)
    human_gate: str | None = Field(default=None, max_length=30)
    source_ids: str | None = Field(default=None, max_length=2000)


class DraftUpdate(_Payload):
    """Save the draft. Every field is optional; `rules` replaces the set when sent.

    `exclude_unset` at the call site means a field left out is left alone, and a field sent as null
    is cleared. A form that has not loaded a section yet therefore cannot blank it.
    """

    expected_version: int

    name: str | None = Field(default=None, min_length=1, max_length=300)
    department: str | None = Field(default=None, max_length=200)
    industry: str | None = Field(default=None, max_length=200)
    archetype_id: str | None = Field(default=None, max_length=8)
    purpose: str | None = Field(default=None, max_length=8000)
    positive_trigger: str | None = Field(default=None, max_length=4000)
    exclusions: str | None = Field(default=None, max_length=4000)
    minimum_inputs: str | None = Field(default=None, max_length=4000)
    primary_if: str | None = Field(default=None, max_length=4000)
    primary_then: str | None = Field(default=None, max_length=4000)
    output: str | None = Field(default=None, max_length=4000)
    validation_gate: str | None = Field(default=None, max_length=4000)
    autonomy: Autonomy | None = None
    source_ids: str | None = Field(default=None, max_length=2000)

    rules: list[RuleInput] | None = Field(default=None, max_length=60)


class SkillTestWrite(_Payload):
    """The situation and what should happen. Writing a test clears its previous result."""

    sample_situation: str | None = Field(default=None, max_length=4000)
    expected_result: str | None = Field(default=None, max_length=4000)


class SkillTestResultWrite(_Payload):
    """What happened. An observation is required — a pass nobody can check is not evidence."""

    status: SkillResultStatus
    observed: str = Field(min_length=1, max_length=4000)


class RuleRead(BaseModel):
    id: uuid.UUID
    position: int
    condition_type: str
    if_clause: str
    then_clause: str
    priority: str
    evidence_required: str | None
    failure_state: str | None
    human_gate: str | None
    source_ids: str | None


class SkillTestRead(BaseModel):
    kind: SkillTestKind
    status: str
    sample_situation: str | None
    expected_result: str | None
    actual_result: str | None
    run_at: datetime | None
    run_by_name: str | None


class DraftRead(BaseModel):
    """One private skill, as the panel reads it."""

    id: uuid.UUID
    name: str
    status: SkillStatus
    version: int
    layer: str
    department: str | None
    industry: str | None
    archetype_id: str | None
    purpose: str | None
    positive_trigger: str | None
    exclusions: str | None
    minimum_inputs: str | None
    primary_if: str | None
    primary_then: str | None
    output: str | None
    validation_gate: str | None
    autonomy: str
    source_ids: str | None

    owner_name: str | None
    approver_name: str | None
    approver_membership_id: uuid.UUID | None
    submitted_by_name: str | None
    approved_by_name: str | None
    approved_at: datetime | None
    published_version_no: int | None

    rules: list[RuleRead]
    tests: list[SkillTestRead]

    #: True only while the design may change — draft, and not the catalogue.
    is_editable: bool
    created_at: datetime
    updated_at: datetime


class DraftCard(BaseModel):
    id: uuid.UUID
    name: str
    status: SkillStatus
    owner_name: str | None
    rule_count: int
    tests_passed: int
    updated_at: datetime


class DraftListRead(BaseModel):
    """`is_empty` separates "none yet" from "none in this state" — different words on screen."""

    drafts: list[DraftCard]
    is_empty: bool


class GapRead(BaseModel):
    field: str
    remedy: str


class DraftSummaryRead(BaseModel):
    """What the draft is waiting for, and who it is waiting on."""

    skill_id: uuid.UUID
    name: str
    status: SkillStatus
    version: int
    owner_name: str | None
    approver_name: str | None
    submitted_by_name: str | None
    rule_count: int
    tests_passed: int
    tests_total: int
    published_version_no: int | None
    gaps: list[GapRead]
    next_action: str
    can_submit: bool
    can_approve: bool

    @classmethod
    def of(cls, summary: DraftSummary) -> DraftSummaryRead:
        return cls(
            skill_id=summary.skill_id,
            name=summary.name,
            status=SkillStatus(summary.status),
            version=summary.version,
            owner_name=summary.owner_name,
            approver_name=summary.approver_name,
            submitted_by_name=summary.submitted_by_name,
            rule_count=summary.rule_count,
            tests_passed=summary.tests_passed,
            tests_total=summary.tests_total,
            published_version_no=summary.published_version_no,
            gaps=[GapRead(field=gap.field, remedy=gap.remedy) for gap in summary.gaps],
            next_action=summary.next_action,
            can_submit=summary.can_submit,
            can_approve=summary.can_approve,
        )


class SkillVersionRead(BaseModel):
    """The frozen version an approval produced.

    Named `SkillVersionRead` and not `VersionRead`: the Objective's publish schemas already have a
    `VersionRead`, and two classes sharing a name make the generator fully qualify **both** — so
    the collision renames the existing one and whichever frontend alias pointed at it stops
    compiling. `test_the_contract_has_no_fully_qualified_schema_names` catches it; this happened
    while writing the Factory, and the fix is the one that test recommends — rename the newer.

    Immutable: there is no route that edits one.
    """

    id: uuid.UUID
    skill_id: uuid.UUID
    version_no: int
    name: str
    published_at: datetime
