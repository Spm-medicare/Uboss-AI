"""The deterministic gates, on their own.

No database. `gates.py` takes a plain record and a requirement and returns verdicts, which means
the rule that matters most here can be tested directly rather than inferred from an HTTP response:

    Similarity never overrides a hard gate.

The wording map is the catalogue's, passed in. These tests use the real `failure_state` strings so
a refusal is checked against the words the approved workbook actually uses — including the em dash,
which is what `BLOCKED — ambiguous scope` is written with.
"""

from __future__ import annotations

from uboss.modules.agents import gates
from uboss.modules.agents.gates import Candidate, Outcome, Requirement

#: The five gates whose refusals quote the catalogue, with the workbook's own words. Verified
#: against the imported rows in `test_skill_registry.py`; repeated here so a gate test does not
#: need a database to know what a refusal should say.
WORDING = {
    "E01": "BLOCKED — ambiguous scope",
    "E02": "DRAFT — missing input",
    "E03": "BLOCKED — authority unresolved",
    "E06": "UNVERIFIED — no trace",
    "E12": "CANDIDATE ONLY — approval pending",
}

TENANT = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"


def catalogue_skill(**overrides: object) -> Candidate:
    """One of the 400 shared rows, with the shape the real ones have."""
    fields: dict[str, object] = {
        "skill_id": "aaaaaaaa-0000-0000-0000-000000000001",
        "name": "Invoice exception triage",
        "tenant_id": None,
        "catalogue_id": "U-001",
        "status": "published",
        "autonomy": "A2",
        "layer": "Universal Department",
        "department": "Finance, Accounting & Controlling",
        "industry": "All Industries",
        "purpose": "Sort invoice exceptions and route them.",
        "minimum_inputs": "Invoice; purchase order; goods receipt",
        "exclusions": "Do not approve payment or change a vendor bank account.",
        "source_ids": "SRC-001; SRC-014",
    }
    fields.update(overrides)
    return Candidate(**fields)  # type: ignore[arg-type]


def requirement(**overrides: object) -> Requirement:
    fields: dict[str, object] = {
        "need": "triage invoice exceptions",
        "autonomy_ceiling": "A2",
        "department": "Finance, Accounting & Controlling",
        "available_inputs": ("Invoice", "purchase order", "goods receipt"),
    }
    fields.update(overrides)
    return Requirement(**fields)  # type: ignore[arg-type]


def outcome_of(verdict: gates.Verdict, gate: str) -> gates.GateResult:
    return next(result for result in verdict.results if result.gate == gate)


# ------------------------------------------------------------------ the requirement itself


def test_a_requirement_naming_no_scope_is_ambiguous() -> None:
    """E01. "Find me a skill" is a question the catalogue answers four hundred ways."""
    assert not Requirement(need="do the thing").states_a_scope()
    assert Requirement(need="do the thing", department="Finance").states_a_scope()
    assert Requirement(need="do the thing", industry="Steel").states_a_scope()
    assert Requirement(need="do the thing", layer="Industry Overlay").states_a_scope()
    #  A scope with nothing to search for is still nothing to search for.
    assert not Requirement(need="  ", department="Finance").states_a_scope()


# ------------------------------------------------------------------ each gate


def test_a_matching_skill_passes_every_gate_that_can_run() -> None:
    verdict = gates.evaluate(
        catalogue_skill(), requirement(), tenant_id=TENANT, wording=WORDING
    )
    assert verdict.passed
    assert verdict.failures == ()


def test_another_workspaces_skill_is_refused() -> None:
    """Row-level security would not have returned it. The gate says so in words anyway."""
    verdict = gates.evaluate(
        catalogue_skill(tenant_id=OTHER, catalogue_id=None),
        requirement(),
        tenant_id=TENANT,
        wording=WORDING,
    )
    assert outcome_of(verdict, "visibility").outcome is Outcome.FAILED


def test_a_retired_skill_is_refused_and_says_retirement_was_a_decision() -> None:
    verdict = gates.evaluate(
        catalogue_skill(status="archived", tenant_id=TENANT, catalogue_id=None),
        requirement(),
        tenant_id=TENANT,
        wording=WORDING,
    )
    lifecycle = outcome_of(verdict, "lifecycle")
    assert lifecycle.outcome is Outcome.FAILED
    assert "retired" in lifecycle.reason
    #  Not configurable: no amount of supplying things un-retires a skill.
    assert not lifecycle.configurable


