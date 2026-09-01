# UBOSS AI NEW — Fresh Product and Engineering Master Plan

**Status:** Authoritative vNext plan  
**Build mode:** Greenfield rebuild  
**Old application:** Reference-only; do not extend it as the vNext foundation  
**Date:** 29 August 2026

## 1. Product definition

UBOSS AI is an enterprise Human + AI Work Operating System. A company defines its hierarchy, creates Objectives, converts them into reusable Jobs, assigns governed Job Agents, and supervises execution through Personal or Department Supervisor Agents.

Core journey:

~~~text
Company and Hierarchy
→ Objective Agent Builder
→ Job Builder
→ Job Agent
→ Personal/Department Supervisor Agent
→ Human tasks and approvals
→ Outputs, evidence and Objective progress
~~~

Claude analyzes, drafts and explains. UBOSS deterministic services enforce permissions, validation, scheduling, approvals, budgets and database writes.

## 2. Greenfield rules

- Build inside this new folder/repository boundary.
- Do not import the old backend, database schema or UI automatically.
- Old spreadsheets, forms, docs and code are requirement/reference inputs.
- Reuse an old component only after architecture, security and behavior review.
- Do not delete the old application until migration, reconciliation and rollback are proven.
- New canonical vocabulary, API contracts, schema and UI state model apply everywhere.
- Drafts are editable; Published versions are immutable.
- Preview every AI/import/publish mutation before applying it.
- Never display fake Agent progress; UI uses real run events.

### 2.1 Authoritative source order

When requirements conflict, use this order:

1. Latest explicitly approved user/client decision.
2. This new PLAN.md.
3. Approved canonical field dictionary.
4. UBOSS_Agent_Builder_Forms.xlsx.
5. UBOSS_Complete_Builder_Forms_Organogram (1).xlsx.
6. Universal_Enterprise_Skill_Catalog_IF_THEN (1).xlsx for Skill Registry seed/rules.
7. Old sandbox/documents for non-conflicting reference ideas.
8. Old application code and database only as evidence of prior behavior.

Conflicts between sources are recorded and decided; they are never silently merged. Old code being reference-only does not mean valid client-owned data is discarded.

The approved canonical field dictionary is the implementation bridge between source workbooks, UI controls, API properties and persisted fields. A workbook is a requirement source, not a screen layout. No approved workbook field may be omitted, renamed, combined or given different conditional behavior without a recorded Product decision and updated traceability mapping.

## 3. Final sidebar

Navigation is persona- and scope-aware. A hidden row is a usability decision only; every route,
record and action remains protected by backend authorization.

~~~text
COMPANY / DELEGATED ADMIN

HOME
  Dashboard

BUILDERS
  Hierarchy
  Objective Optimization
  Agent Builder / Sync

OPERATIONS
  Job Agents
  Supervisor Agents
  To-do List

------------------------------------------------
Settings
~~~

~~~text
NORMAL EMPLOYEE

HOME
  My Dashboard

OPERATIONS
  My Job Agent
  My Supervisor Agent
  My To-do List

------------------------------------------------
Settings
~~~

Top bar:

~~~text
Breadcrumb/title | Global search | Context action | Notifications | UBOSS Copilot
~~~

Sidebar behavior:

- Expanded and collapsed modes with remembered user preference.
- Icons have labels/tooltips and accessible focus states.
- Department admins see the admin information architecture but only for assigned departments,
  hierarchy subtrees, resources and actions.
- Normal employees never receive Builder destinations unless an administrator grants an effective
  Builder capability.
- Mobile/tablet uses a dismissible drawer.
- Menu visibility is role-based; backend permission enforcement remains mandatory.
- Footer contains Settings only. Profile, security, sessions, workspace switching and sign-out
  live inside Settings or the top-bar account control.
- Job Builder has no permanent navigation item. It remains an internal, versioned execution model
  compiled from an approved Objective Optimization result.
- Do not add more permanent MVP menu items. Search, Notifications and Help stay outside the sidebar.

## 4. Dashboard

Purpose: show what needs attention now.

- Pending and overdue tasks.
- Approvals and inputs waiting for the user.
- Running, scheduled and failed Agents.
- Upcoming schedules.
- Recent outputs and Objective progress.
- Personal summary for employees.
- Selected team/department summary for Supervisors.
- Company and usage summary for authorized admins.
- Quick actions that route into the correct Builder.

Every metric is clickable, defined and timestamped.

## 5. Hierarchy

One editable company tree:

- Add/edit/move/archive department, position and person.
- Preserve vacant positions.
- Primary manager plus optional dotted-line reporting.
- Effective-dated assignments.
- Search/filter by unit, location, level, vacancy and date.
- Detect cycles, orphan managers and duplicate identifiers.
- Revision history, undo/redo and complete audit.

Safe CSV/XLSX import:

1. Upload into quarantine and scan/validate.
2. Parse sheets and columns deterministically.
3. Claude proposes only ambiguous column mappings.
4. User reviews mapping and ignored columns.
5. Show row errors, warnings and proposed tree.
6. User edits and confirms change summary.
7. Backend applies atomically and records source/mapping/audit.

Claude never writes the live hierarchy directly.

## 6. Shared Builder experience

All approved fields from existing Builder forms remain until the field-dictionary review approves a change. New UI reorganizes fields; it does not silently remove business requirements.

Shared journey:

~~~text
Create/Open Draft
→ Complete form
→ Preview complete summary
→ Approve AI analysis
→ Real analysis timeline
→ Editable generated output
→ Validate/test
→ Publish summary
→ Authorized approval
→ Immutable Published version/card
~~~

Shared form standards:

- Section navigation/stepper and readable form width.
- Autosave plus explicit Save Draft.
- Saving/Saved/Offline/Failed state.
- Required/conditional fields and inline plus summary validation.
- Never lose entered data after an error.
- Repeatable WHO, INPUT and step cards.
- Searchable selectors.
- Explicit timezone on all date/time fields.
- File scan/parse/processing status.
- Human-readable summaries, not JSON.
- Drawers for selection/detail; modals for focused confirmation.
- Accessible keyboard, screen reader, contrast and reduced motion.

## 7. Objective Agent Builder

This single module contains all Objective cards, creation, analysis, publishing and progress. There is no duplicate Objective page.

Views/statuses:

- Draft
- Analyzing
- Needs review
- Ready to publish
- Published
- Active/Paused
- Archived

Form groups:

