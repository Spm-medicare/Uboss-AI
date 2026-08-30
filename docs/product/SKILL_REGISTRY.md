# UBOSS AI — Skill Registry, Resolver and Factory Contract

## Decision

The Universal Enterprise Skill Catalogue is retained. It is seed data for a governed, extensible Skill Registry—not 400 hard-coded product features.

Source: Universal_Enterprise_Skill_Catalog_IF_THEN (1).xlsx.

Verified source structure:

- 400 Skill records.
- 2,400 normalized IF-THEN rules.
- 12 Skill archetypes.
- 26 department coverage groups.
- 24 industry packs.
- 12 exactness gates.
- 24 master rule modules.
- Standards/evidence source registry.

## Product placement

Skill capabilities live inside Agent Builder:

~~~text
Agent Builder
├─ My Agents
├─ Shared with me
├─ Department
├─ Skills
│  ├─ Registry
│  ├─ Resolver
│  └─ Private Skill Drafts
└─ Agent tests and Publish
~~~

No Skill Registry sidebar item in MVP.

## Skill archetypes

- Router / Intake
- Research / Discovery
- Extractor / Normalizer
- Analyst / Scorer
- Planner / Optimizer
- Generator / Document
- Validator / Auditor
- Monitor / Detector
- Workflow / Orchestrator
- Integrator / Synchronizer
- Communicator / Follow-up
- Governance / Approval

## Resolver route

1. Build a Skill Requirement Profile from the Job/Agent.
2. Search allowed active catalogue/private Skills.
3. Rank semantic/structured candidates.
4. Apply deterministic hard gates.
5. Present route and evidence.

Routes:

- Reuse approved active Skill.
- Configure an allowed variant.
- Compose compatible Skills.
- Create a new private Skill Draft.
- Block/route change when no safe choice exists.

Hard gates:

- Tenant/visibility.
- Permission and delegated authority.
- Jurisdiction/applicability.
- Data classification and allowed AI use.
- Tool availability and scope.
- Required approval.
- Input/output schema compatibility.
- Lifecycle: active, suspended, retired.
- Evidence freshness.

Similarity never overrides a hard gate.

## Skill Factory

Collect:

- Name, purpose and owner.
- Positive triggers and exclusions.
- Minimum inputs and source authority.
- Input/output schemas.
- IF-THEN decisions and tie-breakers.
- Tools and minimum scopes.
- Human approvals.
- Missing/conflicting input behavior.
- Tool failure/retry/escalation.
- Golden, negative, injection, permission, tool-failure and rollback tests.
- Monitoring and acceptance metrics.
- Visibility and version.

Lifecycle:

~~~text
Proposed → Draft → Sandbox Tested → Pilot → Approved → Active
                                                ↓
                         Change Pending | Suspended | Retired
~~~

Published versions are immutable. User-created Skills begin private. No Skill or Agent can approve/promote itself.

## Initial data model

- skills
- skill_versions
- skill_rules
- skill_inputs
- skill_outputs
- skill_tool_requirements
- skill_approval_requirements
- skill_tests
- skill_evidence_sources
- skill_visibility_grants
- skill_resolver_decisions
- skill_compositions

These tables are conceptual until Gate 5. They are not implemented during Gate 1.

## Seed import acceptance

- Reconcile 400 Skills and 2,400 rules.
- Stable source IDs remain traceable.
- Duplicate IDs block import.
- Invalid/missing mandatory fields are quarantined.
- Source workbook checksum/version recorded.
- Seed records do not become Active without release-policy validation.
- Import produces counts, errors, warnings and rollback reference.

---

## As built — Gate 5.2

PLAN §39 names six things semantic similarity may not override. Five are enforced by a gate; the
sixth cannot be, and says so rather than passing quietly.

| §39 says similarity cannot override | Gate | Quotes | Status |
|---|---|---|---|
| permissions | `authority` | E03 `BLOCKED — authority unresolved` | enforced |
| jurisdiction | `applicability` | its own words | enforced |
| data classification | `data_classification` | — | **unevaluated** |
| required approval | `approval` | E12 `CANDIDATE ONLY — approval pending` | enforced |
| version status | `lifecycle` | its own words | enforced |
| stale evidence | `evidence` | E06 `UNVERIFIED — no trace` | enforced |

Two gates run beyond that list: `visibility` (the tenant boundary, in words, alongside the RLS
policy that already enforces it) and `minimum_inputs` (E02 `DRAFT — missing input`), which is the
only **configurable** gate — the one whose refusal has a named remedy, and therefore the one that
produces the *Configure* route rather than *Block*.

**What is not evaluated yet, and why it is reported.** `data_classification`, `tool_scope`,
`schema_compatibility` and `scope_exclusions` read tables the Skill Factory brings. Until then they
are recorded on every decision as `unevaluated` — never as passed. A resolution carrying any of
them comes back with `requires_confirmation: true`, so it is offered to a person rather than
applied. CLAUDE.md's rule is that a missing approval or evidence fails closed, and a gate nobody
ran has not been satisfied.

`scope_exclusions` is a deliberate permanent exception rather than a temporary gap. In the approved
workbook an exclusion is a sentence — *"Do not release a heat/coil/plate … without competent
metallurgical and quality authority"* — and a sentence is something a person reads, not something a
matcher decides. It is carried verbatim onto every candidate card for that reason.

### Where the gate wording comes from

A refusal quotes `skill_exactness_gates.failure_state`, read from the row at evaluation time. So a
client correcting the workbook corrects the message, and a refusal reads the same on screen as it
does in the approved sheet. Where none of the twelve says what a gate means, the gate gives its own
reason and quotes nothing — inventing the catalogue's words would produce a message nobody can
check against the source.

### Search

Full-text over the generated `tsvector` from migration 0019, weighted name → purpose → trigger →
primary IF, ranked with `ts_rank_cd`. No embedding call: a search inside the Builder should be
repeatable, and a decision recorded today should be re-derivable tomorrow.

A plain sentence is widened to match **any** of its words rather than all of them. A requirement is
a sentence, no skill contains every word of one, and an AND search would return nothing — making
the *Compose* route unreachable. Recall is what search owes the resolver; the gates refuse what does
not belong. A caller who types an operator (`"phrase"`, `-word`, `or`) has their string passed
through untouched.

Inactive skills are **returned and then refused**, not filtered out. "No skill does this" and "one
does, and it was retired" are different answers, and the lifecycle gate is not configurable, so an
inactive skill can never be selected either way.

### The decision record

`skill_resolver_decisions` (migration 0020) is append-only — a trigger refuses `UPDATE`/`DELETE`
and the privilege was never granted to `uboss_app`. Each row holds the requirement verbatim, every
candidate with its rank, its `ts_rank_cd` value, its exclusions and every gate that judged it,
passes included, plus the gates that could not run. Gate results are **stored, not recomputed**:
the catalogue changes, and re-running today's gates against last quarter's decision would produce
today's answer and present it as history.

Of the conceptual tables listed above, `skill_resolver_decisions` is implemented. The rest arrive
with the Skill Factory in 5.3 and 5.4.
