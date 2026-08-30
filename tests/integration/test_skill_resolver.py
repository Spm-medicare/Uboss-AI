"""Search, gate, route, record — PLAN §39 end to end.

    Agent requirement → Search Skill Registry → Deterministic compatibility gates
    → Reuse | Configure | Compose | Create private Skill Draft

Gate 5's exit test is written into this suite as one sentence: *a search returns candidates a gate
then refuses for a stated reason*. So does the rule the whole design rests on — *similarity never
overrides a hard gate* — which is proved here against real ranking rather than argued about.

The skills these tests search are written by the fixture rather than taken from the 400. A test
that depended on the approved workbook happening to contain a particular row would fail the day a
client corrected the sheet, and would be testing the catalogue rather than the resolver.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.conftest import Workspace
from uboss.core.context import SecurityContext
from uboss.core.errors import PermissionDenied
from uboss.db.base import build_sessionmaker
from uboss.modules.agents import resolver, search
from uboss.modules.agents.gates import Requirement
from uboss.modules.agents.models import (
    ResolverRoute,
    Skill,
    SkillExactnessGate,
    SkillResolverDecision,
)
from uboss.modules.identity.models import Membership
from uboss.modules.identity.service import access_for

pytestmark = pytest.mark.anyio

#: The five gates whose wording the resolver quotes. Written here so the suite does not depend on
#: the seed being imported into the throwaway test database — `test_skill_registry.py` is what
#: proves these are the workbook's actual words.
GATES: tuple[tuple[str, str, str], ...] = (
    ("E01", "Scope determinism", "BLOCKED — ambiguous scope"),
    ("E02", "Minimum-input completeness", "DRAFT — missing input"),
    ("E03", "Authority and identity", "BLOCKED — authority unresolved"),
    ("E06", "Evidence traceability", "UNVERIFIED — no trace"),
    ("E12", "Human authority and change control", "CANDIDATE ONLY — approval pending"),
)

DEPARTMENT = "Finance, Accounting & Controlling"


async def _context(session: AsyncSession, workspace: Workspace) -> SecurityContext:
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(workspace.tenant_id)}
    )
    membership = await session.get(Membership, workspace.membership_id)
    assert membership is not None
    roles, granted, ceiling = await access_for(session, membership)
    now = datetime.now(UTC)
    return SecurityContext(
        tenant_id=workspace.tenant_id,
        user_id=workspace.user_id,
        membership_id=workspace.membership_id,
        session_id=uuid.uuid4(),
        email="person@test",
        display_name=membership.display_name,
        roles=roles,
        granted_actions=granted,
        org_node_id=membership.org_node_id,
        policy_grants=ceiling,
        step_up_at=now,
        step_up_expires_at=now + timedelta(minutes=10),
    )


@pytest_asyncio.fixture(loop_scope="session")
async def wording(owner_engine: AsyncEngine) -> dict[str, str]:
    """The twelve gates' words, present in the test database whether or not the seed ran.

    Inserted as the owner because the application role holds `SELECT` on this table and nothing
    else — which `test_skill_registry.py` proves, and which is why the fixture cannot use the
    session the tests use.
    """
    async with build_sessionmaker(owner_engine)() as owner:
        for position, (gate_id, name, failure_state) in enumerate(GATES, start=1):
            existing = await owner.get(SkillExactnessGate, gate_id)
            if existing is None:
                owner.add(
                    SkillExactnessGate(
                        id=gate_id,
                        name=name,
                        if_clause="IF …",
                        then_clause="THEN …",
                        pass_evidence="…",
                        failure_state=failure_state,
                        position=position,
                    )
                )
        await owner.commit()
    return {gate_id: failure_state for gate_id, _, failure_state in GATES}


async def _catalogue_skill(owner: AsyncSession, catalogue_id: str, **fields: object) -> uuid.UUID:
    """A shared catalogue row, written as the owner. The application cannot write these."""
    defaults: dict[str, object] = {
        "name": "Invoice exception triage",
        "layer": "Universal Department",
        "department": DEPARTMENT,
        "industry": "All Industries",
        "purpose": "Sort invoice exceptions and route them to the right person.",
        "minimum_inputs": "Invoice; purchase order; goods receipt",
        "exclusions": "Do not approve payment or change a vendor bank account.",
        "source_ids": "SRC-001",
        "autonomy": "A2",
        "status": "published",
    }
    defaults.update(fields)
    skill = Skill(tenant_id=None, catalogue_id=catalogue_id, **defaults)  # type: ignore[arg-type]
    owner.add(skill)
    await owner.flush()
    return skill.id


@pytest_asyncio.fixture(loop_scope="session")
async def catalogue(owner_engine: AsyncEngine) -> AsyncIterator[list[uuid.UUID]]:
    """Four shared skills that between them exercise every route.

    Removed afterwards by catalogue id: these rows have no tenant, so the workspace teardown
    would never touch them and every run would leave four more behind.
    """
    marker = uuid.uuid4().hex[:6].upper()
    ids: list[uuid.UUID] = []
    async with build_sessionmaker(owner_engine)() as owner:
        ids.append(
            await _catalogue_skill(
                owner,
                f"T-{marker}-1",
                name="Invoice exception triage for accounts payable",
                purpose="Triage invoice exceptions and route them.",
            )
        )
        #  Ranks above the first for the word "invoice", and is refused: A1 cannot write.
        ids.append(
            await _catalogue_skill(
                owner,
                f"T-{marker}-2",
                name="Invoice invoice invoice register lookup",
                purpose="Look up an invoice in the register. Invoice reference only.",
                autonomy="A1",
                minimum_inputs="Invoice",
            )
        )
        #  Belongs to another industry entirely.
        ids.append(
            await _catalogue_skill(
                owner,
                f"T-{marker}-3",
                name="Invoice exception triage for clinical billing",
                layer="Industry Overlay",
                industry="Healthcare & Life Sciences",
                department="Clinical Operations, Patient Safety & Quality",
            )
        )
        #  Retired, and still findable.
        ids.append(
            await _catalogue_skill(
                owner,
                f"T-{marker}-4",
                name="Invoice exception triage, superseded",
                status="archived",
            )
        )
        await owner.commit()

    yield ids

    async with build_sessionmaker(owner_engine)() as owner:
        await owner.execute(
            text("DELETE FROM skills WHERE catalogue_id LIKE :like"), {"like": f"T-{marker}-%"}
        )
        await owner.commit()


# ------------------------------------------------------------------------------- search


async def test_search_ranks_by_what_was_asked_for_and_gates_nothing(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    catalogue: list[uuid.UUID],
) -> None:
    """The search discovers. Everything it returns has passed no gate, retired ones included."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        await _context(session, left)
        hits = await search.search(session, need="invoice exception triage")

        assert hits, "the catalogue rows should be findable"
        assert [hit.rank for hit in hits] == list(range(1, len(hits) + 1))
        assert hits[0].text_match > 0
        #  A retired skill is found, not hidden — the lifecycle gate is what refuses it, and
        #  "nothing does this" would be a different and untrue answer.
        assert "archived" in {hit.skill.status for hit in hits}
        await session.rollback()


