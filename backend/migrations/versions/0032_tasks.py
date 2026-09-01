"""Tasks — where a run waits for a person, and where §11's To-do list gets its rows.

Gate 7.1 gave the runtime a `waiting` state and nothing to wait *on*: a human step marked the run
waiting and the workflow blocked on a signal nobody could send. This is the other half. A human
step becomes a row somebody can find, act on, and be counted for — and completing it is what sends
that signal.

## One table, three kinds

`kind` is `work`, `input` or `approval`, and those are §11's first three tabs. They are one table
rather than three because they are the same object with the same lifecycle — assigned to somebody,
acted on once, recorded with who and when — and three tables would mean three queries behind one
badge count and three chances for the count to be wrong.

What differs is what "acting on it" means, and that lives in the service, not the schema.
**7.3 adds the approval rules** — a decision with a reason, and the separation of duty Gate 3.3
already established. The `approval` kind exists here so that the tab and the count are one query
from the start rather than a rework.

## Assignment is a snapshot, not a rule

`assignee_membership_id` is written when the task is created, from §8's WHO rules on the version.
The rule is not re-evaluated afterwards. Somebody who leaves a department does not silently lose
the task they were already given — the work is theirs until it is reassigned by a person, and a
reassignment is a decision with an actor rather than a side effect of an org change.

Nullable, because a rule can resolve to nobody. An unassigned task is visible and obviously
unassigned, which is a state somebody can fix; a task quietly assigned to the wrong person is not.

## What is deliberately absent

**No `priority`.** Nothing in §11 asks for one, and a priority nobody sets is a column that sorts
every list by "Normal".

**No `state = 'overdue'`.** Overdue is `due_at < now()` and a state that has to be swept for is a
state that is wrong between sweeps.

Revision: 0032
Parent:   0031
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: §11's first three tabs, as the thing a person is being asked for.
TASK_KINDS = ("work", "input", "approval")

#: `delegated` is its own end state rather than `done`: the task was passed on, not performed, and
#: a report that counted delegations as completions would overstate what got done.
TASK_STATES = ("pending", "in_progress", "done", "declined", "delegated", "cancelled")

#: What somebody did. `approved` and `rejected` belong to the `approval` kind; `completed` and
#: `provided` to the other two. Null while the task is open.
OUTCOMES = ("completed", "provided", "approved", "rejected", "changes_requested")


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", pg.UUID(as_uuid=True), nullable=False),
        #: The step this task is for. A run step has at most one open task; a second would mean
        #: two people each believing the step was theirs.
        sa.Column("run_step_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        #: What the version said to do, copied from the step. A task that pointed back at a
        #: snapshot would be unreadable the day somebody archived it.
        sa.Column("instructions", sa.Text(), nullable=True),
        #: Null when the WHO rules resolved to nobody. Visible and obviously unassigned.
        sa.Column("assignee_membership_id", pg.UUID(as_uuid=True), nullable=True),
        #: Null when the runtime assigned it from a rule; set when a person did.
        sa.Column("assigned_by_membership_id", pg.UUID(as_uuid=True), nullable=True),
        #: How it was decided, in the vocabulary of §8's WHO rules — `user`, `role`,
        #: `hierarchy_position` and so on, or `unresolved`. Recorded so "why me?" has an answer.
        sa.Column("assigned_via", sa.String(30), nullable=False, server_default="unresolved"),
        sa.Column("state", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(30), nullable=True),
        #: What they wrote when they did it — the note, the input, the reason for a rejection.
        sa.Column("outcome_note", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_by_membership_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "kind IN " + str(TASK_KINDS).replace("'", "'"), name="ck_tasks_kind"
        ),
        sa.CheckConstraint(
            "state IN " + str(TASK_STATES).replace("'", "'"), name="ck_tasks_state"
        ),
        sa.CheckConstraint(
            "outcome IS NULL OR outcome IN " + str(OUTCOMES).replace("'", "'"),
            name="ck_tasks_outcome",
        ),
        #: A finished task says who finished it and when. Without this a row can read `done` with
        #: nobody's name on it, which is the one thing an audit asks first.
        sa.CheckConstraint(
            "(state IN ('done', 'declined', 'delegated')) = (completed_at IS NOT NULL)",
            name="ck_tasks_completed_at_matches_state",
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_by_membership_id IS NOT NULL",
            name="ck_tasks_completed_has_actor",
        ),
        #: A rejection says why. `outcome_note` is where the reason lives, and a rejection without
        #: one is a decision nobody can act on.
        sa.CheckConstraint(
            "outcome NOT IN ('rejected', 'changes_requested') "
            "OR (outcome_note IS NOT NULL AND btrim(outcome_note) <> '')",
            name="ck_tasks_refusal_has_reason",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_tasks_tenant_id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["runs.tenant_id", "runs.id"],
            name="fk_tasks_run",
            ondelete="CASCADE",
        ),
    )
    #  One open task per step. A partial index rather than a plain unique: a step retried after a
    #  decline gets a new task, and the closed one stays as evidence.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_tasks_one_open_per_step
        ON tasks (run_step_id)
        WHERE state IN ('pending', 'in_progress')
        """
    )
    #  The To-do list's own query: my open tasks, newest first.
    op.create_index(
        "ix_tasks_assignee_state",
        "tasks",
        ["tenant_id", "assignee_membership_id", "state"],
    )
    op.create_index("ix_tasks_run", "tasks", ["tenant_id", "run_id"])

    # ── following ────────────────────────────────────────────────────────────────────────
    #
    # §11's *Following* tab. Its own table rather than a column, because following is many people
    # per task and because it is a *preference* — a person follows a task, and the task should not
    # have to be rewritten when they stop.
    op.create_table(
        "task_followers",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("membership_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("task_id", "membership_id", name="uq_task_followers_once"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "task_id"],
            ["tasks.tenant_id", "tasks.id"],
            name="fk_task_followers_task",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_task_followers_membership", "task_followers", ["tenant_id", "membership_id"]
    )

    # ── comments ─────────────────────────────────────────────────────────────────────────
    #
    # Append-only. A comment somebody edited after a decision was taken on the strength of it is
    # not a record of the conversation — and this conversation is part of a run's evidence.
    op.create_table(
        "task_comments",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("membership_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("btrim(body) <> ''", name="ck_task_comments_body"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "task_id"],
            ["tasks.tenant_id", "tasks.id"],
            name="fk_task_comments_task",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_task_comments_task", "task_comments", ["task_id", "created_at"])

    # ── evidence ─────────────────────────────────────────────────────────────────────────
    #
    # A join to `files`, not a copy of one. Gate 1's file module already owns scanning, the digest
    # and the short-lived signed URL; a second path to a stored object would be a second path with
    # none of that.
    op.create_table(
        "task_evidence",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("file_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("attached_by_membership_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("task_id", "file_id", name="uq_task_evidence_once"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "task_id"],
            ["tasks.tenant_id", "tasks.id"],
            name="fk_task_evidence_task",
            ondelete="CASCADE",
        ),
        #  RESTRICT into `files`: a file somebody attached as evidence must not vanish because
        #  somebody tidied a folder. Detaching it is a decision.
        sa.ForeignKeyConstraint(
            ["tenant_id", "file_id"],
            ["files.tenant_id", "files.id"],
            name="fk_task_evidence_file",
            ondelete="RESTRICT",
        ),
    )

    # ── row-level security ───────────────────────────────────────────────────────────────
    #
    # `app_current_tenant()`, not the raw `current_setting(...)::uuid` — see migration 0031 for
    # what the difference costs.
    for table in ("tasks", "task_followers", "task_comments", "task_evidence"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_tenant ON {table}
            USING (tenant_id = app_current_tenant())
            WITH CHECK (tenant_id = app_current_tenant())
            """
        )

    op.execute("GRANT SELECT, INSERT, UPDATE ON tasks TO uboss_app")
    #  Following is a preference, so it can be withdrawn.
    op.execute("GRANT SELECT, INSERT, DELETE ON task_followers TO uboss_app")
    op.execute("GRANT SELECT, INSERT ON task_comments TO uboss_app")
    #  Evidence can be detached — which is a decision somebody takes — but not rewritten.
    op.execute("GRANT SELECT, INSERT, DELETE ON task_evidence TO uboss_app")

    op.execute(
        """
        CREATE TRIGGER trg_task_comments_append_only
        BEFORE UPDATE OR DELETE ON task_comments
        FOR EACH ROW EXECUTE FUNCTION refuse_change()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_task_comments_append_only ON task_comments")
    op.drop_table("task_evidence")
    op.drop_table("task_comments")
    op.drop_table("task_followers")
    op.drop_table("tasks")
