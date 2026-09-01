# UBOSS AI — Authoritative UI/UX Specification

**Status:** Gate 0 design contract  
**Applies to:** Web application, responsive tablet/mobile web, future native clients  
**Principle:** Calm outside, governed inside

## 1. Experience goal

UBOSS must feel immediately understandable to a new employee and remain powerful for enterprise administrators. It combines:

- ChatGPT-like simplicity in navigation, Settings and contextual Copilot.
- Linear-like speed, hierarchy and keyboard efficiency.
- monday.com-like structured work, permissions and collaboration.
- UBOSS-specific Objective → Job → Agent → Supervisor governance.

Do not copy another product's visual identity. UBOSS owns its dark navigation, electric-blue brand, structured Builder shell and Human/AI execution language.

## 2. Non-negotiable UI principles

1. One obvious primary action per screen.
2. Progressive disclosure: common fields first, Advanced only when needed.
3. Preserve context: use drawers for detail and avoid unnecessary navigation.
4. Never lose user input.
5. Real system state only; no fake progress or optimistic success for governed actions.
6. Summary before AI analysis and a separate summary before Publish.
7. Text and icons accompany every color/status.
8. Draft, Published and Run state are never visually confused.
9. Permission denial explains what is blocked without leaking inaccessible data.
10. Desktop supports dense enterprise work; mobile prioritizes tasks, approvals and monitoring.
11. Copilot proposes; it never silently mutates.
12. Accessibility is part of Definition of Done.

## 3. Final application shell

### 3.1 Sidebar

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

---------------------------------------------------
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

---------------------------------------------------
Settings
~~~

There is no separate Objective menu and no user-facing Job Builder menu. Objective creation,
participant selection, Claude allocation review, publishing, activation and progress begin in
Objective Optimization. Approved work is compiled into the internal Job execution model.

Dimensions:

- Expanded desktop: 280 px.
- Collapsed desktop: 72 px.
- Top bar: 64 px.
- Mobile: overlay drawer, maximum 320 px.
- Sidebar does not horizontally scroll.

Behavior:

- Expansion state persists per user/workspace.
- Collapsed icons expose accessible names and tooltips.
- Arrow keys move, Enter activates and Left/Right collapse/expand.
- Unauthorized items are not rendered, but backend remains authoritative.
- Company and Department Admins share the admin information architecture; records and actions are
  narrowed to their effective scope.
- Employees receive only their personal operational destinations unless granted a Builder
  capability.
- Footer contains Settings only. Account, sign-out and workspace controls live within Settings or
  the top-bar account control.

### 3.2 Top bar

Left:

- Breadcrumb when depth is greater than one.
- Page title.
- Compact status/version metadata when relevant.

Right:

- Global search/command trigger.
- One contextual primary action.
- Notification bell.
- Copilot toggle.

Do not repeat all sidebar actions in the top bar.

### 3.3 Main workspace

- Light-first neutral background.
- Content begins 24–32 px from shell edges.
- Maximum reading/form width is controlled; tables and visual editors may use full width.
- Main content never sits beneath fixed chrome.
- Right Copilot/help drawer is 360–420 px and collapsible.

## 4. Responsive layout

Breakpoints are content-driven; initial implementation targets:

| Width | Behavior |
|---|---|
| 1440+ | Expanded sidebar, three-column Builder when helpful |
| 1024–1439 | Expanded/collapsed sidebar, right panel optional |
| 768–1023 | Collapsed sidebar or drawer, Builder becomes two-column |
| Under 768 | Drawer navigation, single-column forms, sticky mobile action bar |

Mobile priorities:

- To-do and approvals.
- Supervisor alerts.
- Run status.
- Evidence/input submission.
- Safe pause/approve/reject actions.

Complex graph construction remains usable through list mode; mobile graph view is read-focused.

### 4.1 Language, locale and connectivity

- Launch UI is English unless Gate 0 approves Hindi for the pilot.
- UI copy uses translation keys from the first coded slice; components must tolerate text expansion without clipping.
- User preferences control supported language, timezone, date/number/currency formatting and AI response language within workspace policy.
- Stable IDs, API enums, event codes and audit facts are language-neutral; translated labels are presentation only.
- Hindi is the first additional language pack when approved. Every enabled pack receives critical-journey, accessibility and overflow testing.
- The MVP is online-first. Temporary disconnection preserves recoverable Draft input and shows truthful Saving/Saved/Offline/Failed/Reconnecting states.
- Publish, approval, permission changes, Agent/Supervisor commands and schedule mutations are disabled offline. Reconnection performs safe retry and surfaces conflicts for explicit resolution.