async def test_search_with_no_words_browses_the_filters(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    catalogue: list[uuid.UUID],
) -> None:
    """A caller who supplied only a department wants the department, not an empty list."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        await _context(session, left)
        hits = await search.search(session, need="", department=DEPARTMENT)
        assert hits
        assert all(hit.skill.department == DEPARTMENT for hit in hits)
        await session.rollback()


async def test_an_industry_filter_keeps_the_all_industries_wildcard(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    catalogue: list[uuid.UUID],
) -> None:
    """208 catalogue skills carry `All Industries`. Filtering them out would hide most of it."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        await _context(session, left)
        hits = await search.search(
            session, need="invoice", industry="Steel, Metals & Mining"
        )
        industries = {hit.skill.industry for hit in hits}
        assert "All Industries" in industries
        assert "Healthcare & Life Sciences" not in industries
        await session.rollback()


async def test_a_sentence_matches_any_of_its_words_not_all_of_them(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    catalogue: list[uuid.UUID],
) -> None:
    """Recall is what this step owes the resolver.

    A requirement is a sentence, and no single skill contains every word of one. An AND search
    would return nothing and make the Compose route unreachable — so a plain sentence is widened
    to match any of its words, and `ts_rank_cd` puts the denser matches first. The gates refuse
    what does not belong; a wide net costs ordering, not correctness.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        await _context(session, left)
        hits = await search.search(
            session, need="invoice exception triage and vendor onboarding paperwork"
        )
        assert hits, "not one catalogue skill contains every word of that sentence"
        #  Denser matches first: the triage skills outrank anything matching a single word.
        assert "triage" in hits[0].skill.name.lower()
        await session.rollback()


async def test_a_quoted_phrase_is_passed_through_as_the_caller_wrote_it(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    catalogue: list[uuid.UUID],
) -> None:
    """Somebody who typed an operator meant it, so their string is not widened."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        await _context(session, left)
        phrase = await search.search(session, need='"exception triage"')
        assert phrase
        assert all("exception triage" in hit.skill.name.lower() for hit in phrase)

        #  The same words unquoted match more, because each is matched on its own.
        loose = await search.search(session, need="exception triage")
        assert len(loose) >= len(phrase)
        await session.rollback()