1. Identity: title, description, owner, department and priority.
2. Outcome: desired result, baseline and KPI/success measures.
3. Scope: included/excluded work, teams, geography and stakeholders.
4. Time: start, target/end, milestones and urgency.
5. Constraints: budget, policy, resources, dependencies and risk.
6. Context/inputs: files, data and related Objectives.
7. Governance: approver, visibility and sensitive-data policy.
8. AI preferences: permitted help, budget and human checkpoints.

Claude proposes an execution graph with Human, AI Agent, Hybrid, Approval and Output blocks. Users may add, edit, delete, duplicate, merge, reorder, change dependencies, compare AI/human changes and rerun only a selected section.

Publish shows owners, steps, schedules, permissions, cost, warnings and approval route. Approval creates immutable ObjectiveVersion.

## 8. Job Builder

Job Builder defines reusable work; it is not a runtime Agent.

Job form:

1. Identity and linked Objective step/version.
2. Purpose and expected output.
3. WHEN trigger.
4. Multiple WHO assignment rules.
5. Multiple typed INPUT definitions.
6. Human/AI/Hybrid steps and dependencies.
7. Tools/integrations.
8. Evidence, quality, SLA and completion.
9. Retry, failure, escalation and approval.
10. Schedule, access, sharing and publishing.

The Job Builder must preserve and map every approved field from `UBOSS_Agent_Builder_Forms.xlsx`, Form 3 — Job Method. Its repeatable Step card covers: Step, WHO Person, WHO Role, WHEN Trigger, WHEN Frequency, WHAT Exact Work, INPUT Exact Input, WHERE Input Found, HOW Exact Method, WHERE Work Performed, Rule/Formula/Check, Output, Output Destination, Approval, If Missing/Wrong and Time. Header-level Job fields and dropdown/conditional rules are also retained. `docs/product/UI_SPEC.md` defines their presentation; the approved canonical field dictionary defines their exact names, types, required/conditional rules, API properties and storage mapping.

WHO types:

- User
- Team
- Department
- Role
- Hierarchy position/subtree
- Dynamic eligible group

INPUT fields include name, schema/type, source, required status, validation, classification, retention and AI-access permission.

If WHEN repeats, ask Auto-run Yes/No. If enabled, require timezone, recurrence preview, DST, overlap, missed-run policy, calendar, concurrency, pinned versions and approval behavior.

## 9. Agent Builder

Agent Builder creates actual Job Agents.

An eligible user may create, own, run and schedule multiple personal Job Agents according to plan entitlement and workspace policy.

Example:

~~~text
Rahul
├─ Lead Research Agent
├─ Email Agent
├─ Follow-up Agent
└─ Report Agent
~~~

Agent form:

1. Identity and linked Job version.
2. Purpose, instructions, boundaries and prohibited actions.
3. Owner, audience and sharing.
4. Multiple input/output schemas.
5. Claude/model policy.
6. Knowledge sources and retention.
7. Tools and explicit scopes.
8. Human approval and escalation.
9. Cost, token, time, concurrency and retries.
10. Sandbox tests, expected results and publishing.

Access choices: Only me, selected users, teams, department, role/subtree or workspace. Tool suggestions never grant access. Tests and permission review are publish gates.

## 10. Supervisor Agent

Supervisor Agent monitors and coordinates published Job Agents. It combines a deterministic orchestration runtime with Claude analysis/explanation.

Types:

- **Personal Supervisor Agent:** logically isolated per eligible account; supervises that user's permitted Job Agents.
- **Department Supervisor Agent:** supervises selected users/Agents in a department.
- Workspace-wide Supervisor is restricted and may be added later.

Two independent scopes are mandatory:

1. **Supervised members/Agents:** whose Agents are monitored?
2. **Allowed handlers:** who may control this Supervisor?

Handler roles:

- Viewer
- Operator: pause/resume and safe retry
- Reviewer: review output/request changes
- Approver
- Manager: manage scope/policy
- Owner

Supervisor capabilities:

- Monitor status, heartbeat, dependencies and input.
- Start eligible dependency-ready work.
- Pause/resume/cancel within permission.
- Safe idempotent retry.
- Create input and approval tasks.
- Track SLA, deadline, cost, tokens and concurrency.
- Detect quality/policy problems.
- Escalate to configured people.
- Combine results into an Objective report.
- Notify handlers and stakeholders.

Claude cannot bypass policy, grant permission, perform uncontrolled retries or approve high-risk actions.

Supervisor form:

1. Identity, owner, department and linked Objective scope.
2. Supervised members and Agent versions.
3. Human handlers and granular permissions.
4. Trigger/schedule and execution order.
5. Dependency, concurrency and routing policy.
6. Quality and evidence gates.
7. Budget, SLA and retry limits.
8. Approval and escalation.
9. Notifications and reports.
10. Sandbox/failure simulation and Publish.

## 11. To-do list

Tabs:

- Assigned to me
- Approvals
- Input requested
- Following
- Completed

Users can complete work, provide input, upload evidence, comment, approve/reject with reason, request changes and delegate where allowed. Sidebar count includes actionable pending items, not informational notifications.

## 12. Notifications and Copilot

Bell opens a right drawer with All, Unread and Action required.

Categories: task/assignment, approval/input, Agent failure/result, schedule/lifecycle, mention/comment and security/admin. Store actor, object, event, timestamp, read state and deep link. Support per-category in-app/email, immediate/digest, quiet hours, escalation, grouping and deduplication.

Delivery uses a transactional outbox.

UBOSS Copilot is contextual. It may search, explain, draft and propose changes. Every mutation requires permission, preview and confirmation.

Gate 3 includes only the Objective-specific Claude proposal experience required by the first vertical slice. The global cross-product Copilot is a Gate 7 deliverable with permission-filtered retrieval, source references, proposal-versus-saved labeling, preview/diff, confirmation and audit evidence. It cannot publish, approve, grant access or perform destructive/high-risk actions on the user's behalf.

## 13. ChatGPT-style Settings

Dedicated Settings page/panel with category navigation left and focused content right.

Personal:

- Profile and timezone/locale
- Appearance and reduced motion
- Notifications and quiet hours
- Security, MFA and sessions
- Personal AI defaults within company policy

Workspace/admin:

- General and branding/logo
- People, teams and guests
- Roles, permissions and sharing
- Hierarchy rules
- Objective/Job policy
- Agent, Supervisor and Claude governance
- Integrations and credentials health
- Schedules/calendars
- Data, privacy, cookies and retention
- Audit/compliance and SIEM export
- Billing, usage and entitlements
- Developer API, keys and webhooks

Risky settings require impact summary, step-up authentication and audit.

## 14. Enterprise permissions

