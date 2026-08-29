"""What the identity endpoints accept and return.

Nothing here exposes a `users` row. The API's idea of a person is a membership: the name, title
and roles that this organisation gave them. A user id is an internal join key and does not
appear in any response.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SignInRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: A plain string, normalised but not strictly validated — deliberately.
    #:
    #: A strict address validator on *this* form would answer a question the endpoint is built
    #: to refuse: a 422 for "not a valid address" and a 401 for "wrong credentials" are
    #: distinguishable, so an attacker learns which addresses are even worth trying. It would
    #: also lock out a real person whose provisioned address the validator happens to dislike.
    #:
    #: Strict validation belongs where an address is *created* — an invite — because that is
    #: where a typo has a cost and where telling the truth about it is safe.
    email: str = Field(min_length=3, max_length=320)

    #: Not length-validated beyond the obvious. A minimum on sign-in tells an attacker the shape
    #: of valid passwords, and would reject someone whose password predates a rule change —
    #: locking out a real person to no benefit. Strength is checked when a password is *set*.
    password: str = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def normalise_email(cls, value: str) -> str:
        """Trim and lowercase, so the lookup matches how the address was stored."""
        return value.strip().lower()


class WorkspaceSummary(BaseModel):
    """One organisation this person belongs to."""

    slug: str
    name: str
    display_name: str = Field(description="Their name as this organisation knows them.")


class ChooseWorkspaceResponse(BaseModel):
    """The password was right, but the person belongs to more than one organisation.

    Returned with 200, not an error: nothing failed. The client shows a chooser and submits the
    short-lived challenge — never the password again. The list is only ever produced after a
    correct password.
    """

    status: Literal["choose_workspace"] = "choose_workspace"
    challenge: str = Field(description="Short-lived, single-use workspace selection proof.")
    workspaces: list[WorkspaceSummary]


class WorkspaceSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    challenge: str = Field(min_length=32, max_length=200)
    workspace: str = Field(min_length=1, max_length=63)


class CurrentUser(BaseModel):
    """Who is signed in, and what they may do.

    `actions` drives menu visibility. It is a convenience for the interface and never a
    substitute for the check: every route re-resolves permissions server-side, because a list
    sent to a browser is a list the browser can edit.
    """

    membership_id: uuid.UUID
    display_name: str
    #: Output only. Validating an address on the way *out* would mean the API could refuse to
    #: describe a person whose address is already in the database — a failure with no upside.
    email: str
    job_title: str | None = None
    roles: list[str]
    actions: list[str]

    workspace_slug: str
    workspace_name: str
    timezone: str

    org_node_id: uuid.UUID | None = None
    #: True when this session proved a second factor. High-risk actions read it.
    stepped_up: bool = False
    session_expires_at: datetime


class SignInResponse(BaseModel):
    status: Literal["signed_in"] = "signed_in"
    user: CurrentUser


class PasswordStepUpRequest(BaseModel):
    """Re-prove the current account's password before a high-risk action."""

    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=1, max_length=256)


class StepUpResponse(BaseModel):
    status: Literal["stepped_up"] = "stepped_up"
    method: Literal["password"] = "password"
    expires_at: datetime


class SessionSummary(BaseModel):
    """One of a person's active sessions, for a "where am I signed in?" list."""

    id: uuid.UUID
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    ip_address: str | None = None
    user_agent: str | None = None
    #: True for the session making this request, so the interface can label it rather than
    #: inviting someone to end the session they are using without warning.
    is_current: bool = False