## 5. Visual system

### 5.1 Typography

- Primary font: Inter Variable.
- Monospace: JetBrains Mono for IDs, technical values and code only.
- Body default: 16 px.
- Secondary metadata: 13–14 px, never below 12 px in product UI.
- Use weights 400, 500 and 600; reserve 700 for rare marketing emphasis.
- Page titles are concise and sentence case.
- Use tabular numerals for usage, cost, time and SLA tables.

### 5.2 Spacing and geometry

- Base grid: 4 px; standard rhythm: 8 px.
- Page gap: 24–32 px.
- Section gap: 24 px.
- Field gap: 16 px.
- Card padding: 16–20 px.
- Control height: 40 px standard, 36 px compact.
- Radius: 8 px controls, 10–12 px cards/dialogs.
- Shadows are subtle and only communicate elevation.
- Do not nest visually heavy cards.

### 5.3 Semantic colors

| Meaning | Token direction |
|---|---|
| Primary/brand | Electric blue |
| Human work | Blue/cyan |
| AI Agent | Violet |
| Human + AI | Teal |
| Approval/warning | Amber |
| Output/success | Green |
| Failure/destructive | Red |
| Neutral | Slate/charcoal |

Rules:

- Purple is functional AI meaning, not decoration.
- Red is reserved for errors/destructive actions.
- Large background areas use neutral tones.
- Status uses icon + text + color.
- Contrast targets WCAG 2.2 AA.

The product launches light-first with its dark signature sidebar. Full dark mode is a committed Enterprise Pilot deliverable, uses the same semantic tokens and must pass contrast, focus, chart, editor and reduced-motion verification. The sidebar remains dark in both themes unless approved user testing changes it.

### 5.4 Motion

- Micro-interactions: approximately 150–200 ms.
- Drawers/dialogs: approximately 200–250 ms.
- No looping decorative Agent animation.
- Run timeline animates state transitions only when real events arrive.
- Respect reduced-motion preference.

## 6. Component hierarchy

### Foundations

- Color, type, spacing, radius, elevation, motion and breakpoints.
- Focus ring, disabled state, skeleton and selection state.

### Primitives

- Button, icon button, link, input, textarea, select, checkbox, radio, switch.
- Badge/status, avatar, tooltip, separator and spinner.

### Composites

- Searchable selector.
- Multi-select.
- Date/time/timezone control.
- File uploader with scan/parse state.
- Repeatable WHO/INPUT card.
- Permission picker.
- Schedule builder/preview.
- Approval summary.
- Version selector/diff.
- Empty/error/denied state.

### Domain components

- Hierarchy node and detail drawer.
- Objective step card.
- Job input and assignment rule.
- Agent tool permission card.
- Supervisor scope/handler matrix.
- Run timeline.
- Task/approval item.
- Evidence viewer.
- Usage/cost panel.

Pages compose domain components; pages do not restyle primitives locally.

## 7. Buttons and actions

Priority:

1. Primary: one main action in a region.
2. Secondary: safe alternate action.
3. Ghost: navigation/low-emphasis.
4. Destructive: explicit irreversible/high-impact action.

Rules:

- Use verbs: Create Objective, Analyze, Publish, Approve, Pause Agent.
- Avoid generic OK/Submit where business meaning exists.
- Disable only when reason is obvious; otherwise allow action and explain validation.
- Destructive confirmations state exact impact.
- Long operations return a Run ID and real state.

## 8. Forms

### 8.1 Standard Builder layout

~~~text
Header: breadcrumb | title | status | owner | version | save state

Left section navigation
Center form/editor
Right context, completeness, warnings and summary

Sticky footer:
Save Draft | Preview Summary | Continue/Analyze/Publish
~~~

### 8.2 Behavior

- Autosave after short idle and on section change.
- Also expose Save Draft.
- Show Saving, Saved at time, Offline changes and Save failed.
- Preserve values after API/validation failure.
- Required fields have text indication.
- Inline error plus top error summary with anchors.
- Conditional fields appear only when condition is active.
- Repeating fields use cards, not comma-separated text.
- Dates always show timezone.
- Advanced sections remain searchable.
- Help text explains business meaning.
- Unsaved navigation warns only when recovery is not guaranteed.

### 8.3 Summary and approval

Analysis summary:

- Shows important form values and missing warnings.
- Authorizes Claude processing.
- Does not publish or grant governance approval.

Publish summary:

