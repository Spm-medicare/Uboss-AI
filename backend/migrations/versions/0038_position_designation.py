"""A seat's grade, in the organisation's own words.

`positions.level` is an integer that orders people inside a box, and the UI offered exactly three
bands for it — Executive, Manager, Employee. That is a reasonable default set and it is not what
companies call their grades. An Indian org says *Senior Manager*, *AVP*, *Associate Director*,
*Deputy General Manager*; a hospital says *Consultant* and *Registrar*. Forcing one of three
words on a seat makes the chart describe a company that does not exist.

So `designation` is free text: whatever the organisation calls that grade. `level` stays, and
stays an integer, because ordering needs a number and text cannot be ordered — the two answer
different questions and neither replaces the other:

* **`designation`** is what the badge on the chart says. The customer's vocabulary.
* **`level`** is where the seat sits among its siblings. Derived from the designation when it
  matches one of the three known bands, and null otherwise — an unrecognised grade sorts last
  rather than pretending to a rank nobody gave it.

Nullable, with no default. A seat whose grade nobody recorded has no grade, and the chart draws
the band from `level` as it did before. Nothing existing changes meaning.

Revision: 0038
Parent:   0037
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0038"
down_revision: str | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "positions",
        #: 80 characters: long enough for "Deputy General Manager, Operations" and short enough
        #: that it cannot become a description of the job. The job's name is `title`.
        sa.Column("designation", sa.String(80), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("positions", "designation")