Permission ceiling:

~~~text
Company policy
→ Department/workspace policy
→ Objective/Job/Agent/Supervisor permission
→ Individual action permission
~~~

Lower scope cannot grant more power than the parent policy.

Principals: user, team, role, guest and service account. Permissions include view, comment, edit Draft, Publish, run, approve, assign, schedule, manage access, export, integrate, administer and audit.

Separate Agent owner, maintainers, allowed runners, approvers, viewers and Supervisor handlers. Deactivating a user triggers ownership reassignment for Agents, schedules and connections.

## 15. Subscription and entitlements

Backend checks plan entitlements for:

- Seats and Builder seats
- Personal Job Agents per user
- Personal/Department Supervisor Agents
- Monthly and parallel runs
- Schedules
- Claude tokens/cost
- Storage
- Integrations
- API limits

Define warning, hard stop, approved overage and upgrade behavior.

## 16. Responsible AI and risk

Action risk:

| Level | Example | Default |
|---|---|---|
| Low | Read/summarize | Automatic |
| Medium | Internal reversible Draft/update | Logged and policy-controlled |
| High | External email/CRM write | Human approval |
| Critical | Payment, deletion, legal/HR decision | Strong approval or prohibited |

AI Governance dashboard includes risk, sensitive-data exposure, prompt-injection tests, human rejection, quality incidents, tool actions, cost, policy violations, provenance, kill switches and periodic recertification.

## 17. Core data model

Identity: tenants, users, memberships, teams, roles, permissions, resource grants, sessions, guests and service accounts.

Hierarchy: org units, positions, effective assignments, reporting edges, revisions, imports and import rows.

Design: Objectives/versions/steps, Jobs/versions/steps/inputs/assignment rules, Agents/versions/tools/tests, prompts.

Supervisor: supervisor agents/versions, scopes, member links, Agent links, handler grants, policies and events.

Runtime: runs, run steps, tasks, approvals, schedules, outputs, evidence, model calls and tool calls.

Governance: files, audit events, outbox, idempotency, notifications, privacy notices/purposes, processing bases, consent records, Data Principal requests, retention/legal holds, breach cases, processor/subprocessor records, entitlements and usage meters.

Rules:

- Every tenant-owned row has tenant_id and tested isolation.
- Published versions are immutable.
- Normalize governed/searchable fields; JSON only for flexible proposals/snapshots.
- Use optimistic concurrency.
- Store instants UTC and explicit IANA timezones.
- Archive without silently erasing audit evidence.

## 18. Technical architecture

- Next.js and TypeScript web.
- Typed modular monolith API; FastAPI/Python is suitable.
- PostgreSQL with RLS where practical.
- Temporal workflows and schedules.
- Redis for short-lived coordination/cache.
- S3-compatible files.
- Claude through an internal provider-neutral AI Gateway.
- Transactional outbox.
- OpenTelemetry logs, traces and metrics.

Deploy Web, API and durable workers. APIs are versioned and documented, mutations support idempotency, runs emit SSE/WebSocket events, webhooks are signed/replay-protected.

## 19. Enterprise security and operations

- Tenant isolation across database, files, cache, search, workers and AI context.
- SAML/OIDC, MFA, SCIM, domain verification and session policy for enterprise.
- Secret vault, credential rotation and least-privilege OAuth scopes.
- Encryption, file scanning and short-lived signed URLs.
- Append-only security/business audit and SIEM export.
- Workspace/Agent/integration/schedule kill switches.
- Per-tenant rate, concurrency, storage and cost limits.
- SLOs for availability, schedules and notifications.
- Point-in-time recovery, object versioning, restore drills, RPO/RTO and disaster runbooks.
- Dependency/container scanning, penetration testing and incident response.
- Privacy exports/deletion, subprocessors, residency roadmap and compliance evidence.

### 19.1 Privacy and compliance baseline

India DPDP is the launch baseline, implemented according to the provisions and Rules applicable on the deployment date and validated by qualified privacy/legal counsel. The architecture is jurisdiction-aware so GDPR or another market pack can be added without rewriting the core privacy lifecycle.

Responsibility is explicit per processing purpose:

- The customer company will normally act as Data Fiduciary/controller for workforce and workflow data; UBOSS will normally act as its Data Processor under contract.
- UBOSS may separately act as Data Fiduciary/controller for its own account administration, security, billing, support and permitted product telemetry.
- The approved DPA, customer instructions and data-flow inventory decide the role; product copy or code must not assume one universal role.
- Claude/model, cloud, communications, support and analytics vendors that process personal data are governed subprocessors with approved purpose, region, safeguards, contract and change-notice records.

Required privacy capabilities:

- Versioned, plain-language privacy notices with purpose, data category, processing basis, recipient/processor disclosure, retention and contact information.
- Consent grant, evidence, version, purpose, expiry where applicable and withdrawal as easy as grant; consent is not incorrectly required where another approved lawful/legitimate basis applies.
- A Personal Privacy Center for access, correction, completion, update, erasure, grievance and nomination requests, with identity verification, assignment, SLA, decision reason, exemptions/legal hold and delivery evidence.
- Data inventory and processing-purpose register covering collection, source, classification, residency, recipient/subprocessor, AI access, retention and deletion path.
- Policy-driven retention, legal holds, deletion/anonymisation, backup/search/cache propagation and reconciliation evidence; an erasure request never silently destroys records that law requires to be retained.
- Personal-data-breach case management covering detection, containment, affected data/principals, impact, decisions, communications, regulator/Board and affected-person notification evidence, remediation and closure.
- Configurable privacy contact/DPO where applicable, grievance route and separation of requestor/decision-maker duties.
- Processor/subprocessor registry, DPA/instructions, data-region and transfer controls, subprocessor change workflow and customer-facing disclosure.
- Privacy by design for AI: minimised permission-checked context, purpose enforcement, redaction where required, provider retention/training controls, provenance and deletion propagation.

Never claim legal compliance from code or tests alone. Gate evidence demonstrates control implementation; qualified counsel and the accountable customer/UBOSS privacy owners approve applicability, wording, roles and statutory timelines.

Authoritative detail: `docs/security/PRIVACY_COMPLIANCE.md`

### 19.2 Incident response and on-call operations