def test_an_unapproved_private_skill_quotes_E12() -> None:
    """PLAN §39: *"Skills cannot self-publish."* The schema refuses it; this is the sentence."""
    verdict = gates.evaluate(
        catalogue_skill(tenant_id=TENANT, catalogue_id=None, status="ready_to_publish"),
        requirement(),
        tenant_id=TENANT,
        wording=WORDING,
    )
    approval = outcome_of(verdict, "approval")
    assert approval.outcome is Outcome.FAILED
    assert approval.failure_state == "CANDIDATE ONLY — approval pending"


def test_asking_a_read_only_skill_to_write_is_refused_not_downgraded() -> None:
    """E03. A downgrade would deliver less than the job asked for and report success."""
    verdict = gates.evaluate(
        catalogue_skill(autonomy="A1"),
        requirement(autonomy_ceiling="A3"),
        tenant_id=TENANT,
        wording=WORDING,
    )
    authority = outcome_of(verdict, "authority")
    assert authority.outcome is Outcome.FAILED
    assert authority.failure_state == "BLOCKED — authority unresolved"
    assert "A3" in authority.reason and "A1" in authority.reason


def test_a_skill_cleared_higher_than_the_work_needs_passes() -> None:
    """The ceiling is a maximum, not an exact match. A2 work may use an A3 skill."""
    verdict = gates.evaluate(
        catalogue_skill(autonomy="A3"),
        requirement(autonomy_ceiling="A2"),
        tenant_id=TENANT,
        wording=WORDING,
    )
    assert outcome_of(verdict, "authority").outcome is Outcome.PASSED


def test_all_industries_is_a_wildcard_not_a_mismatch() -> None:
    """208 Universal Department skills carry it. Treating it as a value would hide all of them."""
    verdict = gates.evaluate(
        catalogue_skill(industry="All Industries"),
        requirement(industry="Steel, Metals & Mining"),
        tenant_id=TENANT,
        wording=WORDING,
    )
    assert outcome_of(verdict, "applicability").outcome is Outcome.PASSED


def test_a_skill_scoped_to_another_industry_is_refused_in_its_own_words() -> None:
    """None of the twelve says "wrong department", so this gate does not borrow one that nearly
    fits — telling somebody to refresh a skill that is simply not theirs would be worse."""
    verdict = gates.evaluate(
        catalogue_skill(industry="Healthcare & Life Sciences"),
        requirement(industry="Steel, Metals & Mining"),
        tenant_id=TENANT,
        wording=WORDING,
    )
    applicability = outcome_of(verdict, "applicability")
    assert applicability.outcome is Outcome.FAILED
    assert applicability.failure_state is None
    assert "Healthcare & Life Sciences" in applicability.reason


def test_a_missing_mandatory_input_names_exactly_what_is_needed() -> None:
    """E02, and the only configurable gate. The refusal publishes the checklist."""
    verdict = gates.evaluate(
        catalogue_skill(),
        requirement(available_inputs=("Invoice",)),
        tenant_id=TENANT,
        wording=WORDING,
    )
    inputs = outcome_of(verdict, "minimum_inputs")
    assert inputs.outcome is Outcome.FAILED
    assert inputs.failure_state == "DRAFT — missing input"
    assert inputs.configurable
    assert inputs.missing == ("purchase order", "goods receipt")
    assert verdict.only_configurable_failures


def test_input_matching_ignores_case_and_spacing_and_nothing_else() -> None:
    """Deliberately not fuzzy. A near-match that passed would defeat the gate E02 exists to be."""
    supplied = ("  INVOICE ", "Purchase   Order", "goods receipt")
    verdict = gates.evaluate(
        catalogue_skill(),
        requirement(available_inputs=supplied),
        tenant_id=TENANT,
        wording=WORDING,
    )
    assert outcome_of(verdict, "minimum_inputs").outcome is Outcome.PASSED

    #  A synonym is not a match, and the refusal says which one is still needed.
    near = gates.evaluate(
        catalogue_skill(),
        requirement(available_inputs=("Invoice", "PO", "goods receipt")),
        tenant_id=TENANT,
        wording=WORDING,
    )
    assert outcome_of(near, "minimum_inputs").missing == ("purchase order",)


