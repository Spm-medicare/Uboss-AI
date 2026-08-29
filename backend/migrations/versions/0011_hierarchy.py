"""The company tree — units, positions, effective-dated assignments, reporting and revisions.

PLAN §5 and §17. Four of the rules it states are enforced here, in the database, rather than in
the service that happens to be in front of it today:

**Cycles are refused by trigger.** §5: *"Detect cycles, orphan managers and duplicate
identifiers."* A department that is its own ancestor makes every scope query non-terminating, and
a reporting loop is an approval that never reaches a human. Gate 2.3 applies an imported tree in
bulk; a check written in Python is a check the bulk path can be written around. A trigger cannot
be.

**A position has one holder at a time.** An exclusion constraint over
`daterange(effective_from, effective_to)` refuses overlapping assignments outright. "Who is the
Regional Manager today" has to have one answer, and two concurrent requests each checking before
writing will both find the seat empty.

**Duplicate identifiers are refused at the point of writing.** `external_ref` is unique per
tenant where present — the customer's own cost centre or HR code. Finding duplicates in a report
afterwards means they are already referenced by something.

**Revision numbers are gapless.** A gap is indistinguishable from a deletion, which is the one
thing a history exists to make impossible. The number is assigned by trigger under an advisory
lock, and the table refuses UPDATE and DELETE like `audit_events` does.

`btree_gist` is required for the exclusion constraints: they need to compare a uuid with `=` and a
range with `&&` in the same index. It has been a trusted extension since PostgreSQL 13, so the
database owner can install it without superuser.

Revision: 0011
Parent:   0010
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UNIT_TYPES: tuple[str, ...] = ("company", "division", "department", "team")
REPORTING_KINDS: tuple[str, ...] = ("primary", "dotted")

TENANT_TABLES: tuple[str, ...] = (
    "org_units",
    "positions",
    "position_assignments",
    "reporting_edges",
    "org_revisions",
)


def _uuid_pk() -> sa.Column[object]:
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        server_default=sa.text("gen_random_uuid()"),
        nullable=False,
    )


def _timestamps() -> list[sa.Column[object]]:
    return [
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
    ]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    unit_types = ", ".join(f"'{value}'" for value in UNIT_TYPES)
    kinds = ", ".join(f"'{value}'" for value in REPORTING_KINDS)

    # ------------------------------------------------------------------ org_units

    op.create_table(
        "org_units",
        _uuid_pk(),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        #  Null for the root. Exactly one per tenant, enforced by a partial unique index below.
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("unit_type", sa.String(length=20), nullable=False),
        #  The customer's own identifier — a cost centre, an HR code.
        sa.Column("external_ref", sa.String(length=120), nullable=True),
        sa.Column("location", sa.String(length=200), nullable=True),
        #  Archived, never deleted. PLAN §30: "Archive without silently erasing audit evidence."
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_org_units"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_org_units_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        #  The composite target every child key below points at, so a row can never reference a
        #  unit belonging to another organisation (the rule migration 0002 established).
        sa.UniqueConstraint("tenant_id", "id", name="uq_org_units_tenant_id"),
        sa.CheckConstraint(f"unit_type IN ({unit_types})", name="ck_org_units_type_known"),
        sa.CheckConstraint("id <> parent_id", name="ck_org_units_not_own_parent"),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_org_units_name_not_blank"),
    )
    op.execute(
        """
        ALTER TABLE org_units
            ADD CONSTRAINT fk_org_units_tenant_parent
            FOREIGN KEY (tenant_id, parent_id)
            REFERENCES org_units (tenant_id, id)
            ON DELETE RESTRICT
        """
    )
    op.create_index("ix_org_units_tenant_id", "org_units", ["tenant_id"])
    op.create_index("ix_org_units_tenant_parent", "org_units", ["tenant_id", "parent_id"])
    op.execute(
        """
        CREATE UNIQUE INDEX uq_org_units_external_ref
            ON org_units (tenant_id, external_ref)
            WHERE external_ref IS NOT NULL;
        """
    )
    #  One root. A tree with two roots is two trees, and every scope query would have to decide
    #  which one it meant.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_org_units_single_root
            ON org_units (tenant_id)
            WHERE parent_id IS NULL;
        """
    )

    # ------------------------------------------------------------------ positions

    op.create_table(
        "positions",
        _uuid_pk(),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_unit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        #  Seniority as the customer counts it, for filtering. Never a permission: what a person
        #  may do comes from roles and grants, not from a number here.
        sa.Column("level", sa.Integer(), nullable=True),
        sa.Column("location", sa.String(length=200), nullable=True),
        sa.Column("external_ref", sa.String(length=120), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_positions"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_positions_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "org_unit_id"],
            ["org_units.tenant_id", "org_units.id"],
            name="fk_positions_tenant_org_unit",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_positions_tenant_id"),
        sa.CheckConstraint("length(btrim(title)) > 0", name="ck_positions_title_not_blank"),
    )
    op.create_index("ix_positions_tenant_id", "positions", ["tenant_id"])
    op.create_index("ix_positions_tenant_unit", "positions", ["tenant_id", "org_unit_id"])
    op.execute(
        """
        CREATE UNIQUE INDEX uq_positions_external_ref
            ON positions (tenant_id, external_ref)
            WHERE external_ref IS NOT NULL;
        """
    )

    # ------------------------------------------------------- position_assignments

    op.create_table(
        "position_assignments",
        _uuid_pk(),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        #  Dates, not timestamps. Somebody starts a job on a day; a moment would be more precise
        #  and less true. `effective_to` is exclusive; null is open-ended.
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_position_assignments"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_assignments_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "position_id"],
            ["positions.tenant_id", "positions.id"],
            name="fk_assignments_tenant_position",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_assignments_tenant_membership",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_assignments_range_ordered",
        ),
    )
    op.create_index("ix_assignments_tenant_id", "position_assignments", ["tenant_id"])
    op.create_index(
        "ix_assignments_tenant_position", "position_assignments", ["tenant_id", "position_id"]
    )
    op.create_index(
        "ix_assignments_tenant_membership",
        "position_assignments",
        ["tenant_id", "membership_id"],
    )
    #  One holder at a time. Two concurrent requests that each check before writing will both
    #  find the seat empty; only the database can refuse the second.
    op.execute(
        """
        ALTER TABLE position_assignments
            ADD CONSTRAINT ex_assignments_one_holder
            EXCLUDE USING gist (
                tenant_id WITH =,
                position_id WITH =,
                daterange(effective_from, effective_to, '[)') WITH &&
            );
        """
    )

    # ----------------------------------------------------------- reporting_edges

    op.create_table(
        "reporting_edges",
        _uuid_pk(),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("manager_position_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_reporting_edges"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_edges_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "position_id"],
            ["positions.tenant_id", "positions.id"],
            name="fk_edges_tenant_position",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "manager_position_id"],
            ["positions.tenant_id", "positions.id"],
            name="fk_edges_tenant_manager",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(f"kind IN ({kinds})", name="ck_edges_kind_known"),
        sa.CheckConstraint("position_id <> manager_position_id", name="ck_edges_not_self_managed"),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_edges_range_ordered",
        ),
    )
    op.create_index("ix_edges_tenant_id", "reporting_edges", ["tenant_id"])
    op.create_index("ix_edges_tenant_position", "reporting_edges", ["tenant_id", "position_id"])
    op.create_index(
        "ix_edges_tenant_manager", "reporting_edges", ["tenant_id", "manager_position_id"]
    )
    #  One primary manager at a time. Dotted lines are unrestricted — that is what they are for.
    op.execute(
        """
        ALTER TABLE reporting_edges
            ADD CONSTRAINT ex_edges_one_primary_manager
            EXCLUDE USING gist (
                tenant_id WITH =,
                position_id WITH =,
                daterange(effective_from, effective_to, '[)') WITH &&
            ) WHERE (kind = 'primary');
        """
    )

    # ------------------------------------------------------------- org_revisions

    op.create_table(
        "org_revisions",
        _uuid_pk(),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        #  Assigned by trigger, gapless per tenant.
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("change_type", sa.String(length=60), nullable=False),
        sa.Column("entity_type", sa.String(length=40), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        #  Enough to render the change and to reverse it. Null `before` means created; null
        #  `after` means archived.
        sa.Column("before", postgresql.JSONB(), nullable=True),
        sa.Column("after", postgresql.JSONB(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("actor_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("reverts_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_org_revisions"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_revisions_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reverts_revision_id"],
            ["org_revisions.id"],
            name="fk_revisions_reverts",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "revision_no", name="uq_revisions_tenant_no"),
    )
    op.execute(
        """
        ALTER TABLE org_revisions
            ADD CONSTRAINT fk_revisions_tenant_actor
            FOREIGN KEY (tenant_id, actor_membership_id)
            REFERENCES memberships (tenant_id, id)
            ON DELETE SET NULL (actor_membership_id)
        """
    )
    op.create_index("ix_org_revisions_tenant_id", "org_revisions", ["tenant_id"])
    op.create_index(
        "ix_revisions_tenant_entity", "org_revisions", ["tenant_id", "entity_type", "entity_id"]
    )

    # ------------------------------------------------------------------- triggers

    #  A unit may not be its own ancestor. Walked up from the new parent; if we arrive back at
    #  the row being written, the write is refused.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION org_units_refuse_cycle() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $$
        DECLARE
            cursor_id uuid := NEW.parent_id;
            hops int := 0;
        BEGIN
            WHILE cursor_id IS NOT NULL LOOP
                IF cursor_id = NEW.id THEN
                    RAISE EXCEPTION
                        'org unit % cannot sit under its own descendant', NEW.id
                        USING ERRCODE = 'check_violation';
                END IF;
                hops := hops + 1;
                --  A depth guard as well as the equality test. If the table already held a loop
                --  from some future bug, the walk above would never end and this trigger would
                --  hang every write to the table.
                IF hops > 100 THEN
                    RAISE EXCEPTION 'org unit hierarchy is deeper than 100 levels'
                        USING ERRCODE = 'check_violation';
                END IF;
                SELECT parent_id INTO cursor_id
                    FROM org_units
                    WHERE id = cursor_id AND tenant_id = NEW.tenant_id;
            END LOOP;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER org_units_refuse_cycle
            BEFORE INSERT OR UPDATE OF parent_id ON org_units
            FOR EACH ROW EXECUTE FUNCTION org_units_refuse_cycle();
        """
    )

    #  The same rule for reporting. Only primary edges are walked: a dotted line is advisory and
    #  is allowed to point anywhere, including back up its own chain.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION reporting_refuse_cycle() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $$
        DECLARE
            cursor_id uuid := NEW.manager_position_id;
            hops int := 0;
        BEGIN
            IF NEW.kind <> 'primary' THEN
                RETURN NEW;
            END IF;

            WHILE cursor_id IS NOT NULL LOOP
                IF cursor_id = NEW.position_id THEN
                    RAISE EXCEPTION
                        'position % would report to itself through the management chain',
                        NEW.position_id
                        USING ERRCODE = 'check_violation';
                END IF;
                hops := hops + 1;
                IF hops > 100 THEN
                    RAISE EXCEPTION 'reporting chain is deeper than 100 levels'
                        USING ERRCODE = 'check_violation';
                END IF;
                --  Only edges that could be in force at the same time as this one. An edge that
                --  ended before this one starts is history, and history cannot be part of a
                --  loop that exists today.
                SELECT manager_position_id INTO cursor_id
                    FROM reporting_edges
                    WHERE tenant_id = NEW.tenant_id
                      AND position_id = cursor_id
                      AND kind = 'primary'
                      AND id <> NEW.id
                      AND daterange(effective_from, effective_to, '[)')
                          && daterange(NEW.effective_from, NEW.effective_to, '[)')
                    LIMIT 1;
            END LOOP;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER reporting_refuse_cycle
            BEFORE INSERT OR UPDATE ON reporting_edges
            FOR EACH ROW EXECUTE FUNCTION reporting_refuse_cycle();
        """
    )

    #  Gapless revision numbers. The advisory lock serialises the read-then-write within the
    #  tenant; without it two concurrent changes read the same maximum and the unique constraint
    #  turns a routine edit into a failure.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION org_revisions_assign_number() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $$
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtextextended(NEW.tenant_id::text, 0));
            SELECT COALESCE(MAX(revision_no), 0) + 1 INTO NEW.revision_no
                FROM org_revisions
                WHERE tenant_id = NEW.tenant_id;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER org_revisions_assign_number
            BEFORE INSERT ON org_revisions
            FOR EACH ROW EXECUTE FUNCTION org_revisions_assign_number();
        """
    )
    #  Append-only, like `audit_events`. A history somebody can edit is not a history.
    op.execute(
        """
        CREATE TRIGGER org_revisions_append_only
            BEFORE UPDATE OR DELETE ON org_revisions
            FOR EACH ROW EXECUTE FUNCTION refuse_change();
        """
    )

    for table in ("org_units", "positions", "position_assignments", "reporting_edges"):
        op.execute(
            f"""
            CREATE TRIGGER {table}_set_updated_at
                BEFORE UPDATE ON {table}
                FOR EACH ROW EXECUTE FUNCTION set_updated_at();
            """
        )

    # ---------------------------------------------------------------------- RLS

    for table in TENANT_TABLES:
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

    #  `org_revisions` is append-only, so the application never needs more than these two. The
    #  trigger would refuse an UPDATE anyway; withholding the privilege means it never gets that
    #  far, and the intent is readable in the grant itself.
    op.execute("REVOKE UPDATE, DELETE ON org_revisions FROM uboss_app;")

    #  `memberships.org_node_id` finally has something to point at. RESTRICT because units are
    #  archived rather than deleted: deleting one people are still placed in should fail loudly.
    op.execute(
        """
        ALTER TABLE memberships
            ADD CONSTRAINT fk_memberships_tenant_org_node
            FOREIGN KEY (tenant_id, org_node_id)
            REFERENCES org_units (tenant_id, id)
            ON DELETE RESTRICT
        """
    )


def downgrade() -> None:
    """Drops the tree. **Everything in it goes with it.**

    Reversing this is not a rollback of a schema detail — it removes the organisation's structure
    and its revision history. It exists so the migration is reversible in development; running it
    against real data needs an export first.
    """
    op.execute("ALTER TABLE memberships DROP CONSTRAINT IF EXISTS fk_memberships_tenant_org_node")
    for table in reversed(TENANT_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    op.execute("DROP FUNCTION IF EXISTS org_units_refuse_cycle()")
    op.execute("DROP FUNCTION IF EXISTS reporting_refuse_cycle()")
    op.execute("DROP FUNCTION IF EXISTS org_revisions_assign_number()")
