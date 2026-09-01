"""A firing outlives its run, so it cannot hold a foreign key to one.

0034 pointed `schedule_firings.(tenant_id, run_id)` at `runs` with `ON DELETE SET NULL`, meaning
"a run may be cleaned up one day, and the record that the schedule fired must outlive it". Two
things were wrong with that, and the second only appeared once a run was actually deleted.

**A bare `SET NULL` on a composite key nulls every referencing column** — `tenant_id` included,
and that one is `NOT NULL`. So `DELETE FROM runs` failed with a not-null violation on a table
three joins away from the statement.

**And `SET NULL (run_id)` does not fix it either.** `ck_schedule_firings_started_has_run` says a
`started` firing has a run and a non-`started` one does not. Nulling `run_id` under a row that
still reads `started` breaks exactly that constraint. The two rules contradict each other: one
says the link may disappear, the other says a started firing always has it.

The contradiction is resolved by deciding what a firing *is*. It is **evidence** — the record that
this schedule reached this occurrence and started run 47. If run 47 is later removed, "run 47 was
started and has since been removed" is the truth; a null is the loss of it. So the id stays as a
plain value and the foreign key goes. Nothing else changes: `tenant_id` still keys the row to its
workspace, row-level security still applies, and the schedule's own cascade still removes firings
with the schedule.

This is the same reasoning `tasks` decides the other way, and the difference is worth stating. A
task has no meaning without its run — it *is* a step of one — so it cascades. A firing is a
statement about the past, and the past does not stop having happened when a row is removed.

Revision: 0036
Parent:   0035
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE schedule_firings DROP CONSTRAINT fk_schedule_firings_run"
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE schedule_firings
        ADD CONSTRAINT fk_schedule_firings_run
        FOREIGN KEY (tenant_id, run_id) REFERENCES runs (tenant_id, id)
        ON DELETE SET NULL
        """
    )
