"""What the import API accepts and returns.

The response types carry more than the happy path on purpose. `ignored_columns`, `error_count`
and `proposal.consulted` are all things a screen must be able to state plainly — PLAN §5 asks for
a review, and a review with nothing to review is a confirmation dialog.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ImportMappingUpdate(BaseModel):
    """`{"Cost Centre": "unit_ref", ...}` — the mapping a person confirmed."""

    model_config = ConfigDict(extra="forbid")

    mapping: dict[str, str]
    expected_version: int = Field(ge=1)


class ImportApply(BaseModel):
    """The version the person was looking at when they decided.

    Not decoration: between reading the preview and pressing apply, somebody else may have
    re-mapped the columns. Applying a tree the person never saw is the failure this prevents.
    """

    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)


class KnownField(BaseModel):
    """A field the importer understands, for the mapping picker."""

    name: str
    description: str
    required: bool


class ImportSummary(BaseModel):
    """Where an import has got to, and what it made of the file."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: str
    sheet_name: str | None
    source_columns: list[str]
    #: `{column: {"field": ..., "source": "exact" | "proposed" | "chosen"}}`. The source is kept
    #: so a model's suggestion is never indistinguishable from a person's choice.
    column_mapping: dict[str, Any]
    #: Columns deliberately not used. Shown, so "we ignored six columns" is something the person
    #: read rather than something they find out afterwards.
    ignored_columns: list[str]
    #: Null until step 3 runs. `consulted: false` means no model was reachable — a supported
    #: state the screen must say out loud rather than showing an empty suggestion list.
    proposal: dict[str, Any] | None
    row_count: int
    error_count: int
    warning_count: int
    applied_at: datetime | None
    version: int


class ImportRowRead(BaseModel):
    """One staged row, and what is wrong with it."""

    row_number: int
    kind: str
    parsed: dict[str, Any]
    #: Any of these stops the whole import. A row nobody can see is a row nobody can fix, so
    #: rows with errors are still returned.
    errors: list[str]
    #: Worth saying; does not stop anything.
    warnings: list[str]


class ProposedUnit(BaseModel):
    """A department as the file describes it, before it exists."""

    name: str
    parent_name: str | None
    unit_type: str
    external_ref: str | None
    positions: list[dict[str, Any]]


class ImportPreview(BaseModel):
    """Everything a person needs before deciding — PLAN §5 steps 5 and 6."""

    model_config = ConfigDict(from_attributes=True)

    import_id: uuid.UUID
    status: str
    source_columns: list[str]
    column_mapping: dict[str, Any]
    ignored_columns: list[str]
    proposal: dict[str, Any] | None
    row_count: int
    error_count: int
    warning_count: int
    #: Flat, with `parent_name` rather than an id — nothing exists yet to have one. The client
    #: nests it, exactly as it does the live tree.
    proposed_tree: list[ProposedUnit]
    #: Capped for the response. The counts above are exact regardless, so "12 errors" stays true
    #: when the list shows the first 200 rows.
    rows: list[ImportRowRead]
    can_apply: bool
