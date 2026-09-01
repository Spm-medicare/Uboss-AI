"""Notifications — §12's six categories, and the two rules that stop a bell being noise.

The shell has had a bell and a right-hand drawer since AS.5, showing a governed empty state
because nothing real could fill it. `WORK_BREAKDOWN.md` was explicit about the alternative:
*"Notifications and Copilot show governed empty states. No fake activity, no invented counts."*
This is what makes the count real.

## Deduplication is a constraint, not a cleanup job

§12 asks for *"grouping and deduplication"*, and the honest way to implement dedup is to make the
duplicate impossible rather than to sweep for it afterwards. `uq_notifications_unread_dedupe` is a
**partial** unique index on `(membership_id, dedupe_key)` where the row is unread: the same
unresolved fact cannot sit in somebody's bell twice.

A repeat is then an UPDATE, not an INSERT — `occurrences` goes up and `last_at` moves. So five
failures of one schedule overnight are one line saying *"failed 5 times, last at 04:00"*, which is
the thing a person can act on. Five identical lines is the shape people mute.

**Once it is read, the constraint stops applying**, and that is deliberate. Something happening
again *after* you have seen it is genuinely new information; suppressing it would mean an
acknowledged problem could recur silently forever.

## `group_key` is not `dedupe_key`

They answer different questions and collapsing them loses one of the answers.

* `dedupe_key` is *"this is the same fact"* — repeats fold into one row.
* `group_key` is *"these belong together"* — nine task assignments from one run are nine separate
  facts a person may act on individually, shown under one heading.

## `action_required` is a column, not a query

§12's drawer has three tabs: All, Unread and **Action required**. Whether something needs an
action is a property of the event — a task assigned to you needs one, a run that succeeded does
not — and it is decided once, by the code that raises the notification. Deriving it later from
the category would be a second implementation of the same judgement, and the tab would disagree
with the badge.

## Preferences are absent by default, and that is the design

There is no row per person per category created at sign-up. A person with no preference row gets
the code's defaults, and a row exists only where somebody has actually chosen something. The
alternative — six rows written for every new member — is six rows to migrate every time a
category is added, and a `false` that nobody chose is indistinguishable from one they did.

`notification_settings` is per person: quiet hours and the digest hour are properties of a human
being, not of a category. Quiet hours need a timezone of their own, because "do not disturb me
between 22:00 and 07:00" means where that person is, and that is not necessarily where the
workspace is.

## What is deliberately absent

**No `sent_at` / `delivery_status`.** Delivery is the outbox's job and it already records
attempts, failures and dead letters per event. A second copy of delivery state here would be a
second copy to keep true, and the one people read would be whichever the screen happened to join.

**No `expires_at`.** Retention is a tenant policy (§17, and the privacy module), not a per-row
guess made by whichever code raised the notification.

Revision: 0037
Parent:   0036
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0037"
down_revision: str | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: §12's six categories, verbatim: *"task/assignment, approval/input, Agent failure/result,
#: schedule/lifecycle, mention/comment and security/admin"*. Six, because that is the list a
#: person is offered when they choose what to be told about — a seventh invented here would be a
#: preference nobody in the plan asked for.
CATEGORIES = (
    "task_assignment",
    "approval_input",
    "agent_result",
    "schedule_lifecycle",
    "mention_comment",
    "security_admin",
)

#: How a category reaches somebody. `off` is a real choice and is stored, not represented by the
#: absence of a row — absence means "never decided", which is a different thing and gets the
#: defaults.
DELIVERY = ("immediate", "digest", "off")


def upgrade() -> None:
    # ── the notifications themselves ─────────────────────────────────────────────────────
    op.create_table(
        "notifications",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=False),
        #: Who is being told. A membership, not a user: the same person in two workspaces has two
        #: bells, and one workspace's events must never appear in the other's.
        sa.Column("membership_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("category", sa.String(30), nullable=False),
        #: The specific thing that happened — `task.assigned`, `approval.requested`. Finer than
        #: the category, because the category is what a person subscribes to and this is what the
        #: line actually says.
        sa.Column("event", sa.String(60), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        #: Null for anything nobody did — a schedule firing, a run failing on its own. §12 asks
        #: for the actor and this is honest about there not always being one.
        sa.Column("actor_membership_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("subject_type", sa.String(40), nullable=False),
        sa.Column("subject_id", pg.UUID(as_uuid=True), nullable=True),
        #: §12's "deep link". Stored as a path the app owns, never a full URL: a stored origin
        #: goes stale the day the product moves domain, and a notification that navigates
        #: somewhere else is worse than one that does not navigate at all.
        sa.Column("deep_link", sa.String(500), nullable=False),
        #: The *Action required* tab. Decided by whoever raises the notification, because only
        #: they know whether this is a request or a report.
        sa.Column(
            "action_required", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        #: "These are the same fact." Repeats fold into this row rather than adding one.
        sa.Column("dedupe_key", sa.String(200), nullable=False),
        #: "These belong together." Nine assignments from one run are nine facts under one
        #: heading — a different question from dedup, and a different column.
        sa.Column("group_key", sa.String(200), nullable=True),
        sa.Column(
            "occurrences", sa.Integer(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        #: When it last happened. Equal to `created_at` until something folds into it, and then
        #: the honest answer to "when did this last go wrong".
        sa.Column(
            "last_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "category IN " + str(CATEGORIES), name="ck_notifications_category"
        ),
        sa.CheckConstraint("occurrences >= 1", name="ck_notifications_occurrences"),
        #: A repeat cannot predate the first one. Cheap, and it catches a clock or a bad update
        #: before somebody reads "last happened" as a time that has not arrived.
        sa.CheckConstraint("last_at >= created_at", name="ck_notifications_last_at"),
        sa.CheckConstraint(
            "length(btrim(deep_link)) > 0 AND deep_link LIKE '/%'",
            name="ck_notifications_deep_link_is_a_path",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_notifications_tenant_id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_notifications_membership",
            ondelete="CASCADE",
        ),
    )
    #  **Dedup, enforced.** The same unresolved fact cannot sit in one bell twice. Partial, so
    #  that something recurring after it has been read is allowed to be new again — an
    #  acknowledged problem recurring silently forever is the worse failure.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_notifications_unread_dedupe
        ON notifications (membership_id, dedupe_key)
        WHERE read_at IS NULL
        """
    )
    #  The bell's own two queries: my unread, and my unread that need doing.
    op.create_index(
        "ix_notifications_inbox",
        "notifications",
        ["tenant_id", "membership_id", "read_at", "last_at"],
    )
    op.create_index(
        "ix_notifications_group",
        "notifications",
        ["tenant_id", "membership_id", "group_key"],
    )

    # ── what each person wants to be told ────────────────────────────────────────────────
    #
    # One row per person per category, and **only where somebody chose**. No row means the
    # defaults in code, which is different from a `false` nobody selected.
    op.create_table(
        "notification_preferences",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("membership_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("in_app", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("email", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("delivery", sa.String(20), nullable=False, server_default="immediate"),
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
        sa.CheckConstraint(
            "category IN " + str(CATEGORIES), name="ck_notification_prefs_category"
        ),
        sa.CheckConstraint(
            "delivery IN " + str(DELIVERY), name="ck_notification_prefs_delivery"
        ),
        sa.UniqueConstraint(
            "membership_id", "category", name="uq_notification_prefs_one_per_category"
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_notification_prefs_membership",
            ondelete="CASCADE",
        ),
    )

    # ── quiet hours, which belong to a person and not to a category ──────────────────────
    op.create_table(
        "notification_settings",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("membership_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "quiet_hours_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        #: Local times, not instants. "Do not disturb me between 22:00 and 07:00" is a statement
        #: about a clock on a wall, and it stays true across a daylight-saving change — which
        #: storing an offset would not.
        sa.Column("quiet_from", sa.Time(), nullable=True),
        sa.Column("quiet_to", sa.Time(), nullable=True),
        #: IANA, and the person's own. Quiet hours mean where *they* are, which is not
        #: necessarily where the workspace is.
        sa.Column("timezone", sa.String(64), nullable=False, server_default="Asia/Kolkata"),
        #: The local hour a digest is sent. One number rather than a cron: §12 asks for a digest,
        #: and a person choosing when to receive theirs is choosing an hour.
        sa.Column("digest_hour", sa.Integer(), nullable=False, server_default=sa.text("9")),
        #: When their last digest went, so the next one covers exactly what has happened since
        #: and a restarted worker cannot send the same summary twice.
        sa.Column("last_digest_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "digest_hour BETWEEN 0 AND 23", name="ck_notification_settings_digest_hour"
        ),
        #: Quiet hours that are switched on must say when. Switched off, the times may be
        #: anything — including what they were, so turning it back on restores the choice.
        sa.CheckConstraint(
            "NOT quiet_hours_enabled OR (quiet_from IS NOT NULL AND quiet_to IS NOT NULL)",
            name="ck_notification_settings_quiet_hours_have_times",
        ),
        sa.UniqueConstraint(
            "membership_id", name="uq_notification_settings_one_per_person"
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_notification_settings_membership",
            ondelete="CASCADE",
        ),
    )

    # ── isolation ────────────────────────────────────────────────────────────────────────
    for table in ("notifications", "notification_preferences", "notification_settings"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_tenant ON {table}
            USING (tenant_id = app_current_tenant())
            WITH CHECK (tenant_id = app_current_tenant())
            """
        )

    #  No DELETE on `notifications`: reading one is `read_at`, not removal, and a bell that could
    #  erase its own history would be a bell somebody could clear to hide what they were told.
    #  Retention is the tenant's policy and runs as the owner.
    op.execute("GRANT SELECT, INSERT, UPDATE ON notifications TO uboss_app")
    #  Preferences are a person's own settings: they may change them, and clearing one back to
    #  "never decided" is a legitimate thing to want.
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON notification_preferences TO uboss_app"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON notification_settings TO uboss_app")

    #  The digest worker sweeps every workspace, exactly as the outbox and the scheduler do, so
    #  it needs the same narrow discovery grant: *which* people are due a digest. Reading their
    #  notifications and writing the outbox row happens on the application connection with the
    #  tenant bound — see 0035 for the same split and the same reasoning.
    op.execute("GRANT SELECT ON TABLE notification_settings TO uboss_relay")
    op.execute(
        """
        CREATE POLICY notification_settings_relay ON notification_settings
            FOR SELECT
            TO uboss_relay
            USING (true)
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS notification_settings_relay ON notification_settings"
    )
    op.execute("REVOKE SELECT ON TABLE notification_settings FROM uboss_relay")
    for table in ("notification_settings", "notification_preferences", "notifications"):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant ON {table}")
    op.drop_table("notification_settings")
    op.drop_table("notification_preferences")
    op.drop_index("ix_notifications_group", table_name="notifications")
    op.drop_index("ix_notifications_inbox", table_name="notifications")
    op.execute("DROP INDEX IF EXISTS uq_notifications_unread_dedupe")
    op.drop_table("notifications")
