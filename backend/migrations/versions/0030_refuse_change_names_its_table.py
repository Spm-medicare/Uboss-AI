"""`refuse_change()` said `audit_events` whatever table it was defending.

The function is shared. Migration 0001 wrote its message with the table name hard-coded, because
at the time it guarded one table; five tables use it now — `audit_events`, the hierarchy
revisions, the `*_versions` tables and, from 0029, `run_events`. Every one of them refuses a write
with:

    audit_events is append-only: UPDATE on this table is not permitted

...which names a table the caller was not touching. Somebody debugging a refused write on
`run_events` goes and looks at the audit trail.

`TG_TABLE_NAME` is the table the trigger actually fired on, so the message says what happened.
Nothing about the behaviour changes: the same operations are refused with the same error code.

**Replaced rather than dropped and recreated.** `CREATE OR REPLACE FUNCTION` keeps every trigger
that references it; dropping it would need `CASCADE`, which would take the triggers with it and
leave five append-only tables writable until the next statement ran.

Revision: 0030
Parent:   0029
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION refuse_change() RETURNS trigger
            LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION
                '% is append-only: % on this table is not permitted',
                TG_TABLE_NAME, TG_OP
                USING ERRCODE = 'restrict_violation';
        END;
        $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION refuse_change() RETURNS trigger
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
