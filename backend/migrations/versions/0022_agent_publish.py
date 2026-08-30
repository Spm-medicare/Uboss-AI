"""Form 4 section C, and the immutable version an Agent publishes to.

`PLAN.md` §9 ends its list with *"Sandbox tests, expected results and publishing"* and states the
rule this migration exists to make enforceable:

> Tests and permission review are publish gates.

**Section C of the approved form, exactly.** Five printed tests — normal case, missing input,
conflicting input, prohibited action, system failure — each with a *Sample Situation*, an
*Expected Result* and a *Status* from the sheet's own list: `Not Run`, `Pass`, `Fail`, `Blocked`.
A closed set, because the sheet prints all five: a missing one is not a value outside a list, it
is a test nobody thought about.

**A result belongs to a design.** `agent_tests` results are cleared whenever the Agent is saved.
A pass recorded against yesterday's steps says nothing about today's, and deciding which edits
"do not count" is exactly the judgement that lets a stale pass through. It costs somebody
re-recording five results after a typo fix, and that is the right side to err on.

**There is no sandbox runtime yet.** Gate 7 brings execution. Until then a status is recorded by
the person who ran the test, and `run_by_membership_id` and `run_at` are what make that a piece of
evidence rather than a checkbox. The gate is real either way: an Agent with a `Fail`, a `Blocked`
or a `Not Run` cannot publish.

**The version is immutable and its numbers are gapless.** Same shape as `job_versions`: an
advisory lock in a BEFORE INSERT trigger assigns `version_no`, `UPDATE` and `DELETE` are refused
by a trigger, and the privileges are withheld from `uboss_app` as well. Version 3 existing with no
version 2 would mean a published thing nobody can account for.

Revision: 0022
Parent:   0021
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Form 4 section C's five printed tests, in the sheet's order.
TEST_KINDS: tuple[str, ...] = (
    "normal_case",
    "missing_input",
    "conflicting_input",
    "prohibited_action",
    "system_failure",
)

#: The workbook's "Test Status" list, exactly: Not Run, Pass, Fail, Blocked.
TEST_STATUSES: tuple[str, ...] = ("not_run", "pass", "fail", "blocked")


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    kinds = _quoted(TEST_KINDS)
    statuses = _quoted(TEST_STATUSES)

    # ---------------------------------------------------------------- section C
    op.create_table(
        "agent_tests",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("sample_situation", sa.Text(), nullable=True),
        sa.Column("expected_result", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="not_run", nullable=False),
        #  What actually happened. Required when the status is anything but `not_run`: a `Fail`
        #  with no observation is a claim nobody can act on, and a `Pass` with none is a claim
        #  nobody can check.
        sa.Column("actual_result", sa.Text(), nullable=True),
        sa.Column("run_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("run_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name="pk_agent_tests"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_agent_tests_tenant", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "agent_id"],
            ["agents.tenant_id", "agents.id"],
            name="fk_agent_tests_agent",
            ondelete="CASCADE",
        ),
        #  One row per printed test. Two "normal case" rows would be two answers to one question.
        sa.UniqueConstraint("tenant_id", "agent_id", "kind", name="uq_agent_tests_kind"),
        sa.CheckConstraint(f"kind IN ({kinds})", name="ck_agent_tests_kind_known"),
        sa.CheckConstraint(f"status IN ({statuses})", name="ck_agent_tests_status_known"),
        sa.CheckConstraint(
            "status = 'not_run' OR (run_by_membership_id IS NOT NULL AND run_at IS NOT NULL)",
            name="ck_agent_tests_result_has_a_runner",
        ),
        sa.CheckConstraint(
            "status = 'not_run' OR length(btrim(coalesce(actual_result, ''))) > 0",
            name="ck_agent_tests_result_was_observed",
        ),
    )
    op.execute(
        """
        ALTER TABLE agent_tests
            ADD CONSTRAINT fk_agent_tests_runner
            FOREIGN KEY (tenant_id, run_by_membership_id)
            REFERENCES memberships (tenant_id, id)
            ON DELETE SET NULL (run_by_membership_id);
        """
    )

    # ---------------------------------------------------------------- the frozen version
    op.create_table(
        "agent_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        #  Assigned by the trigger below, under an advisory lock. Gapless on purpose.
        sa.Column("version_no", sa.Integer(), nullable=False),
        #  The whole design, frozen: header, steps, escalation rules, I/O schemas, knowledge,
        #  tools with their grants, skills with the decisions that chose them, and the five test
        #  results as they stood. What ran is what was approved, and this is the proof of it.
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        #  The Job version this Agent was approved to run. Recorded here as well as on the Agent,
        #  because the Agent can later be pointed at a newer one and this row must still say what
        #  *this* version was approved against.
        sa.Column("job_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("published_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("approved_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_agent_versions"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_agent_versions_tenant", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "agent_id"],
            ["agents.tenant_id", "agents.id"],
            name="fk_agent_versions_agent",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "agent_id", "version_no", name="uq_agent_versions_no"),
        #  The composite target the Agent's `published_version_id` points at.
        sa.UniqueConstraint("tenant_id", "id", name="uq_agent_versions_tenant_id"),
    )
    #  `published_by_membership_id` and `approved_by_membership_id` carry **no foreign key**, and
    #  that is deliberate — it is what `audit_events.actor_membership_id` already does, for the
    #  same reason.
    #
    #  An `ON DELETE SET NULL` on an append-only table is a contradiction: removing a person makes
    #  Postgres try to rewrite the row, the trigger refuses, and the deletion fails. The effect is
    #  that anybody who has ever approved anything becomes undeletable — an offboarding blocked by
    #  a foreign key, and a right-to-erasure request that cannot be honoured. `RESTRICT` would
    #  block it outright, which is the same failure said more plainly.
    #
    #  So the id is kept as a historical reference and nothing cascades to it. Who approved this
    #  version is a fact about the past; a person leaving does not change it.

    op.execute(
        """
        CREATE OR REPLACE FUNCTION agent_versions_assign_number() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $$
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtextextended(NEW.agent_id::text, 0));
            SELECT COALESCE(MAX(version_no), 0) + 1 INTO NEW.version_no
                FROM agent_versions
                WHERE agent_id = NEW.agent_id;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER agent_versions_assign_number
            BEFORE INSERT ON agent_versions
            FOR EACH ROW EXECUTE FUNCTION agent_versions_assign_number();
        """
    )
    op.execute(
        """
        CREATE TRIGGER agent_versions_append_only
            BEFORE UPDATE OR DELETE ON agent_versions
            FOR EACH ROW EXECUTE FUNCTION refuse_change();
        """
    )

    # ---------------------------------------------------------------- the pointer
    op.add_column(
        "agents",
        sa.Column("published_version_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute(
        """
        ALTER TABLE agents
            ADD CONSTRAINT fk_agents_published_version
            FOREIGN KEY (tenant_id, published_version_id)
            REFERENCES agent_versions (tenant_id, id)
            ON DELETE RESTRICT;
        """
    )
    #  An Agent in a running state runs *something*. Added here rather than in 0021 because the
    #  table it points at did not exist yet.
    op.create_check_constraint(
        "ck_agents_running_has_published_version",
        "agents",
        "status NOT IN ('published', 'active', 'paused') OR published_version_id IS NOT NULL",
    )

    for table in ("agent_tests", "agent_versions"):
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

    #  Two independent refusals on the frozen version, as everywhere else: the trigger stops a
    #  change written by mistake, the withheld privilege stops one written on purpose.
    op.execute("REVOKE UPDATE, DELETE ON agent_versions FROM uboss_app;")

    #  The same defect, already shipped on `job_versions` in 0016 and found while building its
    #  sibling: an `ON DELETE SET NULL` pointing into an append-only table. A person who has ever
    #  approved a Job cannot currently be deleted, because Postgres tries to null the column and
    #  the append-only trigger refuses. Corrected here rather than reported, because dropping a
    #  foreign key loses no data and leaving a known offboarding block in place is worse than
    #  touching a shipped table.
    op.execute(
        "ALTER TABLE job_versions DROP CONSTRAINT IF EXISTS fk_job_versions_tenant_publisher"
    )
    op.execute(
        "ALTER TABLE job_versions DROP CONSTRAINT IF EXISTS fk_job_versions_tenant_approver"
    )


def downgrade() -> None:
    #  Dropped first so the downgrade is repeatable: a run that failed part-way must not leave a
    #  second attempt refusing with "constraint already exists".
    op.execute(
        "ALTER TABLE job_versions DROP CONSTRAINT IF EXISTS fk_job_versions_tenant_publisher"
    )
    op.execute(
        "ALTER TABLE job_versions DROP CONSTRAINT IF EXISTS fk_job_versions_tenant_approver"
    )
    op.execute(
        """
        ALTER TABLE job_versions
            ADD CONSTRAINT fk_job_versions_tenant_publisher
            FOREIGN KEY (tenant_id, published_by_membership_id)
            REFERENCES memberships (tenant_id, id)
            ON DELETE SET NULL (published_by_membership_id);
        """
    )
    op.execute(
        """
        ALTER TABLE job_versions
            ADD CONSTRAINT fk_job_versions_tenant_approver
            FOREIGN KEY (tenant_id, approved_by_membership_id)
            REFERENCES memberships (tenant_id, id)
            ON DELETE SET NULL (approved_by_membership_id);
        """
    )
    op.execute("ALTER TABLE agents DROP CONSTRAINT IF EXISTS ck_agents_running_has_published_version")
    op.execute("ALTER TABLE agents DROP CONSTRAINT IF EXISTS fk_agents_published_version")
    op.drop_column("agents", "published_version_id")
    op.execute("DROP TABLE IF EXISTS agent_versions CASCADE")
    op.execute("DROP TABLE IF EXISTS agent_tests CASCADE")
    op.execute("DROP FUNCTION IF EXISTS agent_versions_assign_number()")
