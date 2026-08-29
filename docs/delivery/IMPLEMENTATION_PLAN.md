# UBOSS AI — Gate-Aligned Implementation Plan

**Status:** Authoritative execution sequence under `PLAN.md`  
**Applies to:** `Uboss Ai New` only  
**Old UBOSS application:** Reference/data-migration source only; never the implementation base

## 1. Execution rule

The product is built as thin, production-quality vertical slices. We do not finish every table, every API or every backend layer before usable journeys exist.

The authority order is:

1. Latest explicitly approved client/user decision.
2. `PLAN.md`.
3. Approved canonical field dictionary and permission/entitlement matrices.
4. This implementation plan and `docs/delivery/GATE_CONTROLS.md`.
5. `docs/product/UI_SPEC.md` for UI behavior.
6. Architecture Decision Records for implementation choices.
7. Old workbooks/docs/code as reference according to the source order in `PLAN.md`.

If two sources conflict, feature work pauses until the conflict is recorded and decided. Code does not silently become the new requirement.

## 2. Current verified baseline

### Implemented and statically verified

- Separate `frontend/`, `backend/` and `infra/` foundations.
- FastAPI application, health/readiness, structured errors and correlation IDs.
- Next.js application, semantic tokens, sign-in, workspace selection and basic real-session dashboard.
- PostgreSQL/Redis local services.
- Eight initial tables: tenants, users, memberships, membership roles, sessions, audit events, outbox events and idempotency records.
- Application/migration role separation, tenant RLS and append-only audit trigger.
- Argon2 password verification, opaque hashed session tokens, sign-in/out, `/me` and session management.
- Multi-workspace memberships with tenant-specific profile and roles.
- Ruff, strict mypy, frontend lint and frontend typecheck currently pass.
- Live API, database readiness and web route currently respond.

### Partial or over-claimed

- Gate 0 product approval is not complete.
- Gate 1 is not complete.
- Server-side idempotency does not exist; only a table/model and client header convention exist.
- Outbox relay/worker does not exist and current authentication does not publish an outbox event.
- Permission-ceiling algorithm exists, but company/department/resource policies are not persisted or resolved.
- OpenAPI-generated TypeScript types do not exist.
- i18n foundation does not exist and current UI copy is hard-coded.
- Files/S3, OpenTelemetry, deployment/rollback and CI/CD do not exist.
- No automated test suite exists.
- The project is not yet protected by an initialized Git history/remote workflow.

### Security corrections required before expansion

- Restrict the global credentials table; email/password hashes are sensitive and must not be broadly accessible to the normal application role.
- Add composite tenant-ownership constraints so a role/session cannot reference a membership from another tenant.
- Correct failed-login timing claims and workspace-failure audit behavior.
- Add rate limiting, CSRF/origin controls and explicit idle/absolute session policy.
- Do not treat per-tenant `flush()` as permission for ordinary requests to write across tenants; cross-tenant writers are exceptional reviewed system components.

## 3. Delivery status vocabulary

Every milestone uses only these states:

- **Not started:** no approved implementation.
- **In progress:** implementation exists but deliverables or evidence are incomplete.
- **Implemented, unverified:** code exists but mandatory automated/operational evidence is deferred.
- **Gate passed:** every Gate exit criterion and required sign-off has passed.

“Page opens”, “manual check passed” and “code compiles” never mean “Gate passed”.

## 4. Immediate sequence — Stabilise before new feature work

### Step 0A — Protect the new codebase

**Goal:** Make further work reviewable and recoverable.

Deliver:

- Initialize the new folder as its own Git repository.
- Confirm `.gitignore` excludes secrets, environments, caches and build output.
- Create the first reviewed baseline commit and connect the approved private remote.
- Adopt protected `main`, short-lived feature branches and pull-request review.
- Add secret scanning, dependency lock verification and conventional migration review.

Exit:

- A clean clone can reproduce dependency installation and static checks without using the old project.
- No real secret is committed.
- A bad change can be reverted without deleting user work.

### Step 0B — Resolve authoritative-document contradictions

**Goal:** One build contract before more UI/schema decisions spread.

