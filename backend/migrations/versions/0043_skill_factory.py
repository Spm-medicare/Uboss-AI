"""The Skill Factory — a private skill's tests, and the frozen version approval produces.

Revision ID: 0043
Revises: 0042
Create Date: 2026-09-01

`PLAN.md` §39 fixes the flow, and its last three arrows had nowhere to land:

    … → Reuse | Configure | Compose | Create private Skill Draft
      → Sandbox tests → Human approval → Versioned active Skill

The resolver has reached the *Create* route since 5.2 and says so in as many words — *"Start a
private Skill Draft for the gap"* — with nothing at the other end. `skills` already holds a
tenant's own rows beside the 400 shared ones, with a status, an owner and an approver, and
`skill_rules` already holds their IF-THEN decisions. Two tables were missing.

## `skill_tests`

`docs/product/SKILL_REGISTRY.md` lists six the Factory must collect: *"Golden, negative,
injection, permission, tool-failure and rollback tests."* One row per kind per skill, the same
shape as `agent_tests` from 0021 — deliberately, because the two are the same governance object at
different scales and a second shape would be a second set of rules to keep true.

There is still no sandbox runtime for a skill, so a status is recorded by the person who ran the
test. `run_by_membership_id` and `run_at` are what make that evidence rather than a checkbox, and
the check constraint below refuses a decided result with nothing to show for it. The gate is real
either way.

**Only private skills have tests.** `tenant_id` is `NOT NULL` here, and the composite foreign key
can therefore only reach a tenant's own rows: the catalogue's 400 are shared, read-only, and
tested by whoever maintains the workbook.

## `skill_versions`

*"Published versions are immutable."* The same arrangement as `job_versions`, `agent_versions` and
`supervisor_versions`: an advisory lock in a `BEFORE INSERT` trigger assigns a gapless
`version_no`, `refuse_change()` refuses `UPDATE` and `DELETE`, and the privilege is withheld from
`uboss_app` as well — two independent refusals, one for the change written by mistake and one for
the change written on purpose.

`skills.published_version_id` then names the active version, and a new check makes a published
private skill name one. Without it *"Versioned active Skill"* would be a status rather than a
version, and there would be nothing to point an Agent at that could not later be edited underneath
it.

## The unique constraint added to `skills`

`UNIQUE (tenant_id, id)` — the composite target both new tables need. `skills.tenant_id` is
nullable because the catalogue shares its rows, and a composite foreign key from a child whose
`tenant_id` is `NOT NULL` can only ever match a private skill. That is exactly the reach both of
these should have.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None

#: The six the Factory collects, in the contract's own order.
TEST_KINDS = ("golden", "negative", "injection", "permission", "tool_failure", "rollback")

#: The workbook's own list, shared with `agent_tests`.
TEST_STATUSES = ("not_run", "pass", "fail", "blocked")


def upgrade() -> None:
    #  The composite target. Nothing referenced a skill before this.
    op.create_unique_constraint("uq_skills_tenant_id", "skills", ["tenant_id", "id"])

    # ---------------------------------------------------------------- the six tests
    op.create_table(
        "skill_tests",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("sample_situation", sa.Text(), nullable=True),
        sa.Column("expected_result", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="not_run", nullable=False),
        #: What actually happened. A `fail` with no observation is a claim nobody can act on; a
        #: `pass` with none is a claim nobody can check.
        sa.Column("actual_result", sa.Text(), nullable=True),
        sa.Column("run_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_skill_tests"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_skill_tests_tenant", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "skill_id"],
            ["skills.tenant_id", "skills.id"],
            name="fk_skill_tests_skill",
            ondelete="CASCADE",
        ),
        #  `SET NULL (run_by_membership_id)` — the column is named on purpose. A composite
        #  foreign key with a bare `ON DELETE SET NULL` nulls **every** referencing column,
        #  `tenant_id` included, and a `skill_tests` row with no tenant is a row row-level security
        #  cannot see and the NOT NULL refuses outright. Postgres 15 lets the column be named, and
        #  every other composite key in this schema names it.
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_by_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_skill_tests_runner",
            ondelete="SET NULL (run_by_membership_id)",
        ),
        sa.UniqueConstraint("tenant_id", "skill_id", "kind", name="uq_skill_tests_kind"),
        sa.CheckConstraint(
            "kind IN ('" + "', '".join(TEST_KINDS) + "')", name="ck_skill_tests_kind"
        ),
        sa.CheckConstraint(
            "status IN ('" + "', '".join(TEST_STATUSES) + "')", name="ck_skill_tests_status"
        ),
        #  A decided result carries its evidence. Held here rather than in a service, because the
        #  publish gate reads these rows and a `pass` nobody can check would clear it.
        sa.CheckConstraint(
            "status NOT IN ('pass', 'fail') OR ("
            "actual_result IS NOT NULL AND run_by_membership_id IS NOT NULL "
            "AND run_at IS NOT NULL)",
            name="ck_skill_tests_result_has_evidence",
        ),
    )
    op.create_index("ix_skill_tests_skill", "skill_tests", ["tenant_id", "skill_id"])

    # ---------------------------------------------------------------- the frozen version
    op.create_table(
        "skill_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        #  Assigned by the trigger below, under an advisory lock. Gapless on purpose.
        sa.Column("version_no", sa.Integer(), nullable=False),
        #  The whole skill, frozen: every field, its IF-THEN rules and the six test results as
        #  they stood when it was approved. What a resolver selects is what was approved.
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("published_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("approved_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_skill_versions"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_skill_versions_tenant", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "skill_id"],
            ["skills.tenant_id", "skills.id"],
            name="fk_skill_versions_skill",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "skill_id", "version_no", name="uq_skill_versions_no"),
        #  The composite target `skills.published_version_id` points at.
        sa.UniqueConstraint("tenant_id", "id", name="uq_skill_versions_tenant_id"),
    )
    #  `published_by_membership_id` and `approved_by_membership_id` carry no foreign key, for the
    #  reason 0022 sets out at length: an `ON DELETE SET NULL` into an append-only table makes
    #  anybody who has ever approved anything undeletable, and a right-to-erasure request
    #  impossible to honour. Who approved this version is a fact about the past.

    op.execute(
        """
        CREATE OR REPLACE FUNCTION skill_versions_assign_number() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $$
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtextextended(NEW.skill_id::text, 0));
            SELECT COALESCE(MAX(version_no), 0) + 1 INTO NEW.version_no
                FROM skill_versions
                WHERE skill_id = NEW.skill_id;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER skill_versions_assign_number
            BEFORE INSERT ON skill_versions
            FOR EACH ROW EXECUTE FUNCTION skill_versions_assign_number();
        """
    )
    op.execute(
        """
        CREATE TRIGGER skill_versions_append_only
            BEFORE UPDATE OR DELETE ON skill_versions
            FOR EACH ROW EXECUTE FUNCTION refuse_change();
        """
    )

    # ---------------------------------------------------------------- a third layer
    #
    #  0019 constrained `layer` to the workbook's two — *Universal Department* and *Industry
    #  Overlay* — which are the only two the 400 catalogue rows can be. A private skill is neither:
    #  it belongs to one organisation, and labelling it with a classification from a sheet it did
    #  not come from would be a small lie repeated on every card.
    #
    #  The constraint is replaced rather than widened in place because a `CHECK` cannot be altered.
    #  Dropped by both possible names: 0019 declared it inside `create_table`, where the metadata
    #  naming convention prefixes it a second time, so the database holds
    #  `ck_skills_ck_skills_layer_known`.
    op.execute("ALTER TABLE skills DROP CONSTRAINT IF EXISTS ck_skills_ck_skills_layer_known")
    op.execute("ALTER TABLE skills DROP CONSTRAINT IF EXISTS ck_skills_layer_known")
    op.execute(
        """
        ALTER TABLE skills
            ADD CONSTRAINT ck_skills_layer_known
            CHECK (layer IN ('Universal Department', 'Industry Overlay', 'Workspace'));
        """
    )

    # ---------------------------------------------------------------- who sent it, who decides
    #
    #  `skills` carried an owner and an approver's *signature* — `approved_by_membership_id` and
    #  `approved_at` — but no way to say who a draft was sent **to**, or by whom. Without those two
    #  facts "nobody approves their own work" cannot be checked, and §39's *"No Skill or Agent can
    #  approve/promote itself"* would be a sentence in a document. The same three columns every
    #  other builder in this schema has, for the same three reasons.
    op.add_column(
        "skills",
        sa.Column("approver_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "skills",
        sa.Column("submitted_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column("skills", sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True))
    #  `SET NULL ({column})` and not a bare `SET NULL`. This one cost a test run to find: a bare
    #  clause on a composite key nulls every referencing column, so deleting a person turned their
    #  workspace's private skills into **catalogue rows** — `tenant_id` set to NULL — and
    #  `ck_skills_catalogue_or_private` refused the delete. The offboarding failed, and the reason
    #  named a constraint two tables away. `fk_skills_tenant_owner` in 0019 already named its
    #  column; these two were written without looking at it.
    for column, name in (
        ("approver_membership_id", "fk_skills_tenant_approver"),
        ("submitted_by_membership_id", "fk_skills_tenant_submitter"),
    ):
        op.execute(
            f"""
            ALTER TABLE skills
                ADD CONSTRAINT {name}
                FOREIGN KEY (tenant_id, {column})
                REFERENCES memberships (tenant_id, id)
                ON DELETE SET NULL ({column});
            """
        )
    #  A draft waiting for a decision names the person who sent it. The same constraint the
    #  Objective, the Job and the Agent each carry.
    #  Written as raw DDL rather than through `op.create_check_constraint`, which prefixes the
    #  name from the metadata convention and produces `ck_skills_ck_skills_…` — the doubled name
    #  several older constraints in this schema carry, and the reason a `drop_constraint` with the
    #  obvious name fails. Here the name in the database is the name written here, and the model
    #  declares the same one.
    op.execute(
        """
        ALTER TABLE skills
            ADD CONSTRAINT ck_skills_submitted_has_submitter
            CHECK (tenant_id IS NULL OR status <> 'ready_to_publish' OR
                   (submitted_by_membership_id IS NOT NULL
                    AND approver_membership_id IS NOT NULL));
        """
    )

    # ---------------------------------------------------------------- the pointer
    op.add_column(
        "skills",
        sa.Column("published_version_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute(
        """
        ALTER TABLE skills
            ADD CONSTRAINT fk_skills_published_version
            FOREIGN KEY (tenant_id, published_version_id)
            REFERENCES skill_versions (tenant_id, id)
            ON DELETE RESTRICT;
        """
    )
    #  *"Versioned active Skill"* — a published private skill names the version that was approved.
    #  The catalogue is exempt: its 400 rows are published seed data with no version of their own,
    #  which is what `tenant_id IS NULL` means everywhere else in this schema too.
    op.execute(
        """
        ALTER TABLE skills
            ADD CONSTRAINT ck_skills_published_has_version
            CHECK (tenant_id IS NULL OR status <> 'published'
                   OR published_version_id IS NOT NULL);
        """
    )

    # ---------------------------------------------------------------- isolation
    for table in ("skill_tests", "skill_versions"):
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

    #  Two independent refusals on the frozen version, as everywhere else.
    op.execute("REVOKE UPDATE, DELETE ON skill_versions FROM uboss_app;")


def downgrade() -> None:
    #  Back to the workbook's two. Any private skill on the third layer has to go first — there is
    #  no honest way to reclassify one, and silently relabelling somebody's skill as a catalogue
    #  layer would be worse than refusing the downgrade.
    op.execute(
        "DELETE FROM skill_tests WHERE skill_id IN "
        "(SELECT id FROM skills WHERE layer = 'Workspace')"
    )
    op.execute("UPDATE skills SET published_version_id = NULL WHERE layer = 'Workspace'")
    op.execute(
        "DELETE FROM skill_versions WHERE skill_id IN "
        "(SELECT id FROM skills WHERE layer = 'Workspace')"
    )
    op.execute(
        "DELETE FROM skill_rules WHERE skill_id IN "
        "(SELECT id FROM skills WHERE layer = 'Workspace')"
    )
    op.execute("DELETE FROM skills WHERE layer = 'Workspace'")
    op.execute("ALTER TABLE skills DROP CONSTRAINT IF EXISTS ck_skills_layer_known")
    op.execute(
        """
        ALTER TABLE skills
            ADD CONSTRAINT ck_skills_layer_known
            CHECK (layer IN ('Universal Department', 'Industry Overlay'));
        """
    )

    op.execute("ALTER TABLE skills DROP CONSTRAINT IF EXISTS ck_skills_submitted_has_submitter")
    op.execute("ALTER TABLE skills DROP CONSTRAINT IF EXISTS fk_skills_tenant_approver")
    op.execute("ALTER TABLE skills DROP CONSTRAINT IF EXISTS fk_skills_tenant_submitter")
    #  `IF EXISTS` because a downgrade has to work from a half-applied state as well as a whole
    #  one — which this migration proved while it was being written, when an earlier revision of it
    #  failed partway and left the version table at 0043 with three of its columns missing.
    for column in ("submitted_at", "submitted_by_membership_id", "approver_membership_id"):
        op.execute(f"ALTER TABLE skills DROP COLUMN IF EXISTS {column}")

    op.execute("ALTER TABLE skills DROP CONSTRAINT IF EXISTS ck_skills_published_has_version")
    op.execute("ALTER TABLE skills DROP CONSTRAINT IF EXISTS fk_skills_published_version")
    op.execute("ALTER TABLE skills DROP COLUMN IF EXISTS published_version_id")

    op.execute("DROP TRIGGER IF EXISTS skill_versions_append_only ON skill_versions")
    op.execute("DROP TRIGGER IF EXISTS skill_versions_assign_number ON skill_versions")
    op.execute("DROP TABLE IF EXISTS skill_versions")
    op.execute("DROP FUNCTION IF EXISTS skill_versions_assign_number()")

    op.execute("DROP TABLE IF EXISTS skill_tests")

    op.execute("ALTER TABLE skills DROP CONSTRAINT IF EXISTS uq_skills_tenant_id")
