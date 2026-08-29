# Canonical Lifecycles

**Status:** Working Draft — not approved

Lifecycle codes are stable, language-neutral API/audit values. UI labels may be translated.
Published versions are immutable; editing creates a new Draft version.

## 1. Tenant and membership

| Aggregate | States | Allowed transition summary |
|---|---|---|
| Tenant | `PROVISIONING`, `ACTIVE`, `SUSPENDED`, `CLOSING`, `CLOSED` | Provision → activate; active ↔ suspended; close through retained/deletion workflow |
| Membership | `INVITED`, `ACTIVE`, `SUSPENDED`, `DEACTIVATED` | Invite → active; active ↔ suspended; deactivation is terminal for login |

## 2. Hierarchy

| Aggregate | States | Rules |
|---|---|---|
| Import batch | `UPLOADED`, `PARSING`, `NEEDS_MAPPING`, `VALIDATED`, `BLOCKED`, `APPLIED`, `CANCELLED` | Applying requires validation, preview and explicit confirmation |
| Hierarchy version | `DRAFT`, `IN_REVIEW`, `PUBLISHED`, `SUPERSEDED`, `ARCHIVED` | Published immutable; a newer Publish supersedes the previous active version |
| Position | `FILLED`, `VACANT`, `PROPOSED`, `INACTIVE` | Occupant required only for Filled; inactive remains auditable |

## 3. Objective, Job, Agent, Supervisor and Skill

| Aggregate/version | States | Rules |
|---|---|---|
| Objective version | `DRAFT`, `ANALYZING`, `PROPOSED`, `IN_REVIEW`, `PUBLISHED`, `SUPERSEDED`, `ARCHIVED`, `ANALYSIS_FAILED` | AI output is Proposal, never Published state; human confirmation required |
| Job version | `DRAFT`, `IN_REVIEW`, `PUBLISHED`, `SUPERSEDED`, `ARCHIVED` | Schedule/run pins a Published immutable version |
| Agent version | `DRAFT`, `TESTING`, `TEST_FAILED`, `READY_FOR_REVIEW`, `PUBLISHED`, `PAUSED`, `SUPERSEDED`, `ARCHIVED` | Publish requires tests, permissions, budget and independent approval where policy requires |
| Supervisor version | `DRAFT`, `TESTING`, `READY_FOR_REVIEW`, `PUBLISHED`, `PAUSED`, `SUPERSEDED`, `ARCHIVED` | Scope/handler change produces a new version or controlled policy revision with audit |
| Skill version | `PRIVATE_DRAFT`, `TESTING`, `READY_FOR_REVIEW`, `PUBLISHED`, `DEPRECATED`, `REVOKED`, `ARCHIVED` | New Skill starts private and cannot self-publish |

## 4. Approval and task

| Aggregate | States | Rules |
|---|---|---|
| Approval | `PENDING`, `APPROVED`, `REJECTED`, `CHANGES_REQUESTED`, `EXPIRED`, `CANCELLED` | Terminal decision is immutable; resubmission creates a new approval request |
| Task | `OPEN`, `IN_PROGRESS`, `BLOCKED`, `AWAITING_INPUT`, `AWAITING_APPROVAL`, `COMPLETED`, `CANCELLED` | Completion records actor, evidence and source run/version |

## 5. Schedule and runtime

| Aggregate | States | Rules |
|---|---|---|
| Schedule | `DRAFT`, `ACTIVE`, `PAUSED`, `DISABLED`, `ARCHIVED` | Activation requires timezone, version pin, overlap/missed-run policy and permission |
| Run | `QUEUED`, `RUNNING`, `WAITING_INPUT`, `WAITING_APPROVAL`, `RETRYING`, `SUCCEEDED`, `FAILED`, `CANCELLED`, `TIMED_OUT` | Event history is append-only; retry preserves idempotency identity and lineage |
| Run step | `PENDING`, `RUNNING`, `WAITING_INPUT`, `WAITING_APPROVAL`, `SUCCEEDED`, `FAILED`, `SKIPPED`, `CANCELLED` | Cannot exceed parent run/Agent permissions |

## 6. Privacy and operations

| Aggregate | States | Rules |
|---|---|---|
| Data Principal request | `RECEIVED`, `IDENTITY_CHECK`, `SCOPING`, `IN_PROGRESS`, `AWAITING_CUSTOMER`, `COMPLETED`, `PARTIALLY_FULFILLED`, `REJECTED`, `CANCELLED` | Decision, legal basis, deadline and evidence required |
| Breach case | `SUSPECTED`, `CONFIRMED`, `CONTAINED`, `ASSESSING`, `NOTIFYING`, `RECOVERING`, `CLOSED` | Closure requires evidence and corrective actions |
| Incident | `DECLARED`, `INVESTIGATING`, `MITIGATING`, `MONITORING`, `RESOLVED`, `REVIEWED` | P0/P1 require postmortem and action tracking |
| Legal hold | `ACTIVE`, `RELEASED` | Active hold overrides deletion only for documented scope/basis |

## 7. Transition controls

- Every mutation checks tenant, role, entitlement, current state and version/ETag.
- Publish, approval, access, schedule activation and destructive transitions require server
  confirmation; they cannot complete offline.
- Invalid transitions return a stable error code and current legal actions.
- Every sensitive transition writes audit and outbox records in the same transaction.
- State labels never substitute for evidence: `SUCCEEDED` requires completion evidence and
  persisted outputs; `PUBLISHED` requires the exact immutable version identifier.