Deliver:

- Update `PLAN.md` UI source-of-truth paths from removed `packages/ui/...` locations to `frontend/src/ui/README.md` and `frontend/src/styles/tokens.css`.
- Decide whether pilot tenants are operator-provisioned, admin-created through a protected control plane, or self-service. Recommended pilot default: controlled operator/admin provisioning; self-service is a separate post-pilot decision.
- Define how the first-slice “Create company” journey is satisfied by that decision.
- Finish privacy/DPDP and incident/on-call detailed contracts referenced by the master plan.
- Record the reviewed status of every existing Architecture Decision; decisions may be superseded through a new ADR, not silently rewritten.

Exit:

- `PLAN.md`, UI spec, Gate Controls, implementation plan and actual folder paths agree.
- Company onboarding has one approved owner, API boundary and UI journey.

## 5. Gate 0 — Product Contract

**Target:** 2 weeks from formal Gate 0 start  
**Current status:** In progress; do not mark passed from existing prose alone

### Step 0.1 — Canonical vocabulary and field dictionary

**Status:** Working drafts created in `docs/product/contracts/`; Product, Design and Engineering approval pending.

Deliver:

- Map every approved workbook/form field to canonical name, meaning, type, required/conditional rule, enum, UI control, API property and persisted field.
- Record every rename, merge, omission or changed conditional rule as an approved Product decision.
- Finalize lifecycle/status enums for tenant, hierarchy, Objective, Job, Agent, Supervisor, version, approval, schedule, run, task, Skill and privacy records.

### Step 0.2 — Roles, permission ceiling, sharing and entitlements

**Status:** Working draft created in `docs/product/contracts/ACCESS_MODEL.md`; commercial limits and approval owners remain open decisions.

Deliver:

- Role/action matrix for Owner, Admin, Builder, Supervisor, Employee, Approver, Auditor, Guest and service accounts.
- Company → department/workspace → resource → action ceiling behavior.
- Personal and Department Supervisor member/Agent/handler matrices.
- Personal Agent creation limits, workspace sharing rules and subscription entitlements.
- Separation-of-duty and step-up actions.

### Step 0.3 — Launch decisions

**Status:** Open decision register created in `docs/product/contracts/LAUNCH_DECISIONS.md`; no recommendation is treated as approval.

Deliver:

- Pilot company and primary workflow.
- India-primary region and residency decision.
- Identity strategy for pilot and enterprise SSO/SCIM sequence.
- First required integrations.
- English launch and Hindi-pack decision.
- Privacy roles/DPA, processing bases, retention, breach authority and privacy contact.
- Operator/admin/self-service company onboarding decision.

### Step 0.4 — Clickable first-slice contract

**Status:** Acceptance contract created in `docs/product/contracts/FIRST_SLICE_ACCEPTANCE.md`; Figma prototype and representative reviews remain pending.

Figma prototype covers:

~~~text
Sign in
→ Company onboarding/provisioning outcome
→ Hierarchy manual/import
→ Objective Draft
→ Summary approval
→ Claude proposal
→ Human edit
→ Publish
→ Audit evidence
~~~

Test with Owner/Admin, Supervisor and Employee/Approver representatives at desktop and mobile widths.

Gate 0 passes only when Product, Design and Engineering sign the same field, permission, lifecycle and first-slice contracts.

## 6. Gate 1 — Minimum Platform Foundation

**Target:** 3–4 weeks after Gate 0; current partial code reduces work but security corrections can extend it  
**Current status:** In progress

### Step 1.1 — Database and tenant-boundary hardening

**Implemented and statically verified:** migration `0002` adds composite membership/tenant/user
integrity for membership roles and sessions; ORM metadata matches, Ruff and strict mypy pass,
offline SQL generation passes and the local development database is at `0002 (head)`. Narrow
global credential access, future-domain composite FKs, migration CI and restore evidence remain
pending.

Deliver:

