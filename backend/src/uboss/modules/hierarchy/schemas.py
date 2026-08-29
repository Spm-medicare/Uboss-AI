"""What the hierarchy API accepts and returns.

Two decisions run through all of it:

**A date, not a moment.** Somebody starts a job on a day, in their own timezone. `date` says
exactly that; a timestamp would be more precise and less true, and would make "did they hold this
on the first of June" depend on which side of midnight the server was.

**`expected_version` on every change.** PLAN §28. The client sends the version it read and the
update matches on it. Without it two people editing the same department means the second save
quietly discards the first — no error, and nothing to notice.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from uboss.modules.hierarchy.models import ReportingKind, UnitType


class _Payload(BaseModel):
    #: Unknown fields are rejected rather than ignored. A typo in a field name would otherwise
    #: succeed silently and change nothing — the worst possible outcome for a write.
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="after")
    @classmethod
    def _blank_is_absent(cls, value: object) -> object:
        """An empty box in a form is "not set", never the empty string.

        Stored as `""`, a blank external reference would collide with the next blank one under
        the unique index — turning "I left it empty" into "that identifier is already taken".
        """
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        return value


class OrgUnitCreate(_Payload):
    parent_id: uuid.UUID | None = None
    name: str = Field(min_length=1, max_length=200)
    unit_type: UnitType
    external_ref: str | None = Field(default=None, max_length=120)
    location: str | None = Field(default=None, max_length=200)


class OrgUnitUpdate(_Payload):
    """A rename or a re-code. All fields optional; what is absent is left alone.

    Moving is deliberately not here — see `OrgUnitMove`. Re-parenting through this payload would
    mean `parent_id: uuid | None`, in which "not sent" and "sent as null" are the same value, and
    null is meaningful: it would make this unit the root.
    """

    name: str | None = Field(default=None, min_length=1, max_length=200)
    unit_type: UnitType | None = None
    external_ref: str | None = Field(default=None, max_length=120)
    location: str | None = Field(default=None, max_length=200)
    expected_version: int = Field(ge=1)


class OrgUnitMove(_Payload):
    """Re-parenting, which is separate from editing on purpose.

    Moving a department takes its whole subtree with it — every position, every reporting line
    below it. That is a different kind of change from correcting a spelling, and it reads
    differently in the revision history because it is a different endpoint.
    """

    new_parent_id: uuid.UUID
    expected_version: int = Field(ge=1)


class PositionCreate(_Payload):
    org_unit_id: uuid.UUID
    title: str = Field(min_length=1, max_length=200)
    level: int | None = Field(default=None, ge=0, le=100)
    location: str | None = Field(default=None, max_length=200)
    external_ref: str | None = Field(default=None, max_length=120)


class PositionUpdate(_Payload):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    level: int | None = Field(default=None, ge=0, le=100)
    location: str | None = Field(default=None, max_length=200)
    external_ref: str | None = Field(default=None, max_length=120)
    org_unit_id: uuid.UUID | None = None
    expected_version: int = Field(ge=1)


class AssignmentCreate(_Payload):
    """Put a person in a seat from a date.

    An open-ended assignment (`effective_to` absent) is the normal case — most people do not know
    when they will leave a job. Closing one is `PATCH`, not a delete: they held it, and that
    stays true.
    """

    membership_id: uuid.UUID
    effective_from: date
    effective_to: date | None = None

    @model_validator(mode="after")
    def _ordered(self) -> AssignmentCreate:
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("effective_to must be after effective_from")
        return self


class AssignmentEnd(_Payload):
    """Close an assignment on a date. The row stays; only its end moves."""

    effective_to: date
    expected_version: int = Field(ge=1)


class ReportingEdgeCreate(_Payload):
    manager_position_id: uuid.UUID
    kind: ReportingKind = ReportingKind.PRIMARY
    effective_from: date
    effective_to: date | None = None

    @model_validator(mode="after")
    def _ordered(self) -> ReportingEdgeCreate:
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("effective_to must be after effective_from")
        return self


# ---------------------------------------------------------------------------- reading


class PersonInSeat(BaseModel):
    """Whoever holds a position on the date being asked about."""

    membership_id: uuid.UUID
    display_name: str
    job_title: str | None = None
    effective_from: date
    effective_to: date | None = None
    assignment_id: uuid.UUID
    assignment_version: int


class PositionRead(BaseModel):
    id: uuid.UUID
    org_unit_id: uuid.UUID
    title: str
    level: int | None
    location: str | None
    external_ref: str | None
    archived_at: datetime | None
    version: int

    #: Null means the seat is vacant on the date asked for. PLAN §5 requires vacancies to be
    #: visible — an org chart that hides its empty seats hides the hiring plan.
    holder: PersonInSeat | None = None
    #: The position this one reports to, primary line only, on that same date.
    reports_to_position_id: uuid.UUID | None = None
    dotted_line_position_ids: list[uuid.UUID] = Field(default_factory=list)


class OrgUnitRead(BaseModel):
    id: uuid.UUID
    parent_id: uuid.UUID | None
    name: str
    unit_type: UnitType
    external_ref: str | None
    location: str | None
    archived_at: datetime | None
    version: int
    positions: list[PositionRead] = Field(default_factory=list)


class TreeRead(BaseModel):
    """The whole tree, flat.

    Flat rather than nested, deliberately. The client builds the nesting from `parent_id`, which
    means one shape serves the tree view, a search result and a partially expanded view without
    the server guessing which is wanted. A nested response would also have to pick a depth limit,
    and any limit is wrong for somebody.
    """

    #: The date this view describes. Every holder and reporting line is as at this date, so the
    #: whole response is one consistent picture rather than a mixture of "now" and "then".
    as_at: date
    units: list[OrgUnitRead]
    #: True when there is no tree yet, so the interface can offer to build one rather than
    #: rendering an empty box that looks like a failure.
    is_empty: bool


class RevisionRead(BaseModel):
    id: uuid.UUID
    revision_no: int
    change_type: str
    entity_type: str
    entity_id: uuid.UUID
    summary: str
    actor_membership_id: uuid.UUID | None
    actor_display_name: str | None
    created_at: datetime
    #: True when this change can still be reversed — see `service.undo`.
    can_undo: bool


class RevisionPage(BaseModel):
    revisions: list[RevisionRead]
    #: Absent when there is nothing older. Keyset rather than an offset: a page numbered from the
    #: end shifts under you as new revisions arrive.
    next_before_revision_no: int | None = None


class ValidationIssue(BaseModel):
    """Something wrong with the tree that is not wrong enough to refuse a write.

    PLAN §5 asks the product to detect *"cycles, orphan managers and duplicate identifiers"*.
    Cycles and duplicates are refused outright by the database. Orphans are different: a position
    whose manager has been archived is a real state an organisation passes through during a
    restructure, and refusing it would mean refusing the restructure. So it is reported here,
    where somebody can see it and decide.
    """

    kind: str
    entity_type: str
    entity_id: uuid.UUID
    detail: str
