"""An assignment made today could not be ended today.

0011 wrote, on both dated tables:

    effective_to IS NULL OR effective_to > effective_from

and `effective_to` is **exclusive** — `_effective_on` reads `effective_to > :as_at`. Put those
together and a row created today cannot be closed today: `effective_to = today` is refused by the
constraint, and `effective_to = tomorrow` still shows the person in the seat *today*, because
tomorrow is greater than today.

So "I have just put the wrong person in this seat, take them out" had no answer. The UI raised
*"An assignment cannot end before it started"* — a true sentence about a rule that should not have
applied. Found by driving the screen, not by reading it.

`>=` allows a zero-length range, and that is a real state rather than a loophole: **recorded and
corrected on the same day.** The row stays, which is the point — they were assigned, somebody
undid it, and both facts are in the history. It simply covers no date, so no chart shows them in
the seat.

The same argument covers reporting edges: a line drawn and corrected within the day is the same
mistake, and its row is the same evidence.

Nothing widens. An `effective_to` *before* `effective_from` is still refused, which is the
condition the constraint exists for — a range that runs backwards is a data error, and a range of
zero days is a correction.

Revision: 0039
Parent:   0038
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0039"
down_revision: str | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    ("position_assignments", "ck_assignments_range_ordered"),
    ("reporting_edges", "ck_edges_range_ordered"),
)


def upgrade() -> None:
    for table, constraint in TABLES:
        op.drop_constraint(constraint, table, type_="check")
        op.create_check_constraint(
            constraint,
            table,
            "effective_to IS NULL OR effective_to >= effective_from",
        )


def downgrade() -> None:
    #  Rows that now legitimately have `effective_to = effective_from` would break the old
    #  constraint, so they are closed a day later on the way down rather than the migration
    #  failing. A day is the smallest change that satisfies the stricter rule, and the state it
    #  produces — held for one day — is the closest true statement available under it.
    for table, constraint in TABLES:
        op.execute(
            f"UPDATE {table} SET effective_to = effective_from + 1 "  # noqa: S608
            "WHERE effective_to = effective_from"
        )
        op.drop_constraint(constraint, table, type_="check")
        op.create_check_constraint(
            constraint,
            table,
            "effective_to IS NULL OR effective_to > effective_from",
        )
