"""Who submitted an objective for approval, and when.

PLAN §6's journey ends *"Publish summary → Authorized approval → Immutable Published
version/card"*, and §14 separates the author from the approver. Separation needs a name to compare
against: without recording who submitted, "you cannot approve your own work" has nothing to check.

Two columns rather than an approvals table. A general approval queue arrives in Gate 7 with the
runtime, where approvals of runs, outputs and changes all live together; putting a one-row table
here now would be a second thing to migrate into it later.

Revision: 0015
Parent:   0014
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "objectives",
        sa.Column("submitted_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "objectives", sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute(
        """
        ALTER TABLE objectives
            ADD CONSTRAINT fk_objectives_tenant_submitter
            FOREIGN KEY (tenant_id, submitted_by_membership_id)
            REFERENCES memberships (tenant_id, id)
            ON DELETE SET NULL (submitted_by_membership_id)
        """
    )
    #  An objective waiting for approval must name who sent it there. Without this the separation
    #  check has nothing to compare against, and would pass by default — failing open, which is
    #  the one way a governance rule must never fail.
    op.create_check_constraint(
        "ck_objectives_submitted_has_submitter",
        "objectives",
        "status <> 'ready_to_publish' OR submitted_by_membership_id IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_objectives_submitted_has_submitter", "objectives", type_="check")
    op.execute("ALTER TABLE objectives DROP CONSTRAINT IF EXISTS fk_objectives_tenant_submitter")
    op.drop_column("objectives", "submitted_at")
    op.drop_column("objectives", "submitted_by_membership_id")
