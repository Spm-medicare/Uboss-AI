"""The resolver's decisions — what was searched, which gates refused, and the route taken.

PLAN §39 ends its flow with a route, not a match:

    Agent requirement → Search Skill Registry → Deterministic compatibility gates
    → Reuse | Configure | Compose | Create private Skill Draft

`docs/product/SKILL_REGISTRY.md` adds the sentence this table exists to make true: *"Present route
and evidence."* A resolver that answered without leaving a record would be a recommendation
engine. One that writes down every gate it ran, and the catalogue's own words for each refusal, is
the governance asset the registry is supposed to be — six months later somebody can ask why a
skill was not reused and read the answer rather than reconstruct it.

**Append-only, like every other evidence table here.** A decision describes a moment: the
requirement as it was stated, the candidates as they then stood, the gates as the catalogue then
defined them. Editing one afterwards would make the record agree with the present rather than with
what happened. `UPDATE` and `DELETE` are refused by a trigger *and* withheld from `uboss_app`, so
neither a bug nor a compromised connection can rewrite it.

**The gate results are stored, not recomputed.** A gate is data — a row in `skill_exactness_gates`
— and the catalogue is corrected over time. Re-running today's gates against last quarter's
decision would produce today's answer and present it as history.

Revision: 0020
Parent:   0019
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The five routes §39 allows, and nothing else. `blocked` is a route: *"Block/route change when
#: no safe choice exists"* is a decision the resolver is required to be able to reach, not a
#: failure to decide.
ROUTES: tuple[str, ...] = (
    "reuse",
    "configure",
    "compose",
    "create",
    "blocked",
)


def upgrade() -> None:
    op.create_table(
        "skill_resolver_decisions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("requested_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        #  What was asked for, in the caller's own words and codes. Kept verbatim: a decision read
        #  back beside a paraphrase of the question proves nothing.
        sa.Column("requirement", postgresql.JSONB, nullable=False),
        #  Where the requirement came from, when it came from somewhere. A job step asking for a
        #  skill is the ordinary case; an ad-hoc search from the Agent Builder is not.
        sa.Column("source_type", sa.String(40), nullable=True),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("route", sa.String(20), nullable=False),
        #  Why, in one sentence, for the person reading a list of decisions rather than one.
        sa.Column("rationale", sa.Text(), nullable=False),
        #  The chosen skill, when the route chose one. Null for `create` and `blocked`, and for
        #  `compose`, where the choice is the set in `candidates` rather than a single row.
        sa.Column(
            "selected_skill_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("skills.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        #  Every candidate the search returned, each with its rank, its score and the gate results
        #  that decided it. This is the evidence; the route is only the summary.
        sa.Column(
            "candidates",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        #  Gates the resolver could not evaluate because the data they need is not modelled yet —
        #  tool scope, data classification, schema compatibility. Recorded rather than passed:
        #  a gate that cannot run has not been satisfied, and saying so is the difference between
        #  a governed answer and a confident one.
        sa.Column(
            "unevaluated_gates",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "route IN ('reuse', 'configure', 'compose', 'create', 'blocked')",
            name="ck_resolver_route_known",
        ),
        #  A route that names a skill must name one; a route that cannot must not. `compose` is
        #  deliberately on the second list: its answer is a set, and singling one member out would
        #  misreport what was decided.
        sa.CheckConstraint(
            "(route IN ('reuse', 'configure') AND selected_skill_id IS NOT NULL) OR "
            "(route IN ('compose', 'create', 'blocked') AND selected_skill_id IS NULL)",
            name="ck_resolver_selection_matches_route",
        ),
        sa.CheckConstraint("length(rationale) > 0", name="ck_resolver_rationale_present"),
        sa.CheckConstraint(
            "jsonb_typeof(candidates) = 'array'", name="ck_resolver_candidates_are_a_list"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(unevaluated_gates) = 'array'",
            name="ck_resolver_unevaluated_is_a_list",
        ),
    )

    #  The list a person opens: this workspace's decisions, newest first.
    op.create_index(
        "ix_resolver_decisions_recent",
        "skill_resolver_decisions",
        ["tenant_id", sa.text("created_at DESC")],
    )
    #  "Which step asked for this?" — answered without scanning the tenant's whole history.
    op.create_index(
        "ix_resolver_decisions_source",
        "skill_resolver_decisions",
        ["tenant_id", "source_type", "source_id"],
        postgresql_where=sa.text("source_id IS NOT NULL"),
    )
    #  "How often does E02 block us?" is the question the improvement gate will ask of this table,
    #  and a GIN index on the evidence is what makes it answerable without a scan.
    op.execute(
        """
        CREATE INDEX ix_resolver_decisions_candidates
            ON skill_resolver_decisions USING gin (candidates jsonb_path_ops);
        """
    )

    op.execute("ALTER TABLE skill_resolver_decisions ENABLE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY skill_resolver_decisions_tenant ON skill_resolver_decisions
            FOR ALL
            USING (tenant_id = app_current_tenant())
            WITH CHECK (tenant_id = app_current_tenant());
        """
    )

    #  Two independent refusals, because one of them can be got around. The trigger stops an
    #  UPDATE written by mistake; the withheld privilege stops one written on purpose.
    op.execute(
        """
        CREATE TRIGGER skill_resolver_decisions_append_only
            BEFORE UPDATE OR DELETE ON skill_resolver_decisions
            FOR EACH ROW EXECUTE FUNCTION refuse_change();
        """
    )
    op.execute("GRANT SELECT, INSERT ON skill_resolver_decisions TO uboss_app;")


def downgrade() -> None:
    """Drops the decision record. Nothing recreates it — this is evidence, not derived data."""
    op.execute("DROP TABLE IF EXISTS skill_resolver_decisions CASCADE")
