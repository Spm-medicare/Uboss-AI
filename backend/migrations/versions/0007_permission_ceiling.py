"""The permission ceiling, persisted.

PLAN §14 defines the chain:

    Company policy
    → Department/workspace policy
    → Objective/Job/Agent/Supervisor permission
    → Individual action permission

with one rule: "Lower scope cannot grant more power than the parent policy."

The resolution algorithm already existed and was correct. Nothing above the role layer was ever
*loaded*, so in practice a role was the whole answer and the top two links of the chain did
nothing. This migration gives them somewhere to live.

**A policy withholds; it never grants.** `scope_policies` lists actions taken away from every
role beneath it. That distinction is what makes the chain safe to leave unconfigured: a company
that has written no policy has not taken anything away, so a brand-new tenant works. Failing
closed applies to a missing *grant* — a person with no role is refused everything — not to an
unwritten optional restriction.

**A resource grant narrows too.** `resource_grants` answers "may this principal do this on this
object", and PLAN §17 lists "resource grants" as a table in the Identity domain. It cannot hand
out an action the principal's roles do not already hold: the chain is intersected, so a grant
naming something the role lacks resolves to nothing. That is checked when the grant is written,
too, so the mistake is visible at the point it is made rather than silently inert.

Revision: 0007
Parent:   0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: PLAN §14's thirteen. Repeated here rather than imported: a migration has to keep describing
#: the schema it created even after the application's enum moves on.
ACTIONS: tuple[str, ...] = (
    "view",
    "comment",
    "edit_draft",
    "publish",
    "run",
    "approve",
    "assign",
    "schedule",
    "manage_access",
    "export",
    "integrate",
    "administer",
    "audit",
)

#: The two scopes above a role, from PLAN §14. `resource` and `action` are the lower two links
#: and are handled by `resource_grants`, not by a policy.
SCOPES: tuple[str, ...] = ("company", "department")


def upgrade() -> None:
    action_list = ", ".join(f"'{action}'" for action in ACTIONS)
    scope_list = ", ".join(f"'{scope}'" for scope in SCOPES)

    # ── scope_policies ───────────────────────────────────────────────────────────────────
    op.create_table(
        "scope_policies",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope", sa.String(length=20), nullable=False),
        #  Null for a company policy — there is one per tenant and it applies to everyone. Set
        #  for a department policy, naming the hierarchy node it covers. The hierarchy arrives in
        #  Gate 2, so there is no foreign key yet and department policies cannot be created until
        #  there is something to point at. Modelled now because the *company* half is needed now
        #  and adding the column later would be a second migration over the same table.
        sa.Column("org_node_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        #  Why this restriction exists, in the words of whoever set it. Shown to an administrator
        #  looking at a refusal; a policy nobody can explain is a policy nobody dares change.
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_scope_policies"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_scope_policies_tenant_id_tenants", ondelete="RESTRICT"
        ),
        sa.CheckConstraint(f"scope IN ({scope_list})", name="ck_scope_policies_scope_known"),
        #  A company policy has no node; a department policy must have one. Enforced here because
        #  a company policy with a node attached would silently apply to nobody.
        sa.CheckConstraint(
            "(scope = 'company' AND org_node_id IS NULL) OR "
            "(scope = 'department' AND org_node_id IS NOT NULL)",
            name="ck_scope_policies_node_matches_scope",
        ),
    )
    op.create_index("ix_scope_policies_tenant_id", "scope_policies", ["tenant_id"])
    #  At most one company policy per tenant. Two would have no defined precedence.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_scope_policies_one_company_per_tenant
            ON scope_policies (tenant_id)
            WHERE scope = 'company';
        """
    )
    op.create_index(
        "ix_scope_policies_tenant_id_org_node_id", "scope_policies", ["tenant_id", "org_node_id"]
    )
    op.create_unique_constraint(
        "uq_scope_policies_tenant_id_id", "scope_policies", ["tenant_id", "id"]
    )

    # ── scope_policy_restrictions ────────────────────────────────────────────────────────
    op.create_table(
        "scope_policy_restrictions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("policy_id", postgresql.UUID(as_uuid=True), nullable=False),
        #  The action this policy **withholds**. A row here takes something away; there is no
        #  column that could grant, which is the point.
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_scope_policy_restrictions"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_scope_policy_restrictions_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "policy_id"],
            ["scope_policies.tenant_id", "scope_policies.id"],
            name="fk_scope_policy_restrictions_tenant_policy",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "policy_id", "action", name="uq_scope_policy_restrictions_policy_id_action"
        ),
        sa.CheckConstraint(
            f"action IN ({action_list})", name="ck_scope_policy_restrictions_action_known"
        ),
    )
    op.create_index(
        "ix_scope_policy_restrictions_tenant_id", "scope_policy_restrictions", ["tenant_id"]
    )
    op.create_index(
        "ix_scope_policy_restrictions_policy_id", "scope_policy_restrictions", ["policy_id"]
    )

    # ── resource_grants ──────────────────────────────────────────────────────────────────
    op.create_table(
        "resource_grants",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        #  What is being shared. A string rather than a foreign key, because a grant points at
        #  an objective, a job, an agent or a supervisor and those tables arrive across four
        #  different Gates. Constrained to a known list so a typo cannot create a grant on a
        #  resource type nothing will ever check.
        sa.Column("resource_type", sa.String(length=40), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        #  Who it is granted to. PLAN §14: user, team, role, guest, service account. Only
        #  `user` — meaning a membership — can be resolved today; the rest arrive with their
        #  tables and are refused by the application until then.
        sa.Column("principal_kind", sa.String(length=20), nullable=False),
        sa.Column("principal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("granted_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        #  An access grant that never ends is an access grant nobody revisits. Null means
        #  indefinite, which is allowed but is a decision rather than a default.
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_resource_grants"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_resource_grants_tenant_id_tenants", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "granted_by_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_resource_grants_tenant_grantor",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "resource_type",
            "resource_id",
            "principal_kind",
            "principal_id",
            "action",
            name="uq_resource_grants_subject_action",
        ),
        sa.CheckConstraint(f"action IN ({action_list})", name="ck_resource_grants_action_known"),
        sa.CheckConstraint(
            "principal_kind IN ('user', 'team', 'role', 'guest', 'service_account')",
            name="ck_resource_grants_principal_kind_known",
        ),
        sa.CheckConstraint(
            "resource_type IN ('objective', 'job', 'agent', 'supervisor', 'skill')",
            name="ck_resource_grants_resource_type_known",
        ),
    )
    op.create_index("ix_resource_grants_tenant_id", "resource_grants", ["tenant_id"])
    #  The lookup every permission check makes: what does this principal hold on this object.
    op.create_index(
        "ix_resource_grants_lookup",
        "resource_grants",
        ["tenant_id", "resource_type", "resource_id", "principal_kind", "principal_id"],
    )

    # ── row-level security, same shape as every other tenant-owned table ─────────────────
    for table in ("scope_policies", "scope_policy_restrictions", "resource_grants"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(
            f"""
            CREATE POLICY {table}_tenant_isolation ON {table}
                FOR ALL
                USING (tenant_id = app_current_tenant())
                WITH CHECK (tenant_id = app_current_tenant());
            """
        )
        #  ENABLE without FORCE, matching every other table since 0005 — see DECISIONS 22.

    for table in ("scope_policies", "resource_grants"):
        op.execute(
            f"""
            CREATE TRIGGER {table}_set_updated_at
                BEFORE UPDATE ON {table}
                FOR EACH ROW EXECUTE FUNCTION set_updated_at();
            """
        )


def downgrade() -> None:
    """Reversible: these tables are new and nothing else references them.

    A tenant that has written policies loses them, so the operator is expected to have taken the
    backup the runbook asks for.
    """
    for table in ("resource_grants", "scope_policy_restrictions", "scope_policies"):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE;")
