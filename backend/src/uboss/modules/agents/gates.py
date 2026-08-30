"""The deterministic compatibility gates — what refuses a candidate, and in whose words.

PLAN §39 puts these between a search and a choice, and `docs/product/SKILL_REGISTRY.md` ends the
list with the sentence the whole module exists to honour:

    Similarity never overrides a hard gate.

A search ranks by resemblance. Resemblance is a guess, and a guess is exactly the wrong thing to
let decide whether an agent may write to a customer record. So the search **discovers** and the
gates **decide**: a top-ranked candidate that fails one gate loses to a lower-ranked one that
passes all of them, every time, with the reason recorded.

## Three kinds of gate, kept apart on purpose

**Gates that quote the catalogue.** Where one of the twelve exactness gates says exactly what a
refusal means, the refusal uses that gate's own `failure_state` — read from the row, not copied
into this file. `DRAFT — missing input` reads the same on screen as it does in the approved
workbook, and correcting the sheet corrects the message.

**Gates that speak for themselves.** Visibility, lifecycle and applicability have no counterpart
among the twelve. They say so plainly rather than borrowing a sentence that nearly fits — quoting
`STALE — refresh required` at somebody whose real problem is that the skill belongs to a different
department would be worse than saying nothing.

**Gates that cannot run yet.** Data classification, tool scope and input/output schema
compatibility need tables that arrive with the Skill Factory. They are **reported as unevaluated,
never as passed** (`UNEVALUATED`). CLAUDE.md: missing permission, mandatory input, approval or
evidence fails closed — and a gate nobody ran has not been satisfied. What that costs is honest:
a resolution carrying unevaluated gates is offered for confirmation, not applied silently.

## Why input matching is exact rather than clever

`minimum_inputs` is a semicolon-separated list in the catalogue's own vocabulary — *"Grade/customer
specification; raw-material certificates; heat/lot genealogy"*. A fuzzy match against whatever the
caller happened to type would sometimes pass a skill whose mandatory input was never supplied,
which is the one failure mode E02 exists to prevent. So the comparison is exact after normalising
case and spacing, and the refusal **publishes the checklist**: it names every input still needed,
in the catalogue's words, so the caller ticks a list rather than guesses at spelling.

`exclusions` is deliberately **not** gated on. In the approved workbook it is a sentence — *"Do not
release a heat/coil/plate … without competent metallurgical and quality authority"* — and a
sentence is something a person reads, not something a matcher decides. It is carried onto every
candidate for exactly that reason, and scope-against-exclusions is recorded as needing a person.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

#: The autonomy ladder, in order. A skill may operate at its own level or below it; a requirement
#: needing more than a skill allows is refused rather than quietly downgraded.
AUTONOMY_ORDER: tuple[str, ...] = ("A1", "A2", "A3", "A4")

#: The catalogue's wildcard. An Industry Overlay skill carrying this applies to every industry, so
#: it is not a mismatch with anything.
ANY_INDUSTRY = "All Industries"

#: How the catalogue separates the items of a list column.
_LIST_SEPARATOR = re.compile(r"\s*;\s*")

#: Collapses runs of whitespace so "raw-material  certificates" and "raw-material certificates"
#: are the same input rather than two.
_SPACES = re.compile(r"\s+")


class Outcome(StrEnum):
    """What a gate concluded.

    `UNEVALUATED` is not a third kind of pass. It is a gate that could not run, which is why the
    resolver treats it as an open question rather than a satisfied condition.
    """

    PASSED = "passed"
    FAILED = "failed"
    UNEVALUATED = "unevaluated"


def normalise(value: str) -> str:
    """Case and spacing removed; nothing else. Deliberately not a stemmer or a synonym table."""
    return _SPACES.sub(" ", value).strip().lower()


def split_list(value: str | None) -> list[str]:
    """A catalogue list column, as its items. Empty entries dropped, order and wording kept."""
    if not value:
        return []
    return [item.strip() for item in _LIST_SEPARATOR.split(value) if item.strip()]


@dataclass(frozen=True, slots=True)
class Requirement:
    """What a skill is being looked for *for*.

    Stated by the caller rather than inferred, because E01 refuses an ambiguous scope and a scope
    this module guessed at would defeat the gate that checks it.
    """

    #: What the skill must do, in the caller's words. Drives the search; never gated on.
    need: str
    #: The most autonomy the caller may grant. A skill needing more is refused by E03.
    autonomy_ceiling: str = "A1"
    department: str | None = None
    industry: str | None = None
    layer: str | None = None
    archetype_id: str | None = None
    #: The inputs the caller can actually supply, in the catalogue's vocabulary.
    available_inputs: tuple[str, ...] = ()
    #: Whether the output will carry factual claims. When it does, E06 requires a skill that names
    #: where its authority comes from.
    evidence_required: bool = False
    #: The distinct things the requirement needs done. Two or more with no single skill covering
    #: them is what makes §39's *Compose* route the honest answer rather than *Reuse*.
    capabilities: tuple[str, ...] = ()

    def states_a_scope(self) -> bool:
        """E01. One of department, industry or layer, and something to search for.

        Without any of them the question is "find me a skill", which the catalogue answers four
        hundred ways — and the gate's own instruction is to *"ask one focused question"*.
        """
        return bool(self.need.strip()) and any((self.department, self.industry, self.layer))


@dataclass(frozen=True, slots=True)
class Candidate:
    """The fields of a skill the gates actually read.

    A plain record rather than the ORM object so the gates can be tested without a database, and
    so it is obvious at a glance which columns a refusal can depend on.
    """

    skill_id: str
    name: str
    #: Null for one of the 400 shared catalogue rows.
    tenant_id: str | None
    catalogue_id: str | None
    status: str
    autonomy: str
    layer: str
    department: str | None = None
    industry: str | None = None
    archetype_id: str | None = None
    purpose: str | None = None
    minimum_inputs: str | None = None
    #: Carried for a person to read. Never matched against.
    exclusions: str | None = None
    source_ids: str | None = None
    approved_by_membership_id: str | None = None
    approved_at: str | None = None


@dataclass(frozen=True, slots=True)
class GateResult:
    """One gate's verdict on one candidate, with everything a person needs to act on it."""

    gate: str
    name: str
    outcome: Outcome
    #: One sentence naming what is wrong and, where there is one, what would fix it.
    reason: str = ""
    #: The exactness gate whose words this refusal uses, when one of the twelve says exactly this.
    catalogue_gate_id: str | None = None
    #: That gate's `failure_state`, verbatim from the row.
    failure_state: str | None = None
    #: Set when supplying something would turn this refusal into a pass — the `configure` route.
    configurable: bool = False
    #: For E02: the inputs still needed, in the catalogue's own words, ready to be ticked off.
    missing: tuple[str, ...] = ()

    @property
    def refused(self) -> bool:
        return self.outcome is Outcome.FAILED