- Define P0–P3 severity, 24x7 escalation expectations for production-critical events, primary/secondary on-call ownership and an always-current contact matrix.
- Monitoring pages the responsible service owner for tenant isolation, security, privacy, unavailable runtime, missed schedules, stuck approvals/outbox, integration failure and error-budget breach.
- Incident workflow is acknowledge → assign commander → contain/kill switch → preserve evidence → assess impact → communicate → recover → verify → close.
- Suspected personal-data impact opens the privacy-breach branch immediately; notification decisions and delivery evidence are owned by the approved privacy/legal authority, not an autonomous Agent.
- P0/P1 incidents require a blameless post-incident review with timeline, root/contributing causes, customer impact, control failures, corrective actions, owners, due dates and recurrence tests.
- Emergency changes remain audited and receive retrospective approval/review. Status-page and customer communication responsibilities are named before pilot.

Authoritative detail: `docs/operations/INCIDENT_RESPONSE.md`

## 20. Templates and collaboration

Builder-contained Objective, Job, Agent, Supervisor and approval templates. Later add industry template library/marketplace.

Collaboration includes comments, mentions, followers, attachments, approval discussion, change requests and activity timeline. Add saved views, controlled custom fields/tags and department dashboards without turning UBOSS into a generic board clone.

## 21. UI visual system

- Supplied dark sidebar is signature navigation.
- Main workspace launches clean light-first. Full dark mode is a committed Enterprise Pilot deliverable after accessibility tokens are verified; the sidebar remains dark in both themes unless approved user testing changes it.
- UBOSS electric blue: primary action.
- Violet: AI Agent.
- Blue/cyan: Human.
- Teal: Hybrid.
- Amber: Approval/warning.
- Green: success/output.
- Red: error/destructive only.
- Labels/icons accompany color.
- 8 px spacing, restrained radii/shadows and readable typography.
- Define empty, loading, no-results, denied, offline, partial failure, success and archived states.

### 21.1 Language, locale, responsive and connectivity policy

- Launch language is English unless the Gate 0 pilot decision explicitly requires Hindi.
- The application is internationalization-ready from Gate 1: no hard-coded user-facing copy, locale-aware dates/numbers/currency, user language and timezone preferences, translation keys and expansion-safe layouts.
- Hindi is the first additional language pack when approved for the pilot; future tenant-enabled languages use the same framework.
- AI prompts may accept the user's supported language and AI responses follow the user/workspace language policy. Stable object identifiers, event codes and audit facts remain language-neutral.
- The responsive web application supports desktop, tablet and mobile. Complex authoring is desktop-first but must remain usable on mobile through list/card alternatives; task, approval and monitoring journeys are mobile-priority.
- The MVP is online-first, not offline-first. Temporary disconnection must preserve recoverable Draft input, show truthful save/reconnect state and support safe retry after reconnection.
- Offline Publish, approval, permission changes, Agent/Supervisor commands and schedule changes are prohibited. Server-confirmed state is authoritative and conflicts require explicit resolution.

## 22. Delivery plan

1. **Product contract:** vocabulary, field dictionary, role/permission/entitlement matrix and clickable flows.
2. **Minimum foundation:** new repo plus only the identity, tenant, schema, design-system, audit/outbox and CI/CD capabilities needed by the first working slice.
3. **Hierarchy:** manual tree plus safe staged import.
4. **Objective:** complete Draft → Analyze → Edit → Publish vertical slice.
5. **Job:** multiple WHO/INPUT and schedules.
6. **Agent:** personal/shared Job Agents, internal Skill Registry/Resolver/Factory, tools, tests and Publish.
7. **Supervisor:** personal/department supervision, handlers and failure simulation.
8. **Runtime:** tasks, approvals, durable execution, notifications and reporting.
9. **Enterprise hardening:** SSO/SCIM, security, load/restore/DR and pilot.

This is vertical-slice delivery, not layer-by-layer platform construction. Define the conceptual whole, but implement only the schema/API/runtime needed for the current end-to-end slice.

Practical credible pilot estimate: roughly 22–32 weeks with a focused senior team of one Product Manager/BA, one Product Designer, two Frontend Engineers, two Backend/Platform Engineers, one AI Engineer, one QA Automation Engineer and part-time DevOps/Security support.

## 23. Mandatory design gate

Before frontend coding, test clickable designs for:

- Expanded/collapsed/mobile sidebar
- Dashboard
- Hierarchy tree/import
- Objective Agent Builder form/analysis/editor/Publish/cards
- Job Builder
- Agent Builder
- Personal and Department Supervisor
- To-do and notifications
- Personal/admin Settings

Test with Owner, Admin, Builder, Supervisor, Employee, Approver and Auditor.

## 24. Definition of done

A feature is done only when product acceptance, permission and tenant-isolation tests, all UI states, accessibility, audit, reviewed API/migration, unit/integration/E2E tests, observability, security checks, documentation/runbook and rollback/disable path pass.

## 25. First implementation deliverables

1. Approved canonical field dictionary traced to every source Excel/form.
2. Final role, sharing, Supervisor-handler and entitlement matrix.
3. High-fidelity UI prototype.
4. New database ERD and API contracts.
5. Threat model and tenant-isolation test strategy.
6. One end-to-end thin slice: company → hierarchy → Objective Draft → AI proposal → human edit → Publish.

## 26. Locked technology stack

These are the default engineering decisions for the new build. Change them only through an architecture decision record with a clear reason.

### Frontend

| Concern | Decision |
|---|---|
| Language | TypeScript in strict mode |
| Framework | Next.js App Router with React |
| Styling | Tailwind CSS with centralized design tokens |
| Component foundation | shadcn/ui with Base UI primitives; component code owned by UBOSS |
| Forms | React Hook Form plus Zod schemas |
| Server state | TanStack Query |
| Local editor/UI state | Zustand; introduce a state machine only for complex lifecycle flows |
| Graph editor | React Flow for Objective dependencies, with an accessible list view as the default |
| Icons | Lucide |
| Charts | Recharts initially; use a heavier chart library only when required |
| Tables | TanStack Table with server-side pagination/filtering |
| Testing | Vitest, Testing Library and Playwright |

Rules:

- Server data is not duplicated into a global client store.
- Server Components are used for safe initial reads/layouts; interactive Builders use focused Client Components.
- API types are generated from the backend OpenAPI contract.
- Every route defines loading, error, empty, denied and offline/reconnect behavior.
- No page may invent new colors, spacing or status labels outside the design system.

### Backend

| Concern | Decision |
|---|---|
| Language | Modern supported Python with strict typing |
| API framework | FastAPI |
| Validation | Pydantic |
| ORM/data access | SQLAlchemy |
| Migrations | Alembic |
| Database | PostgreSQL |
| Durable runtime | Temporal Python SDK |
| Cache/coordination | Redis; never the source of truth |
| File storage | S3-compatible object storage |
| AI | Anthropic Claude through internal AI Gateway |
| API style | Versioned REST/OpenAPI; SSE for run timelines |
| Events | Transactional outbox; add a broker only after a proven need |
| Observability | OpenTelemetry-compatible traces, metrics and structured logs |
| Testing | pytest, integration tests and contract tests |

