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

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from uboss.db.base import Base
from uboss.db.mixins import OptimisticVersion, PrimaryKey, Timestamps


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

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "owner_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_skills_tenant_owner",
            ondelete="SET NULL (owner_membership_id)",
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
        Index("ix_skills_department", "department", "industry"),
        Index("ix_skills_archetype", "archetype_id"),
    )

    @property
    def is_catalogue(self) -> bool:
        """True for one of the 400 shared rows. These are never editable by a tenant."""
        return self.tenant_id is None


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
