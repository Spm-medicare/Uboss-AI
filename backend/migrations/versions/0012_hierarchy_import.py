"""Staged hierarchy import — the file, the mapping, and every row before any of it is applied.

PLAN §5 sets out seven steps and one rule. The rule is the reason this table exists:

    Claude never writes the live hierarchy directly.

So an upload lands **here**, not in `org_units`. Every row is parsed, mapped, validated and shown
to a person, and only a deliberate, separate act moves it across — atomically, in one transaction
that either produces the whole tree or none of it. A half-applied org chart is worse than a failed
one: nobody can tell which half is real.

**`hierarchy_imports` is the run.** It carries the file it came from, the column mapping actually
used, who proposed each part of that mapping, and where the import got to. The mapping is stored
rather than recomputed, because "why did this row become a department" has to be answerable a
month later — and §5 requires the applied import to record its source and mapping.

**`hierarchy_import_rows` is the staging area.** One row per spreadsheet row, holding the raw
cells as they arrived and what they were understood to mean, plus the errors and warnings found.
Keeping the raw cells is what makes a re-map possible without asking for the file again.

`status` never goes backwards from `applied`. Once rows are live, the staging copy is evidence,
not a draft.

Revision: 0012
Parent:   0011
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Where an import has got to. Forward only.
#
#  `parsed` and `mapped` are separate because a person reviews the mapping between them — that
#  review is PLAN §5 step 4, and collapsing the two states would make it invisible.
IMPORT_STATUSES: tuple[str, ...] = (
    "uploaded",
    "parsed",
    "mapped",
    "validated",
    "applied",
    "failed",
    "abandoned",
)

#: What a staged row was understood to be.
ROW_KINDS: tuple[str, ...] = ("org_unit", "position", "assignment", "ignored")

#: How a column's meaning was decided. Recorded per import so the audit answers "who chose this".
MAPPING_SOURCES: tuple[str, ...] = ("exact", "proposed", "chosen")


def upgrade() -> None:
    statuses = ", ".join(f"'{value}'" for value in IMPORT_STATUSES)
    kinds = ", ".join(f"'{value}'" for value in ROW_KINDS)

    #  `files` predates the composite-key rule and was never a target of one, so it has no
    #  `(tenant_id, id)` to point at. Added here rather than left out: without it the import's
    #  key can only reference `files.id`, and a row could then name a file belonging to another
    #  organisation. Row-level security would hide that file — but the reference would exist, and
    #  a dangling cross-tenant reference is the kind of thing that is only ever found later.
    op.create_unique_constraint("uq_files_tenant_id", "files", ["tenant_id", "id"])

    op.create_table(
        "hierarchy_imports",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        #  The uploaded file. Kept `pending` in `files` for its whole life: an import source is
        #  never served back to a browser, so it never needs to leave quarantine.
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="uploaded"),
        #  Which sheet was read. Null for CSV, which has exactly one.
        sa.Column("sheet_name", sa.String(length=200), nullable=True),
        #  The header row exactly as it arrived, so a re-map never needs the file again.
        sa.Column("source_columns", postgresql.JSONB(), nullable=False),
        #  `{"Cost centre": {"field": "external_ref", "source": "exact"}}`. The applied mapping,
        #  stored rather than recomputed — §5 requires an applied import to record its mapping.
        sa.Column("column_mapping", postgresql.JSONB(), nullable=False, server_default="{}"),
        #  Columns deliberately not used. Shown to the person reviewing (§5 step 4) so "we
        #  ignored six columns" is a stated fact rather than something they discover later.
        sa.Column("ignored_columns", postgresql.JSONB(), nullable=False, server_default="[]"),
        #  What the model was asked and what it proposed, for the columns nothing matched. Null
        #  when every column matched exactly and no model was called — which is the common case
        #  and worth being able to prove.
        sa.Column("proposal", postgresql.JSONB(), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("warning_count", sa.Integer(), nullable=False, server_default="0"),
        #  Set when the rows were moved into the live tree, with the revision that records it.
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        #  Why it failed, in the words a person is shown. Null unless `status = 'failed'`.
        sa.Column("failure_detail", sa.Text(), nullable=True),
        sa.Column("created_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name="pk_hierarchy_imports"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_imports_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "file_id"],
            ["files.tenant_id", "files.id"],
            name="fk_imports_tenant_file",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["applied_revision_id"],
            ["org_revisions.id"],
            name="fk_imports_revision",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_imports_tenant_id"),
        sa.CheckConstraint(f"status IN ({statuses})", name="ck_imports_status_known"),
        #  An applied import must say when and under which revision. Without this a row could
        #  claim to be applied with no evidence, which is exactly the claim nobody could check.
        sa.CheckConstraint(
            "(status <> 'applied') OR "
            "(applied_at IS NOT NULL AND applied_revision_id IS NOT NULL)",
            name="ck_imports_applied_has_evidence",
        ),
        sa.CheckConstraint(
            "(status <> 'failed') OR (failure_detail IS NOT NULL)",
            name="ck_imports_failure_has_reason",
        ),
    )
    op.execute(
        """
        ALTER TABLE hierarchy_imports
            ADD CONSTRAINT fk_imports_tenant_creator
            FOREIGN KEY (tenant_id, created_by_membership_id)
            REFERENCES memberships (tenant_id, id)
            ON DELETE SET NULL (created_by_membership_id)
        """
    )
    op.create_index("ix_hierarchy_imports_tenant_id", "hierarchy_imports", ["tenant_id"])
    op.create_index(
        "ix_imports_tenant_status", "hierarchy_imports", ["tenant_id", "status"]
    )

    op.create_table(
        "hierarchy_import_rows",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("import_id", postgresql.UUID(as_uuid=True), nullable=False),
        #  1-based, as the spreadsheet numbers them, so an error message names the row the person
        #  can actually see. Zero-based here would mean every message was off by one.
        sa.Column("row_number", sa.Integer(), nullable=False),
        #  The cells exactly as they arrived, keyed by source column. Keeping them is what makes
        #  a re-map possible without asking for the file again.
        sa.Column("raw", postgresql.JSONB(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False, server_default="org_unit"),
        #  What the row was understood to mean, after mapping: `{"name": "Operations", ...}`.
        sa.Column("parsed", postgresql.JSONB(), nullable=False, server_default="{}"),
        #  Problems that stop this row being applied. An import with any of these cannot proceed.
        sa.Column("errors", postgresql.JSONB(), nullable=False, server_default="[]"),
        #  Things worth saying that do not stop it — a blank location, an unknown level.
        sa.Column("warnings", postgresql.JSONB(), nullable=False, server_default="[]"),
        #  Filled when the row is applied, so the staging copy points at what it became.
        sa.Column("applied_entity_id", postgresql.UUID(as_uuid=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name="pk_hierarchy_import_rows"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_import_rows_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        #  CASCADE here and nowhere else in this schema. A staged row has no meaning without its
        #  import: abandoning an import should take its scratch rows with it, and they are not
        #  evidence of anything until `applied_at` is set — at which point the import itself is
        #  RESTRICT and cannot be deleted.
        sa.ForeignKeyConstraint(
            ["tenant_id", "import_id"],
            ["hierarchy_imports.tenant_id", "hierarchy_imports.id"],
            name="fk_import_rows_tenant_import",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "tenant_id", "import_id", "row_number", name="uq_import_rows_number"
        ),
        sa.CheckConstraint(f"kind IN ({kinds})", name="ck_import_rows_kind_known"),
        sa.CheckConstraint("row_number >= 1", name="ck_import_rows_number_positive"),
    )
    op.create_index("ix_hierarchy_import_rows_tenant_id", "hierarchy_import_rows", ["tenant_id"])
    op.create_index(
        "ix_import_rows_import", "hierarchy_import_rows", ["tenant_id", "import_id", "row_number"]
    )
    #  The reviewer's first question is always "what is wrong with it".
    op.execute(
        """
        CREATE INDEX ix_import_rows_with_errors
            ON hierarchy_import_rows (tenant_id, import_id)
            WHERE errors <> '[]'::jsonb;
        """
    )

    for table in ("hierarchy_imports", "hierarchy_import_rows"):
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
        op.execute(
            f"""
            CREATE TRIGGER {table}_set_updated_at
                BEFORE UPDATE ON {table}
                FOR EACH ROW EXECUTE FUNCTION set_updated_at();
            """
        )

    #  Matching a spreadsheet's email column to a person needs `users`, and `uboss_app` cannot
    #  read that table — migration 0006 took the privilege away, and the reason has not changed:
    #  the password hashes are in there.
    #
    #  So the question is answered by a function instead, and only this question: **is there an
    #  active member of the caller's own tenant with this address, and what is their membership
    #  id.** No name, no address back, no credential column, nothing about any other tenant. The
    #  tenant is taken from the transaction's bound value rather than from an argument, so a
    #  caller cannot ask about an organisation they are not in.
    #
    #  This is narrower than it looks: within one workspace, who is a member is not a secret —
    #  colleagues can see each other. What stays secret is everything `users` actually holds.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION directory_membership_for_email(p_email text)
        RETURNS uuid
        LANGUAGE sql
        SECURITY DEFINER
        STABLE
        SET search_path = pg_catalog, public
        AS $$
            SELECT m.id
            FROM memberships m
            JOIN users u ON u.id = m.user_id
            WHERE m.tenant_id = app_current_tenant()
              AND m.status = 'active'
              AND u.email = lower(btrim(p_email))
            LIMIT 1;
        $$;
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION directory_membership_for_email(text) FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION directory_membership_for_email(text) TO uboss_app"
    )

    #  An applied import is the record of how part of the tree came to exist. It may be
    #  abandoned before it is applied, and not after.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION imports_refuse_unapply() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $$
        BEGIN
            IF OLD.status = 'applied' AND NEW.status <> 'applied' THEN
                RAISE EXCEPTION
                    'an applied import cannot be moved back to %', NEW.status
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER imports_refuse_unapply
            BEFORE UPDATE OF status ON hierarchy_imports
            FOR EACH ROW EXECUTE FUNCTION imports_refuse_unapply();
        """
    )


def downgrade() -> None:
    """Drops the staging tables. The live hierarchy they fed is untouched.

    That asymmetry is the point of staging: what was applied is `org_units` and `positions`, and
    those are real rows with their own history. Losing the import record loses the provenance —
    which is a real loss, and not the same as losing the tree.
    """
    op.execute("DROP TABLE IF EXISTS hierarchy_import_rows CASCADE")
    op.execute("DROP TABLE IF EXISTS hierarchy_imports CASCADE")
    op.execute("DROP FUNCTION IF EXISTS imports_refuse_unapply()")
    op.execute("ALTER TABLE files DROP CONSTRAINT IF EXISTS uq_files_tenant_id")
    op.execute("DROP FUNCTION IF EXISTS directory_membership_for_email(text)")
