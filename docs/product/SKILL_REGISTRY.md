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