Python is chosen for AI, data/file processing and Agent evaluation. TypeScript is chosen for safe, maintainable enterprise UI. Do not force one language across the whole product merely to claim a single-language stack.

### Infrastructure defaults

- Docker containers.
- Managed PostgreSQL, Redis and object storage for production.
- Temporal Cloud or a deliberately operated Temporal cluster.
- Managed secret store.
- CDN/WAF in front of the web/API edge.
- Infrastructure as code.
- CI/CD with migration, test, security and rollback gates.
- Initial deployment region is selected during Product Contract; data-residency architecture remains explicit.

### Version policy

- Pin exact versions in lock files.
- Use only supported stable releases at implementation kickoff.
- Renovation/dependency updates arrive as reviewed pull requests.
- No automatic major-version production upgrades.
- Maintain a software bill of materials and vulnerability scan.

## 27. New repository structure

~~~text
Uboss Ai New/
├─ backend/                        FastAPI application, migrations, workers
│  ├─ src/uboss/
│  │  ├─ core/                     settings, logging, errors, permissions, security context
│  │  ├─ db/                       engine, session, tenant binding
│  │  ├─ api/                      health probes and the versioned router
│  │  └─ modules/
│  │     ├─ identity/
│  │     ├─ tenancy/
│  │     ├─ hierarchy/
│  │     ├─ objectives/
│  │     ├─ jobs/
│  │     ├─ agents/
│  │     ├─ supervisors/
│  │     ├─ runtime/               Temporal workflows and workers
│  │     ├─ approvals/
│  │     ├─ tasks/
│  │     ├─ notifications/
│  │     ├─ files/
│  │     ├─ integrations/
│  │     ├─ ai_gateway/
│  │     ├─ audit/
│  │     └─ entitlements/
│  └─ migrations/
├─ frontend/                       Next.js application
│  └─ src/
│     ├─ app/                      one directory per route
│     ├─ ui/                       UBOSS design system — the only source of visual foundations
│     ├─ lib/api/                  API client and the generated schema
│     └─ styles/tokens.css         semantic design tokens, light and dark
├─ tests/
│  ├─ contract/
│  ├─ integration/
│  ├─ e2e/
│  ├─ security/
│  └─ load/
├─ infra/                          local development stack
├─ docs/
│  ├─ architecture/
│  ├─ product/
│  ├─ api/
│  ├─ security/
│  └─ runbooks/
├─ scripts/
├─ PLAN.md
└─ README.md
~~~

Two application folders, `backend/` and `frontend/`, and no workspace packages. An earlier
draft of this section described the API twice — once as `apps/api/` and again as
`backend/modules/` — and put the design system in a third top-level `packages/ui`. One
authoritative structure is the point of this section, so the duplication is resolved here in
favour of the two folders the product is actually built in.

Consequences of that choice, recorded so they are not rediscovered later:

- The design system lives at `frontend/src/ui/`. Its ownership rules are unchanged: product
  pages consume its components and never fork them, and they use semantic tokens rather than
  literal colours.
- The generated TypeScript API client lives at `frontend/src/lib/api/`. It is generated from
  `backend/openapi.json` and regenerated in the same commit as any route change.
- Temporal workers are a module inside the API (`modules/runtime/`) and a separate process at
  deployment, not a separate application folder. They share the domain code they execute.
- Lint, type and build configuration lives in each application folder. Two applications in two
  languages share no build configuration worth extracting.

The API remains a modular monolith. A module owns its domain rules and public application interface. Other modules do not read/write its tables arbitrarily.

## 28. API and command standards

- Base path starts with version, for example /api/v1.
- Opaque UUID identifiers.
- Tenant derives from authenticated membership, never a trusted free-form tenant field.
- Commands use idempotency keys when clients or workflows may retry.
- Optimistic concurrency prevents silent overwrite.
- List endpoints use cursor pagination, filtering and stable sorting.
- Error envelope contains stable code, safe message, field errors, correlation ID and retryability.
- Publish validation returns blockers and warnings separately.
- Every sensitive mutation writes an audit event in the same transaction.
- Outbox events are committed with business data.
- Webhooks are signed, timestamped, replay-protected and retried with dead-letter visibility.
- Generated frontend client is refreshed and checked in CI after API-contract changes.
- Internal Claude/tool payloads are not exposed directly to browser clients.

## 29. Final UI implementation specification

### Product style

Use ChatGPT simplicity for the shell and Settings, Linear clarity/speed for interaction, and monday.com-style structured work management. Do not clone any product. UBOSS differentiation is Objective → Job → Agent → Supervisor governance.

### Layout

~~~text
Dark collapsible sidebar
        +
Compact top bar
        +
Light structured main workspace
        +
Optional right Copilot/help drawer
~~~

Main workspace is light-first. Dark mode is supported after accessibility tokens are verified. The sidebar remains dark in both modes unless user testing proves otherwise.

### Design tokens

- 8 px spacing grid.
- Restrained 8–12 px radii.
- One clear primary action per screen.
- UBOSS electric blue for primary actions.
- Violet for AI, blue/cyan for Human, teal for Hybrid.
- Amber for approvals/warnings, green for outputs/success and red only for errors/destructive actions.
- Typography and density optimized for long enterprise work sessions.
- WCAG 2.2 AA target.
- Icon plus label/status text; never color alone.
- Motion approximately 150–250 ms and reduced-motion support.

### Standard Builder layout

~~~text
Header: breadcrumb, title, status, owner, version, save state

Left: section navigation
Center: form/editor
Right: contextual help, warnings and summary

Sticky footer:
Save Draft | Preview Summary | Continue/Analyze/Publish
~~~

Forms preserve all approved workbook fields, use reusable cards for WHO/INPUT/steps, autosave, show completion and never discard values after validation/network errors.

### Required design artifacts

- Component inventory and token sheet.
- Expanded/collapsed/mobile sidebar.
- Dashboard for Employee, Supervisor and Admin.
- Hierarchy empty/manual/import/error/revision screens.
- Objective form, analysis summary, real timeline, list editor, graph and Publish.
- Job form with multiple WHO/INPUT and schedule preview.
- Agent form, tools/permissions, tests and Publish.
- Personal/Department Supervisor monitoring and configuration.
- To-do, task detail, approval and evidence.
- Notification drawer.
- Personal/admin Settings.
- Permission denied, offline, failure and archived states.