@dataclass(frozen=True, slots=True)
class Verdict:
    """Every gate run against one candidate."""

    candidate: Candidate
    results: tuple[GateResult, ...] = field(default_factory=tuple)

    @property
    def failures(self) -> tuple[GateResult, ...]:
        return tuple(result for result in self.results if result.refused)

    @property
    def unevaluated(self) -> tuple[GateResult, ...]:
        return tuple(r for r in self.results if r.outcome is Outcome.UNEVALUATED)

    @property
    def passed(self) -> bool:
        """No refusal. Unevaluated gates do not refuse — the resolver reports them separately."""
        return not self.failures

    @property
    def only_configurable_failures(self) -> bool:
        """Every refusal is one the caller could clear by supplying something.

        This is what separates §39's *Configure* from its *Block*: one is a shortfall with a named
        remedy, the other is a rule that no amount of configuration changes.
        """
        failures = self.failures
        return bool(failures) and all(result.configurable for result in failures)


#: The gates that cannot run until the Skill Factory models what they read. Named here rather than
#: left out, so a resolution says which questions it did not answer instead of implying there were
#: none. Each names the hard gate from `docs/product/SKILL_REGISTRY.md` it stands for.
UNEVALUATED_GATES: tuple[tuple[str, str, str], ...] = (
    (
        "data_classification",
        "Data classification and allowed AI use",
        "No skill in the registry declares a data classification yet, so whether this skill may "
        "process the data this work touches has not been checked.",
    ),
    (
        "tool_scope",
        "Tool availability and scope",
        "Skill tool requirements are not modelled yet, so whether the tools this skill needs are "
        "available at the scope it needs them has not been checked.",
    ),
    (
        "schema_compatibility",
        "Input/output schema compatibility",
        "Skill input and output schemas are not modelled yet. Minimum-input completeness was "
        "checked; field-level compatibility was not.",
    ),
    (
        "scope_exclusions",
        "Scope against the skill's exclusions",
        "The catalogue states exclusions as a sentence for a person to read, not as a rule a "
        "matcher can decide. Read the exclusions before accepting this candidate.",
    ),
)


