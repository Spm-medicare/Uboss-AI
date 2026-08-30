"""The Agent — the approved workbook's Form 4, and `PLAN.md` §9's ten form groups.

Read from `UBOSS_Agent_Builder_Forms.xlsx`, sheet **"FORM 4 — AGENT BUILDER | DESIGN, CONTROLS &
TESTS"**, rather than summarised. As with the Objective, the sheet and the plan describe the same
object from two sides and **both are kept whole** — `docs/architecture/AGENT_FIELDS.md` records
which field came from where and why nothing was dropped.

Form 4 is the business form: a header, twelve design rows with nine columns, six named error
situations and five sandbox tests. §9 adds what a governed runtime needs and a paper form has no
column for — model policy, knowledge retention, explicit tool scopes, cost and concurrency limits,
and an audience. Neither is a superset of the other.

**An Agent is not a Job.** §8: *"Job Builder defines reusable work; it is not a runtime Agent."*
A Job describes a method. An Agent executes an **approved version** of one, which is why
`job_version_id` points at the immutable `job_versions` row rather than at the mutable draft, and
why a published Agent without one is refused by a check constraint.

**Tool suggestions never grant access.** §9's own words. Every `agent_tools` row is a suggestion
until somebody with the authority grants it, and the schema refuses a row marked granted that does
not name who granted it and when. A design that let a suggestion carry access would mean an agent
acquiring a permission because a form proposed one.

**A skill is chosen through the resolver, not typed in.** `agent_skills` carries the
`skill_resolver_decision_id` that chose it, so the answer to *"why does this agent use that
skill"* is the recorded decision from 5.2 — the gates that ran, the candidates that were refused
and the route that was taken — rather than somebody's memory.

Section C of Form 4 — the five sandbox tests — is deliberately **not** here. Tests are a publish
gate (§9: *"Tests and permission review are publish gates"*), and a gate belongs with the thing it
guards. It arrives in 5.4 with `agent_versions`.

Revision: 0021
Parent:   0020
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The same lifecycle as a Job and an Objective. One vocabulary across the Builders, so a person
#: who has published one knows what the words mean on the next.
STATUSES: tuple[str, ...] = (
    "draft",
    "needs_review",
    "ready_to_publish",
    "published",
    "active",
    "paused",
    "archived",
)

#: §9: *"Access choices: Only me, selected users, teams, department, role/subtree or workspace."*
#: Six, exactly. The default is `only_me` because the plan's decision table says so — *"Personal
#: Agent visibility | Only me"* — and a default that shared by accident is the one mistake this
#: field cannot afford.
VISIBILITY: tuple[str, ...] = (
    "only_me",
    "selected_users",
    "teams",
    "department",
    "role_subtree",
    "workspace",
)

#: Who a share names. `selected_users` and `teams` need a row each; `department`, `role_subtree`
#: and `workspace` are answered by the caller's own position, and `only_me` names nobody.
SHARE_PRINCIPALS: tuple[str, ...] = (
    "user",
    "team",
    "department",
    "role",
    "hierarchy_subtree",
)

#: Form 4, section B. Six situations, printed on the approved form as fixed rows — so this is a
#: closed set rather than a suggestion list, and 5.4 requires all six before an Agent publishes.
#: An agent with no answer for "prohibited action requested" is an agent nobody has decided about.
SITUATIONS: tuple[str, ...] = (
    "mandatory_input_missing",
    "information_unclear",
    "information_conflicts",
    "tool_or_system_fails",
    "approval_rejected",
    "prohibited_action_requested",
)

#: §9 group 4: *"Multiple input/output schemas."* Plural on purpose — one agent may accept more
#: than one shape of input and produce more than one kind of output.
DIRECTIONS: tuple[str, ...] = ("input", "output")

#: The five routes a resolver decision can take (migration 0020). Recorded on the chosen skill so
#: the agent says how it came by it — reused, configured, composed, or newly drafted.
ROUTES: tuple[str, ...] = ("reuse", "configure", "compose", "create")

#: The workbook's "Time Unit" list, for Form 4's "Completion Time".
TIME_UNITS: tuple[str, ...] = ("Minutes", "Hours", "Days")


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    statuses = _quoted(STATUSES)
    visibility = _quoted(VISIBILITY)
    principals = _quoted(SHARE_PRINCIPALS)
    situations = _quoted(SITUATIONS)
    directions = _quoted(DIRECTIONS)
    routes = _quoted(ROUTES)
    time_units = _quoted(TIME_UNITS)

    # ---------------------------------------------------------------- the agent
    op.create_table(
        "agents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        #  Group 1: identity, and the approved Job version this Agent runs.
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("objective_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=True),
        #  The immutable version, not the draft. An Agent that ran whatever the draft happened to
        #  say would change what it does when somebody edited a form.
        sa.Column("job_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        #  Form 4's header. Suggestions from the workbook's lists, which all end in "Other", so
        #  they are stored as text rather than constrained to a closed set.
        sa.Column("trigger", sa.String(length=120), nullable=True),
        sa.Column("frequency", sa.String(length=60), nullable=True),
        sa.Column("completion_time_value", sa.Integer(), nullable=True),
        sa.Column("completion_time_unit", sa.String(length=20), nullable=True),
        #  Group 2: purpose, instructions, boundaries, prohibited actions. Kept as four columns
        #  rather than one "description", because a boundary and a prohibition are read by
        #  different people for different reasons and a reviewer needs to find each on its own.
        sa.Column("purpose", sa.Text(), nullable=True),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column("boundaries", sa.Text(), nullable=True),
        sa.Column("prohibited_actions", sa.Text(), nullable=True),
        #  Group 3: owner and audience.
        sa.Column("owner_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "visibility", sa.String(length=20), server_default="only_me", nullable=False
        ),
        #  Group 5: model policy. A **policy key**, never a model name — CLAUDE.md forbids a
        #  hard-coded model in domain logic, and the gateway is what resolves this to a provider.
        #  No vocabulary is invented here: v3.2 approves *"Claude first through provider-neutral
        #  Gateway"* and names no policy catalogue, so the column is free text until one exists.
        sa.Column("model_policy_key", sa.String(length=60), nullable=True),
        #  Group 8: Form 4's "Main Approver *" and "Error Escalation To *". A membership where the
        #  person is known and a label where the form named a role — "Department Head" is a real
        #  answer on the approved sheet and pretending it is a person would lose it.
        sa.Column("main_approver_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("main_approver_label", sa.String(length=200), nullable=True),
        sa.Column("escalation_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("escalation_label", sa.String(length=200), nullable=True),
        #  Group 9: cost, token, time, concurrency and retries. Null means the tenant's policy
        #  decides; a number here is this Agent's own ceiling and is never raised by a run.
        sa.Column("cost_cap_minor_units", sa.Integer(), nullable=True),
        sa.Column("cost_cap_currency", sa.String(length=3), nullable=True),
        sa.Column("token_cap", sa.Integer(), nullable=True),
        sa.Column("time_limit_seconds", sa.Integer(), nullable=True),
        sa.Column("max_concurrency", sa.Integer(), nullable=True),
        sa.Column("max_retries", sa.Integer(), nullable=True),
        #  Lifecycle. `published_version_id` is filled by 5.4 and referenced here so the check
        #  that a published Agent has a version can exist from the start.
        sa.Column("status", sa.String(length=20), server_default="draft", nullable=False),
        sa.Column("submitted_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name="pk_agents"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_agents_tenant_id_tenants", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "objective_id"],
            ["objectives.tenant_id", "objectives.id"],
            name="fk_agents_tenant_objective",
            ondelete="SET NULL (objective_id)",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "job_id"],
            ["jobs.tenant_id", "jobs.id"],
            name="fk_agents_tenant_job",
            ondelete="SET NULL (job_id)",
        ),
        #  RESTRICT, not SET NULL: a published version is evidence of what was approved, and an
        #  Agent quietly losing the version it runs would be an Agent running nothing in
        #  particular.
        sa.ForeignKeyConstraint(
            ["tenant_id", "job_version_id"],
            ["job_versions.tenant_id", "job_versions.id"],
            name="fk_agents_tenant_job_version",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_agents_tenant_id"),
        sa.CheckConstraint(f"status IN ({statuses})", name="ck_agents_status_known"),
        sa.CheckConstraint(f"visibility IN ({visibility})", name="ck_agents_visibility_known"),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_agents_name_not_blank"),
        #  Operation runs only approved, immutable versions. An Agent in a running state without
        #  one has nothing to run.
        sa.CheckConstraint(
            "status NOT IN ('published', 'active', 'paused') OR job_version_id IS NOT NULL",
            name="ck_agents_running_has_job_version",
        ),
        sa.CheckConstraint(
            "status <> 'ready_to_publish' OR submitted_by_membership_id IS NOT NULL",
            name="ck_agents_submitted_has_submitter",
        ),
        #  Form 4 marks both required with an asterisk. Enforced from the moment the design is
        #  put forward, not before and not after: a form is filled in over time, so refusing the
        #  first save would be refusing to let somebody start — and an abandoned draft is
        #  archived without ever having needed an approver.
        sa.CheckConstraint(
            "status NOT IN ('ready_to_publish', 'published', 'active', 'paused') "
            "OR main_approver_membership_id IS NOT NULL OR main_approver_label IS NOT NULL",
            name="ck_agents_submitted_has_approver",
        ),
        sa.CheckConstraint(
            "status NOT IN ('ready_to_publish', 'published', 'active', 'paused') "
            "OR escalation_membership_id IS NOT NULL OR escalation_label IS NOT NULL",
            name="ck_agents_submitted_has_escalation",
        ),
        sa.CheckConstraint(
            "completion_time_value IS NULL OR completion_time_value > 0",
            name="ck_agents_completion_time_positive",
        ),
        sa.CheckConstraint(
            f"completion_time_unit IS NULL OR completion_time_unit IN ({time_units})",
            name="ck_agents_completion_time_unit_known",
        ),
        sa.CheckConstraint(
            "completion_time_value IS NULL OR completion_time_unit IS NOT NULL",
            name="ck_agents_completion_time_has_unit",
        ),
        #  A cost is a number and a currency or it is neither. "12" with no currency is not a cap.
        sa.CheckConstraint(
            "(cost_cap_minor_units IS NULL) = (cost_cap_currency IS NULL)",
            name="ck_agents_cost_cap_has_currency",
        ),
        sa.CheckConstraint(
            "cost_cap_minor_units IS NULL OR cost_cap_minor_units >= 0",
            name="ck_agents_cost_cap_not_negative",
        ),
        sa.CheckConstraint("token_cap IS NULL OR token_cap > 0", name="ck_agents_token_cap_positive"),
        sa.CheckConstraint(
            "time_limit_seconds IS NULL OR time_limit_seconds > 0",
            name="ck_agents_time_limit_positive",
        ),
        sa.CheckConstraint(
            "max_concurrency IS NULL OR max_concurrency >= 1",
            name="ck_agents_concurrency_at_least_one",
        ),
        sa.CheckConstraint(
            "max_retries IS NULL OR max_retries >= 0", name="ck_agents_retries_not_negative"
        ),
    )
    for column, constraint in (
        ("owner_membership_id", "fk_agents_tenant_owner"),
        ("main_approver_membership_id", "fk_agents_tenant_approver"),
        ("escalation_membership_id", "fk_agents_tenant_escalation"),
        ("submitted_by_membership_id", "fk_agents_tenant_submitter"),
        ("created_by_membership_id", "fk_agents_tenant_creator"),
    ):
        op.execute(
            f"""
            ALTER TABLE agents
                ADD CONSTRAINT {constraint}
                FOREIGN KEY (tenant_id, {column})
                REFERENCES memberships (tenant_id, id)
                ON DELETE SET NULL ({column});
            """
        )
    op.create_index("ix_agents_tenant_status", "agents", ["tenant_id", "status"])
    op.create_index("ix_agents_tenant_owner", "agents", ["tenant_id", "owner_membership_id"])
    op.create_index("ix_agents_tenant_job", "agents", ["tenant_id", "job_id"])

    # ---------------------------------------------------------------- section A: design rows
    op.create_table(
        "agent_steps",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        #  Where this row came from, when it came from somewhere. Form 4 is *"generated from
        #  Forms 2 and 3"*, and keeping the link is what lets a reviewer see what was changed.
        sa.Column("job_step_id", postgresql.UUID(as_uuid=True), nullable=True),
        #  Form 4 section A, all nine columns, in the sheet's own order.
        sa.Column("input_used", sa.Text(), nullable=True),
        sa.Column("input_source", sa.Text(), nullable=True),
        sa.Column("tool_system", sa.Text(), nullable=True),
        sa.Column("agent_action", sa.Text(), nullable=True),
        sa.Column("output", sa.Text(), nullable=True),
        sa.Column("output_destination", sa.Text(), nullable=True),
        sa.Column("approval", sa.String(length=120), nullable=True),
        #  The column the whole form turns on. §9 group 2 calls it prohibited actions; the sheet
        #  calls it "Agent Must Never Do". Same field, and it is per step because what an agent
        #  must never do at step 4 is not what it must never do at step 9.
        sa.Column("must_never_do", sa.Text(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name="pk_agent_steps"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_agent_steps_tenant", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "agent_id"],
            ["agents.tenant_id", "agents.id"],
            name="fk_agent_steps_agent",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "job_step_id"],
            ["job_steps.tenant_id", "job_steps.id"],
            name="fk_agent_steps_job_step",
            ondelete="SET NULL (job_step_id)",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_agent_steps_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id", "agent_id", "position", name="uq_agent_steps_position"
        ),
        sa.CheckConstraint("position >= 1", name="ck_agent_steps_position_positive"),
    )

    # ---------------------------------------------------------------- section B: error rules
    op.create_table(
        "agent_escalation_rules",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("situation", sa.String(length=40), nullable=False),
        sa.Column("required_action", sa.Text(), nullable=False),
        sa.Column("escalate_to_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("escalate_to_label", sa.String(length=200), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name="pk_agent_escalation_rules"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_agent_rules_tenant", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "agent_id"],
            ["agents.tenant_id", "agents.id"],
            name="fk_agent_rules_agent",
            ondelete="CASCADE",
        ),
        #  One answer per situation. Two rows for "approval is rejected" would be two policies,
        #  and nothing in the design says which one wins.
        sa.UniqueConstraint(
            "tenant_id", "agent_id", "situation", name="uq_agent_rules_situation"
        ),
        sa.CheckConstraint(f"situation IN ({situations})", name="ck_agent_rules_situation_known"),
        sa.CheckConstraint(
            "length(btrim(required_action)) > 0", name="ck_agent_rules_action_not_blank"
        ),
    )
    op.execute(
        """
        ALTER TABLE agent_escalation_rules
            ADD CONSTRAINT fk_agent_rules_escalate_to
            FOREIGN KEY (tenant_id, escalate_to_membership_id)
            REFERENCES memberships (tenant_id, id)
            ON DELETE SET NULL (escalate_to_membership_id);
        """
    )

    # ---------------------------------------------------------------- group 4: I/O schemas
    op.create_table(
        "agent_io_schemas",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("direction", sa.String(length=10), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        #  The workbook's "Input Type" and "Output Format" lists — suggestions, both ending in
        #  "Other", so stored as text.
        sa.Column("format", sa.String(length=60), nullable=True),
        #  The shape itself. JSON Schema, so a run can validate against it rather than hoping.
        sa.Column("json_schema", postgresql.JSONB, nullable=True),
        sa.Column("required", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name="pk_agent_io_schemas"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_agent_io_tenant", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "agent_id"],
            ["agents.tenant_id", "agents.id"],
            name="fk_agent_io_agent",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "tenant_id", "agent_id", "direction", "name", name="uq_agent_io_name"
        ),
        sa.CheckConstraint(f"direction IN ({directions})", name="ck_agent_io_direction_known"),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_agent_io_name_not_blank"),
        sa.CheckConstraint("position >= 1", name="ck_agent_io_position_positive"),
        #  An object or nothing. A bare string or number stored as "the schema" would pass
        #  validation here and fail everywhere it was used.
        sa.CheckConstraint(
            "json_schema IS NULL OR jsonb_typeof(json_schema) = 'object'",
            name="ck_agent_io_schema_is_an_object",
        ),
    )

    # ---------------------------------------------------------------- group 6: knowledge
    op.create_table(
        "agent_knowledge_sources",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        #  The workbook's "Where" list — Excel, ERP, SharePoint and the rest. A suggestion list.
        sa.Column("location", sa.String(length=200), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        #  §9 group 6 says *"and retention"*, so retention lives with the source rather than in
        #  one setting for the whole Agent: a policy document and a customer export do not keep
        #  for the same length of time. Null means the tenant's own retention policy decides.
        sa.Column("retention_days", sa.Integer(), nullable=True),
        #  Set when the source holds personal data. The privacy gate in Gate 8 reads this, and a
        #  source nobody classified is one nobody can honour a deletion request against.
        sa.Column(
            "contains_personal_data",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name="pk_agent_knowledge_sources"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_agent_knowledge_tenant", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "agent_id"],
            ["agents.tenant_id", "agents.id"],
            name="fk_agent_knowledge_agent",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("tenant_id", "agent_id", "name", name="uq_agent_knowledge_name"),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_agent_knowledge_name_not_blank"),
        sa.CheckConstraint("position >= 1", name="ck_agent_knowledge_position_positive"),
        sa.CheckConstraint(
            "retention_days IS NULL OR retention_days > 0",
            name="ck_agent_knowledge_retention_positive",
        ),
    )

    # ---------------------------------------------------------------- group 7: tools and scopes
    op.create_table(
        "agent_tools",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tool", sa.String(length=200), nullable=False),
        #  The workbook's "Permission" list: Read, Create, Update, Upload, Download, Send,
        #  Monitor, Approve, Other. Explicit and non-empty — §9 says *"explicit scopes"*, and a
        #  tool with no scope is a tool with every scope.
        sa.Column("scopes", postgresql.JSONB, nullable=False),
        sa.Column("purpose", sa.Text(), nullable=True),
        #  §9: *"Tool suggestions never grant access."* False until somebody with the authority
        #  says otherwise, and the constraint below refuses a grant that names nobody.
        sa.Column("granted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("granted_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name="pk_agent_tools"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_agent_tools_tenant", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "agent_id"],
            ["agents.tenant_id", "agents.id"],
            name="fk_agent_tools_agent",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("tenant_id", "agent_id", "tool", name="uq_agent_tools_tool"),
        sa.CheckConstraint("length(btrim(tool)) > 0", name="ck_agent_tools_tool_not_blank"),
        sa.CheckConstraint("position >= 1", name="ck_agent_tools_position_positive"),
        sa.CheckConstraint(
            "jsonb_typeof(scopes) = 'array' AND jsonb_array_length(scopes) > 0",
            name="ck_agent_tools_scopes_present",
        ),
        #  A grant names who made it and when, or it is not a grant.
        sa.CheckConstraint(
            "granted = false OR "
            "(granted_by_membership_id IS NOT NULL AND granted_at IS NOT NULL)",
            name="ck_agent_tools_grant_has_grantor",
        ),
    )
    op.execute(
        """
        ALTER TABLE agent_tools
            ADD CONSTRAINT fk_agent_tools_grantor
            FOREIGN KEY (tenant_id, granted_by_membership_id)
            REFERENCES memberships (tenant_id, id)
            ON DELETE SET NULL (granted_by_membership_id);
        """
    )

    # ---------------------------------------------------------------- the skills it uses
    op.create_table(
        "agent_skills",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        #  RESTRICT: a skill in use cannot be removed out from under the Agent that uses it.
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        #  How it came to be chosen. Nullable because a skill can be attached before a resolution
        #  exists — but 5.5 offers the resolver first, and this is what makes *"why does this
        #  agent use that skill"* answerable from the record rather than from memory.
        sa.Column("resolver_decision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("route", sa.String(length=20), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_agent_skills"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_agent_skills_tenant", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "agent_id"],
            ["agents.tenant_id", "agents.id"],
            name="fk_agent_skills_agent",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"], ["skills.id"], name="fk_agent_skills_skill", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["resolver_decision_id"],
            ["skill_resolver_decisions.id"],
            name="fk_agent_skills_decision",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "agent_id", "skill_id", name="uq_agent_skills_skill"),
        sa.CheckConstraint(f"route IS NULL OR route IN ({routes})", name="ck_agent_skills_route"),
        sa.CheckConstraint("position >= 1", name="ck_agent_skills_position_positive"),
    )

    # ---------------------------------------------------------------- group 3: sharing
    op.create_table(
        "agent_shares",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("principal_type", sa.String(length=30), nullable=False),
        sa.Column("principal_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("label", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_agent_shares"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_agent_shares_tenant", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "agent_id"],
            ["agents.tenant_id", "agents.id"],
            name="fk_agent_shares_agent",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "agent_id",
            "principal_type",
            "principal_id",
            name="uq_agent_shares_principal",
        ),
        sa.CheckConstraint(
            f"principal_type IN ({principals})", name="ck_agent_shares_principal_known"
        ),
        #  A share names somebody. An id where the principal is a record in this system, a label
        #  where the approved form named a role — and never neither.
        sa.CheckConstraint(
            "principal_id IS NOT NULL OR label IS NOT NULL",
            name="ck_agent_shares_names_somebody",
        ),
    )

    for table in (
        "agents",
        "agent_steps",
        "agent_escalation_rules",
        "agent_io_schemas",
        "agent_knowledge_sources",
        "agent_tools",
        "agent_skills",
        "agent_shares",
    ):
        #  Every RLS policy in the schema compares `tenant_id`, so every tenant-owned table is
        #  indexed on it — the `TenantOwned` mixin declares it, and a table missing the index
        #  makes the policy a sequential scan on the busiest predicate in the system.
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(
            f"""
            CREATE POLICY {table}_tenant_isolation ON {table}
                FOR ALL
                USING (tenant_id = app_current_tenant())
                WITH CHECK (tenant_id = app_current_tenant());
            """
        )
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO uboss_app;")


def downgrade() -> None:
    for table in (
        "agent_shares",
        "agent_skills",
        "agent_tools",
        "agent_knowledge_sources",
        "agent_io_schemas",
        "agent_escalation_rules",
        "agent_steps",
        "agents",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