- Add composite membership ownership keys and foreign keys for membership roles, sessions and every later tenant-owned relationship.
- Ensure tenant-owned references cannot point across tenants even if a UUID is known.
- Replace broad normal-app access to global credential rows with an ADR-approved narrow authentication repository: recommended restricted database functions or a dedicated least-privilege auth role/pool.
- Keep migration owner unavailable to API/runtime processes.
- Define dedicated role/policies for each exceptional cross-tenant worker; never give a general bypass role.
- Add migration preflight, forward migration, compatibility and rollback/restore procedure.

### Step 1.2 — Authentication and session completion

**Partially implemented and statically verified:** forbidden/no-active workspace paths use the
same external refusal and write attributable tenant denial evidence. Redis-backed hashed IP,
account and pair buckets now protect sign-in, with a separate workspace-selection bucket and
retry-after response. A short-lived browser-bound challenge is stored hashed, consumed once and
re-authorized before session creation; the frontend clears and never resubmits the password.
Redis is part of readiness and its outage fails new authentication closed while existing sessions
remain independent. Exact Origin/Referer enforcement now protects every unsafe versioned browser
API request, including anonymous sign-in. Sessions enforce fixed absolute and idle lifetimes and
rotate opaque tokens without extending expiry; one prior hash has a short RLS-readable grace
window and row locking prevents concurrent rotation churn. Password step-up now re-verifies the
current account under separate Redis IP/membership limits, opens a server-calculated 15-minute
window on the current session only, records allowed/denied evidence and has a reusable high-risk
route guard that never widens role permissions. Hashed, expiring, single-use invite/reset token
primitives exist, but no public issuance or consumption endpoint claims delivery yet: authorised
issuance, notification relay and identity-wide session revocation remain prerequisites. Local
migration is at `0003 (head)`; Ruff, strict mypy and Python compile pass. Managed MFA and the
complete invite/password recovery journey remain pending. Full browser/concurrency/security/load
tests are intentionally not claimed.

Deliver:

- One canonical external sign-in error envelope without claiming impossible perfect timing equality.
- Rate limits by IP/account/risk with Redis-backed counters and safe lockout behavior.
- Short-lived verified workspace-selection challenge so the browser does not retain/resubmit the password for workspace choice.
- Correct denied-security event strategy for unknown address, wrong password, locked/deactivated user, suspended membership/tenant and forbidden workspace without leaking tenant existence.
- CSRF strategy for cookie authentication: approved same-site deployment, Origin/Referer validation and CSRF token where required.
- Absolute and idle expiry, rotation policy, revoke-current/revoke-other/revoke-all and deprovisioning behavior.
- Invite, password setup/reset and recovery contract needed by the pilot.
- Step-up/MFA interface contract for high-risk actions; enterprise SSO/SCIM remains Gate 8 unless pilot-required.

### Step 1.3 — Real permission ceiling

Deliver:

- Persist company and department policy restrictions.
- Resolve tenant/department policy into the request context.
- Resource/action grants remain narrowing-only and cannot exceed the parent scope or role ceiling.
- Standard service guard APIs for permission, scope and self-approval.
- Audit both allowed high-risk actions and denials without revealing inaccessible resources.

### Step 1.4 — Server idempotency and optimistic concurrency

**Foundation implemented and statically verified:** shared backend code now validates keys,
canonicalizes/fingerprints JSON, scopes by tenant + operation, uses a non-waiting PostgreSQL
transaction advisory lock, replays same-key/same-request success, rejects changed input, returns
a retryable concurrent-operation conflict, enforces retention and refuses credential-like or
oversized replay responses. Ruff, strict mypy and Python compilation pass. No current business
route consumes the guard yet, so end-to-end idempotency and optimistic concurrency are not
claimed; the first Objective/Hierarchy mutation must integrate it with behavior evidence.

Deliver:

- Server reads `Idempotency-Key`, canonicalizes/fingerprints the request and scopes the key by tenant + operation.
- Same key/same request replays the stored response; same key/different request is rejected.
- Concurrent in-progress duplicate receives a deterministic retry response.
- Expiry/cleanup policy and sensitive-response restrictions.
- Sign-in uses its dedicated challenge/retry design rather than a PII-bearing email header key.
- Draft mutation APIs use explicit expected version/ETag and return conflict rather than overwrite.