- Shows changes, version, scope, owners, permissions, schedules, costs, risk, approvals and warnings.
- Creates/routs an immutable version only after authorization.

## 9. Dashboard contract

Default order:

1. Attention strip: critical failures, overdue approvals and missing credentials.
2. My work: pending tasks and inputs.
3. Runs: active, scheduled and failed.
4. Recent Objectives/Jobs/Agents.
5. Role-specific progress/usage.

No vanity metrics. Every number opens its filtered source and displays last updated.

Role variants:

- Employee: personal tasks, Agents, schedules and results.
- Supervisor: selected people/Agents, failures, SLA and approvals.
- Admin: tenant usage, security, integration and governance.
- Auditor: read-only risk/audit summaries.

## 10. Hierarchy contract

Desktop:

- Full-width tree canvas/list hybrid.
- Search/filter and Add/Import/History top actions.
- Node detail in right drawer.
- Zoom/focus only when tree size requires it.

Node displays:

- Position title.
- Person or Vacant.
- Unit/level.
- Dotted-line indicator where applicable.
- Warning/status indicator.

Import uses a five-stage stepper:

~~~text
Upload → Map → Validate → Preview tree → Confirm
~~~

Errors are actionable, downloadable and never produce partial live data.

## 11. Objective Optimization contract

Landing:

- Search/filter.
- Create Objective primary action.
- Cards/table toggle.
- Status tabs or filter chips: Draft, Review, Published, Active/Paused, Archived.

Detail tabs:

- Overview
- Design
- Versions
- Runs
- Access
- Activity

Analysis timeline:

- Validate Objective.
- Load selected, permitted Hierarchy participants.
- Load allowed context.
- Identify workstreams.
- Propose Human, AI Agent, Hybrid and Approval steps.
- Check policy and dependencies.
- Prepare allocation review.

Output editor defaults to accessible list mode:

~~~text
List | Graph | Changes | Validation
~~~

`WHO — Person Name` is a searchable multi-select of active, permitted Hierarchy memberships. Each
step card shows execution mode, one accountable owner, optional contributors/reviewer/approver,
title, inputs, output, dependency, suggested Agent and warning. Claude can suggest only from the
selected participant keys and allowed Agent candidates. Graph mode uses the same data, never a
separate truth.

Before Claude analysis, submission shows a complete input summary. Before Publish, the Changes
view shows the proposed allocation, administrator edits, validation and impact. Publish freezes an
immutable Objective Version but starts no work. A separate Activate action previews and creates the
internal deployment, tasks, Agent bindings, schedules and Supervisor monitoring.

## 12. Internal Job system contract

Job Builder is not a sidebar destination or a normal user-authored screen. The existing Job and
JobVersion records remain the internal execution contract produced by the Objective Deployment
Compiler after Publish and explicit Activate. The compiler preview explains how approved Objective
steps map to WHO rules, inputs, dependencies, approvals, schedules and pinned Agent Versions.

The following groups describe the internal contract and administrator-readable deployment detail;
they do not require a second form entry flow.

Landing and tabs match Objective patterns.

Form sections:

- Identity and Objective link.
- Purpose/output.
- WHEN.
- WHO.
- INPUT.
- Steps/dependencies.
- Tools.
- Quality/evidence/SLA.
- Failure/retry/approval.
- Access and Publish.

WHO and INPUT are repeatable cards with summary, validation and reorder. Scheduling always provides human-readable next occurrences and explicit timezone/DST/overlap behavior.

### 12.1 Workbook-to-UI traceability

Source: `UBOSS_Agent_Builder_Forms.xlsx`, Form 3 — Job Method. The workbook supplies requirement fields; this UI specification supplies their usable presentation. The approved canonical field dictionary remains the exact contract for labels, types, required/conditional rules, API properties and storage mapping.

The repeatable Job Step card must preserve all 16 source columns:

| Workbook field | UI placement |
|---|---|
| Step | Step identity/order |
| WHO — Person Name | WHO card: assigned person |
| WHO — Role | WHO card: role/eligibility |
| WHEN — Trigger | WHEN card: trigger |
| WHEN — Frequency | WHEN/schedule card: frequency |
| WHAT — Exact Work | Step card: exact work |
| INPUT — Exact Input | INPUT card: exact input/schema |
| WHERE — Input Is Found | INPUT card: source/location |
| HOW — Exact Method | Step card: method/instructions |
| WHERE — Work Is Performed | Step card: system/work location |
| Rule / Formula / Check | Quality/rule card |
| Output | Output card: value/schema |
| Output Destination | Output card: destination |
| Approval | Approval card: requirement/authority/timing |
| If Missing / Wrong | Failure/exception card |
| Time | SLA/time card |