def test_traceable_claims_need_a_skill_that_names_its_sources() -> None:
    """E06. A skill with no declared source authority cannot trace a claim to anything."""
    verdict = gates.evaluate(
        catalogue_skill(source_ids=None),
        requirement(evidence_required=True),
        tenant_id=TENANT,
        wording=WORDING,
    )
    evidence = outcome_of(verdict, "evidence")
    assert evidence.outcome is Outcome.FAILED
    assert evidence.failure_state == "UNVERIFIED — no trace"

    #  Not asked when the requirement does not ask for claims.
    quiet = gates.evaluate(
        catalogue_skill(source_ids=None), requirement(), tenant_id=TENANT, wording=WORDING
    )
    assert outcome_of(quiet, "evidence").outcome is Outcome.PASSED


# ------------------------------------------------------------------ honesty about what did not run


def test_the_gates_that_cannot_run_are_reported_rather_than_passed() -> None:
    """CLAUDE.md: missing permission, mandatory input, approval or evidence fails closed.

    Data classification, tool scope and schema compatibility need tables the Skill Factory brings.
    Until then they are `unevaluated` — which is not a third kind of pass, and is why a resolution
    carrying any of them is offered for confirmation rather than applied.
    """
    verdict = gates.evaluate(
        catalogue_skill(), requirement(), tenant_id=TENANT, wording=WORDING
    )
    unevaluated = {result.gate for result in verdict.unevaluated}
    assert unevaluated == {
        "data_classification",
        "tool_scope",
        "schema_compatibility",
        "scope_exclusions",
    }
    #  They do not refuse, and they do not pass.
    assert verdict.passed
    assert all(result.outcome is Outcome.UNEVALUATED for result in verdict.unevaluated)


def test_exclusions_are_carried_for_a_person_and_never_matched_on() -> None:
    """In the workbook an exclusion is a sentence. A matcher deciding a sentence would be guessing.

    The rule this proves is that no gate reads the column: a candidate whose exclusions describe
    exactly what is being asked for still passes, and the *person* is the one who refuses it.
    """
    excluding = catalogue_skill(
        exclusions="Do not triage invoice exceptions for intercompany invoices."
    )
    verdict = gates.evaluate(excluding, requirement(), tenant_id=TENANT, wording=WORDING)
    assert verdict.passed
    #  Carried, so the screen can put it in front of somebody.
    assert verdict.candidate.exclusions is not None
    assert "scope_exclusions" in {result.gate for result in verdict.unevaluated}


def test_a_gate_with_no_catalogue_wording_still_refuses_without_inventing_words() -> None:
    """Started with an empty catalogue, a refusal gives its own reason and quotes nothing.

    Inventing the catalogue's words would be worse than having none: a message that looks like it
    came from the approved sheet and did not is a message nobody can check.
    """
    verdict = gates.evaluate(
        catalogue_skill(autonomy="A1"),
        requirement(autonomy_ceiling="A4"),
        tenant_id=TENANT,
        wording={},
    )
    authority = outcome_of(verdict, "authority")
    assert authority.outcome is Outcome.FAILED
    assert authority.failure_state is None
    assert authority.catalogue_gate_id is None
    assert "A4" in authority.reason


def test_every_gate_runs_even_after_one_refuses() -> None:
    """A person deciding what to do about a rejection needs the whole picture.

    "It failed one gate and we stopped looking" hides whether fixing that one would help.
    """
    verdict = gates.evaluate(
        catalogue_skill(autonomy="A1", source_ids=None),
        requirement(autonomy_ceiling="A4", evidence_required=True, available_inputs=()),
        tenant_id=TENANT,
        wording=WORDING,
    )
    refused = {result.gate for result in verdict.failures}
    assert refused == {"authority", "minimum_inputs", "evidence"}
    #  Three refusals, one of them configurable — so the route is not `configure`.
    assert not verdict.only_configurable_failures


# ------------------------------------------------------------------ helpers the catalogue shapes


def test_a_catalogue_list_column_splits_on_semicolons() -> None:
    """The approved sheet's separator, verified against a real row's wording."""
    real = (
        "Grade/customer specification; raw-material certificates; heat/lot genealogy; recipes"
    )
    assert gates.split_list(real) == [
        "Grade/customer specification",
        "raw-material certificates",
        "heat/lot genealogy",
        "recipes",
    ]
    assert gates.split_list(None) == []
    assert gates.split_list("  ") == []
