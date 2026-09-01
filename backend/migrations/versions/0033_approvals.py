"""Approvals — the decision, kept apart from the task that carries it.

§17 lists `approvals` as a runtime table in its own right, beside `tasks`, and the reason becomes
obvious the moment you try to answer an auditor's questions from `tasks` alone. A task records
*what somebody did*: it was assigned, it was acted on, here is the outcome. An approval has to
record *who asked, who was entitled to decide, by when, and what happened if nobody did* — four
facts that have no column on a task and no business acquiring one, because they are meaningless
for the other two kinds.

## One approval, one task

`UNIQUE (task_id)` — an approval is the decision belonging to exactly one approval task. Declining
an approval task closes it and 7.2 creates a replacement; the replacement gets its own approval
row, and the closed one stays as evidence of who was asked first.

## Separation of duty is enforced twice, on purpose

`ck_approvals_not_self` refuses a row whose decider is its requester. `guard.refuse_self_approval`
already refuses it in the service, with a sentence a person can read. Neither substitutes for the
other: the service is what somebody sees, and the constraint is what holds when a row is written
by a script, a migration, or a route somebody adds next year without reading this file.

This is the same doubling `CLAUDE.md` requires of authorization and RLS, applied to the one rule
whose failure is indistinguishable from success in the data: an approval that was never really a
second pair of eyes looks exactly like one that was.

## Escalation is recorded, not routed

A Job carries `escalation_to` as **free text** — `String(200)`, a label somebody typed, not a
membership id. So `escalation_note` is copied here as text and `escalated_to_membership_id` is set
only when a person actually escalates to somebody nameable. Nothing here fires on a deadline:
`due_at` is stored and read, and the sweep that acts on it belongs with 7.4's scheduler and 7.5's
notifications. A column that implied an automatic escalation nothing performs would be worse than
no column.

## What is deliberately absent

**No `approval_events`.** Every transition writes an `AuditEvent` with the actor, the object and
the reason, which is the trail an audit actually reads. A second, parallel history is a second
history to keep true.

**No `delegated_approver`.** Delegation is the task's, and it already produces a new task — which
produces a new approval, with the new person named as its approver. An approval that quietly
changed hands without a new row would lose who was asked first.

Revision: 0033
Parent:   0032
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: `withdrawn` is what happens when the work it was asked about went away — the run was cancelled,
#: or the task was declined and replaced. Distinct from `rejected`: nobody said no, the question
#: stopped being asked.
STATES = ("pending", "approved", "rejected", "changes_requested", "withdrawn")

#: The states in which a decision has been made. Kept as a tuple so the check constraint and the
#: model read the same list rather than two copies that drift.
DECIDED = ("approved", "rejected", "changes_requested")

#: Refusals. Each one must carry a reason — a rejection nobody explained is a decision nobody can
#: act on, and "changes requested" without the changes is worse than silence.
REFUSALS = ("rejected", "changes_requested")


def upgrade() -> None:
    op.create_table(
        "approvals",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("run_step_id", pg.UUID(as_uuid=True), nullable=False),
        #: The approval task this decision belongs to. `CASCADE`, because an approval with no task
        #: is a question with nothing to answer it.
        sa.Column("task_id", pg.UUID(as_uuid=True), nullable=False),
        #: Who set the work going and is therefore asking. Not null: an approval nobody requested
        #: has no separation of duty to enforce, and that is exactly the row this table exists to
        #: make impossible.
        sa.Column("requested_by_membership_id", pg.UUID(as_uuid=True), nullable=False),
        #: Who was entitled to decide, resolved when the approval was raised. Nullable, because
        #: §8's WHO rules can match nobody — and an approval visibly waiting on nobody is a state
        #: somebody can fix, unlike one quietly addressed to the wrong person.
        sa.Column("approver_membership_id", pg.UUID(as_uuid=True), nullable=True),
        #: What the Job's author wrote in §9's Approval column, frozen with the version. The
        #: question being asked, in their words.
        sa.Column("question", sa.Text(), nullable=True),
        sa.Column("state", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("decided_by_membership_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        #: Escalation. The note is free text because the Job's `escalation_to` is; the membership
        #: is set only when a person escalates to somebody nameable.
        sa.Column("escalation_note", sa.String(200), nullable=True),
        sa.Column("escalated_to_membership_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("state IN " + str(STATES), name="ck_approvals_state"),
        #: A decided approval says who decided and when. Without this a row can read `approved`
        #: with nobody's name on it, which is the first thing an audit asks.
        sa.CheckConstraint(
            f"(state IN {DECIDED}) = (decided_at IS NOT NULL)",
            name="ck_approvals_decided_at_matches_state",
        ),
        sa.CheckConstraint(
            "decided_at IS NULL OR decided_by_membership_id IS NOT NULL",
            name="ck_approvals_decision_has_actor",
        ),
        sa.CheckConstraint(
            f"state NOT IN {REFUSALS} OR (reason IS NOT NULL AND btrim(reason) <> '')",
            name="ck_approvals_refusal_has_reason",
        ),
        #: **Separation of duty, in the database.** The author of the work cannot be the person
        #: who approved it. The service refuses this first, with a sentence; this is what holds
        #: when the row is written by something that never called the service.
        sa.CheckConstraint(
            "decided_by_membership_id IS NULL "
            "OR decided_by_membership_id <> requested_by_membership_id",
            name="ck_approvals_not_self",
        ),
        sa.CheckConstraint(
            "escalated_at IS NULL OR "
            "(escalated_to_membership_id IS NOT NULL OR escalation_note IS NOT NULL)",
            name="ck_approvals_escalation_names_somebody",
        ),
        #: One approval per task. A second row would be a second decision on one question, and
        #: whichever the screen read first would win.
        sa.UniqueConstraint("task_id", name="uq_approvals_one_per_task"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_approvals_tenant_id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "task_id"],
            ["tasks.tenant_id", "tasks.id"],
            name="fk_approvals_task",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["runs.tenant_id", "runs.id"],
            name="fk_approvals_run",
            ondelete="CASCADE",
        ),
    )
    #  The Approvals tab's own query: what is waiting on me.
    op.create_index(
        "ix_approvals_approver_state",
        "approvals",
        ["tenant_id", "approver_membership_id", "state"],
    )
    op.create_index("ix_approvals_run", "approvals", ["tenant_id", "run_id"])

    op.execute("ALTER TABLE approvals ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE approvals FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY approvals_tenant ON approvals
        USING (tenant_id = app_current_tenant())
        WITH CHECK (tenant_id = app_current_tenant())
        """
    )
    #  No DELETE. An approval is evidence of a decision — or of a question nobody answered, which
    #  is evidence of a different kind. `withdrawn` is how one stops mattering.
    op.execute("GRANT SELECT, INSERT, UPDATE ON approvals TO uboss_app")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS approvals_tenant ON approvals")
    op.drop_index("ix_approvals_run", table_name="approvals")
    op.drop_index("ix_approvals_approver_state", table_name="approvals")
    op.drop_table("approvals")