Form 3 header fields, approved dropdown options and conditional behavior are mapped in the canonical field dictionary and must not be dropped. UI grouping may reduce repetition but may not silently merge or remove approved meaning.

## 13. Agent Builder / Sync contract

Landing views:

- My Agents.
- Shared with me.
- Department.
- Draft.
- Published.
- Active/Paused.
- Attention required.
- Skills.

The Skills view is internal to Agent Builder and contains Registry search, compatible candidate comparison, Use Existing, Configure, Compose and Create Private Skill Draft. It is never a separate sidebar module.

Form sections:

- Identity/Job.
- Instructions/boundaries.
- Audience.
- Inputs/outputs.
- Model policy.
- Knowledge.
- Tools/scopes.
- Approvals/escalation.
- Budgets/retries.
- Tests/Publish.

Tool permission card always shows connection owner, granted scopes, risk and last health check. Publish screen shows test evidence and cost estimate.

Objective Sync adds an explicit lifecycle: Not configured, Draft, Validation failed, Ready to
sync, Synced, Outdated and Resync required. Sync selects an existing published Agent, clones one or
opens a new draft, then pins an exact published Agent Version. A changed Agent never silently
changes an active Objective; the impact diff must be reviewed before resync.

Skill Resolver UI shows semantic match as discovery evidence, then separately displays blocking compatibility gates: permission, jurisdiction, data classification, tool, approval, lifecycle and freshness. A high similarity score never visually implies approval.

Skill Factory uses the shared Builder shell for trigger, exclusions, schemas, IF-THEN rules, tools, approvals, failures, tests, visibility, version and rollback. New Skills start private and cannot self-publish.

## 14. Supervisor Agent contract

Landing tabs:

- My Supervisor.
- Shared Supervisors.
- Department Supervisors.
- Templates.

Monitoring view:

- Overview.
- Running.
- Waiting/Approvals.
- Failures.
- People and scope.
- Policies.
- Cost/SLA.
- Reports.
- Versions.
- Activity.

Configuration visibly separates:

~~~text
Supervised members/Agents
from
Allowed human handlers and their permissions
~~~

Never imply that being supervised grants control. Critical controls display exact affected Agents/runs before execution.

## 15. Job Agent and To-do contract

Job Agent is an operational projection over real Tasks, Runs, approvals, inputs and evidence—not a
second AI Agent record. Employees receive `My Job Agent`; permitted admins receive scoped `Job
Agents`. Views are Assigned, Input Requested, In Progress, Waiting for Approval, Blocked and
Completed. Each item exposes its Objective, instructions, due/SLA, required input, AI output,
comments, evidence and only the state transitions the signed-in person may perform.

To-do is the compact actionable queue across the same governed records.

Tabs:

- Assigned to me.
- Approvals.
- Input requested.
- Following.
- Completed.

Default list prioritizes overdue, high-risk and near-due items. Detail supports instructions, context, linked run, comments, evidence and decision history.

Approve/Reject requires appropriate reason policy. Rejection and change request are distinct actions.

## 16. Notifications

Bell drawer:

- All.
- Unread.
- Action required.

Group repeated run events. Badge counts actionable unread items, not all information.

Each item includes:

- Actor/system.
- Event.
- Object.
- Timestamp.
- Deep link.
- Safe inline action when possible.

Notification settings control channel, category, digest, quiet hours and escalation.

## 17. Settings contract

Desktop Settings uses left categories and one focused right panel. Mobile uses category list then detail.

Personal:

- Profile.
- Appearance.
- Notifications.
- Security/sessions.
- AI preferences.
- Privacy Center.

Workspace:

- General.
- Branding.
- People/teams/guests.
- Roles/permissions.
- Hierarchy.
- Objective policy.
- Job policy.
- Agent/Claude.
- Supervisor policy.
- Integrations.
- Schedules.
- Data/privacy/cookies: notices and purposes, processing bases/consent, rights requests, retention/legal holds, data inventory, processors/subprocessors, residency/transfers, breach cases and privacy contact/DPO where applicable.
- Audit/compliance.
- Billing/usage.
- Developer.

Settings search finds controls by natural terms. Risky changes show impact summary, step-up authentication and audit result.

### 17.1 Privacy Center and admin compliance UI

Personal Privacy Center:

