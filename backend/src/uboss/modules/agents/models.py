"""The Skill Registry — PLAN §39's client-owned seed asset.

Four tables, and the shape of them is the design:

* `skill_archetypes` and `skill_exactness_gates` are shared reference data with no tenant, seeded
  from the approved workbook and read-only to the application.
* `skills` holds **both** the 400 shared catalogue rows and a tenant's own private drafts. One
  table, because a search has to return both and a resolver has to gate both identically.
* `skill_rules` is the 2,400 IF-THEN rules, each carrying what happens when it does not hold.

§39: *"Skill Registry is internal to Agent Builder and is not a sidebar module."* Nothing here
adds a menu item.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    FetchedValue,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from uboss.db.base import Base
from uboss.db.mixins import OptimisticVersion, PrimaryKey, TenantOwned, Timestamps


class Autonomy(enum.StrEnum):
    """How far a skill may go on its own — the workbook's "Autonomy" column.

    A ceiling, not a description. An agent asking a skill to operate above its level is refused,
    which is the difference between a catalogue and a control.
    """

    READ = "A1"
    DRAFT = "A2"
    WRITE_AFTER_APPROVAL = "A3"
    HUMAN_REQUIRED = "A4"


class SkillStatus(enum.StrEnum):
    """A private skill's lifecycle. Catalogue rows are always `PUBLISHED`."""

    DRAFT = "draft"
    READY_TO_PUBLISH = "ready_to_publish"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class SkillArchetype(Base):
    """One of the twelve types — Router, Extractor, Validator, Governance and the rest.

    Carries its own IF and THEN, and the controls every skill of that type must have. A reviewer
    checking a composed skill against its archetype is comparing exactly these.
    """

    __tablename__ = "skill_archetypes"

    #: "T01" … "T12", from the sheet.
    id: Mapped[str] = mapped_column(String(8), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    if_clause: Mapped[str] = mapped_column(Text, nullable=False)
    then_clause: Mapped[str] = mapped_column(Text, nullable=False)
    typical_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    mandatory_controls: Mapped[str | None] = mapped_column(Text, nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class SkillExactnessGate(Base):
    """One of the twelve gates — PLAN §39's *"deterministic compatibility gates"*.

    The workbook already writes all twelve down with their own failure states, so the resolver
    reads rows rather than running twelve `if` statements. A refusal then quotes the catalogue
    word for word — `BLOCKED — ambiguous scope` — instead of a message somebody invented.
    """

    __tablename__ = "skill_exactness_gates"

    #: "E01" … "E12".
    id: Mapped[str] = mapped_column(String(8), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    if_clause: Mapped[str] = mapped_column(Text, nullable=False)
    then_clause: Mapped[str] = mapped_column(Text, nullable=False)
    #: What proves it passed. This is what an evidence panel shows and what an audit reads.
    pass_evidence: Mapped[str] = mapped_column(Text, nullable=False)
    #: In the catalogue's own words. Quoted verbatim by the resolver.
    failure_state: Mapped[str] = mapped_column(String(120), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class Skill(Base, PrimaryKey, Timestamps, OptimisticVersion):
    """A skill — either one of the 400 shared catalogue rows, or a tenant's own draft.

    **The seed is shared, private drafts are not.** `tenant_id` null means the catalogue: the same
    rows for every organisation, read-only to the application. Copying 400 rows per tenant would
    mean 400 copies of every correction, and a catalogue that had diverged before anybody noticed.

    §39: *"Skills cannot self-publish."* A published private skill must name who approved it, and
    the schema refuses one that does not.
    """

    __tablename__ = "skills"

    #: Null for the shared catalogue; set for a private draft.
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=True
    )
    #: The workbook's "Skill ID" — `U-001`, `I-014`. Null for a private draft.
    catalogue_id: Mapped[str | None] = mapped_column(String(20), nullable=True)

    name: Mapped[str] = mapped_column(String(300), nullable=False)
    layer: Mapped[str] = mapped_column(String(40), nullable=False)
    department: Mapped[str | None] = mapped_column(String(200), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(200), nullable=True)
    archetype_id: Mapped[str | None] = mapped_column(
        String(8), ForeignKey("skill_archetypes.id", ondelete="RESTRICT"), nullable=True
    )

    purpose: Mapped[str | None] = mapped_column(Text, nullable=True)
    positive_trigger: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: What this skill is **not** for. The column that matters most on a search result: it is
    #: what stops a plausible hit from being the wrong skill.
    exclusions: Mapped[str | None] = mapped_column(Text, nullable=True)
    minimum_inputs: Mapped[str | None] = mapped_column(Text, nullable=True)
    primary_if: Mapped[str | None] = mapped_column(Text, nullable=True)
    primary_then: Mapped[str | None] = mapped_column(Text, nullable=True)
    output: Mapped[str | None] = mapped_column(Text, nullable=True)
    validation_gate: Mapped[str | None] = mapped_column(Text, nullable=True)

    autonomy: Mapped[str] = mapped_column(String(4), nullable=False, server_default="A1")
    #: Where the skill's authority comes from. §39 forbids similarity overriding *"stale
    #: evidence"*, and this is what freshness is judged against.
    source_ids: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="published")
    owner_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    approved_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Who a draft was sent to, and who sent it. Without both, *"nobody approves their own work"*
    #: cannot be checked — §39's *"No Skill or Agent can approve/promote itself"* would be a
    #: sentence in a document rather than a rule.
    approver_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    submitted_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    #: Both carry `SET NULL (<column>)` in migration 0043 — see the note there. A bare clause on a
    #: composite key would null `tenant_id` as well and turn a private skill into a catalogue row.
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: The frozen version a published private skill is running. Null for a draft, and null for the
    #: catalogue — its 400 rows are shared seed data with no version of their own.
    published_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "owner_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_skills_tenant_owner",
            ondelete="SET NULL (owner_membership_id)",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "approver_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_skills_tenant_approver",
            ondelete="SET NULL (approver_membership_id)",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "submitted_by_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_skills_tenant_submitter",
            ondelete="SET NULL (submitted_by_membership_id)",
        ),
        CheckConstraint(
            "(tenant_id IS NULL AND catalogue_id IS NOT NULL) OR "
            "(tenant_id IS NOT NULL AND catalogue_id IS NULL)",
            name="ck_skills_catalogue_or_private",
        ),
        CheckConstraint(
            "tenant_id IS NULL OR status <> 'published' OR "
            "(approved_by_membership_id IS NOT NULL AND approved_at IS NOT NULL)",
            name="ck_skills_published_was_approved",
        ),
        CheckConstraint(
            "tenant_id IS NULL OR status <> 'published' OR published_version_id IS NOT NULL",
            name="ck_skills_published_has_version",
        ),
        CheckConstraint(
            "tenant_id IS NULL OR status <> 'ready_to_publish' OR "
            "(submitted_by_membership_id IS NOT NULL AND approver_membership_id IS NOT NULL)",
            name="ck_skills_submitted_has_submitter",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_skills_tenant_id"),
        Index("ix_skills_department", "department", "industry"),
        Index("ix_skills_archetype", "archetype_id"),
    )

    @property
    def is_catalogue(self) -> bool:
        """True for one of the 400 shared rows. These are never editable by a tenant."""
        return self.tenant_id is None

    @property
    def is_editable(self) -> bool:
        """Whether the design may still be changed.

        The same two states as every other builder in this codebase — and for the same reason:
        between submitting and approving, a design has to hold still, or the approver approves
        something other than what was sent and the immutable version published from it is not the
        thing that was reviewed. The catalogue is never editable by a tenant at all.
        """
        return not self.is_catalogue and self.status == SkillStatus.DRAFT


class SkillRule(Base, PrimaryKey):
    """One IF-THEN rule.

    `failure_state` is the reason these are worth importing rather than summarising: it is what
    turns the registry from a search index into a governance asset, because the answer to "why was
    this refused" is a row rather than somebody's judgement.
    """

    __tablename__ = "skill_rules"

    skill_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("skills.id", ondelete="CASCADE"), nullable=False
    )
    #: The workbook's "Rule ID" — `R-0001`.
    catalogue_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    #: One of the six the sheet uses: trigger, input completeness, primary decision, evidence,
    #: validation, authority.
    condition_type: Mapped[str] = mapped_column(String(60), nullable=False)
    if_clause: Mapped[str] = mapped_column(Text, nullable=False)
    then_clause: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, server_default="High")
    evidence_required: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_state: Mapped[str | None] = mapped_column(String(120), nullable=True)
    #: Whether a person has to be in the loop: Yes, No, Conditional, As needed.
    human_gate: Mapped[str | None] = mapped_column(String(30), nullable=True)
    source_ids: Mapped[str | None] = mapped_column(Text, nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")

    __table_args__ = (Index("ix_skill_rules_skill", "skill_id", "position"),)


class ResolverRoute(enum.StrEnum):
    """The five endings PLAN §39 allows a resolution to have.

    `BLOCKED` is one of them. *"Block/route change when no safe choice exists"* is a decision the
    resolver is required to be able to reach — not a failure to reach one.
    """

    REUSE = "reuse"
    CONFIGURE = "configure"
    COMPOSE = "compose"
    CREATE = "create"
    BLOCKED = "blocked"


class SkillResolverDecision(Base, PrimaryKey):
    """What was asked, what was found, which gates refused, and what was decided.

    `docs/product/SKILL_REGISTRY.md`: *"Present route and evidence."* Without this row the
    resolver would be a recommendation engine — an answer nobody could question six months later.

    Append-only. A decision describes a moment: the requirement as stated, the candidates as they
    then stood, the gates as the catalogue then defined them. `UPDATE` and `DELETE` are refused by
    a trigger and withheld from the application role, so a later correction to the catalogue
    cannot rewrite what was decided under the old wording.
    """

    __tablename__ = "skill_resolver_decisions"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False
    )
    requested_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    #: The requirement verbatim. A decision read back beside a paraphrase proves nothing.
    requirement: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    source_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)

    route: Mapped[str] = mapped_column(String(20), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    #: Null for `create` and `blocked`, and for `compose` — whose answer is a set, so naming one
    #: member of it would misreport what was decided.
    selected_skill_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("skills.id", ondelete="RESTRICT"), nullable=True
    )
    #: Every candidate with its rank and its gate results. The evidence; the route is the summary.
    candidates: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    #: Gates that could not run because what they read is not modelled yet. Recorded rather than
    #: passed — a gate nobody ran has not been satisfied.
    unevaluated_gates: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SkillTestKind(enum.StrEnum):
    """The six `docs/product/SKILL_REGISTRY.md` says the Factory collects.

    > Golden, negative, injection, permission, tool-failure and rollback tests.

    A closed set, because the contract prints all six: a missing one is not a value outside a list,
    it is a test nobody thought about. Named `SkillTest…` rather than `Test…` because pytest
    collects any imported class whose name begins with `Test`.
    """

    #: It works on the case it was built for.
    GOLDEN = "golden"
    #: It declines the case it is not for — the exclusions, tested.
    NEGATIVE = "negative"
    #: Instructions inside the input are reported, never followed.
    INJECTION = "injection"
    #: It stops at its authority rather than at its ability.
    PERMISSION = "permission"
    #: A tool that fails leaves the work in a state somebody can act on.
    TOOL_FAILURE = "tool_failure"
    #: What it did can be undone, and the test says how.
    ROLLBACK = "rollback"