No production page is built before its responsive high-fidelity flow and acceptance criteria are approved.

## 30. Data, versions and state rules

- A root object stores stable identity; version tables store immutable published definitions.
- A Draft is mutable with optimistic concurrency.
- Publishing never edits an earlier published version.
- Runs pin Objective, Job, Agent and Supervisor versions.
- Schedules pin versions and require an explicit reviewed upgrade.
- Person assignment uses effective-dated hierarchy positions.
- Personal Supervisor is logical tenant/user-isolated configuration, not a separately deployed Claude model.
- Department Supervisor scope and handler grants are independent.
- Files live in object storage; database stores metadata, classification, hashes and references.
- Audit events are append-only from the application's perspective.
- Sensitive data retention follows tenant policy.
- Search indexes, caches and object keys include tenant isolation.

## 31. Claude and Agent implementation contract

- All model calls pass through AI Gateway.
- Each use case has its own versioned prompt, input/output schema, evaluations and budget.
- AI Gateway selects the allowed Claude model according to workspace policy.
- Claude receives only permission-checked minimum context.
- Uploaded content is untrusted and cannot override system/policy instructions.
- Structured output is schema-validated.
- AI result is a proposal until deterministic policy and human approval permit a command.
- Tools have explicit allowlists, credentials and scopes per Agent version.
- High/Critical actions follow the risk table and approval policy.
- Store model, prompt, schema, token, latency, cost and tool provenance.
- Do not store/display hidden chain-of-thought.
- Support per-Agent, per-workspace and global kill switches.
- Prompt/model upgrades run regression evaluations before rollout.

## 32. Environments and delivery pipeline

Environments:

~~~text
Local → Test → Staging → Production
~~~

- Local uses safe fake/test integrations and non-production data.
- Test runs automated contract/integration/E2E suites.
- Staging mirrors production topology and uses isolated data/credentials.
- Production changes require successful migrations, security checks and rollback plan.
- Feature flags support staged tenant rollout.
- Database migrations are forward-safe and rehearsed on representative data.
- Secrets never live in repository files.
- Every deployment records commit, schema, prompt versions and actor.
- Production access is least privilege and audited.

CI gates:

1. Formatting/lint/type checks.
2. Unit and contract tests.
3. Tenant-isolation/security tests.
4. Migration checks.
5. Frontend build and accessibility checks.
6. E2E critical journey.
7. Dependency/container scans.
8. Staging smoke test.
9. Controlled production rollout.

## 33. Test strategy

### Product tests

- Field/conditional validation.
- Draft autosave/recovery.
- Analysis and Publish summaries.
- Human edits survive reruns.
- Versioning/diff.
- Scheduling/timezone/DST.
- Personal and shared Supervisor scopes.
- To-do/approval/notification delivery.

### Security tests

- Cross-tenant database, file, cache, search and AI-context isolation.
- Role/action permission matrix.
- Self-approval and permission-ceiling denial.
- Prompt-injection and malicious file cases.
- Tool credential/scope enforcement.
- Webhook signature/replay.
- Session revocation and deprovisioning.

### Reliability tests

- Worker/API restart during a run.
- Retry and idempotent external effects.
- Duplicate event/command.
- Provider rate limit/timeout.
- Notification outbox recovery.
- Backup restore.
- Load/noisy-neighbour limits.

### AI evaluations

- Schema validity.
- Groundedness and completeness.
- Unsafe/tool policy violations.
- Sensitive-data leakage.
- Human rejection/edit rate.
- Cost/latency thresholds.
- Regression by prompt/model version.

## 34. Exact build order and exit gates

### Gate 0 — Product Contract (target 2 weeks)

Deliver:

- Canonical field dictionary from every Excel/form.
- Canonical enums/status lifecycle.
- Role and permission-ceiling matrix.
- Personal/Department Supervisor sharing matrix.
- Plan/entitlement limits.
- Launch region, identity provider and initial integrations.
- Approved clickable UI for the first vertical slice.

Owner: Product Designer with Product Manager and Tech Lead. Tool default: Figma. Reviewers: Owner, Admin, Supervisor and Employee representatives.

Exit: product, design and engineering sign off the same contracts and first-slice prototype.

### Gate 1 — Minimum Platform Foundation (target 3 weeks)

Deliver only the auth, tenant isolation, memberships, design system, API conventions, database migrations, audit, outbox, files, CI/CD and observability required by Hierarchy plus the Objective slice. Do not implement future Supervisor/billing/SCIM tables merely because they appear in the conceptual ERD.

Exit: cross-tenant tests, session/security tests and deployment/rollback smoke test pass.

### Gate 2 — Hierarchy slice (target 2–3 weeks)

Deliver manual tree, effective assignments, safe staged CSV/XLSX import and revision history.

Exit: cycle/orphan/duplicate validation, atomic import and subtree permission tests pass.

### Gate 3 — Objective vertical slice (target 5–6 weeks)

Deliver unified cards/form, summary approval, Claude proposal, real events, editable plan, Publish and audit.

Exit: one real end-to-end Objective is created without mock production logic.

### Gate 4 — Job slice (target 3–4 weeks)

Deliver multiple WHO/INPUT, reusable versions, schedule configuration and assignment preview.

Exit: deterministic validation plus timezone/DST/version-pinning tests pass.

### Gate 5 — Job Agent and Skills slice (target 4–5 weeks)

Deliver personal/shared Agents, tools, knowledge, tests, risk classification and Publish. Add Skill Registry seed import, Skill Resolver safe routing and private Skill Factory Drafts inside Agent Builder; no separate sidebar item.

Exit: catalogue reconciliation, Resolver hard-gate, tool permission, prompt-injection, approval and cost tests pass.

### Gate 6 — Supervisor slice (target 4–5 weeks)

Deliver Personal/Department Supervisors, independent supervised/handler scopes, monitoring, safe retry, escalation and consolidated reporting.

Exit: failure simulation and forbidden-action tests pass.

### Gate 7 — Governed Runtime (target 3–4 weeks)

Deliver Temporal execution, tasks, approvals, To-do, notifications, schedules, run evidence and the global governed Copilot. Copilot includes permission-filtered context, sources, proposal/saved distinction, preview/diff, explicit confirmation and audit.

Exit: crash/retry/idempotency/outbox recovery tests pass. Copilot permission-ceiling, cross-tenant leakage, prompt-injection, source-grounding, mutation-preview and forbidden-action tests pass.