- Shows the current applicable notice, purpose-level data use, relevant processing basis, recipients/processors, retention summary and privacy contact.
- Shows consent separately from other approved processing bases. Where consent applies, grant/withdraw actions are equally discoverable and preserve versioned evidence.
- Allows supported access, correction/completion/update, erasure, grievance and nomination requests.
- Request timeline shows received, identity verification needed, assigned, in review, information requested, completed/rejected and appeal/escalation path, without exposing internal restricted notes.
- Export/download and decision notices are secure, expiring and audited.

Workspace privacy administration:

- Notice/purpose Builder uses Draft → independent review/approval → effective version; no self-approval where separation is required.
- Processing register maps data categories and sources to purpose/basis, recipients/subprocessors, AI access, region, retention and deletion path.
- Rights-request queue supports verified identity, assignment, SLA, search across authorised systems, exemptions/legal hold, redaction, decision reason and delivery evidence.
- Retention screen previews affected categories/records before delete/anonymise/archive execution and provides reconciliation evidence across primary storage, files, search, caches and backups according to policy.
- Breach workspace is permission-restricted and shows severity, commander, affected categories/principals, containment, decisions, communications, regulator/Board and affected-person notification evidence, remediation and closure.
- Processor/subprocessor view shows service, purpose, data categories, region/transfer basis, contract/DPA status, security review, effective dates and customer change notice.

Privacy UI never displays a generic “compliant” badge based only on configuration. It displays control status, evidence, owner, last review and any gap. Legal wording, applicability and statutory deadlines require approved privacy/legal configuration.

## 18. Copilot contract

- Opens as optional right drawer.
- Inherits current permitted object context.
- Clearly labels proposal versus saved state.
- Shows sources/object references when using company data.
- Commands that mutate produce preview/diff.
- Publish, approval, permission grant, destructive and high-risk actions remain explicit UI decisions.
- Chat history is not the authoritative object record.

## 19. Universal UI states

Every screen/component specifies:

- First-use empty.
- Loading/skeleton.
- Loaded.
- No results.
- Validation error.
- Permission denied.
- Offline/reconnecting.
- Partial failure with retry.
- Rate/plan limit.
- Success and next action.
- Archived/read-only.

Failure copy states what happened, what was preserved and what the user can do.

## 20. Accessibility

- WCAG 2.2 AA target.
- Semantic landmarks/headings.
- Native controls when possible.
- Keyboard-accessible tree, dialogs, menus and drag alternatives.
- Visible focus.
- Screen-reader status announcements for save/run/import.
- Focus returns correctly after dialog/drawer close.
- Minimum target approximately 40×40 px on touch.
- Color-independent meaning.
- Text zoom/reflow and reduced motion.
- Automated checks plus manual keyboard/screen-reader test.

## 21. Content and naming

- Sentence case.
- Short, direct labels.
- Consistent canonical names from PLAN.md.
- Human-readable errors; correlation ID remains available.
- Never show raw model prompts, JSON or stack traces to ordinary users.
- Explain AI uncertainty and validation warnings without fake percentages.

## 22. Performance budget

- Shell becomes interactive quickly on normal enterprise networks.
- Route-level code splitting.
- Virtualize large hierarchy/table lists.
- Server-side pagination/filtering.
- Avoid loading graph/chart libraries on screens that do not use them.
- Skeletons reflect real layout.
- Monitor Core Web Vitals and interaction latency.

## 23. UI design and implementation gate

Before coding a feature:

1. Confirm user/role and primary job.
2. Approve responsive wireflow.
3. Approve high-fidelity states.
4. Confirm components/tokens already exist or formally add them.
5. Write accessibility behavior.
6. Write API/loading/error contract.
7. Write acceptance scenarios.

Before calling it done:

1. Visual comparison at desktop/tablet/mobile.
2. Keyboard and focus test.
3. Light/dark/reduced-motion check where supported.
4. Empty/loading/error/denied/offline states.
5. Permission and tenant tests.
6. Automated accessibility and E2E critical path.
7. Product/design/engineering review.

## 24. First design deliverables

Create in this order:

1. Foundations and component primitives.
2. Shell/sidebar/top bar.
3. Dashboard role variants.
4. Shared Builder shell and form controls.
5. Hierarchy tree/import.
6. Objective end-to-end vertical slice.
7. Job Builder.
8. Agent Builder.
9. Supervisor Agent.
10. To-do/Notifications.
11. Settings.

The first coded UI milestone is the shell plus an end-to-end Objective Draft flow using real component contracts—not a collection of disconnected dashboard screens.
