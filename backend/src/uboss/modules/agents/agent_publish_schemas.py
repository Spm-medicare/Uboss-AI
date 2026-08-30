"""What the Agent publish screen accepts and returns.

Every class here is prefixed `Agent…` or `Sandbox…` rather than named for what it is. FastAPI names
an OpenAPI component after the class, so two modules with a `PublishSummary` make the generator
fall back to fully-qualified module paths **on both of them** — which breaks whichever frontend
alias already pointed at the other one. `test_the_contract_has_no_fully_qualified_schema_names`
catches it now; this naming is what keeps it caught.

Every number here is counted from rows and every sentence comes from a gate or a warning that
actually ran. There is no readiness percentage and no confidence score — the screen shows what is
true, and *"2 of 5 tests pass"* is more use than *"40% ready"* to the person who has to fix it.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from uboss.modules.agents.agent_models import SandboxTestKind, SandboxTestStatus

#: Form 4 section C's five tests, with the sheet's own words — so a screen labels them exactly as
#: the approved form does rather than prettifying an enum.
TEST_LABELS: dict[str, str] = {
    SandboxTestKind.NORMAL_CASE: "Normal case",
    SandboxTestKind.MISSING_INPUT: "Missing input",
    SandboxTestKind.CONFLICTING_INPUT: "Conflicting input",
    SandboxTestKind.PROHIBITED_ACTION: "Prohibited action",
    SandboxTestKind.SYSTEM_FAILURE: "System failure",
}

#: The workbook's "Test Status" list, in its own wording.
STATUS_LABELS: dict[str, str] = {
    SandboxTestStatus.NOT_RUN: "Not Run",
    SandboxTestStatus.PASS: "Pass",
    SandboxTestStatus.FAIL: "Fail",
    SandboxTestStatus.BLOCKED: "Blocked",
}


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SandboxTestInput(_Payload):
    """One of the five tests: what it tries, what should happen, and what did.

    `run_by` and `run_at` are deliberately absent. They are stamped by the server from the caller
    and the clock — a result somebody could backdate or attribute to a colleague is not evidence.
    """

    kind: SandboxTestKind
    sample_situation: str | None = Field(default=None, max_length=4000)
    expected_result: str | None = Field(default=None, max_length=4000)
    status: SandboxTestStatus = SandboxTestStatus.NOT_RUN
    #: Required by the schema for any status but `Not Run`. A `Fail` with no observation is a
    #: claim nobody can act on; a `Pass` with none is a claim nobody can check.
    actual_result: str | None = Field(default=None, max_length=4000)


class SandboxTestsUpdate(_Payload):
    """The five tests, written together. `expected_version` guards the design they describe."""

    expected_version: int
    tests: list[SandboxTestInput] = Field(max_length=5)


class SandboxTestRead(BaseModel):
    id: uuid.UUID
    kind: SandboxTestKind
    #: The sheet's wording, so a screen never invents a label for a printed row.
    label: str
    sample_situation: str | None
    expected_result: str | None
    status: SandboxTestStatus
    status_label: str
    actual_result: str | None
    run_by_membership_id: uuid.UUID | None
    run_by_name: str | None
    run_at: datetime | None


class SandboxTestList(BaseModel):
    tests: list[SandboxTestRead]
    #: Which of the five have not been written at all. Different from "not run".
    missing: list[SandboxTestKind]
    passed: int
    total: int


class AgentPublishGate(BaseModel):
    """One of §9's two publish gates.

    `reason` says what would clear it, not merely that it is closed — a screen that says "blocked"
    without saying why sends somebody hunting through six sections.
    """

    gate: str
    name: str
    passed: bool
    reason: str


class AgentPublishWarning(BaseModel):
    """Worth saying, and not a gate. Shown, never hidden, never in the way."""

    code: str
    message: str


class AgentPublishSummary(BaseModel):
    """What publishing this would mean, and what is standing in the way."""

    agent_id: uuid.UUID
    name: str
    status: str
    owner_name: str | None
    approver_name: str | None
    submitted_by_name: str | None
    job_name: str | None
    job_version_no: int | None

    step_count: int
    skill_count: int
    tool_count: int
    #: What this thing can actually reach. The number people most want on this screen.
    granted_tool_count: int
    io_input_count: int
    io_output_count: int
    knowledge_count: int
    #: Sources holding personal data. The privacy review reads this line.
    personal_data_sources: int
    shared_with_count: int

    tests_passed: int
    tests_total: int

    gates: list[AgentPublishGate]
    warnings: list[AgentPublishWarning]
    next_action: str
    can_submit: bool
    can_approve: bool
    version: int


class AgentVersionCard(BaseModel):
    """One published version. The snapshot itself is fetched separately — it is large."""

    id: uuid.UUID
    version_no: int
    name: str
    job_version_id: uuid.UUID | None
    published_by_name: str | None
    approved_by_name: str | None
    published_at: datetime


class AgentVersionList(BaseModel):
    versions: list[AgentVersionCard]
    is_empty: bool


class AgentPublishRequest(_Payload):
    """`expected_version` is the design the approver read. Approving a different one is not
    approving."""

    expected_version: int