# ------------------------------------------------------------------------------- the routes


async def test_an_ambiguous_requirement_is_blocked_in_the_catalogues_own_words(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    wording: dict[str, str],
) -> None:
    """E01, before anything is searched.

    Searching an ambiguous requirement and presenting the top twenty would be answering a question
    nobody asked. The gate's own remedy is one focused question, so that is what comes back.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        resolution, decision = await resolver.resolve(
            session, context, Requirement(need="sort out our invoices")
        )
        assert resolution.route is ResolverRoute.BLOCKED
        assert "BLOCKED — ambiguous scope" in resolution.rationale
        assert decision.candidates == []
        #  Blocked, and still recorded: the question was asked and this is the answer it got.
        assert decision.route == "blocked"
        await session.rollback()


async def test_similarity_never_overrides_a_hard_gate(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    catalogue: list[uuid.UUID],
    wording: dict[str, str],
) -> None:
    """The sentence the whole module exists to honour.

    The register-lookup skill repeats "invoice" and outranks everything for it — and it is cleared
    only to A1. Asked for A2 work, the resolver takes a lower-ranked candidate that passes, and the
    record shows both the ranking and the reason it was overridden.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        resolution, decision = await resolver.resolve(
            session,
            context,
            Requirement(
                need="invoice",
                department=DEPARTMENT,
                autonomy_ceiling="A2",
                available_inputs=("Invoice", "purchase order", "goods receipt"),
            ),
        )

        top = decision.candidates[0]
        assert top["rank"] == 1
        assert top["autonomy"] == "A1"
        assert not top["passed"], "the top-ranked hit should be refused, not selected"
        assert resolution.route is ResolverRoute.REUSE
        assert str(resolution.selected_skill_id) != top["skill_id"]

        refusal = next(
            gate for gate in top["gates"] if gate["gate"] == "authority" and not gate["configurable"]
        )
        assert refusal["failure_state"] == "BLOCKED — authority unresolved"
        await session.rollback()


async def test_every_candidate_is_recorded_with_the_gate_that_judged_it(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    catalogue: list[uuid.UUID],
    wording: dict[str, str],
) -> None:
    """Gate 5's exit test: a search returns candidates a gate then refuses for a stated reason.

    "Nothing matched" and "four matched and each was refused, here is why" are different answers,
    and only the second is one somebody can act on.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        _, decision = await resolver.resolve(
            session,
            context,
            Requirement(
                need="invoice exception triage",
                department=DEPARTMENT,
                autonomy_ceiling="A2",
                available_inputs=("Invoice", "purchase order", "goods receipt"),
            ),
        )

        refused = [entry for entry in decision.candidates if not entry["passed"]]
        assert refused, "the retired and the wrong-industry skills should both be refused"
        for entry in refused:
            failures = [gate for gate in entry["gates"] if gate["outcome"] == "failed"]
            assert failures, f"{entry['name']} was refused with no reason"
            assert all(gate["reason"] for gate in failures)

        #  Passes are recorded too, so a reviewer sees what was checked rather than what failed.
        assert any(
            gate["outcome"] == "passed"
            for entry in decision.candidates
            for gate in entry["gates"]
        )
        await session.rollback()


async def test_a_missing_input_routes_to_configure_and_names_the_checklist(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    catalogue: list[uuid.UUID],
    wording: dict[str, str],
) -> None:
    """E02 is the only configurable gate: the remedy is to supply what is listed.

    So the refusal publishes the list, in the catalogue's own words, ready to be ticked rather than
    typed from memory.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        resolution, decision = await resolver.resolve(
            session,
            context,
            Requirement(
                need="invoice exception triage",
                department=DEPARTMENT,
                autonomy_ceiling="A2",
                available_inputs=("Invoice",),
            ),
        )
        assert resolution.route is ResolverRoute.CONFIGURE
        assert resolution.selected_skill_id is not None
        assert "purchase order" in resolution.rationale

        chosen = next(
            entry
            for entry in decision.candidates
            if entry["skill_id"] == resolution.selected_skill_id
        )
        inputs = next(gate for gate in chosen["gates"] if gate["gate"] == "minimum_inputs")
        assert inputs["configurable"]
        assert inputs["failure_state"] == "DRAFT — missing input"
        assert inputs["missing"] == ["purchase order", "goods receipt"]
        await session.rollback()