def _quoted(
    gate_id: str, wording: Mapping[str, str]
) -> tuple[str | None, str | None]:
    """The catalogue's own failure state for a gate, when the row is loaded.

    Returns nothing rather than a placeholder when it is not: a refusal that invented the
    catalogue's words would be worse than one that simply gives its own.
    """
    text = wording.get(gate_id)
    return (gate_id, text) if text else (None, None)


def _visibility(candidate: Candidate, tenant_id: str) -> GateResult:
    """Shared catalogue, or this workspace's own. Nothing else is a candidate.

    Row-level security already refuses to return anything else, so this ordinarily passes. It is
    run anyway because the resolver can be handed a specific skill to check, and because a gate
    that only exists in the database cannot be shown to a person as evidence.
    """
    visible = candidate.tenant_id is None or candidate.tenant_id == tenant_id
    if visible:
        return GateResult(
            gate="visibility",
            name="Tenant and visibility",
            outcome=Outcome.PASSED,
            reason=(
                "Shared catalogue skill."
                if candidate.tenant_id is None
                else "Belongs to this workspace."
            ),
        )
    return GateResult(
        gate="visibility",
        name="Tenant and visibility",
        outcome=Outcome.FAILED,
        reason="This skill belongs to another workspace.",
    )


def _lifecycle(candidate: Candidate) -> GateResult:
    """Active only. A draft is unfinished and a retired skill was withdrawn for a reason."""
    if candidate.status == "published":
        return GateResult(
            gate="lifecycle",
            name="Lifecycle",
            outcome=Outcome.PASSED,
            reason="Active.",
        )
    withdrawn = {
        "draft": "This skill is still a draft. It has not been through sandbox tests or approval.",
        "ready_to_publish": "This skill is waiting for approval and is not active yet.",
        "archived": "This skill was retired. Retirement is a decision somebody made; reusing it "
        "would undo that decision silently.",
    }
    return GateResult(
        gate="lifecycle",
        name="Lifecycle",
        outcome=Outcome.FAILED,
        reason=withdrawn.get(candidate.status, f"Status is {candidate.status!r}, not active."),
    )


def _approval(candidate: Candidate, wording: Mapping[str, str]) -> GateResult:
    """E12. A private skill that is active must name who approved it, and when.

    The schema already refuses to store one that does not (`ck_skills_published_was_approved`).
    Running it again here is not redundancy for its own sake: this is the gate that produces the
    *sentence* a reviewer reads, and a constraint violation is not a sentence.
    """
    gate_id, failure_state = _quoted("E12", wording)
    if candidate.tenant_id is None:
        return GateResult(
            gate="approval",
            name="Required approval",
            outcome=Outcome.PASSED,
            reason="Shared catalogue skill, released with the seed.",
        )
    if candidate.approved_by_membership_id and candidate.approved_at:
        return GateResult(
            gate="approval",
            name="Required approval",
            outcome=Outcome.PASSED,
            reason="Approved by a person other than its author.",
        )
    return GateResult(
        gate="approval",
        name="Required approval",
        outcome=Outcome.FAILED,
        reason="This skill has not been approved. PLAN §39: skills cannot self-publish.",
        catalogue_gate_id=gate_id,
        failure_state=failure_state,
    )