### Gate 8 — Enterprise Pilot (target 4–6 weeks)

Deliver SSO/SCIM as required, billing/entitlements, security hardening, DPDP/privacy controls, incident/on-call operations, DR, load tests, support runbooks, migration tooling and production-ready appearance/locale/responsive verification. Full dark mode is completed here unless an earlier Gate needs it.

Exit: pilot tenant acceptance, reconciliation, restore drill and go-live checklist pass. Supported desktop/tablet/mobile journeys, English and every enabled language pack, light/dark/reduced-motion accessibility, reconnect/Draft recovery and the prohibition of unsafe offline actions are verified. Privacy role/data-flow inventory, DPA/subprocessor register, notice/processing-basis/consent behavior, Data Principal rights drill, retention/legal-hold/deletion evidence, personal-data-breach tabletop, on-call page and P0/P1 postmortem exercise pass with Security, Privacy/Legal, Product and Engineering sign-off.

### Gate stop/review rule

Pause new scope and hold a formal Continue / Reduce / Redesign / Stop review when any condition occurs:

- A gate misses two consecutive sprint reviews.
- A gate exceeds its approved timebox by more than 50 percent.
- Gate 3 cannot produce a pilot-usable end-to-end Objective without mock production logic.
- Tenant isolation, permission ceiling, audit integrity or rollback cannot be demonstrated.
- Critical requirements keep changing without an approved change decision.
- Pilot users cannot finish the primary journey without developer assistance.

The review records root cause, remaining value, revised scope/cost, owner and decision. Work resumes only after explicit approval.

## 35. Remaining client inputs and recommended defaults

These are not missing architecture; they are business decisions required before their affected feature is finalized.

| Decision | Recommended default |
|---|---|
| First launch region | India-primary region with explicit international expansion plan |
| Identity | Managed provider with MFA now; SAML/OIDC and SCIM for enterprise |
| Objective approval | Owner's authorized supervisor; no self-approval when separation is required |
| Schedule overlap | Queue one run |
| Missed schedule | No catch-up unless explicitly enabled |
| High-risk Agent action | Human approval |
| Personal Agent visibility | Only me |
| Personal Supervisor | Enabled for entitled users |
| Department Supervisor handlers | Explicit selected people; no automatic department-wide control |
| Data retention | Tenant policy with safe enterprise defaults |
| Privacy baseline | India DPDP with effective-date tracking and counsel-approved jurisdiction packs |
| Default privacy roles | Customer normally Data Fiduciary/controller for tenant workflow data; UBOSS normally Processor, decided per purpose/DPA |
| Production incidents | Named P0–P3 on-call and escalation; P0/P1 post-incident review mandatory |
| Claude provider | Claude first through provider-neutral Gateway |
| External integrations | Start with only pilot-critical systems |
| Logo/brand | Final SVG logo, wordmark, favicon and approved color tokens required |

Client must supply/approve:

- Final logo/brand assets.
- Exact launch country/data-region requirement.
- First pilot company and workflows.
- Required first integrations.
- Approval authority matrix.
- Subscription packages/limits.
- Data-retention/legal requirements.
- Privacy role/DPA, notice wording, processing bases, privacy contact/DPO where applicable, request SLA, subprocessors/transfers and breach-notification authority.
- Final wording and conditional behavior of workbook forms.

## 36. Readiness verdict

The product concept and target architecture have no known fundamental gap for beginning Gate 0. Coding should begin only after Gate 0 artifacts are approved; otherwise the team will recreate the confusion of the old application.

The chosen stack is:

~~~text
TypeScript + Next.js frontend
Python + FastAPI modular backend
PostgreSQL
Temporal
Redis
S3-compatible storage
Claude through AI Gateway
Transactional outbox
OpenTelemetry
~~~

The first coding milestone is not the entire platform. It is one production-quality vertical slice:

~~~text
Sign in
→ Create company
→ Build/import Hierarchy
→ Create Objective Draft
→ Claude proposal
→ Human edit
→ Publish
→ Audit evidence
~~~

Only after that slice passes the Definition of Done should Job, Agent and Supervisor runtime expand.

## 37. Official technical references

- Next.js App Router and TypeScript: https://nextjs.org/docs/app
- shadcn/ui and Base UI direction: https://ui.shadcn.com/docs/changelog/2026-07-base-ui-default
- FastAPI OpenAPI/Pydantic features: https://fastapi.tiangolo.com/features/
- Temporal durable execution: https://docs.temporal.io/
- Anthropic API/tool use: https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-reference
- monday.com GraphQL/platform model: https://developer.monday.com/api-reference/docs/basics
- TCS AI WisdomNext governance/orchestration: https://www.tcs.com/what-we-do/services/artificial-intelligence/solution/enterprise-generative-ai-adoption-wisdomnext

## 38. UI source of truth and current execution status

The build has entered Gate 0 — UI Contract. The authoritative implementation documents are:

- docs/product/UI_SPEC.md
- frontend/src/ui/README.md
- frontend/src/styles/tokens.css

No feature team may invent a separate layout, color, form pattern, status or navigation convention. Any deliberate exception must update these sources and record the reason.

## 39. Skill Registry decision

The 400-skill catalogue and 2,400 IF-THEN rules are retained as a client-owned seed asset. Skill Registry is internal to Agent Builder and is not a sidebar module.

~~~text
Agent requirement
→ Search Skill Registry
→ Deterministic compatibility gates
→ Reuse | Configure | Compose | Create private Skill Draft
→ Sandbox tests
→ Human approval
→ Versioned active Skill
~~~

Semantic similarity discovers candidates but cannot override permissions, jurisdiction, data classification, required approval, version status or stale evidence. Skills cannot self-publish.

Authoritative detail: docs/product/SKILL_REGISTRY.md

## 40. Legacy data decision

Old code/schema remains reference-only. Valid client-owned data receives an explicit inventory, classification, mapping, reconciliation and approval decision.

- Preserve/import validated Skill Catalogue records and IF-THEN rules.
- Evaluate real hierarchy, users, Objectives, Jobs, Agents, published versions, approvals and evidence for migration.
- Preserve governance-relevant audit in the new ledger when safely mappable, otherwise in a signed/read-only legacy archive linked by cutover date.
- Exclude demo/test records, simulated runs/approvals, duplicates, broken placeholders, development identities and all secrets.

Authoritative detail: docs/migration/LEGACY_DATA_POLICY.md

## 41. Delivery controls

Gate timeboxes, stop/review triggers, ownership and evidence are mandatory controls, not estimates hidden in project reporting.

