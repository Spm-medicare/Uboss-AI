"""Roles and permissions become tables, as PLAN §17 requires.

PLAN §17 lists the Identity domain as: "tenants, users, memberships, teams, **roles**,
**permissions**, resource grants, sessions, guests and service accounts." Roles are a table. They
were implemented as a hard-coded Python dictionary and a `CHECK` constraint listing six names —
`viewer, contributor, builder, approver, manager, admin` — that appear nowhere in PLAN. Those
names were invented during implementation. This migration removes them.

Two things follow from doing it the way PLAN says.

**The role matrix is a Gate 0 deliverable, not a code constant.** PLAN §25 lists "Final role,
sharing, Supervisor-handler and entitlement matrix" as first implementation deliverable #2 — it
has not been approved yet. With roles as data, approving it later is a seed change. With roles in
a `CHECK` constraint and a Python dict, it was a migration plus a code change plus a redeploy.

**The thirteen actions stay exactly as they are.** PLAN §14 names them — view, comment, edit
Draft, Publish, run, approve, assign, schedule, manage access, export, integrate, administer,
audit — and the `Action` enum already matches. Those are constrained here, because unlike the
role names they *are* in the approved specification.

The rows seeded alongside this migration come from `docs/product/contracts/ACCESS_MODEL.md`,
which is the Gate 0 §0.2 working draft. It is marked "not approved" and the seeded rows carry
that status, so nothing here can be mistaken for a decision that has been made.

Revision: 0004
Parent:   0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: The thirteen from PLAN §14, in the wording the specification uses. Constrained in the database
#: because a role that grants an action nobody defined is a permission bug that looks like a data
#: entry mistake.
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


def upgrade() -> None:
    action_list = ", ".join(f"'{action}'" for action in ACTIONS)

    # ── roles ────────────────────────────────────────────────────────────────────────────
    op.create_table(
        "roles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        #  Stable, machine-readable, never shown to a person. The display name can be renamed or
        #  translated; this cannot, because grants reference it.
        sa.Column("key", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        #  A system role is seeded with the tenant and cannot be deleted — removing the only role
        #  that holds `administer` would leave an organisation nobody can administer. A tenant may
        #  still narrow what a system role grants.
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        #  True until the Gate 0 §0.2 matrix is approved. Read by the interface so a screen can
        #  say the access model is provisional instead of presenting a draft as settled.
        sa.Column(
            "is_draft", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_roles"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_roles_tenant_id_tenants", ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("tenant_id", "key", name="uq_roles_tenant_id_key"),
        sa.CheckConstraint(r"key ~ '^[a-z][a-z0-9_]*$'", name="ck_roles_key_shape"),
    )
    op.create_index("ix_roles_tenant_id", "roles", ["tenant_id"])
    #  Referenced by the composite foreign key below, so that a membership in one tenant cannot
    #  be given a role belonging to another — the same protection 0002 added everywhere else.
    op.create_unique_constraint("uq_roles_tenant_id_id", "roles", ["tenant_id", "id"])

    # ── role_permissions ─────────────────────────────────────────────────────────────────
    op.create_table(
        "role_permissions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=False),
        #  ACCESS_MODEL.md distinguishes `A` (allowed by the role) from `C` (allowed only with an
        #  explicit resource or scope grant). A conditional row grants nothing on its own; the
        #  resource-grant layer decides. Recorded now so the approved matrix can be seeded
        #  faithfully rather than flattened into allow/deny.
        sa.Column(
            "is_conditional", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_role_permissions"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_role_permissions_tenant_id_tenants", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "role_id"],
            ["roles.tenant_id", "roles.id"],
            name="fk_role_permissions_tenant_role",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("role_id", "action", name="uq_role_permissions_role_id_action"),
        sa.CheckConstraint(f"action IN ({action_list})", name="ck_role_permissions_action_known"),
    )
    op.create_index("ix_role_permissions_tenant_id", "role_permissions", ["tenant_id"])
    op.create_index("ix_role_permissions_role_id", "role_permissions", ["role_id"])

    # ── membership_roles points at a role row, not at a string ───────────────────────────
    op.add_column(
        "membership_roles", sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=True)
    )

    #  Existing rows carry one of the six invented names. They are migrated by creating a role of
    #  that key in the tenant, so no membership silently loses its access while the Gate 0 matrix
    #  is still pending. The seeded rows are marked `is_draft`, which is the truth about them.
    #
    #  FORCE is lifted first, and this is the important part to understand before writing any
    #  future data migration:
    #
    #  `FORCE ROW LEVEL SECURITY` binds the table's owner to its own policies, which is exactly
    #  why it is set — it stops a maintenance script run as the owner from quietly reading every
    #  tenant. But a migration has no bound tenant, so those same policies make every tenant-owned
    #  table look empty to it. The first attempt at this migration read zero rows, inserted zero
    #  roles, and then failed on the NOT NULL — a silent no-op that only surfaced two steps later.
    #
    #  Lifting FORCE for the rewrite and restoring it immediately after, inside one transaction,
    #  is the narrow answer. `SET row_security = off` is not: under FORCE it raises an error
    #  rather than granting a bypass. Iterating tenant by tenant would also work and is the right
    #  shape when a migration must respect per-tenant policy; here the rewrite is uniform.
    op.execute("ALTER TABLE membership_roles NO FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        INSERT INTO roles (tenant_id, key, name, description, is_system, is_draft)
        SELECT DISTINCT
            mr.tenant_id,
            mr.role,
            initcap(replace(mr.role, '_', ' ')),
            'Carried over from the pre-Gate-0 implementation. Replace when the approved role '
            || 'matrix (PLAN §25 deliverable 2) is seeded.',
            true,
            true
        FROM membership_roles mr
        ON CONFLICT (tenant_id, key) DO NOTHING;
        """
    )
    op.execute(
        """
        UPDATE membership_roles mr
        SET role_id = r.id
        FROM roles r
        WHERE r.tenant_id = mr.tenant_id AND r.key = mr.role;
        """
    )

    op.execute("ALTER TABLE membership_roles FORCE ROW LEVEL SECURITY;")
    #  Restored inside the same transaction as the lift above, so there is never a committed
    #  moment in which the table is unforced.

    #  Only now can the column be required — every row has a value.
    op.alter_column("membership_roles", "role_id", nullable=False)

    #  Dropped by raw SQL, using the names exactly as PostgreSQL holds them.     #  re-applies the metadata naming convention to whatever it is given, which turns an
    #  already-prefixed name into a doubly-prefixed one that does not exist. Creating with the
    #  convention and dropping without it is the pairing that works.
    op.execute(
        'ALTER TABLE membership_roles DROP CONSTRAINT uq_membership_roles_membership_id_role;'
    )
    op.execute(
        'ALTER TABLE membership_roles '
        'DROP CONSTRAINT ck_membership_roles_ck_membership_roles_role_known;'
    )
    op.drop_column("membership_roles", "role")

    op.create_foreign_key(
        "fk_membership_roles_tenant_role",
        "membership_roles",
        "roles",
        ["tenant_id", "role_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )
    #  RESTRICT, not CASCADE: deleting a role that people still hold would silently remove their
    #  access. The role has to be taken off every membership first, deliberately.
    op.create_unique_constraint(
        "uq_membership_roles_membership_id_role_id", "membership_roles", ["membership_id", "role_id"]
    )
    op.create_index("ix_membership_roles_role_id", "membership_roles", ["role_id"])

    # ── row-level security, same shape as every other tenant-owned table ─────────────────
    for table in ("roles", "role_permissions"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        op.execute(
            f"""
            CREATE POLICY {table}_tenant_isolation ON {table}
                FOR ALL
                USING (tenant_id = app_current_tenant())
                WITH CHECK (tenant_id = app_current_tenant());
            """
        )

    op.execute(
        """
        CREATE TRIGGER roles_set_updated_at
            BEFORE UPDATE ON roles
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )

    #  Roles that were carried over have no permission rows: the six invented names had their
    #  action sets in Python, and copying an invented matrix into the database would preserve
    #  exactly the thing this migration removes. The provisioning command seeds the ACCESS_MODEL
    #  draft; until then a carried-over role grants nothing, and that is visible rather than
    #  hidden.


def downgrade() -> None:
    raise RuntimeError(
        "0004 cannot be downgraded. Reversing it would require re-creating the invented role "
        "names this migration exists to remove, and would drop any role definition seeded since. "
        "To go back, restore from a backup taken before it ran."
    )
