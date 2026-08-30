"""§10 group 10 — failure simulation, and the immutable version a Supervisor publishes to.

`PLAN.md` states Gate 6's exit itself, so this is not a reading:

> Exit: failure simulation and forbidden-action tests pass.

Two different things, and they live in different places. **Failure simulation** is per Supervisor:
scenarios a team writes down, and a publish gate that refuses while any of them has not passed.
**Forbidden-action** is repository-wide — §10's *"Claude cannot bypass policy, grant permission,
perform uncontrolled retries or approve high-risk actions"* — and its home is
`tests/integration/test_supervisor_forbidden_actions.py`, one test per prohibition.

## Why the simulations are not a printed list

The Agent's Form 4 prints five named tests, so `agent_tests` has a closed `kind`. §10 prints none
for the Supervisor — it says *"sandbox/failure simulation"* and stops. So a scenario here is named
by whoever writes it, and the gate is *"at least one, and every one passes"* rather than *"all
five of a set"*. Inventing five named failures would have been inventing the plan's missing half.

## The same three rules as everywhere else here

**A result belongs to a design.** Editing the Supervisor clears every observed result: a pass
recorded against yesterday's dependencies says nothing about today's.

**There is no runtime.** Gate 7 brings execution, so a status is recorded by the person who ran
the scenario, and `run_by_membership_id` and `run_at` are what make that evidence rather than a
checkbox. The gate is real either way.

**The version is immutable and its numbers are gapless.** Trigger *and* withheld privilege, and an
advisory lock assigns `version_no` — version 3 with no version 2 would be a published thing nobody
can account for. Its `published_by_membership_id` and `approved_by_membership_id` carry **no
foreign key**, the choice `audit_events` already makes and the one `job_versions` had to be
corrected to in 0022: an `ON DELETE SET NULL` into an append-only table makes anybody who ever
approved something undeletable.

Revision: 0025
Parent:   0024
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The same four the Agent's sandbox tests use — the approved workbook's "Test Status" list. One
#: vocabulary across the product, so a person who has read one screen knows what the words mean on
#: the next.
STATUSES: tuple[str, ...] = ("not_run", "pass", "fail", "blocked")


def upgrade() -> None:
    statuses = ", ".join(f"'{value}'" for value in STATUSES)

    # ---------------------------------------------------------------- the simulations
    op.create_table(
        "supervisor_simulations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("supervisor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        #  What goes wrong. Free text, because §10 prints no list of failures the way Form 4
        #  prints five tests — a closed set here would be failures somebody invented.
        sa.Column("what_fails", sa.Text(), nullable=False),
        #  What the Supervisor is supposed to do about it. This is the thing being tested.
        sa.Column("expected_response", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="not_run", nullable=False),
        #  What actually happened. Required for any status but `not_run`: a `Fail` with no
        #  observation is a claim nobody can act on, and a `Pass` with none is one nobody can
        #  check.
        sa.Column("observed", sa.Text(), nullable=True),
        sa.Column("run_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name="pk_supervisor_simulations"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_sup_sim_tenant", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "supervisor_id"],
            ["supervisors.tenant_id", "supervisors.id"],
            name="fk_sup_sim_supervisor",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("tenant_id", "supervisor_id", "name", name="uq_sup_sim_name"),
        sa.CheckConstraint(f"status IN ({statuses})", name="ck_sup_sim_status_known"),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_sup_sim_name_not_blank"),
        sa.CheckConstraint(
            "length(btrim(what_fails)) > 0", name="ck_sup_sim_what_fails_not_blank"
        ),
        sa.CheckConstraint(
            "length(btrim(expected_response)) > 0", name="ck_sup_sim_expected_not_blank"
        ),
        sa.CheckConstraint(
            "status = 'not_run' OR (run_by_membership_id IS NOT NULL AND run_at IS NOT NULL)",
            name="ck_sup_sim_result_has_a_runner",
        ),
        sa.CheckConstraint(
            "status = 'not_run' OR length(btrim(coalesce(observed, ''))) > 0",
            name="ck_sup_sim_result_was_observed",
        ),
        sa.CheckConstraint("position >= 1", name="ck_sup_sim_position"),
    )
    op.execute(
        """
        ALTER TABLE supervisor_simulations
            ADD CONSTRAINT fk_sup_sim_runner
            FOREIGN KEY (tenant_id, run_by_membership_id)
            REFERENCES memberships (tenant_id, id)
            ON DELETE SET NULL (run_by_membership_id);
        """
    )

    # ---------------------------------------------------------------- the frozen version
    op.create_table(
        "supervisor_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("supervisor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        #  The whole design, frozen: both scopes with the handler roles as they stood, the
        #  schedule, the dependencies, the quality gates, the budgets, the escalations, the
        #  notifications and the simulation results. What ran is what was approved.
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        #  No foreign key on either. See the module docstring — an `ON DELETE SET NULL` into an
        #  append-only table makes anybody who ever approved something undeletable.
        sa.Column("published_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("approved_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_supervisor_versions"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_sup_versions_tenant", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "supervisor_id"],
            ["supervisors.tenant_id", "supervisors.id"],
            name="fk_sup_versions_supervisor",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id", "supervisor_id", "version_no", name="uq_sup_versions_no"
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_sup_versions_tenant_id"),
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION supervisor_versions_assign_number() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $$
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtextextended(NEW.supervisor_id::text, 0));
            SELECT COALESCE(MAX(version_no), 0) + 1 INTO NEW.version_no
                FROM supervisor_versions
                WHERE supervisor_id = NEW.supervisor_id;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER supervisor_versions_assign_number
            BEFORE INSERT ON supervisor_versions
            FOR EACH ROW EXECUTE FUNCTION supervisor_versions_assign_number();
        """
    )
    op.execute(
        """
        CREATE TRIGGER supervisor_versions_append_only
            BEFORE UPDATE OR DELETE ON supervisor_versions
            FOR EACH ROW EXECUTE FUNCTION refuse_change();
        """
    )

    # ---------------------------------------------------------------- the pointer
    op.add_column(
        "supervisors",
        sa.Column("published_version_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute(
        """
        ALTER TABLE supervisors
            ADD CONSTRAINT fk_supervisors_published_version
            FOREIGN KEY (tenant_id, published_version_id)
            REFERENCES supervisor_versions (tenant_id, id)
            ON DELETE RESTRICT;
        """
    )
    #  A Supervisor in a running state runs something.
    op.create_check_constraint(
        "ck_supervisors_running_has_version",
        "supervisors",
        "status NOT IN ('published', 'active', 'paused') OR published_version_id IS NOT NULL",
    )

    for table in ("supervisor_simulations", "supervisor_versions"):
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

    op.execute("REVOKE UPDATE, DELETE ON supervisor_versions FROM uboss_app;")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE supervisors DROP CONSTRAINT IF EXISTS ck_supervisors_running_has_version"
    )
    op.execute(
        "ALTER TABLE supervisors DROP CONSTRAINT IF EXISTS fk_supervisors_published_version"
    )
    op.drop_column("supervisors", "published_version_id")
    op.execute("DROP TABLE IF EXISTS supervisor_versions CASCADE")
    op.execute("DROP TABLE IF EXISTS supervisor_simulations CASCADE")
    op.execute("DROP FUNCTION IF EXISTS supervisor_versions_assign_number()")
