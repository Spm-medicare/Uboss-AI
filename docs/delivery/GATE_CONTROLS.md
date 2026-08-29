# UBOSS AI — Gate Controls, Timeboxes and Stop/Review Rules

## Delivery principle

Build thin end-to-end vertical slices. Define the conceptual platform, but do not implement future tables/services before the current slice needs them.

## Owners and targets

| Gate | Target | Accountable owner | Visible outcome |
|---|---:|---|---|
| 0 Product Contract | 2 weeks | Product Manager | Approved workbook-to-field-to-UI/API mapping, permissions, launch languages/connectivity scope and responsive Figma first-slice prototype |
| 1 Minimum Foundation | 3 weeks | Tech Lead | Secure deployable i18n-ready, responsive, online-first shell/foundation |
| 2 Hierarchy | 2–3 weeks | Product + Engineering | Working manual/import hierarchy |
| 3 Objective | 5–6 weeks | Product Manager | Production-quality Objective end-to-end |
| 4 Job | 3–4 weeks | Product Manager | Workbook-complete Job creation/publish/schedule |
| 5 Agent + Skills | 4–5 weeks | AI/Platform Lead | Job Agent plus governed Skill resolution |
| 6 Supervisor | 4–5 weeks | Platform Lead | Personal/Department supervision |
| 7 Governed Runtime | 3–4 weeks | Platform Lead | Durable runs, tasks, approvals, notifications and governed global Copilot |
| 8 Enterprise Pilot | 4–6 weeks | Product/Engineering/Security/Privacy | Accepted privacy-governed, operationally supported, responsive and localized pilot with go-live evidence |

Targets are planning controls, not promises. Approved scope changes update the baseline explicitly.

## Cross-cutting gate evidence

- Gate 0: approve the canonical traceability matrix from every source workbook field to canonical field, UI control, API property and persisted field. Record every deliberate omission/merge/rename as a Product decision.
- Gate 0: lock launch language(s), language owner, online-first boundary, supported browsers/devices and dark-mode milestone.
- Gate 1 onward: user-facing copy uses translation keys; locale/timezone formatting and responsive shell behavior are tested as each slice is built.
- Every product Gate: its critical journey passes approved desktop, tablet and mobile behavior. Complex editors may be desktop-first but require a usable mobile list/card alternative.
- Every write-capable Gate: temporary disconnect preserves recoverable Draft input and exposes truthful reconnect/conflict behavior. Offline Publish, approval, access changes, Agent/Supervisor commands and schedule mutations remain forbidden.
- Gate 4: all approved Form 3 Job header fields, 16 Step fields, dropdowns and conditional rules reconcile with the canonical field dictionary and UI/API/storage mapping.
- Gate 7: global Copilot passes permission-ceiling, cross-tenant leakage, prompt-injection, grounding/source, preview/diff, confirmation, audit and forbidden-action tests.
- Gate 8: English and every enabled language pack, light/dark/reduced-motion accessibility, responsive pilot journeys and reconnect recovery pass production acceptance.
- Gate 8: privacy responsibility/data-flow inventory, DPA/subprocessor register and counsel-approved launch notice, processing bases, privacy contact, request SLA, retention and breach-notification authority are approved.
- Gate 8: notice/consent-withdrawal where applicable, access/correction/erasure/grievance request, legal-hold exception, retention execution and deletion reconciliation pass with immutable evidence.
- Gate 8: run a personal-data-breach tabletop covering detection, containment, affected-principal assessment, authority-approved Board/person communications, delivery evidence, recovery and corrective actions.
- Gate 8: named P0–P3 incident commander/on-call/escalation matrix is tested through a production-like page, kill switch, status communication, recovery and P0/P1 postmortem exercise.

## Stop/review triggers

Pause new scope when:

- Two consecutive sprint reviews miss the current Gate exit.
- Current Gate exceeds timebox by over 50 percent.
- Gate 3 cannot complete the real primary journey without mock production logic.
- Tenant isolation, permission ceiling, audit or rollback evidence fails.
- Requirements change repeatedly without a decision owner.
- Pilot users cannot complete the journey without developer help.
- Quality requires repeated rewrite rather than bounded correction.

## Required decision

The review chooses one:

- Continue with evidence.
- Reduce scope.
- Redesign affected slice.
- Replace a technology/provider.
- Stop the rebuild.

Record root cause, options, remaining value, cost/time, risks, decision owner and next review date.

## Team assumption

- 1 Product Manager/Business Analyst.
- 1 Product Designer.
- 2 Frontend Engineers.
- 2 Backend/Platform Engineers.
- 1 AI Engineer.
- 1 QA Automation Engineer.
- Part-time DevOps/Security.

Materially smaller teams require a new scope/timeline baseline.
