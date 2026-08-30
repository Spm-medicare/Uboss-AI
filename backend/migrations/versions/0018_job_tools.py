"""Which tools a job touches, and what it is allowed to do with each — PLAN §8 group 7.

The gap this closes was found by checking Gate 4 against §8's ten form groups rather than against
what had been built: nine of the ten were there and *"Tools/integrations"* was not. Leaving it as a
documented hole in a gate called complete would have been the worse outcome.

**A tool declaration is a permission, not a note.** The workbook's own "Permission" list — Read,
Create, Update, Upload, Download, Send, Monitor, Approve — is what a step is allowed to do with a
system, and PLAN §19 requires every external action to go through a governed gateway. This table
is what that gateway will check: a job that never declared `Send` on Outlook does not get to send
mail, whatever a model decides mid-run.

**Naming a tool is not connecting one.** `integration_id` is null until Gate 8 wires the real
connections; the name is what a person typed. That is honest and useful now — it says what this
job needs — and it becomes a foreign key later without the rows moving.

Revision: 0018
Parent:   0017
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The workbook's own "Permission" list, from the "Dropdown Lists" sheet.
PERMISSIONS: tuple[str, ...] = (
    "Read",
    "Create",
    "Update",
    "Upload",
    "Download",
    "Send",
    "Monitor",
    "Approve",
    "Other",
)


def upgrade() -> None:
    op.create_table(
        "job_tools",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        #  What the person calls it: "Outlook", "our ERP", "the pricing sheet".
        sa.Column("name", sa.String(length=200), nullable=False),
        #  Null until Gate 8 wires the real connections. Naming a tool is not connecting one, and
        #  saying what a job needs is useful before anything is connected.
        sa.Column("integration_id", postgresql.UUID(as_uuid=True), nullable=True),
        #  What this job may do with it. The workbook's own list; the ceiling a governed gateway
        #  will enforce, not a description of intent.
        sa.Column("permissions", postgresql.JSONB(), nullable=False, server_default="[]"),
        #  Which step uses it. Null means the job as a whole — common for a system somebody has
        #  open throughout rather than at one step.
        sa.Column("step_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name="pk_job_tools"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_job_tools_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "job_id"],
            ["jobs.tenant_id", "jobs.id"],
            name="fk_job_tools_tenant_job",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "step_id"],
            ["job_steps.tenant_id", "job_steps.id"],
            name="fk_job_tools_tenant_step",
            #  The step list is replaced wholesale on every save, so a tool pinned to a step
            #  would lose it. SET NULL means the tool survives as a job-level declaration rather
            #  than disappearing with the step it happened to name.
            ondelete="SET NULL (step_id)",
        ),
        sa.UniqueConstraint("tenant_id", "job_id", "position", name="uq_job_tools_position"),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_job_tools_name_not_blank"),
        sa.CheckConstraint("position >= 1", name="ck_job_tools_position_positive"),
        #  A tool with no permission is a tool the gateway would refuse every call to. Better to
        #  refuse it here, where somebody can say what they meant.
        sa.CheckConstraint(
            "jsonb_array_length(permissions) > 0", name="ck_job_tools_has_a_permission"
        ),
    )
    op.create_index("ix_job_tools_tenant_id", "job_tools", ["tenant_id"])
    op.create_index("ix_job_tools_job", "job_tools", ["tenant_id", "job_id", "position"])

    op.execute(
        """
        CREATE TRIGGER job_tools_set_updated_at
            BEFORE UPDATE ON job_tools
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )
    op.execute("ALTER TABLE job_tools ENABLE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY job_tools_tenant_isolation ON job_tools
            FOR ALL
            USING (tenant_id = app_current_tenant())
            WITH CHECK (tenant_id = app_current_tenant());
        """
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON job_tools TO uboss_app;")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS job_tools CASCADE")