async def test_nothing_matching_routes_to_create(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    wording: dict[str, str],
) -> None:
    """No candidates at all is the one honest case for a private Skill Draft."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        resolution, decision = await resolver.resolve(
            session,
            context,
            Requirement(
                need="zqxjkv unrepeatable nonsense token",
                department=DEPARTMENT,
            ),
        )
        assert resolution.route is ResolverRoute.CREATE
        assert decision.candidates == []
        assert decision.selected_skill_id is None
        await session.rollback()


async def test_two_capabilities_no_single_skill_routes_to_compose(
    owner_engine: AsyncEngine,
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    wording: dict[str, str],
) -> None:
    """§39's Compose: no one skill covers the requirement, and a set of passing ones does."""
    left, _ = two_workspaces
    marker = uuid.uuid4().hex[:6].upper()
    async with build_sessionmaker(owner_engine)() as owner:
        await _catalogue_skill(
            owner,
            f"C-{marker}-1",
            name="Vendor statement reconciliation",
            purpose="Reconcile a vendor statement against the ledger.",
            minimum_inputs="Statement",
        )
        await _catalogue_skill(
            owner,
            f"C-{marker}-2",
            name="Payment run preparation",
            purpose="Prepare a payment run from approved invoices.",
            minimum_inputs="Statement",
        )
        await owner.commit()

    try:
        async with build_sessionmaker(app_engine)() as session:
            context = await _context(session, left)
            resolution, decision = await resolver.resolve(
                session,
                context,
                Requirement(
                    need="vendor statement reconciliation payment run preparation",
                    department=DEPARTMENT,
                    autonomy_ceiling="A2",
                    available_inputs=("Statement",),
                    capabilities=("vendor statement reconciliation", "payment run preparation"),
                ),
            )
            assert resolution.route is ResolverRoute.COMPOSE
            assert len(resolution.composed_of) == 2
            #  A composition's answer is a set, so naming one member would misreport it.
            assert decision.selected_skill_id is None

            covering = {
                entry["skill_id"]: entry["covers"]
                for entry in decision.candidates
                if entry["covers"]
            }
            assert len(covering) == 2
            await session.rollback()
    finally:
        async with build_sessionmaker(owner_engine)() as owner:
            await owner.execute(
                text("DELETE FROM skills WHERE catalogue_id LIKE :like"),
                {"like": f"C-{marker}-%"},
            )
            await owner.commit()


