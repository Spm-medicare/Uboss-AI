"""Job schedules — PLAN §8's auto-run, and every question it says to ask.

    *"If WHEN repeats, ask Auto-run Yes/No. If enabled, require timezone, recurrence preview,
    DST, overlap, missed-run policy, calendar, concurrency, pinned versions and approval
    behavior."*

Every one of those is a column here, and none of them has a default the product chose on
somebody's behalf where the choice actually matters:

**The timezone is IANA and required.** Not an offset. `+05:30` stops being true the moment a
government changes its mind, and they do, with weeks of notice.

**Which version runs is a decision, not an accident.** `pinned_version_id` null means "whatever is
published now", which is right for a job whose method is still settling. Pinned means this exact
version keeps running until somebody moves it — right for anything regulated, where "the process
changed and nobody told me" is the failure.

**A schedule that would run without approval says so.** §8 asks for approval behaviour, and
`requires_approval_per_run` is it: a scheduled run that needs a person is a scheduled run that
waits for one.

Revision: 0017
Parent:   0016
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FREQUENCIES: tuple[str, ...] = ("hourly", "daily", "weekly", "monthly")
DST_POLICIES: tuple[str, ...] = ("skip", "shift")
AMBIGUOUS_POLICIES: tuple[str, ...] = ("first", "both")
MISSED_RUN_POLICIES: tuple[str, ...] = ("skip", "run_once", "run_all")
OVERLAP_POLICIES: tuple[str, ...] = ("skip", "queue", "allow")


def upgrade() -> None:
    #  `job_versions` was written in 0016 as a leaf — nothing pointed at it, so it had no
    #  `(tenant_id, id)` for a composite key to target. The pinned version below needs one:
    #  without it the reference could only name `job_versions.id`, and a schedule could then pin
    #  a version belonging to another organisation. Row-level security would hide that version,
    #  but the reference would exist, and a dangling cross-tenant reference is the kind of thing
    #  found much later.
    op.create_unique_constraint(
        "uq_job_versions_tenant_id", "job_versions", ["tenant_id", "id"]
    )

    frequencies = ", ".join(f"'{value}'" for value in FREQUENCIES)
    dst = ", ".join(f"'{value}'" for value in DST_POLICIES)
    ambiguous = ", ".join(f"'{value}'" for value in AMBIGUOUS_POLICIES)
    missed = ", ".join(f"'{value}'" for value in MISSED_RUN_POLICIES)
    overlap = ", ".join(f"'{value}'" for value in OVERLAP_POLICIES)

    op.create_table(
        "job_schedules",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        #  §8's "Auto-run Yes/No". False means the schedule is described but nothing fires — a
        #  legitimate state while a team decides, and the only honest way to save a half-built
        #  schedule without it going off.
        sa.Column("auto_run", sa.Boolean(), nullable=False, server_default="false"),
        # ── the recurrence ──────────────────────────────────────────────────────────────
        #  IANA, always. Not nullable: a repeating time with no timezone is a repeating time
        #  that means something different to everyone who reads it.
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("frequency", sa.String(length=20), nullable=False),
        sa.Column("interval", sa.Integer(), nullable=False, server_default="1"),
        #  The local time of day. Stored as a time, not a timestamp — the intent is "nine in the
        #  morning where the team is", on both sides of a clock change.
        sa.Column("at_time", sa.Time(), nullable=False),
        #  For weekly: which days, Monday as 0. Empty means the weekday it starts on.
        sa.Column("weekdays", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("monthday", sa.Integer(), nullable=True),
        # ── the two days a year that misbehave ──────────────────────────────────────────
        sa.Column("dst_policy", sa.String(length=10), nullable=False, server_default="shift"),
        sa.Column(
            "ambiguous_policy", sa.String(length=10), nullable=False, server_default="first"
        ),
        # ── §8's calendar ───────────────────────────────────────────────────────────────
        #  Dates this job must not run, in its own timezone. A list rather than a country code,
        #  because every company's shutdown days differ from every other's.
        sa.Column("skip_dates", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("weekdays_only", sa.Boolean(), nullable=False, server_default="false"),
        # ── what happens when runs collide or are missed ────────────────────────────────
        sa.Column(
            "overlap_policy", sa.String(length=10), nullable=False, server_default="skip"
        ),
        sa.Column(
            "missed_run_policy", sa.String(length=10), nullable=False, server_default="skip"
        ),
        #  §8's concurrency. 1 means one at a time, which is what almost every job wants and
        #  what nobody remembers to set.
        sa.Column("max_concurrent", sa.Integer(), nullable=False, server_default="1"),
        # ── §8's pinned versions and approval behaviour ────────────────────────────────
        #  Null means "whatever is published now". Pinned means this exact version runs until
        #  somebody moves it.
        sa.Column("pinned_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "requires_approval_per_run", sa.Boolean(), nullable=False, server_default="false"
        ),
        # ── bookkeeping ────────────────────────────────────────────────────────────────
        #  When it last fired, and when it is next due. Both computed by the runtime; kept here
        #  so a screen can show them without recomputing a recurrence it might get wrong.
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        #  Set when a run is refused or the schedule cannot resolve. Shown, so a schedule that
        #  has quietly stopped working is visible rather than merely silent.
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_job_schedules"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_job_schedules_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "job_id"],
            ["jobs.tenant_id", "jobs.id"],
            name="fk_job_schedules_tenant_job",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "pinned_version_id"],
            ["job_versions.tenant_id", "job_versions.id"],
            name="fk_job_schedules_tenant_version",
            #  RESTRICT: a pinned version must not disappear from under a running schedule. It
            #  is unpinned deliberately, or not at all.
            ondelete="RESTRICT",
        ),
        #  One schedule per job. §8 asks a job whether it auto-runs, not how many ways — several
        #  schedules on one job would each claim the same `last_run_at` and the missed-run
        #  policies would fight.
        sa.UniqueConstraint("tenant_id", "job_id", name="uq_job_schedules_one_per_job"),
        sa.CheckConstraint(f"frequency IN ({frequencies})", name="ck_schedules_frequency_known"),
        sa.CheckConstraint(f"dst_policy IN ({dst})", name="ck_schedules_dst_known"),
        sa.CheckConstraint(
            f"ambiguous_policy IN ({ambiguous})", name="ck_schedules_ambiguous_known"
        ),
        sa.CheckConstraint(f"missed_run_policy IN ({missed})", name="ck_schedules_missed_known"),
        sa.CheckConstraint(f"overlap_policy IN ({overlap})", name="ck_schedules_overlap_known"),
        sa.CheckConstraint(
            "interval >= 1 AND interval <= 999", name="ck_schedules_interval_sane"
        ),
        sa.CheckConstraint(
            "monthday IS NULL OR (monthday >= 1 AND monthday <= 31)",
            name="ck_schedules_monthday_sane",
        ),
        sa.CheckConstraint(
            "max_concurrent >= 1 AND max_concurrent <= 100",
            name="ck_schedules_concurrency_sane",
        ),
        #  A monthly schedule with no day of the month cannot resolve. Refused here so it cannot
        #  be saved looking configured and then never fire.
        sa.CheckConstraint(
            "frequency <> 'monthly' OR monthday IS NOT NULL",
            name="ck_schedules_monthly_has_a_day",
        ),
        sa.CheckConstraint("length(btrim(timezone)) > 0", name="ck_schedules_has_timezone"),
    )
    op.execute(
        """
        ALTER TABLE job_schedules
            ADD CONSTRAINT fk_job_schedules_tenant_creator
            FOREIGN KEY (tenant_id, created_by_membership_id)
            REFERENCES memberships (tenant_id, id)
            ON DELETE SET NULL (created_by_membership_id)
        """
    )
    op.create_index("ix_job_schedules_tenant_id", "job_schedules", ["tenant_id"])
    #  The runtime's own query: what is due. Partial, because a schedule that is not auto-running
    #  is not something the worker should ever look at.
    op.execute(
        """
        CREATE INDEX ix_job_schedules_due
            ON job_schedules (next_run_at)
            WHERE auto_run AND next_run_at IS NOT NULL;
        """
    )

    op.execute(
        """
        CREATE TRIGGER job_schedules_set_updated_at
            BEFORE UPDATE ON job_schedules
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )
    op.execute("ALTER TABLE job_schedules ENABLE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY job_schedules_tenant_isolation ON job_schedules
            FOR ALL
            USING (tenant_id = app_current_tenant())
            WITH CHECK (tenant_id = app_current_tenant());
        """
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON job_schedules TO uboss_app;")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS job_schedules CASCADE")
    op.execute(
        "ALTER TABLE job_versions DROP CONSTRAINT IF EXISTS uq_job_versions_tenant_id"
    )
