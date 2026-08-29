"""${message}

Revision: ${up_revision}
Parent:   ${down_revision | comma,n}
Created:  ${create_date}

Write down here *why* this change is being made, and what happens to existing rows. A migration
that only says what it does leaves the next person guessing whether it was safe.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: str | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    #  A downgrade that destroys data is not a downgrade. If the reverse of this change would
    #  lose rows, raise here and write the recovery procedure in the runbook instead.
    ${downgrades if downgrades else "pass"}
