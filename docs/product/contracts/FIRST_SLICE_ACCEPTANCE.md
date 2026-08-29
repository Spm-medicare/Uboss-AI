# First Vertical Slice Acceptance Contract

**Status:** Working Draft — prototype and representative approval pending

## 1. Journey

~~~text
Sign in
→ enter an approved/provisioned company
→ build or stage-import Hierarchy
→ review/edit tree
→ create Objective Draft inside Objective Agent Builder
→ review form summary and explicitly confirm analysis
→ Claude produces a step-by-step Proposal with truthful progress
→ human edits/adds/deletes/reorders nodes
→ validate and preview Publish impact
→ explicit approval/confirmation
→ immutable Published Objective version
→ Objective card and audit evidence
~~~

There is no separate Objective sidebar item. Objective creation and saved Objectives live inside
Objective Agent Builder.

## 2. Prototype surfaces

1. Sign-in, workspace chooser and safe generic errors.
2. Responsive App Shell: Dashboard, Hierarchy, Agents 01–04, To-do, top bar and Settings entry.
3. Approved company onboarding/invitation journey from `DR-001`.
4. Hierarchy empty state, manual tree, file upload, mapping, validation, preview and editable tree.
5. Objective Agent Builder landing with top-right **Create Objective**.
6. Builder form, sticky progress, Draft recovery and validation summary.
7. Pre-analysis summary modal with explicit approval.
8. AI progress view distinguishing deterministic system steps, human actions and AI actions by
   color, icon, label and text—not color alone.
9. Proposal editor with add/edit/delete/reorder, source/provenance and validation.
10. Publish impact summary, approval/confirmation and success state.
11. Published Objective card/detail/version/audit evidence.
12. Notification drawer, Copilot entry and Settings shell at contract depth needed by this slice.

## 3. Acceptance scenarios

| ID | Actor | Scenario | Pass condition |
|---|---|---|---|
| FS-01 | Owner/Admin | Sign in to one of multiple memberships | Correct tenant identity/role; no data from another tenant |
| FS-02 | Authorized provisioner/Owner | Enter or create approved company path | Journey matches DR-001; immutable provisioning evidence |
| FS-03 | Owner/Admin | Build hierarchy manually | Valid root/parent tree; cycle/duplicate/orphan errors explained |
| FS-04 | Owner/Admin | Upload hierarchy file | Staged mapping and validation; no direct mutation before confirmation |
| FS-05 | Builder | Create Objective Draft | Required source fields preserved; Draft autosave state truthful |
| FS-06 | Builder | Request Claude analysis | Full summary shown first; explicit approval; idempotent request |
| FS-07 | Builder | Observe analysis | Progress is event-backed; human/system/AI work visually distinct |
| FS-08 | Builder | Edit Proposal | Add/edit/delete/reorder supported; no hidden overwrite; provenance retained |
| FS-09 | Unauthorized Employee/Guest | Attempt Publish | Server denies; UI explains missing permission without leaking policy/data |
| FS-10 | Authorized publisher/approver | Publish | Impact summary + step-up/approval if required; immutable version created |
| FS-11 | Auditor | Inspect evidence | Actor, tenant, input version, model/prompt policy, approvals and published version traceable |
| FS-12 | Mobile user | Review/approve critical journey | Usable list/card alternative; no graph-only blocker |
| FS-13 | Any writer | Temporary disconnect during Draft | Recoverable Draft and truthful reconnect/conflict state |
| FS-14 | Any user | Try unsafe action offline | Publish/approval/access/schedule mutation remains blocked |

## 4. UI state matrix

Every surface covers loading, empty, no-results, validation error, denied, offline, reconnecting,
conflict, partial failure, success and archived/superseded where applicable. Destructive actions
require impact copy and confirmation; keyboard/focus/screen-reader behavior is included in the
prototype review.

## 5. AI acceptance boundary

- Claude receives only permission-filtered, tenant-bound context needed for the request.
- User content is treated as untrusted data, not system instruction.
- Proposal, Saved Draft and Published states are visibly different.
- Cancellation, timeout, provider error and safe retry are represented.
- Model/prompt/policy versions, token/cost/latency and source evidence are captured.
- Claude cannot publish, approve, grant access or bypass deterministic validation.

## 6. Gate 0 sign-off

Review the same clickable revision at desktop and mobile widths with Owner/Admin, Supervisor and
Employee/Approver representatives.

| Reviewer group | Representative | Date | Prototype revision | Result/notes |
|---|---|---|---|---|
| Owner/Admin | — | — | — | Pending |
| Supervisor | — | — | — | Pending |
| Employee/Approver | — | — | — | Pending |
| Product | — | — | — | Pending |
| Design | — | — | — | Pending |
| Engineering | — | — | — | Pending |