async def test_candidates_that_all_fail_hard_gates_are_blocked_with_a_quoted_reason(
    owner_engine: AsyncEngine,
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    wording: dict[str, str],
) -> None:
    """Blocked is a decision, not a failure to decide — and it says which gate refused."""
    left, _ = two_workspaces
    marker = uuid.uuid4().hex[:6].upper()
    async with build_sessionmaker(owner_engine)() as owner:
        await _catalogue_skill(
            owner,
            f"B-{marker}-1",
            name="Ledger posting adjustments",
            purpose="Post a ledger adjustment.",
            autonomy="A1",
            minimum_inputs=None,
        )
        await owner.commit()

    try:
        async with build_sessionmaker(app_engine)() as session:
            context = await _context(session, left)
            resolution, _ = await resolver.resolve(
                session,
                context,
                Requirement(
                    need="ledger posting adjustments",
                    department=DEPARTMENT,
                    autonomy_ceiling="A4",
                ),
            )
            assert resolution.route is ResolverRoute.BLOCKED
            assert "BLOCKED — authority unresolved" in resolution.rationale
            await session.rollback()
    finally:
        async with build_sessionmaker(owner_engine)() as owner:
            await owner.execute(
                text("DELETE FROM skills WHERE catalogue_id LIKE :like"),
                {"like": f"B-{marker}-%"},
            )
            await owner.commit()


# ------------------------------------------------------------------------------- the record


async def test_the_decision_records_the_gates_that_could_not_run(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    catalogue: list[uuid.UUID],
    wording: dict[str, str],
) -> None:
    """Reported, never passed. A gate nobody ran has not been satisfied."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        _, decision = await resolver.resolve(
            session,
            context,
            Requirement(
                need="invoice exception triage",
                department=DEPARTMENT,
                autonomy_ceiling="A2",
                available_inputs=("Invoice", "purchase order", "goods receipt"),
            ),
        )
        gates_named = {gate["gate"] for gate in decision.unevaluated_gates}
        assert gates_named == {
            "data_classification",
            "tool_scope",
            "schema_compatibility",
            "scope_exclusions",
        }
        assert all(gate["outcome"] == "unevaluated" for gate in decision.unevaluated_gates)
        await session.rollback()


async def test_a_decision_cannot_be_edited_or_deleted(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    wording: dict[str, str],
) -> None:
    """Append-only, twice over: a trigger refuses the change and the privilege was never granted.

    A decision describes a moment. Editing one afterwards would make the record agree with the
    present rather than with what happened.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        _, decision = await resolver.resolve(
            session, context, Requirement(need="anything at all", department=DEPARTMENT)
        )
        await session.commit()
        decision_id = decision.id

    async with build_sessionmaker(app_engine)() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(left.tenant_id)}
        )
        with pytest.raises((DBAPIError, ProgrammingError)):
            await session.execute(
                text("UPDATE skill_resolver_decisions SET rationale = 'rewritten' WHERE id = :i"),
                {"i": decision_id},
            )
        await session.rollback()

        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(left.tenant_id)}
        )
        with pytest.raises((DBAPIError, ProgrammingError)):
            await session.execute(
                text("DELETE FROM skill_resolver_decisions WHERE id = :i"), {"i": decision_id}
            )
        await session.rollback()


async def test_a_decision_is_invisible_to_another_workspace(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    wording: dict[str, str],
) -> None:
    """Row-level security, on the evidence table as much as on the business one."""
    left, right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        await resolver.resolve(
            session, context, Requirement(need="anything at all", department=DEPARTMENT)
        )
        await session.commit()

    async with build_sessionmaker(app_engine)() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(right.tenant_id)}
        )
        theirs = (await session.execute(select(SkillResolverDecision))).scalars().all()
        assert theirs == []
        await session.rollback()


async def test_resolving_writes_an_audit_event(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    wording: dict[str, str],
) -> None:
    """Every state change writes an `AuditEvent`, and a decision is a state change."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left)
        _, decision = await resolver.resolve(
            session, context, Requirement(need="anything at all", department=DEPARTMENT)
        )
        await session.flush()
        recorded = (
            await session.execute(
                text(
                    "SELECT action, resource_id FROM audit_events "
                    "WHERE tenant_id = :t AND action = 'skill.resolve'"
                ),
                {"t": left.tenant_id},
            )
        ).all()
        assert [row[1] for row in recorded] == [decision.id]
        await session.rollback()


async def test_a_read_only_role_cannot_resolve(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    wording: dict[str, str],
) -> None:
    """Resolving leaves a permanent record, so it is `edit_draft` rather than `view`.

    The right-hand workspace holds `view` and nothing else — the fixture's read-only role.
    """
    _, right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, right)
        with pytest.raises(PermissionDenied):
            await resolver.resolve(
                session, context, Requirement(need="anything at all", department=DEPARTMENT)
            )
        await session.rollback()