def _authority(
    candidate: Candidate, requirement: Requirement, wording: Mapping[str, str]
) -> GateResult:
    """E03. The work needs a level of autonomy; the skill has a ceiling.

    Asking a read-only skill to write is refused rather than downgraded, because a downgrade would
    silently deliver less than the job asked for and report success.
    """
    gate_id, failure_state = _quoted("E03", wording)
    try:
        needed = AUTONOMY_ORDER.index(requirement.autonomy_ceiling)
        allowed = AUTONOMY_ORDER.index(candidate.autonomy)
    except ValueError:
        return GateResult(
            gate="authority",
            name="Permission and delegated authority",
            outcome=Outcome.FAILED,
            reason=(
                f"Autonomy is recorded as {candidate.autonomy!r} against a requirement of "
                f"{requirement.autonomy_ceiling!r}, and one of them is not a level this system "
                "knows."
            ),
            catalogue_gate_id=gate_id,
            failure_state=failure_state,
        )
    if needed <= allowed:
        return GateResult(
            gate="authority",
            name="Permission and delegated authority",
            outcome=Outcome.PASSED,
            reason=(
                f"Needs {requirement.autonomy_ceiling}; this skill is cleared to "
                f"{candidate.autonomy}."
            ),
        )
    return GateResult(
        gate="authority",
        name="Permission and delegated authority",
        outcome=Outcome.FAILED,
        reason=(
            f"The work needs {requirement.autonomy_ceiling} autonomy and this skill is cleared "
            f"only to {candidate.autonomy}."
        ),
        catalogue_gate_id=gate_id,
        failure_state=failure_state,
    )


def _applicability(candidate: Candidate, requirement: Requirement) -> GateResult:
    """Jurisdiction and applicability, in its own words.

    None of the twelve says "wrong department", and borrowing E05's *"STALE — refresh required"*
    for it would tell somebody to refresh a skill that is simply not theirs.
    """
    mismatches: list[str] = []
    if (
        requirement.industry
        and candidate.industry
        and candidate.industry != ANY_INDUSTRY
        and normalise(candidate.industry) != normalise(requirement.industry)
    ):
        mismatches.append(f"industry {candidate.industry!r}, not {requirement.industry!r}")
    if (
        requirement.department
        and candidate.department
        and normalise(candidate.department) != normalise(requirement.department)
    ):
        mismatches.append(f"department {candidate.department!r}, not {requirement.department!r}")

    if mismatches:
        return GateResult(
            gate="applicability",
            name="Jurisdiction and applicability",
            outcome=Outcome.FAILED,
            reason="This skill is scoped to " + "; ".join(mismatches) + ".",
        )
    return GateResult(
        gate="applicability",
        name="Jurisdiction and applicability",
        outcome=Outcome.PASSED,
        reason=(
            "Applies to every industry."
            if candidate.industry == ANY_INDUSTRY
            else "Scope matches the requirement."
        ),
    )


