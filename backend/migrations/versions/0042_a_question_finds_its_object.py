"""Full-text search over the objects the Copilot answers from.

Revision ID: 0042
Revises: 0041
Create Date: 2026-09-01

Gate 7.7 needs retrieval that a *question* can reach. The first version matched the whole question
as one `ILIKE '%…%'` needle, which finds an object only when somebody types its words verbatim —
so *"quotation turnaround"* worked and *"why is the quotation turnaround slow?"* returned nothing.
A test asking the second kind of question is what found it.

The fix is the pattern this codebase already uses for the skill registry (0019): a **generated
stored `tsvector`** and a GIN index, queried with `websearch_to_tsquery` and ordered by
`ts_rank_cd`. Three reasons it is that and not a cleverer `ILIKE`:

* **Ranking is real.** Widening a sentence to *any* of its words is the only way a question matches
  anything, and a wide net is only useful if the densest matches come first. `ts_rank_cd` is
  Postgres computing that. The alternative — a relevance number assembled from match counts — is
  a number this product would be inventing, and `retrieval.py` says so in its own header.
* **Stemming.** *"reduce"* finds *"reduction"*, which is most of what a person means by search.
* **Generated, not maintained.** A trigger or an application-side update is a second place the
  index can fall behind the row. `GENERATED ALWAYS AS … STORED` cannot.

## Weights

`A` is the name or title — the field somebody searches by. `B` is the purpose or the expected
result: what the object is for, in a sentence. `C` is the longer prose. The weights matter because
`ts_rank_cd` uses them, and a match on a Job's name should outrank the same word buried in its
retry policy.

## What is deliberately not searched

Every text column on these tables would be a wider net and a worse one. The searched fields are the
ones `retrieval.py` returns as a source snippet — so what the Copilot can find is exactly what it
can then quote, and there is no field it can match on but not show.
"""

from __future__ import annotations

from alembic import op

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None

#: One entry per table: the column, and the weight it carries.
#:
#: Kept as data rather than six blocks of SQL so a missing weight or a mistyped column name is
#: visible at a glance. The generated expression below is assembled from it.
SEARCHED: dict[str, list[tuple[str, str]]] = {
    "objectives": [
        ("title", "A"),
        ("expected_result", "B"),
        ("description", "C"),
        ("department", "D"),
    ],
    "jobs": [
        ("name", "A"),
        ("purpose", "B"),
        ("high_level_work", "C"),
        ("department", "D"),
    ],
    "agents": [("name", "A"), ("purpose", "B"), ("instructions", "C")],
    "supervisors": [("name", "A"), ("purpose", "B"), ("routing_policy", "C")],
    "org_units": [("name", "A"), ("unit_type", "C"), ("location", "D")],
    "positions": [("title", "A"), ("designation", "B"), ("location", "D")],
}


def _expression(columns: list[tuple[str, str]]) -> str:
    return " ||\n                ".join(
        f"setweight(to_tsvector('english', coalesce({column}, '')), '{weight}')"
        for column, weight in columns
    )


def upgrade() -> None:
    for table, columns in SEARCHED.items():
        op.execute(
            f"""
            ALTER TABLE {table}
                ADD COLUMN search tsvector
                GENERATED ALWAYS AS (
                {_expression(columns)}
                ) STORED;
            """
        )
        op.execute(f"CREATE INDEX ix_{table}_search ON {table} USING gin (search);")


def downgrade() -> None:
    #  Dropping the column takes its index with it. Safe in both directions: nothing reads `search`
    #  except retrieval, and no row's own data lives in it — it is derived from columns that stay.
    for table in SEARCHED:
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS search;")
