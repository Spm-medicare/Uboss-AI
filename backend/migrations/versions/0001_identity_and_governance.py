"""Identity, tenancy and the governance record.

The first migration. It creates the tables every later module depends on, and — more
importantly — it creates the second tenant boundary: PostgreSQL row-level security.

Three things here are worth reading before changing anything.

**Policies are written against transaction-local settings, not against the connecting role.**
`app.tenant_id` is set by the API at the start of each transaction. A connection returned to the
pool carries nothing forward, so one request's tenant cannot leak into the next.

**Fail closed is arithmetic, not a convention.** `nullif(current_setting(...), '')::uuid` is NULL
when nothing was bound, and `tenant_id = NULL` is NULL, which is not true, so the row is not
visible. A connection that forgot to bind its tenant sees nothing rather than everything.

**Two tables need a second way in, and each is deliberate.** A session has to be found before its
tenant is known — so its policy also matches on the token hash the caller already holds. A
person's memberships have to be listed before they have picked a workspace — so that policy also
matches on the verified user id. Both alternatives require something already proved. Neither is
a bypass.

Revision: 0001
Parent:   None
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: Every table that carries `tenant_id` and is protected by the plain tenant policy.
TENANT_SCOPED: tuple[str, ...] = (
    "membership_roles",
    "audit_events",
    "outbox_events",
    "idempotency_records",
)


def upgrade() -> None:
    _create_helper_functions()
    _create_tables()
    _enable_row_level_security()
    _create_triggers()


def downgrade() -> None:
    #  Dropping these tables destroys every tenant, every membership and the whole audit trail.
    #  There is no circumstance in which running that automatically is the right answer: an
    #  environment that needs to go back to nothing is recreated, not downgraded.
    raise RuntimeError(
        "0001 cannot be downgraded. It creates the identity and audit tables; reversing it "
        "would erase them. To reset a development database, drop the volume and migrate again."
    )


# ---------------------------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------------------------


def _create_helper_functions() -> None:
    """Read the transaction's bound identity.

    Written once as functions so that thirty policies cannot drift into thirty slightly
    different expressions. `STABLE` (not `IMMUTABLE`) is correct: the value is constant within a
    statement but changes between transactions, and marking it immutable would let the planner
    cache one tenant's value into a plan reused by another.
    """
    op.execute(
        """
        CREATE FUNCTION app_current_tenant() RETURNS uuid
            LANGUAGE sql STABLE
        AS $$
            SELECT nullif(current_setting('app.tenant_id', true), '')::uuid
        $$;
        """
    )
    op.execute(
        """
        CREATE FUNCTION app_current_user() RETURNS uuid
            LANGUAGE sql STABLE
        AS $$
            SELECT nullif(current_setting('app.user_id', true), '')::uuid
        $$;
        """
    )
    op.execute(
        """
        CREATE FUNCTION app_current_session_hash() RETURNS text
            LANGUAGE sql STABLE
        AS $$
            SELECT nullif(current_setting('app.session_token_hash', true), '')
        $$;
        """
    )


# ---------------------------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------------------------


def _create_tables() -> None:
    op.create_table(
        "tenants",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("slug", sa.String(length=63), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("timezone", sa.String(length=64), server_default="Asia/Kolkata", nullable=False),
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_tenants"),
        sa.UniqueConstraint("slug", name="uq_tenants_slug"),
        sa.CheckConstraint(
            "status IN ('active', 'restricted', 'suspended')", name="ck_tenants_status_known"
        ),
        sa.CheckConstraint(
            r"slug ~ '^[a-z0-9]([a-z0-9-]*[a-z0-9])?$'", name="ck_tenants_slug_shape"
        ),
    )

    #  `users` holds credentials and nothing else, and carries no tenant_id — the same person may
    #  belong to several organisations. That is why it has no row-level security: there is no
    #  tenant to compare against. It is safe to leave unprotected precisely because everything
    #  worth stealing (name, title, position, roles) lives on `memberships`, which is protected.
    #  No endpoint returns a row from this table.
    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("last_sign_in_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_sign_in_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.CheckConstraint("status IN ('active', 'deactivated')", name="ck_users_status_known"),
        sa.CheckConstraint("email = lower(email)", name="ck_users_email_lowercase"),
        sa.CheckConstraint("position('@' in email) > 1", name="ck_users_email_shape"),
    )

    op.create_table(
        "memberships",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("job_title", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="invited", nullable=False),
        sa.Column("org_node_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_memberships"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_memberships_tenant_id_tenants", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_memberships_user_id_users", ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_memberships_tenant_id_user_id"),
        sa.CheckConstraint(
            "status IN ('active', 'invited', 'removed')", name="ck_memberships_status_known"
        ),
    )
    op.create_index("ix_memberships_tenant_id", "memberships", ["tenant_id"])
    op.create_index("ix_memberships_org_node_id", "memberships", ["org_node_id"])
    op.create_index("ix_memberships_tenant_id_status", "memberships", ["tenant_id", "status"])
    #  The sign-in path's only cross-tenant query: which organisations is this person in?
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])

    op.create_table(
        "membership_roles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=40), nullable=False),
        sa.Column("granted_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_membership_roles"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_membership_roles_tenant_id_tenants", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["membership_id"],
            ["memberships.id"],
            name="fk_membership_roles_membership_id_memberships",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["granted_by_membership_id"],
            ["memberships.id"],
            name="fk_membership_roles_granted_by_membership_id_memberships",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("membership_id", "role", name="uq_membership_roles_membership_id_role"),
        sa.CheckConstraint(
            "role IN ('viewer', 'contributor', 'builder', 'approver', 'manager', 'admin')",
            name="ck_membership_roles_role_known",
        ),
    )
    op.create_index("ix_membership_roles_tenant_id", "membership_roles", ["tenant_id"])
    op.create_index("ix_membership_roles_membership_id", "membership_roles", ["membership_id"])

    op.create_table(
        "sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("step_up_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.String(length=400), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_sessions"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_sessions_tenant_id_tenants", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_sessions_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["membership_id"],
            ["memberships.id"],
            name="fk_sessions_membership_id_memberships",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("token_hash", name="uq_sessions_token_hash"),
    )
    op.create_index("ix_sessions_tenant_id", "sessions", ["tenant_id"])
    op.create_index("ix_sessions_membership_id", "sessions", ["membership_id"])
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])
    op.create_index("ix_sessions_tenant_id_user_id", "sessions", ["tenant_id", "user_id"])

    op.create_table(
        "audit_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("resource_type", sa.String(length=60), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("actor_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_label", sa.String(length=200), server_default="", nullable=False),
        sa.Column("correlation_id", sa.String(length=64), server_default="", nullable=False),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column("detail", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("denial_reason", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_audit_events"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_audit_events_tenant_id_tenants", ondelete="RESTRICT"
        ),
        sa.CheckConstraint(
            "outcome IN ('succeeded', 'denied', 'failed')", name="ck_audit_events_outcome_known"
        ),
    )
    op.create_index("ix_audit_events_tenant_id", "audit_events", ["tenant_id"])
    op.create_index("ix_audit_events_action", "audit_events", ["action"])
    op.create_index("ix_audit_events_occurred_at", "audit_events", ["occurred_at"])
    op.create_index("ix_audit_events_resource_id", "audit_events", ["resource_id"])
    op.create_index("ix_audit_events_actor_membership_id", "audit_events", ["actor_membership_id"])
    op.create_index(
        "ix_audit_events_tenant_id_resource",
        "audit_events",
        ["tenant_id", "resource_type", "resource_id"],
    )
    op.create_index(
        "ix_audit_events_tenant_id_occurred_at", "audit_events", ["tenant_id", "occurred_at"]
    )

    op.create_table(
        "outbox_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("subject_type", sa.String(length=60), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("payload", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), server_default="", nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_outbox_events"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_outbox_events_tenant_id_tenants", ondelete="RESTRICT"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'published', 'dead')", name="ck_outbox_events_status_known"
        ),
    )
    op.create_index("ix_outbox_events_tenant_id", "outbox_events", ["tenant_id"])
    op.execute(
        """
        CREATE INDEX ix_outbox_events_due
            ON outbox_events (next_attempt_at)
            WHERE status = 'pending';
        """
    )

    op.create_table(
        "idempotency_records",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("key", sa.String(length=200), nullable=False),
        sa.Column("operation", sa.String(length=200), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_body", postgresql.JSONB(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_idempotency_records"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_idempotency_records_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id", "key", "operation", name="uq_idempotency_records_tenant_id_key_operation"
        ),
    )
    op.create_index("ix_idempotency_records_tenant_id", "idempotency_records", ["tenant_id"])
    op.create_index("ix_idempotency_records_expires_at", "idempotency_records", ["expires_at"])


# ---------------------------------------------------------------------------------------------
# Row-level security
# ---------------------------------------------------------------------------------------------


def _enable_row_level_security() -> None:
    """The second tenant boundary.

    `FORCE` matters as much as `ENABLE`. Without it the table's owner is exempt from its own
    policies, and a future maintenance script run as the owner would quietly see every tenant.
    With it, even the owner has to bind a tenant first.
    """
    for table in TENANT_SCOPED:
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
        #  USING governs which rows are visible; WITH CHECK governs which rows may be written.
        #  Both are required: USING alone would let a caller insert a row belonging to another
        #  tenant and simply not be able to read it back.

    # ── tenants ───────────────────────────────────────────────────────────────────────────
    #  A person choosing a workspace has to see the organisations they belong to before any
    #  tenant is bound. The alternative branch requires a verified user id, which is set only
    #  after a password has been checked.
    op.execute("ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;")
    #  `tenants` is the one table that is deliberately NOT forced.
    #
    #  Forcing it would bind the table's owner to its own policies, and since there is no INSERT
    #  policy, nothing could ever create an organisation — not even an operator. Leaving FORCE
    #  off means `uboss_owner`, which runs migrations and the provisioning script and nothing
    #  else, can create one; `uboss_app`, which serves every API request, is still bound by the
    #  policies below and has no INSERT policy at all.
    #
    #  So: the API can never create, delete or reach another organisation. Provisioning is an
    #  operator action, which is what it is.
    op.execute(
        """
        CREATE POLICY tenants_visible_to_members ON tenants
            FOR SELECT
            USING (
                id = app_current_tenant()
                OR (
                    app_current_user() IS NOT NULL
                    AND EXISTS (
                        SELECT 1 FROM memberships m
                        WHERE m.tenant_id = tenants.id
                          AND m.user_id = app_current_user()
                          AND m.status = 'active'
                    )
                )
            );
        """
    )
    #  Writing a tenant row is provisioning, not an ordinary request. It happens through a
    #  deliberate administrative path, so the write policy is restricted to the bound tenant —
    #  there is no branch that lets a caller create or alter an organisation they are not in.
    op.execute(
        """
        CREATE POLICY tenants_write_own ON tenants
            FOR UPDATE
            USING (id = app_current_tenant())
            WITH CHECK (id = app_current_tenant());
        """
    )

    # ── memberships ───────────────────────────────────────────────────────────────────────
    op.execute("ALTER TABLE memberships ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE memberships FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY memberships_read ON memberships
            FOR SELECT
            USING (
                tenant_id = app_current_tenant()
                OR (app_current_user() IS NOT NULL AND user_id = app_current_user())
            );
        """
    )
    #  Reading your own memberships across tenants is how workspace selection works. *Writing*
    #  one is always an action inside a single organisation, so the write policies carry no such
    #  branch — a verified user id gets you a list of your workspaces and nothing more.
    op.execute(
        """
        CREATE POLICY memberships_write ON memberships
            FOR ALL
            USING (tenant_id = app_current_tenant())
            WITH CHECK (tenant_id = app_current_tenant());
        """
    )

    # ── sessions ──────────────────────────────────────────────────────────────────────────
    #  A session must be found before its tenant is known — that lookup is what establishes the
    #  tenant. The policy therefore also matches on the token hash, which the caller can only
    #  supply if they already hold the token. Knowing the hash of a session is equivalent to
    #  holding it, so this reveals nothing that was not already in the caller's possession.
    op.execute("ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE sessions FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY sessions_access ON sessions
            FOR ALL
            USING (
                tenant_id = app_current_tenant()
                OR (
                    app_current_session_hash() IS NOT NULL
                    AND token_hash = app_current_session_hash()
                )
            )
            WITH CHECK (
                tenant_id = app_current_tenant()
                OR (
                    app_current_session_hash() IS NOT NULL
                    AND token_hash = app_current_session_hash()
                )
            );
        """
    )


# ---------------------------------------------------------------------------------------------
# Triggers
# ---------------------------------------------------------------------------------------------


def _create_triggers() -> None:
    """`updated_at` maintenance, and the rule that makes the audit trail append-only."""

    op.execute(
        """
        CREATE FUNCTION set_updated_at() RETURNS trigger
            LANGUAGE plpgsql
        AS $$
        BEGIN
            NEW.updated_at := now();
            RETURN NEW;
        END;
        $$;
        """
    )
    #  Set by the database rather than the application, so a row changed by a migration or a
    #  maintenance script gets the same treatment as one changed through the API.
    for table in ("tenants", "users", "memberships", "membership_roles", "sessions"):
        op.execute(
            f"""
            CREATE TRIGGER {table}_set_updated_at
                BEFORE UPDATE ON {table}
                FOR EACH ROW EXECUTE FUNCTION set_updated_at();
            """
        )

    op.execute(
        """
        CREATE FUNCTION refuse_change() RETURNS trigger
            LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION
                'audit_events is append-only: % on this table is not permitted', TG_OP
                USING ERRCODE = 'restrict_violation';
        END;
        $$;
        """
    )
    #  PLAN §30: "Audit events are append-only from the application's perspective." Enforced in
    #  the database as well, because a trail that the application could rewrite is a trail that
    #  proves nothing. A correction is a new event, never an edit to an old one.
    op.execute(
        """
        CREATE TRIGGER audit_events_append_only
            BEFORE UPDATE OR DELETE ON audit_events
            FOR EACH ROW EXECUTE FUNCTION refuse_change();
        """
    )