def _minimum_inputs(
    candidate: Candidate, requirement: Requirement, wording: Mapping[str, str]
) -> GateResult:
    """E02. Every mandatory input named by the catalogue has to be one the caller can supply.

    Configurable, and the only gate that is: the remedy is to supply what is listed, so a refusal
    here is a shortfall with a named fix rather than a rule. The names come back in the catalogue's
    own words so they can be offered as a checklist instead of typed.
    """
    gate_id, failure_state = _quoted("E02", wording)
    required = split_list(candidate.minimum_inputs)
    if not required:
        return GateResult(
            gate="minimum_inputs",
            name="Minimum-input completeness",
            outcome=Outcome.PASSED,
            reason="This skill declares no mandatory inputs.",
        )

    supplied = {normalise(item) for item in requirement.available_inputs}
    missing = tuple(item for item in required if normalise(item) not in supplied)
    if not missing:
        return GateResult(
            gate="minimum_inputs",
            name="Minimum-input completeness",
            outcome=Outcome.PASSED,
            reason=f"All {len(required)} mandatory inputs are available.",
        )
    return GateResult(
        gate="minimum_inputs",
        name="Minimum-input completeness",
        outcome=Outcome.FAILED,
        reason=(
            f"{len(missing)} of {len(required)} mandatory inputs are not available: "
            + "; ".join(missing)
            + "."
        ),
        catalogue_gate_id=gate_id,
        failure_state=failure_state,
        configurable=True,
        missing=missing,
    )


def _evidence(
    candidate: Candidate, requirement: Requirement, wording: Mapping[str, str]
) -> GateResult:
    """E06. A skill producing factual claims has to say where its authority comes from.

    Only asked when the caller says the output carries claims. `source_ids` is where the catalogue
    records that authority, and a skill with none cannot trace a claim to anything.
    """
    gate_id, failure_state = _quoted("E06", wording)
    if not requirement.evidence_required:
        return GateResult(
            gate="evidence",
            name="Evidence traceability",
            outcome=Outcome.PASSED,
            reason="The requirement does not ask for traceable claims.",
        )
    sources = split_list(candidate.source_ids)
    if sources:
        return GateResult(
            gate="evidence",
            name="Evidence traceability",
            outcome=Outcome.PASSED,
            reason=f"Traces to {len(sources)} declared sources.",
        )
    return GateResult(
        gate="evidence",
        name="Evidence traceability",
        outcome=Outcome.FAILED,
        reason=(
            "The requirement asks for traceable claims and this skill declares no source "
            "authority."
        ),
        catalogue_gate_id=gate_id,
        failure_state=failure_state,
    )


def unevaluated() -> tuple[GateResult, ...]:
    """The gates that cannot run yet, as results rather than as an omission."""
    return tuple(
        GateResult(gate=gate, name=name, outcome=Outcome.UNEVALUATED, reason=reason)
        for gate, name, reason in UNEVALUATED_GATES
    )


def evaluate(
    candidate: Candidate,
    requirement: Requirement,
    *,
    tenant_id: str,
    wording: Mapping[str, str],
) -> Verdict:
    """Run every gate against one candidate.

    All of them run — none short-circuits on the first refusal. A person deciding what to do about
    a rejected candidate needs the whole picture, and "it failed one gate, and we stopped looking"
    hides whether fixing that one would help.

    `wording` maps an exactness gate id to its `failure_state`, read from the catalogue.
    """
    return Verdict(
        candidate=candidate,
        results=(
            _visibility(candidate, tenant_id),
            _lifecycle(candidate),
            _approval(candidate, wording),
            _authority(candidate, requirement, wording),
            _applicability(candidate, requirement),
            _minimum_inputs(candidate, requirement, wording),
            _evidence(candidate, requirement, wording),
            *unevaluated(),
        ),
    )


def covered_capabilities(
    candidates: Sequence[Candidate], requirement: Requirement
) -> dict[str, list[str]]:
    """Which declared capability each candidate covers, by name.

    Matched against the skill's name and purpose-bearing columns the same exact way inputs are —
    the caller declares capabilities in their own words, so this is a containment test on
    normalised text rather than a ranking. Compose is a coverage decision, and a coverage decision
    made by resemblance would produce a set that looks complete and is not.
    """
    coverage: dict[str, list[str]] = {}
    for capability in requirement.capabilities:
        wanted = normalise(capability)
        covering = [
            c.skill_id
            for c in candidates
            if wanted in normalise(f"{c.name} {c.purpose or ''}")
        ]
        coverage[capability] = covering
    return coverage