### Step 1.5 — Audit and minimum outbox capability

Deliver:

- Canonical audit action dictionary and redaction/classification policy.
- Audit write remains atomic with business mutation and append-only.
- Create an outbox relay only before a first-slice event depends on delivery.
- Relay uses a dedicated least-privilege cross-tenant role limited to due outbox rows, lease/claim semantics, retry/backoff, dead-letter visibility and idempotent consumers.
- Do not claim delivery capability while rows are only being stored.

### Step 1.6 — Files, observability and delivery pipeline

Deliver:

- S3-compatible file abstraction with tenant-prefixed keys, metadata, hash, classification, signed URL expiry and malware-scan state.
- OpenTelemetry traces/metrics/log correlation across Web, API, DB, worker, model and tool calls.
- Health, readiness and dependency telemetry without leaking secrets.
- CI stages: formatting/lint, strict types, migration validation, security/secret/dependency scan, required foundation tests and build.
- Dev/staging/production configuration, secret manager contract and safe deploy/rollback runbook.

### Step 1.7 — Frontend foundation before App Shell expansion

Deliver:

- Translation-key infrastructure from the first screen; English messages now, Hindi pack when approved.
- Locale/timezone/date/number format foundation.
- Generate TypeScript API types/client from reviewed OpenAPI; remove hand-maintained duplicate response contracts progressively.
- Shared UI primitives, semantic tokens, focus/accessibility behavior and universal states.
- Session route guard and error/reconnect handling.

Gate 1 exit evidence:

- Required cross-tenant, session/security, migration and deployment/rollback smoke checks pass.
- Static checks and builds pass from a clean clone in CI.
- Files, audit, server idempotency and observability work in the minimum first-slice form.

## 7. App Shell milestone — after Gate 1 foundation is credible

This is a UI milestone inside the foundation/vertical-slice path, not a replacement for Gate 1.

Deliver:

- Responsive dark signature sidebar and top bar.
- Final navigation only: Dashboard, Hierarchy, Agents 01–04, To-do; no separate Objective menu.
- Role/action-based visibility; server remains authoritative.
- Global search placeholder only if clearly unavailable—no fake results.
- Notification and Copilot launch controls may show governed unavailable/empty states until their Gate.
- Profile/Settings entry, tenant switch where policy permits and sign-out.
- Loading, empty, denied, offline/reconnecting and error shell states.
- Keyboard, focus, reduced-motion and mobile drawer behavior.

Do not build decorative fake Agent activity or disconnected dashboard cards.

## 8. Gate 2 — Company onboarding and Hierarchy slice

**Target:** 2–3 weeks

### Step 2.1 — Approved company onboarding path

- Implement the Gate 0 decision: controlled provisioning/control-plane or approved self-service.
- Apply defaults for region, timezone, language, retention, roles and first Owner/Admin.
- Create an immutable provisioning audit trail and rollback/disable path.

### Step 2.2 — Manual Hierarchy

- Editable tree with add/edit/move, position status, reporting type, effective dates and revision history.
- Position is stable; person assignment is effective-dated.
- Enforce subtree permissions and prevent cycles/orphans/duplicate position IDs.

### Step 2.3 — CSV/XLSX import

~~~text
Upload
→ Scan and deterministic parse
→ Column mapping (Claude may propose ambiguous mappings only)
→ Staging preview
→ Validation/conflict resolution
→ Approved atomic apply
→ Revision/audit evidence
~~~

No AI or import process writes directly into the live hierarchy without preview and approval.

Gate 2 passes when manual/edit/import journeys work with cycle/orphan/duplicate, atomicity and subtree-permission evidence.

## 9. Gate 3 — Objective end-to-end vertical slice

**Target:** 5–6 weeks

### Step 3.1 — Objective cards and Draft form

- Objective work exists only in Objective Agent Builder.
- Create-first-time action in the upper corner, cards/filters/versions and Draft autosave.
- Implement every approved canonical field and conditional rule.
- Preview Summary before analysis; user confirms before Claude runs.