Authoritative detail: docs/delivery/GATE_CONTROLS.md

## 42. Gate-aligned implementation sequence

The executable step-by-step order, current verified baseline, foundation corrections, per-Gate deliverables and evidence rules are defined in `docs/delivery/IMPLEMENTATION_PLAN.md`.

That document is subordinate to this PLAN and approved client decisions. It may sequence work and record implementation status, but it cannot silently change product scope, permissions, workbook contracts, UI source of truth or Gate exit criteria.

## 43. Phase 1 product contract revision — 2026-09-01

This section records the confirmed client workflow and supersedes any earlier wording that presents
Objective Agent Builder, a user-facing Job Builder, or the four-Agent sidebar as the target product.
Existing Job data and services are retained; only their product role changes.

### 43.1 Product operating model

UBOSS is an administrator-governed AI Operations Management System. An administrator builds the
company Hierarchy, invites people, grants bounded access, selects the people participating in an
Objective and records their current work. Claude proposes a Human, AI Agent, Hybrid or Approval
allocation. A human administrator must review and may edit every allocation before it can become
operational.

Human work appears in the assigned person's Job Agent and To-do List. AI work binds to a published,
version-pinned Agent from Agent Builder / Sync. A Supervisor Agent monitors only the people, Agents,
departments and controls placed within its two independent scopes: supervised scope and handler
scope.

### 43.2 Personas, roles and access

Effective access is `role grants ∩ data scope ∩ action ceiling`, with explicit denials winning.

- Company Owner/Super Admin may administer the company within platform policy.
- Company Admin may manage the modules, people and data explicitly granted to the role.
- Department Admin receives the admin interface but only for assigned departments, hierarchy
  subtrees, resources and actions. They cannot grant beyond their own ceiling.
- Supervisor/Operator may monitor or control only assigned Supervisor scopes and handler actions.
- Employee receives the personal operational interface and own/assigned records only.
- Viewer receives read-only access to explicitly shared resources.
- Custom roles combine named actions and scopes; a role name alone never bypasses scope.

Administrators can invite by email, assign or end roles, promote another user to a bounded admin
role and choose which sidebar modules, data scopes and actions that person receives. Access removal
takes effect on the next authorized request. No user, Agent or Supervisor may promote itself,
approve its own protected transition or widen its own scope. Every access change is audited.

### 43.3 Objective Optimization contract

`WHO — Person Name` is a searchable multi-select backed by active Hierarchy memberships, not free
text. The creator can select all permitted participants and record responsibility, contribution,
current work, inputs, method, outputs, controls, approvals and failure handling for each.

Claude receives only opaque keys for the selected permitted participants and allowed Agent
candidates. Its structured proposal references those keys; it cannot invent a user, membership,
permission or executable Agent identifier. The server validates tenant, scope, active membership,
Agent status and every assignment before displaying the proposal.

Each generated work step has exactly one accountable owner, optional contributors, optional
reviewer/approver and one of four execution modes: Human, AI Agent, Hybrid or Approval. The review
screen shows differences, reasoning and confidence. The administrator can add, edit, delete,
reassign and reorder steps before approval.

### 43.4 Publish and Activate are separate transitions

- **Publish** freezes an immutable Objective Version, approved participant allocation and audit
  evidence. Publish does not create notifications or begin work.
- **Activate** compiles the published version into executable internal records, creates or schedules
  human/approval work, binds pinned Agent Versions and begins Supervisor monitoring.
- Re-activation is idempotent. A changed Objective produces a new version and a reviewed deployment
  diff; it never mutates the evidence of an already active version.

Both transitions show an impact summary and require the relevant permission. High-risk activation
requires step-up authentication when workspace policy says so.

### 43.5 Internal Job system

Job Builder is no longer a user-facing Builder or sidebar destination. The existing Job and
JobVersion model remains the canonical internal execution contract. An idempotent Objective
Deployment Compiler maps a published Objective Version to a system-managed Job Version, WHO rules,
inputs, dependencies, approvals, schedules and Agent bindings. Generated Jobs carry their origin,
source Objective Version and managed status and are not silently hand-edited.

This preserves the approved workbook field contract and the existing Tasks, Runs, Schedules,
Approvals and evidence pipeline without forcing administrators to describe the same work twice.

### 43.6 Job Agent contract

A Job Agent is a person's governed operational workspace over assigned Tasks, Runs, approvals,
inputs and evidence; it is not a duplicate AI Agent record. Normal employees see `My Job Agent`.
Authorized admins see `Job Agents` aggregated only over their effective scope.

The workspace provides Assigned, Input Requested, In Progress, Waiting for Approval, Blocked and
Completed views. A work item shows its Objective, instructions, inputs, deadline/SLA, permitted
actions, AI output, comments and evidence. Start, complete, block, clarify, approve/reject and
delegate are offered only when both state and permission allow them.

### 43.7 Agent Builder / Sync contract

An AI allocation can search compatible published Agents, clone one or start a new Agent draft.
Sync always binds an exact published Agent Version after capability, Skill, tool, data, approval and
policy gates pass. Status is explicit: Not configured, Draft, Validation failed, Ready to sync,
Synced, Outdated or Resync required. Updating an Agent never silently changes an active Objective.

### 43.8 Supervisor contract

Supervisor configuration remains separate per tenant/account and may be personal, departmental or
resource-scoped. Supervised scope answers what is watched; handler scope answers who may control
the Supervisor. It can observe run health, missing input, SLA, budget, quality and failure; within
policy it may retry, pause, resume, escalate and notify. It cannot perform protected approvals,
change permissions or widen either scope.

### 43.9 Required implementation data additions

- `objective_participants` links an Objective to selected active memberships and responsibilities.
- `objective_step_assignments` records accountable owner, contributors, reviewer/approver and
  Human/AI/Hybrid/Approval mode.
- `objective_step_agent_bindings` pins a step to an Agent and published Agent Version with sync
  state and evidence.
- `objective_deployments` records idempotent Objective Version to internal Job Version compilation,
  preview, activation and status.
- Job records gain system-managed origin/source metadata; existing Job data is not deleted.

All additions use backward-compatible migrations, explicit backfill and a reversible cutover.

### 43.10 Phase 1 exit criteria

Phase 1 is complete only when PLAN and UI_SPEC agree on the navigation, personas, scoped access,
Objective allocation, internal Job model, Job Agent, Agent Sync and Publish/Activate lifecycle;
the implemented sidebar contains no user-facing Job Builder; and unresolved product decisions are
recorded rather than hidden in code.
