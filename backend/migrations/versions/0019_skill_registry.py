"""The Skill Registry — 12 archetypes, 400 skills, 2,400 IF-THEN rules and 12 exactness gates.

Read from `Universal_Enterprise_Skill_Catalog_IF_THEN (1).xlsx`. PLAN §39 keeps the catalogue as
*"a client-owned seed asset"* and fixes the flow it serves:

    Agent requirement → Search Skill Registry → Deterministic compatibility gates
    → Reuse | Configure | Compose | Create private Skill Draft
    → Sandbox tests → Human approval → Versioned active Skill

Four decisions run through this schema:

**The seed is shared; a tenant's own skills are not.** The 400 catalogue skills are the same rows
for every organisation, so they carry no `tenant_id` and are read-only to the application. A
private Skill Draft belongs to one tenant and lives beside them. Copying 400 rows per tenant would
mean 400 copies of a correction — and a catalogue that had silently diverged before anybody
noticed.

**The gates are data, not code.** §39 calls them *"deterministic compatibility gates"*, and the
workbook already writes all twelve down with their own failure states — `BLOCKED — ambiguous
scope`, `STALE — refresh required`. A resolver reading rows can explain a refusal in the
catalogue's own words; a resolver with twelve `if` statements has to have its reasons re-invented
in a message somewhere.

**A rule's failure state is the point.** 2,400 rules each say what happens when they do not hold.
That is what makes the registry a governance asset rather than a search index: the answer to "why
was this refused" is a row, not a judgement.

**Nothing here can publish itself.** §39: *"Skills cannot self-publish."* A tenant's own skill has
a status and an approver, and the same separation of duty as every other version in this schema.

Revision: 0019
Parent:   0018
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The workbook's "Autonomy" column. A1 reads, A4 needs a person — this is the ceiling a skill
#: may operate at, and the resolver refuses an agent asking for more than the skill allows.
AUTONOMY: tuple[str, ...] = (
    "A1",  # Read / analyze
    "A2",  # Draft / recommend
    "A3",  # Write only after approval
    "A4",  # Human authority required
)

#: The workbook's "Layer".
LAYERS: tuple[str, ...] = ("Universal Department", "Industry Overlay")

#: A tenant's own skill. Catalogue rows are always `published` and are never drafts.
SKILL_STATUSES: tuple[str, ...] = (
    "draft",
    "ready_to_publish",
    "published",
    "archived",
)

#: The workbook's "Condition Type" — the six kinds of IF-THEN rule.
CONDITION_TYPES: tuple[str, ...] = (
    "Trigger / Scope",
    "Input Completeness",
    "Primary Decision",
    "Evidence / Conflict",
    "Validation / Release",
    "Authority / Completion",
)


def upgrade() -> None:
    autonomy = ", ".join(f"'{value}'" for value in AUTONOMY)
    layers = ", ".join(f"'{value}'" for value in LAYERS)
    statuses = ", ".join(f"'{value}'" for value in SKILL_STATUSES)

    # ------------------------------------------------------------ the 12 archetypes

    op.create_table(
        "skill_archetypes",
        sa.Column("id", sa.String(length=8), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        #  The archetype's own IF and THEN. A skill inherits the shape of its type, and a
        #  reviewer comparing a skill against its archetype is checking exactly this.
        sa.Column("if_clause", sa.Text(), nullable=False),
        sa.Column("then_clause", sa.Text(), nullable=False),
        sa.Column("typical_output", sa.Text(), nullable=True),
        #  What every skill of this type must control for. Read by the resolver when a skill is
        #  composed rather than reused.
        sa.Column("mandatory_controls", sa.Text(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_skill_archetypes"),
    )

    # --------------------------------------------------- the 12 exactness gates

    op.create_table(
        "skill_exactness_gates",
        sa.Column("id", sa.String(length=8), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("if_clause", sa.Text(), nullable=False),
        sa.Column("then_clause", sa.Text(), nullable=False),
        #  What proves it passed. This is what an evidence panel shows, and what an audit reads.
        sa.Column("pass_evidence", sa.Text(), nullable=False),
        #  In the catalogue's own words: "BLOCKED — ambiguous scope". The resolver quotes this
        #  rather than inventing a message, so a refusal reads the same everywhere it appears.
        sa.Column("failure_state", sa.String(length=120), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_skill_exactness_gates"),
    )

    # ------------------------------------------------------------------ the skills

    op.create_table(
        "skills",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        #  Null for the shared catalogue, set for a tenant's own Skill Draft. The 400 seed rows
        #  are the same for everybody: 400 copies per tenant would be 400 copies of a correction.
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        #  The workbook's "Skill ID" — U-001, I-014. Stable, and how a rule finds its skill.
        sa.Column("catalogue_id", sa.String(length=20), nullable=True),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("layer", sa.String(length=40), nullable=False),
        sa.Column("department", sa.String(length=200), nullable=True),
        sa.Column("industry", sa.String(length=200), nullable=True),
        sa.Column("archetype_id", sa.String(length=8), nullable=True),
        sa.Column("purpose", sa.Text(), nullable=True),
        #  "Positive Trigger" and "Do Not Use / Exclusions". The exclusions matter more than the
        #  trigger: they are what stops a plausible search hit being the wrong skill.
        sa.Column("positive_trigger", sa.Text(), nullable=True),
        sa.Column("exclusions", sa.Text(), nullable=True),
        sa.Column("minimum_inputs", sa.Text(), nullable=True),
        sa.Column("primary_if", sa.Text(), nullable=True),
        sa.Column("primary_then", sa.Text(), nullable=True),
        sa.Column("output", sa.Text(), nullable=True),
        sa.Column("validation_gate", sa.Text(), nullable=True),
        #  A1..A4. The ceiling this skill may operate at — an agent asking for more is refused.
        sa.Column("autonomy", sa.String(length=4), nullable=False, server_default="A1"),
        #  "Source IDs" — where the skill's authority comes from. §39 forbids similarity
        #  overriding "stale evidence", and this is what freshness is judged against.
        sa.Column("source_ids", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="published"),
        sa.Column("owner_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("approved_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name="pk_skills"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_skills_tenant_id_tenants", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["archetype_id"],
            ["skill_archetypes.id"],
            name="fk_skills_archetype",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(f"autonomy IN ({autonomy})", name="ck_skills_autonomy_known"),
        sa.CheckConstraint(f"layer IN ({layers})", name="ck_skills_layer_known"),
        sa.CheckConstraint(f"status IN ({statuses})", name="ck_skills_status_known"),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_skills_name_not_blank"),
        #  A catalogue row has a catalogue id and no tenant; a private draft has a tenant and no
        #  catalogue id. Anything else is a row nobody could classify.
        sa.CheckConstraint(
            "(tenant_id IS NULL AND catalogue_id IS NOT NULL) OR "
            "(tenant_id IS NOT NULL AND catalogue_id IS NULL)",
            name="ck_skills_catalogue_or_private",
        ),
        #  §39: skills cannot self-publish. A published private skill must name who approved it.
        sa.CheckConstraint(
            "tenant_id IS NULL OR status <> 'published' OR "
            "(approved_by_membership_id IS NOT NULL AND approved_at IS NOT NULL)",
            name="ck_skills_published_was_approved",
        ),
    )
    op.execute(
        """
        ALTER TABLE skills
            ADD CONSTRAINT fk_skills_tenant_owner
            FOREIGN KEY (tenant_id, owner_membership_id)
            REFERENCES memberships (tenant_id, id)
            ON DELETE SET NULL (owner_membership_id)
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_skills_catalogue_id
            ON skills (catalogue_id)
            WHERE catalogue_id IS NOT NULL;
        """
    )
    op.create_index("ix_skills_tenant_id", "skills", ["tenant_id"])
    op.create_index("ix_skills_department", "skills", ["department", "industry"])
    op.create_index("ix_skills_archetype", "skills", ["archetype_id"])

    #  Full-text search over the fields somebody would actually search by. §39 says semantic
    #  similarity *discovers* candidates; this is the discovery half, and it is deliberately
    #  ordinary — a good search that a gate can then refuse beats a clever one that cannot.
    op.execute(
        """
        ALTER TABLE skills
            ADD COLUMN search tsvector
            GENERATED ALWAYS AS (
                setweight(to_tsvector('english', coalesce(name, '')), 'A') ||
                setweight(to_tsvector('english', coalesce(purpose, '')), 'B') ||
                setweight(to_tsvector('english', coalesce(positive_trigger, '')), 'C') ||
                setweight(to_tsvector('english', coalesce(primary_if, '')), 'C') ||
                setweight(to_tsvector('english', coalesce(primary_then, '')), 'C') ||
                setweight(to_tsvector('english', coalesce(department, '')), 'D')
            ) STORED;
        """
    )
    op.execute("CREATE INDEX ix_skills_search ON skills USING gin (search);")

    # ---------------------------------------------------- the 2,400 IF-THEN rules

    op.create_table(
        "skill_rules",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        #  The workbook's "Rule ID" — R-0001.
        sa.Column("catalogue_id", sa.String(length=20), nullable=True),
        sa.Column("condition_type", sa.String(length=60), nullable=False),
        sa.Column("if_clause", sa.Text(), nullable=False),
        sa.Column("then_clause", sa.Text(), nullable=False),
        sa.Column("priority", sa.String(length=20), nullable=False, server_default="High"),
        #  What has to exist for this rule to have been satisfied.
        sa.Column("evidence_required", sa.Text(), nullable=True),
        #  What happens when it does not hold — "DRAFT — input gap", "BLOCKED or ROUTED". This is
        #  what makes the registry a governance asset rather than a search index: the answer to
        #  "why was this refused" is a row rather than a judgement.
        sa.Column("failure_state", sa.String(length=120), nullable=True),
        #  "Yes" / "No" / "Conditional" / "As needed" — whether a person has to be in the loop.
        sa.Column("human_gate", sa.String(length=30), nullable=True),
        sa.Column("source_ids", sa.Text(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="1"),
        sa.PrimaryKeyConstraint("id", name="pk_skill_rules"),
        sa.ForeignKeyConstraint(
            ["skill_id"], ["skills.id"], name="fk_skill_rules_skill", ondelete="CASCADE"
        ),
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_skill_rules_catalogue_id
            ON skill_rules (catalogue_id)
            WHERE catalogue_id IS NOT NULL;
        """
    )
    op.create_index("ix_skill_rules_skill", "skill_rules", ["skill_id", "position"])
    op.create_index("ix_skill_rules_condition", "skill_rules", ["condition_type"])

    # ------------------------------------------------------------------- triggers

    for table in ("skills",):
        op.execute(
            f"""
            CREATE TRIGGER {table}_set_updated_at
                BEFORE UPDATE ON {table}
                FOR EACH ROW EXECUTE FUNCTION set_updated_at();
            """
        )

    # ------------------------------------------------------------------------ RLS

    #  The three reference tables are the same for everybody, so they carry no tenant and are
    #  read-only to the application. Seeded by migration, corrected by migration.
    for table in ("skill_archetypes", "skill_exactness_gates"):
        op.execute(f"GRANT SELECT ON {table} TO uboss_app;")

    #  `skills` holds both the shared catalogue and private drafts, so its policy has two
    #  branches: everybody reads the catalogue, and a tenant sees only its own drafts. The write
    #  policy has no catalogue branch at all — the application cannot touch the seed.
    op.execute("ALTER TABLE skills ENABLE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY skills_read ON skills
            FOR SELECT
            USING (tenant_id IS NULL OR tenant_id = app_current_tenant());
        """
    )
    op.execute(
        """
        CREATE POLICY skills_write ON skills
            FOR ALL
            USING (tenant_id = app_current_tenant())
            WITH CHECK (tenant_id = app_current_tenant());
        """
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON skills TO uboss_app;")

    #  A rule belongs to its skill, so it inherits the same visibility through a join.
    op.execute("ALTER TABLE skill_rules ENABLE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY skill_rules_read ON skill_rules
            FOR SELECT
            USING (
                EXISTS (
                    SELECT 1 FROM skills s
                    WHERE s.id = skill_rules.skill_id
                      AND (s.tenant_id IS NULL OR s.tenant_id = app_current_tenant())
                )
            );
        """
    )
    op.execute(
        """
        CREATE POLICY skill_rules_write ON skill_rules
            FOR ALL
            USING (
                EXISTS (
                    SELECT 1 FROM skills s
                    WHERE s.id = skill_rules.skill_id
                      AND s.tenant_id = app_current_tenant()
                )
            )
            WITH CHECK (
                EXISTS (
                    SELECT 1 FROM skills s
                    WHERE s.id = skill_rules.skill_id
                      AND s.tenant_id = app_current_tenant()
                )
            );
        """
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON skill_rules TO uboss_app;")


def downgrade() -> None:
    """Drops the registry, seed included. The seed is re-importable from the workbook."""
    op.execute("DROP TABLE IF EXISTS skill_rules CASCADE")
    op.execute("DROP TABLE IF EXISTS skills CASCADE")
    op.execute("DROP TABLE IF EXISTS skill_exactness_gates CASCADE")
    op.execute("DROP TABLE IF EXISTS skill_archetypes CASCADE")