### Step 3.2 — Claude proposal through AI Gateway

- Provider-neutral Gateway, permitted Claude model policy and versioned prompt/schema.
- Minimum permission-checked context, budget/timeout/rate handling and prompt-injection controls.
- Structured output validation; AI produces proposal, never direct database writes.
- Real run events only: validate → context → workstreams → propose → policy/dependencies → review.

### Step 3.3 — Human editor and Publish

- Accessible list editor is canonical; graph is another view of the same data.
- Add/edit/delete/duplicate/reorder/dependency changes and Human/AI/Hybrid/Approval/Output blocks.
- Distinguish manual and AI changes visually and in evidence.
- Publish preview includes owners, permissions, approvals, schedule implications, warnings and estimated AI cost.
- Approved Publish creates immutable ObjectiveVersion and auditable evidence; no self-approval where prohibited.

Gate 3 passes only when one pilot Objective completes the real journey without mock production logic.

## 10. Gate 4 — Job Builder slice

**Target:** 3–4 weeks

- Job landing/cards and Draft/version lifecycle.
- Preserve Form 3 header fields and all approved 16 repeatable Step fields through canonical mapping.
- Multiple WHO rules and multiple typed INPUT cards.
- Human/AI/Hybrid steps, exact method, work/input locations, rules/checks, output destination, approval, exception and time/SLA.
- Schedule builder: timezone, recurrence preview, DST, overlap, missed-run/catch-up, concurrency and pinned versions.
- Assignment preview explains exactly who is eligible and why.

Gate 4 passes with workbook reconciliation and deterministic schedule/version tests.

## 11. Gate 5 — Agent Builder and Skills slice

**Target:** 4–5 weeks

- Personal/shared Job Agents with ownership, audience, knowledge, tools/scopes, model policy, budgets/retries and approvals.
- A user may create multiple personal Agents subject to entitlement and policy.
- Tool credentials remain external/vaulted and least-privileged.
- Sandbox test cases and evidence are required before Publish.
- Skill Registry remains inside Agent Builder.
- Import/reconcile approved 400-skill/2,400-rule seed data.
- Resolver routes Reuse / Configure / Compose / Create private Draft.
- Similarity only discovers; permission, jurisdiction, data, tool, approval, lifecycle and freshness hard gates decide compatibility.
- Skills/Agents cannot self-publish.

Gate 5 passes with catalogue reconciliation, hard-gate, prompt-injection, tool-scope, approval and cost evidence.

## 12. Gate 6 — Supervisor slice

**Target:** 4–5 weeks

- Personal Supervisor per entitled account and Department Supervisor.
- Keep supervised people/Agents separate from allowed human handlers.
- Handler roles: viewer, operator, reviewer, approver, manager and owner according to permission ceiling.
- Monitor, SLA/cost/quality alerts, pause/resume, safe retry, input request, approval/escalation and consolidated report.
- A Department Supervisor can supervise selected members and grant control to only explicitly selected handlers.
- Failure simulation proves it cannot exceed Agent, tenant, handler or approval boundaries.

Gate 6 passes with failure simulation, cross-scope and forbidden-action evidence.

## 13. Gate 7 — Governed Runtime, To-do, Notifications and Copilot

**Target:** 3–4 weeks

- Temporal workflows/schedules, version-pinned runs, run steps and truthful event stream.
- Task/approval/evidence lifecycle and To-do tabs: Assigned, Approvals, Input requested, Following, Completed.
- Notification outbox relay, in-app/email preferences, quiet hours, escalation, grouping and deduplication.
- Safe crash/retry/idempotency behavior for internal and external effects.
- Global Copilot with permission-filtered retrieval, sources, proposal/saved distinction, diff/preview, explicit confirmation and audit.
- Copilot cannot publish, approve, grant access or perform destructive/high-risk actions for the user.

Gate 7 passes with crash/retry/outbox recovery plus Copilot leakage, grounding, prompt-injection, preview and forbidden-action evidence.

## 14. Gate 8 — Settings, Privacy, Operations and Enterprise Pilot

**Target:** 4–6 weeks