class SkillTest(Base, PrimaryKey, TenantOwned, Timestamps):
    """One of the six, and what happened when somebody ran it.

    **A result belongs to a design.** Saving the draft clears every result: a pass recorded against
    yesterday's rules says nothing about today's, and deciding which edits "do not count" is
    exactly the judgement that lets a stale pass through. The Agent's tests already work this way.

    **There is no sandbox runtime for a skill yet.** A status is recorded by the person who ran the
    test, and `run_by_membership_id` and `run_at` are what make that evidence rather than a
    checkbox — migration 0043 refuses a decided result that carries neither. The gate is real
    either way.

    Only a private skill has tests. The catalogue's 400 rows are shared and read-only, and the
    composite foreign key cannot reach them.
    """

    __tablename__ = "skill_tests"

    skill_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    sample_situation: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="not_run")
    actual_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "skill_id"],
            ["skills.tenant_id", "skills.id"],
            name="fk_skill_tests_skill",
            ondelete="CASCADE",
        ),
        #  The column is named: a bare `SET NULL` on a composite key nulls `tenant_id` too.
        ForeignKeyConstraint(
            ["tenant_id", "run_by_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_skill_tests_runner",
            ondelete="SET NULL (run_by_membership_id)",
        ),
        UniqueConstraint("tenant_id", "skill_id", "kind", name="uq_skill_tests_kind"),
        Index("ix_skill_tests_skill", "tenant_id", "skill_id"),
    )

    @property
    def passed(self) -> bool:
        """Whether this test cleared.

        Reads `agent_models.SandboxTestStatus` rather than a second copy of the same four words.
        The workbook prints one list — Not Run, Pass, Fail, Blocked — and an Agent's tests and a
        skill's tests are the same governance object at different scales. Imported inside the
        property because the two model modules are otherwise independent, and a module-level import
        would tie the registry's tables to the Agent's for the sake of one comparison.
        """
        from uboss.modules.agents.agent_models import SandboxTestStatus

        return bool(self.status == SandboxTestStatus.PASS)


class SkillVersion(Base, PrimaryKey, TenantOwned):
    """A private skill, frozen when it was approved.

    *"Published versions are immutable."* Append-only in two independent ways, as everywhere else
    in this schema: a trigger refuses `UPDATE` and `DELETE`, and the privilege was never granted to
    `uboss_app`. `version_no` is assigned by a trigger under an advisory lock, so two approvals in
    the same instant cannot produce two version 3s.

    No `Timestamps`: `published_at` is the only time that means anything here, and an `updated_at`
    on a row that cannot be updated would be a column inviting somebody to try.
    """

    __tablename__ = "skill_versions"

    skill_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, server_default=FetchedValue())
    #: Every field, its IF-THEN rules and the six test results as they stood. What a resolver
    #: selects is what was approved.
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    published_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    approved_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "skill_id"],
            ["skills.tenant_id", "skills.id"],
            name="fk_skill_versions_skill",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("tenant_id", "skill_id", "version_no", name="uq_skill_versions_no"),
        UniqueConstraint("tenant_id", "id", name="uq_skill_versions_tenant_id"),
    )
