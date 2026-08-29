"""The permission ceiling: company policy, department policy and resource grants.

PLAN §14's chain is company → department → resource → action, with one rule: a lower scope can
never grant more power than the scope above it.

Everything here **withholds**. A policy is a list of actions taken away from every role beneath
it; there is no shape in this module that could add one. That is what makes an unconfigured
chain safe: a company that has written no policy has not taken anything away, so a new tenant
works, while a company that has written one narrows every role at once.

Failing closed applies to a missing *grant* — someone with no role is refused everything, which
`effective()` already produces from an empty set. It does not mean treating an unwritten optional
restriction as a total prohibition.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from uboss.core.errors import ValidationFailed, as_field_error
from uboss.core.permissions import Action, Grant, Scope
from uboss.db.base import Base
from uboss.db.mixins import OptimisticVersion, PrimaryKey, TenantOwned, Timestamps


class PolicyScope(enum.StrEnum):
    """The two links above a role. `resource` and `action` are grants, not policies."""

    COMPANY = "company"
    DEPARTMENT = "department"


class ScopePolicy(Base, PrimaryKey, TenantOwned, Timestamps, OptimisticVersion):
    """A set of actions withheld from everyone beneath a scope."""

    __tablename__ = "scope_policies"

    scope: Mapped[str] = mapped_column(String(20), nullable=False)

    #: Null for a company policy — one per tenant, applying to everyone. Set for a department
    #: policy, naming the hierarchy node it covers. The hierarchy arrives in Gate 2, so no
    #: department policy can be created until there is a node to point at.
    org_node_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    #: Why this restriction exists, in the words of whoever set it. Shown to an administrator
    #: looking at a refusal — a policy nobody can explain is a policy nobody dares change.
    reason: Mapped[str] = mapped_column(Text, nullable=False, server_default="")

    __table_args__ = (
        CheckConstraint("scope IN ('company', 'department')", name="scope_known"),
        CheckConstraint(
            "(scope = 'company' AND org_node_id IS NULL) OR "
            "(scope = 'department' AND org_node_id IS NOT NULL)",
            name="node_matches_scope",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_scope_policies_tenant_id_id"),
        Index("ix_scope_policies_tenant_id_org_node_id", "tenant_id", "org_node_id"),
    )


class ScopePolicyRestriction(Base, PrimaryKey, TenantOwned):
    """One action a policy withholds.

    A row here takes something away. There is deliberately no column that could grant.
    """

    __tablename__ = "scope_policy_restrictions"

    policy_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "policy_id"],
            ["scope_policies.tenant_id", "scope_policies.id"],
            name="fk_scope_policy_restrictions_tenant_policy",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "policy_id", "action", name="uq_scope_policy_restrictions_policy_id_action"
        ),
    )


async def grants_above_role(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    org_node_id: uuid.UUID | None,
    role_actions: frozenset[Action],
) -> tuple[Grant, ...]:
    """Resolve the company and department layers for one caller.

    Returns a `Grant` per configured scope, each holding what that scope *permits* — which is
    the role's actions minus what the policy withholds. Expressed as a permitted set because
    `effective()` intersects, and intersecting with "everything except X" is how a restriction
    narrows.

    A scope with no policy contributes **no grant at all**, not an empty one. That is the
    difference between "this company has restricted nothing" and "this company permits nothing",
    and getting it backwards makes an unconfigured tenant indistinguishable from a locked-out
    one.

    Department policies are matched on the caller's own hierarchy node. Until the hierarchy
    exists (Gate 2) every membership has a null node, so no department policy can match — which
    is correct rather than a gap: a policy scoped to a node nobody occupies applies to nobody.
    """
    conditions = [ScopePolicy.scope == PolicyScope.COMPANY]
    if org_node_id is not None:
        conditions.append(
            (ScopePolicy.scope == PolicyScope.DEPARTMENT)
            & (ScopePolicy.org_node_id == org_node_id)
        )

    rows = (
        await session.execute(
            select(ScopePolicy.scope, ScopePolicyRestriction.action)
            .select_from(ScopePolicy)
            .outerjoin(
                ScopePolicyRestriction,
                ScopePolicyRestriction.policy_id == ScopePolicy.id,
            )
            .where(ScopePolicy.tenant_id == tenant_id)
            .where(conditions[0] if len(conditions) == 1 else conditions[0] | conditions[1])
        )
    ).all()

    if not rows:
        return ()

    withheld: dict[str, set[Action]] = {}
    for scope_name, action_name in rows:
        bucket = withheld.setdefault(scope_name, set())
        if action_name is None:
            #  A policy with no restriction rows exists but takes nothing away. It still
            #  produces a grant, so an administrator can see the layer is configured.
            continue
        try:
            bucket.add(Action(action_name))
        except ValueError:
            #  The column is constrained to the thirteen, so this only fires if the database and
            #  the enum ever disagree. Ignoring is the fail-closed answer: an unrecognised
            #  restriction withholds nothing rather than being guessed at.
            continue

    scope_by_name = {
        PolicyScope.COMPANY.value: Scope.COMPANY,
        PolicyScope.DEPARTMENT.value: Scope.DEPARTMENT,
    }
    return tuple(
        Grant(
            scope=scope_by_name[name],
            actions=role_actions - taken,
            source=f"{name} policy",
        )
        for name, taken in withheld.items()
        if name in scope_by_name
    )


class ResourceGrant(Base, PrimaryKey, TenantOwned, Timestamps):
    """One action a principal may take on one object.

    PLAN §17 lists "resource grants" in the Identity domain, and PLAN §14 places them third in
    the chain: company → department → **resource** → action.

    Like every other link, it **narrows**. It cannot hand out an action the principal's roles do
    not already hold — the chain is intersected, so a grant naming something the role lacks
    resolves to nothing. `check_grant_is_narrowing` refuses it at write time as well, so the
    mistake is visible where it is made rather than silently inert.
    """

    __tablename__ = "resource_grants"

    #: A string rather than a foreign key: a grant points at an objective, a job, an agent or a
    #: supervisor, and those tables arrive across four different Gates. Constrained in the
    #: database so a typo cannot create a grant on a type nothing will ever check.
    resource_type: Mapped[str] = mapped_column(String(40), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)

    #: PLAN §14: user, team, role, guest, service account. Only `user` — meaning a membership —
    #: can be resolved today; the others have no tables yet and are refused rather than guessed.
    principal_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    principal_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)

    action: Mapped[str] = mapped_column(String(40), nullable=False)

    granted_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    #: Null means indefinite. Allowed, but a decision rather than a default — access that never
    #: ends is access nobody revisits.
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "resource_type",
            "resource_id",
            "principal_kind",
            "principal_id",
            "action",
            name="uq_resource_grants_subject_action",
        ),
        CheckConstraint(
            "principal_kind IN ('user', 'team', 'role', 'guest', 'service_account')",
            name="principal_kind_known",
        ),
        CheckConstraint(
            "resource_type IN ('objective', 'job', 'agent', 'supervisor', 'skill')",
            name="resource_type_known",
        ),
        Index(
            "ix_resource_grants_lookup",
            "tenant_id",
            "resource_type",
            "resource_id",
            "principal_kind",
            "principal_id",
        ),
    )


#: The principal kinds that can be resolved today. The other three from PLAN §14 — team, guest,
#: service account — have no tables yet, so a grant naming one is refused when it is written
#: rather than silently ignored when it is read.
RESOLVABLE_PRINCIPALS: frozenset[str] = frozenset({"user"})


async def grant_for_resource(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    membership_id: uuid.UUID,
    resource_type: str,
    resource_id: uuid.UUID,
    role_actions: frozenset[Action],
) -> Grant | None:
    """What this caller may do on this one object, or None if nothing was granted.

    **None and an empty grant mean opposite things**, which is why this returns an optional.
    None says "no resource-level restriction applies", and the chain skips the layer — a person
    with `view` from their role can still see an object nobody has explicitly shared. An empty
    grant would say "this layer permits nothing", refusing everything on every object, which is
    not what a sharing model means.

    Explicit sharing therefore *adds* nothing here; it is the resource layer's job to narrow when
    it is configured. An object whose access is restricted gets a grant listing who may do what,
    and the caller's own roles still cap it.
    """
    now = datetime.now(UTC)
    rows = (
        await session.execute(
            select(ResourceGrant.action).where(
                ResourceGrant.tenant_id == tenant_id,
                ResourceGrant.resource_type == resource_type,
                ResourceGrant.resource_id == resource_id,
                ResourceGrant.principal_kind == "user",
                ResourceGrant.principal_id == membership_id,
                (ResourceGrant.expires_at.is_(None))
                | (ResourceGrant.expires_at > now),
            )
        )
    ).scalars().all()

    if not rows:
        return None

    permitted: set[Action] = set()
    for name in rows:
        try:
            permitted.add(Action(name))
        except ValueError:
            #  Constrained in the database, so this only fires if the column and the enum ever
            #  disagree. Ignoring is the fail-closed answer.
            continue

    #  Intersected with the role's actions here as well as in the chain. Belt and braces, and it
    #  makes the returned grant honest on its own: it never claims more than the caller holds.
    return Grant(
        scope=Scope.RESOURCE,
        actions=frozenset(permitted) & role_actions,
        source="resource grant",
    )


def check_grant_is_narrowing(
    action: Action, principal_kind: str, principal_actions: frozenset[Action]
) -> None:
    """Refuse a grant that would try to widen, at the moment it is written.

    The chain already makes such a grant inert — intersection means it can never take effect.
    Refusing it here too means the mistake is visible to the person making it, rather than
    becoming a row that looks like access and behaves like nothing. A silently ineffective grant
    is worse than an error: someone believes access was given.
    """
    if principal_kind not in RESOLVABLE_PRINCIPALS:
        raise ValidationFailed(
            f"Grants to a {principal_kind} cannot be resolved yet — only a person can hold one "
            "today. Teams, guests and service accounts arrive with their own tables.",
            field_errors=as_field_error("principal_kind", "Not supported yet.", "unsupported"),
        )
    if action not in principal_actions:
        raise ValidationFailed(
            f"This person's roles do not grant {action}, so sharing it would have no effect. "
            "Give them a role that holds it first.",
            field_errors=as_field_error(
                "action", "Their roles do not include this.", "exceeds_role"
            ),
        )