### Step 8.1 — Personal and Workspace Settings

- ChatGPT-style category navigation.
- Profile/locale/appearance, notifications, sessions/security and personal AI preferences.
- Workspace branding, people/teams/guests, roles, hierarchy, Builder policies, integrations, schedules, audit, billing, developer and privacy controls.
- Risky changes show impact, require step-up where configured and produce audit evidence.

### Step 8.2 — Privacy/DPDP controls

- Versioned notice/purpose and processing-basis records.
- Consent/withdrawal where applicable; do not use consent where another approved basis applies.
- Data Principal access, correction/completion/update, erasure, grievance and nomination workflow.
- Retention, legal hold, deletion/anonymisation and reconciliation evidence.
- Processor/subprocessor/DPA, region/transfer and AI-provider privacy controls.
- Personal-data-breach case, approved notification authority/timelines and delivery evidence.
- Privacy contact/DPO where applicable and qualified legal/privacy sign-off.

### Step 8.3 — Enterprise identity, security and reliability

- Pilot-required SAML/OIDC, SCIM, MFA/step-up, domain verification and session policy.
- Security hardening, penetration test, load/noisy-neighbour limits and dependency/container/SBOM checks.
- Backup/PITR, restore drill, RPO/RTO and disaster recovery.
- P0–P3 severity, on-call/escalation, kill-switch drill, customer/status communication and P0/P1 postmortem exercise.
- Migration inventory/reconciliation/rollback according to legacy policy.
- Full dark mode and enabled language packs verified.

### Step 8.4 — Final test and pilot campaign

This is where the broad final campaign runs:

- Full unit/integration/API/contract suite.
- Complete cross-browser responsive E2E journeys.
- Accessibility and localisation regression.
- Full cross-tenant/permission/security regression and penetration test.
- Temporal restart/retry, provider failure, outbox recovery and restore drills.
- AI evaluation regression for schema, grounding, leakage, safety, cost and latency.
- Load, soak, noisy-neighbour and failure-injection tests.
- Pilot UAT, support rehearsal and go-live/rollback checklist.

Gate 8 passes only with Product, Engineering, Security, Privacy/Legal, Operations and pilot-customer acceptance.

## 15. Testing sequence — what is now and what is last

The large regression/UAT campaign is last, but foundation evidence cannot all be postponed.

| When | Mandatory evidence |
|---|---|
| Every commit/PR | Formatting, lint, strict types, secret/dependency checks |
| Every migration | Forward migration, constraint/RLS review and clean-database smoke |
| Gate 1 | Minimum automated tenant, auth/session, permission, idempotency and rollback checks |
| Each product Gate | Focused service/component/API checks for the new behavior |
| Gate 8 | Full E2E, regression, security, load, DR, AI eval and pilot UAT campaign |

If automated checks are deliberately postponed, the milestone is labelled **Implemented, unverified** and the Gate remains open. This prevents “testing later” from becoming a false completion claim.

## 16. Scope-control rules

- Do not create future Gate tables/services before a current journey needs them.
- Do not add a separate Objective sidebar item.
- Do not create a separate Skill Registry sidebar item.
- Do not copy old database/schema/code wholesale.
- Do not let Claude or another Agent write directly to governed live state.
- Do not show fake run progress or fake dashboard results.
- Do not publish mutable definitions; Published versions are immutable and runs/schedules pin versions.
- Do not broaden permissions at a lower scope.
- Do not add an integration before the pilot workflow requires it.
- Do not call a milestone complete without its exit evidence.

## 17. Recommended next action

Do not begin broad App Shell feature development yet. Execute in this exact order:

1. Step 0A Git/baseline protection.
2. Step 0B document/company-onboarding decisions.
3. Finish Gate 0 contracts and first-slice prototype.
4. Gate 1 database/auth/idempotency/i18n/OpenAPI/CI corrections.
5. Then build the responsive App Shell.
6. Continue into Hierarchy and the Objective vertical slice.

The App Shell may be designed in parallel with Gate 0, but production shell code should use the approved i18n, permission and component contracts rather than hard-coded temporary patterns.
