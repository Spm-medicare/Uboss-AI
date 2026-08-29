"""Composite foreign keys must null only the reference, not the tenant.

**The bug.** Three composite foreign keys point at `memberships (tenant_id, id)` with
`ON DELETE SET NULL`. PostgreSQL's plain `SET NULL` nulls **every column in the key** — including
`tenant_id`, which is `NOT NULL` on all three tables.

So deleting a membership that had ever uploaded a file, granted a role, or shared a resource
would fail:

    null value in column "tenant_id" of relation "files" violates not-null constraint

Which means removing a person from an organisation was impossible as soon as they had done
anything. The intent was always "forget who did it, keep the row" — a file whose uploader has
left is still that organisation's file.

Found by the test suite, in `two_workspaces`' teardown: deleting the fixture's membership failed
before the test could finish cleaning up. It would have surfaced in production the first time
somebody left a company.

**The fix.** PostgreSQL 15 added column-specific `SET NULL`, so the action can name exactly the
column it should clear:

    ON DELETE SET NULL (uploaded_by_membership_id)

`tenant_id` is untouched, which is correct: the row still belongs to the organisation it always
belonged to.

Revision: 0010
Parent:   0009
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: (table, constraint, the column that should be cleared)
AFFECTED: tuple[tuple[str, str, str], ...] = (
    ("files", "fk_files_tenant_uploader", "uploaded_by_membership_id"),
    (
        "membership_roles",
        "fk_membership_roles_tenant_grantor",
        "granted_by_membership_id",
    ),
    ("resource_grants", "fk_resource_grants_tenant_grantor", "granted_by_membership_id"),
)


def upgrade() -> None:
    for table, constraint, column in AFFECTED:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT {constraint}")
        op.execute(
            f"""
            ALTER TABLE {table}
                ADD CONSTRAINT {constraint}
                FOREIGN KEY (tenant_id, {column})
                REFERENCES memberships (tenant_id, id)
                ON DELETE SET NULL ({column})
            """
        )
        #  The composite key stays — that is what stops a row referencing a membership in
        #  another organisation (migration 0002). Only the delete action changes.


def downgrade() -> None:
    """Restores the broken form, and it is broken.

    Reversing this reinstates a schema in which removing a person who has uploaded a file fails.
    Provided for completeness; there is no reason to run it.
    """
    for table, constraint, column in AFFECTED:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT {constraint}")
        op.execute(
            f"""
            ALTER TABLE {table}
                ADD CONSTRAINT {constraint}
                FOREIGN KEY (tenant_id, {column})
                REFERENCES memberships (tenant_id, id)
                ON DELETE SET NULL
            """
        )
