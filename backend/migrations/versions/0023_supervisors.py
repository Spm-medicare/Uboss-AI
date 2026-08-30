"""The Supervisor, and the two scopes `PLAN.md` §10 makes mandatory.

§10 opens by saying what a Supervisor is *not*: it *"monitors and coordinates published Job
Agents"*. CLAUDE.md puts the boundary in one line — **Supervisor coordinates; bounded Job/Synced
workers perform business actions.** Nothing in this schema performs work.

## The two scopes, and why they are two tables

> Two independent scopes are mandatory:
> 1. Supervised members/Agents: whose Agents are monitored?
> 2. Allowed handlers: who may control this Supervisor?

Separate questions, separate answers, and the whole gate turns on their staying separate. A
department head may control a Supervisor watching Agents whose outputs they may not read; somebody
may have their Agents supervised without any say over the Supervisor at all. **Nothing here derives
one scope from the other** — no foreign key, no shared column, no trigger that copies a row from
one to the other. A design that let one imply the other would collapse both into "the manager sees
everything", which is the thing an Org Node hierarchy exists to prevent.

## Two kinds, and the third is deliberately absent

§10 names three and approves two: *"Workspace-wide Supervisor is restricted and may be added
later."* `kind` therefore has two values. Adding a third now would be building against a decision
nobody has taken.

**A personal Supervisor supervises its owner's Agents and nobody else's.** §10: *"logically
isolated per eligible account; supervises that user's permitted Job Agents."* Enforced by a trigger
rather than by a service, because it is the isolation the word "personal" means and a second write
path must not be able to get around it.

**A department Supervisor's handlers are explicit rows.** The plan's decision table settles it:
*"Department Supervisor handlers | Explicit selected people; no automatic department-wide
control."* There is no rule anywhere in this schema that reads a department and produces a handler.

Revision: 0023
Parent:   0022
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: §10's two approved kinds. Workspace-wide is *"restricted and may be added later"*, so it is not
#: here — a third value now would be building against a decision nobody has taken.
KINDS: tuple[str, ...] = ("personal", "department")

#: §10's six handler roles, in the order the plan lists them — which is also increasing authority,
#: and 6.2 depends on that order being real.
HANDLER_ROLES: tuple[str, ...] = (
    "viewer",
    "operator",
    "reviewer",
    "approver",
    "manager",
    "owner",
)

#: The same lifecycle as every other designed object here.
STATUSES: tuple[str, ...] = (
    "draft",
    "needs_review",
    "ready_to_publish",
    "published",
    "active",
    "paused",
    "archived",
)


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    kinds = _quoted(KINDS)
    roles = _quoted(HANDLER_ROLES)
    statuses = _quoted(STATUSES)

    # ---------------------------------------------------------------- the supervisor
    op.create_table(
        "supervisors",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        #  Group 1: identity, owner, department and the linked Objective scope.
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        #  Required. A Supervisor with no owner is one nobody is answerable for, and a personal
        #  Supervisor's whole scope is defined by whose it is.
        sa.Column("owner_membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        #  The department it supervises. Required for a department Supervisor and forbidden for a
        #  personal one — the check below says so rather than leaving it to a service.
        sa.Column("org_node_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("objective_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("purpose", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="draft", nullable=False),
        sa.Column("submitted_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_supervisors"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_supervisors_tenant", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "org_node_id"],
            ["org_units.tenant_id", "org_units.id"],
            name="fk_supervisors_org_node",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "objective_id"],
            ["objectives.tenant_id", "objectives.id"],
            name="fk_supervisors_objective",
            ondelete="SET NULL (objective_id)",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_supervisors_tenant_id"),
        sa.CheckConstraint(f"kind IN ({kinds})", name="ck_supervisors_kind_known"),
        sa.CheckConstraint(f"status IN ({statuses})", name="ck_supervisors_status_known"),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_supervisors_name_not_blank"),
        #  A department Supervisor names a department; a personal one does not have one to name.
        sa.CheckConstraint(
            "(kind = 'department' AND org_node_id IS NOT NULL) OR "
            "(kind = 'personal' AND org_node_id IS NULL)",
            name="ck_supervisors_department_has_a_node",
        ),
        sa.CheckConstraint(
            "status <> 'ready_to_publish' OR submitted_by_membership_id IS NOT NULL",
            name="ck_supervisors_submitted_has_submitter",
        ),
    )
    #  The owner FK is added separately: `ON DELETE SET NULL` is impossible on a NOT NULL column,
    #  and RESTRICT is the honest alternative — removing somebody who owns a Supervisor should
    #  make you reassign it first, which is a decision rather than a cascade.
    op.execute(
        """
        ALTER TABLE supervisors
            ADD CONSTRAINT fk_supervisors_owner
            FOREIGN KEY (tenant_id, owner_membership_id)
            REFERENCES memberships (tenant_id, id)
            ON DELETE RESTRICT;
        """
    )
    for column, constraint in (
        ("submitted_by_membership_id", "fk_supervisors_submitter"),
        ("created_by_membership_id", "fk_supervisors_creator"),
    ):
        op.execute(
            f"""
            ALTER TABLE supervisors
                ADD CONSTRAINT {constraint}
                FOREIGN KEY (tenant_id, {column})
                REFERENCES memberships (tenant_id, id)
                ON DELETE SET NULL ({column});
            """
        )
    op.create_index("ix_supervisors_tenant_status", "supervisors", ["tenant_id", "status"])
    op.create_index(
        "ix_supervisors_tenant_owner", "supervisors", ["tenant_id", "owner_membership_id"]
    )

    # ---------------------------------------------------------------- scope 1: supervised
    op.create_table(
        "supervisor_supervised",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("supervisor_id", postgresql.UUID(as_uuid=True), nullable=False),
        #  Whose Agents. §10 says *"selected users/Agents"*, so a row names a person and may
        #  narrow to one of their Agents.
        sa.Column("membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        #  Null means every Agent that person owns, now and later. Set means this one only.
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        #  §10 group 2: *"Supervised members and Agent versions."* Pinning a version means the
        #  Supervisor watches what was approved rather than whatever the draft became.
        sa.Column("agent_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_supervisor_supervised"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_supervised_tenant", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "supervisor_id"],
            ["supervisors.tenant_id", "supervisors.id"],
            name="fk_supervised_supervisor",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_supervised_membership",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "agent_id"],
            ["agents.tenant_id", "agents.id"],
            name="fk_supervised_agent",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "agent_version_id"],
            ["agent_versions.tenant_id", "agent_versions.id"],
            name="fk_supervised_agent_version",
            ondelete="RESTRICT",
        ),
        #  One row per person-and-Agent. Two would be two answers to one question.
        sa.UniqueConstraint(
            "tenant_id", "supervisor_id", "membership_id", "agent_id", name="uq_supervised_pair"
        ),
        #  A pinned version without an Agent is a version of nothing in particular.
        sa.CheckConstraint(
            "agent_version_id IS NULL OR agent_id IS NOT NULL",
            name="ck_supervised_version_needs_an_agent",
        ),
        sa.CheckConstraint("position >= 1", name="ck_supervised_position_positive"),
    )

    # ---------------------------------------------------------------- scope 2: handlers
    op.create_table(
        "supervisor_handlers",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("supervisor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        #  One of §10's six. A ceiling for this Supervisor, never a grant of anything the person
        #  does not already hold in the workspace — 6.2 is where that becomes enforcement.
        sa.Column("role", sa.String(length=20), nullable=False),
        #  Who added them, and when. A handler nobody can be shown to have granted is a handler
        #  nobody can be asked about.
        sa.Column("granted_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_supervisor_handlers"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_handlers_tenant", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "supervisor_id"],
            ["supervisors.tenant_id", "supervisors.id"],
            name="fk_handlers_supervisor",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_handlers_membership",
            ondelete="CASCADE",
        ),
        #  One role per person per Supervisor. Two rows would be two ceilings, and nothing in the
        #  design says which wins.
        sa.UniqueConstraint(
            "tenant_id", "supervisor_id", "membership_id", name="uq_handlers_membership"
        ),
        sa.CheckConstraint(f"role IN ({roles})", name="ck_handlers_role_known"),
    )
    op.execute(
        """
        ALTER TABLE supervisor_handlers
            ADD CONSTRAINT fk_handlers_grantor
            FOREIGN KEY (tenant_id, granted_by_membership_id)
            REFERENCES memberships (tenant_id, id)
            ON DELETE SET NULL (granted_by_membership_id);
        """
    )

    #  ------------------------------------------------------------- personal means personal
    #
    #  §10: a personal Supervisor *"supervises that user's permitted Job Agents"*. Held by a
    #  trigger rather than by a service, because it is what the word "personal" means and a
    #  second write path — an import, a fixture, a future bulk route — must not be able to get
    #  around it. The check runs on the supervised row, which is where the mistake would be made.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION supervised_matches_kind() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $$
        DECLARE
            supervisor_kind text;
            supervisor_owner uuid;
        BEGIN
            SELECT kind, owner_membership_id
              INTO supervisor_kind, supervisor_owner
              FROM supervisors
             WHERE id = NEW.supervisor_id;

            IF supervisor_kind = 'personal' AND NEW.membership_id <> supervisor_owner THEN
                RAISE EXCEPTION
                    'a personal supervisor supervises only its owner''s agents';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER supervised_matches_kind
            BEFORE INSERT OR UPDATE ON supervisor_supervised
            FOR EACH ROW EXECUTE FUNCTION supervised_matches_kind();
        """
    )

    for table in ("supervisors", "supervisor_supervised", "supervisor_handlers"):
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(
            f"""
            CREATE POLICY {table}_tenant_isolation ON {table}
                FOR ALL
                USING (tenant_id = app_current_tenant())
                WITH CHECK (tenant_id = app_current_tenant());
            """
        )
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO uboss_app;")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS supervisor_handlers CASCADE")
    op.execute("DROP TABLE IF EXISTS supervisor_supervised CASCADE")
    op.execute("DROP TABLE IF EXISTS supervisors CASCADE")
    op.execute("DROP FUNCTION IF EXISTS supervised_matches_kind()")
