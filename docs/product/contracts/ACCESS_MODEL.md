# Roles, Permission Ceiling, Sharing and Entitlements

**Status:** Working Draft — not approved

## 1. Permission evaluation

Effective access is the intersection of:

~~~text
active membership
∩ tenant plan entitlement
∩ role grants
∩ company restrictions (when configured)
∩ department/workspace restrictions (when configured)
∩ resource sharing policy
∩ action-specific conditions
∩ lifecycle/version rules
~~~

A lower scope can only narrow access; it cannot re-grant a denied action. Missing membership,
role grant or required entitlement denies. A missing optional restriction layer does not erase a
valid role grant. Every decision is tenant-bound and explainable.

## 2. Draft role/action matrix

Legend: `A` allowed by role, `C` conditional/scope-limited, `—` not granted. Entitlements and
resource policies can still narrow an `A`.

| Action | Owner | Admin | Builder | Supervisor | Employee | Approver | Auditor | Guest |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| View assigned/shared resources | A | A | A | A | A | A | A | C |
| Comment | A | A | A | A | C | C | C | C |
| Create/edit Drafts | A | A | A | C | C | — | — | — |
| Analyze with AI | A | A | A | C | C | — | — | — |
| Publish resource version | A | A | C | — | — | — | — | — |
| Run allowed Agent | A | A | C | C | C | — | — | — |
| Approve assigned action | C | C | C | C | — | A | — | — |
| Assign people/Agents | A | A | C | C | — | — | — | — |
| Schedule | A | A | C | C | C | — | — | — |
| Manage resource access | A | A | C | C | — | — | — | — |
| Export tenant data | A | C | — | — | — | — | C | — |
| Manage integrations | A | A | C | — | — | — | — | — |
| Tenant administration | A | A | — | — | — | — | — | — |
| View audit/compliance evidence | A | C | — | C | — | — | A | — |
| Billing/plan management | A | C | — | — | — | — | — | — |

`C` requires an explicit resource/scope grant and, where applicable, a step-up or approval.
Service accounts have no human UI role; each receives explicit machine actions, scopes,
credential owner, expiry and audit identity.

## 3. Separation of duty

- No Objective, Job, Agent, Supervisor or Skill may approve/promote itself.
- The author of a high-risk change cannot be its sole approver.
- Copilot may propose but cannot Publish, approve, grant access or execute a destructive/high-risk
  action for the user.
- Agent owner, maintainer, runner, approver, viewer and Supervisor handler are separate grants.
- Connection ownership does not imply permission to use every connection scope.
- Step-up authentication is required for role/access changes, secret/connection management,
  retention/legal-hold changes, exports, billing ownership and destructive administration.

## 4. Personal and Department Supervisor sharing

### Personal Supervisor

- One per entitled account unless the plan later allows more.
- May supervise only Agents the account can view and that workspace policy permits.
- Default handlers: the owning user; additional handlers require explicit sharing.

### Department Supervisor

Three independent lists are required:

1. **Supervised people** — whose allowed work/runs may be monitored.
2. **Supervised Agents** — which Agent versions/runs may be monitored or controlled.
3. **Human handlers** — who may operate the Supervisor.

Handler grants are explicit per person/team and role:

| Handler role | Allowed intent |
|---|---|
| Viewer | Read status/evidence only |
| Operator | Pause/resume and policy-safe retry |
| Reviewer | Inspect evidence and recommend action |
| Approver | Decide only assigned approvals within ceiling |
| Manager | Configure supervised scope and non-owner handlers within ceiling |
| Owner | Own Supervisor lifecycle; cannot bypass company ceiling |

Example: a department has Rahul, Vaibhav and Asha, but only Rahul and Vaibhav are selected
handlers. Asha may still be supervised if selected in the supervised-members list, but receives
no Supervisor controls.

## 5. Personal Agent and sharing rules

- An entitled user may create multiple personal Job Agents up to the backend-enforced plan limit.
- Private is the default for a new Agent/Skill Draft.
- Sharing supports user, team and role audiences with explicit viewer/runner/maintainer/approver
  grants.
- Shared access never transfers ownership implicitly.
- Deactivating an owner blocks unsafe execution until ownership, schedules and connections are
  reassigned or disabled.

## 6. Entitlement contract

Backend checks—not hidden UI alone—enforce seats, Builder seats, personal Agents, Supervisor
availability, runs/concurrency/schedules, AI models/budgets, Skill capability, storage/retention,
exports/audit, integrations, API/webhooks and SSO/SCIM.

Commercial numbers remain `DR-004`. Until approved, code uses named entitlement keys and test
fixtures, never guessed production limits.

## 7. Required evidence

- Deny-by-default tests for no membership/no role/no entitlement.
- Matrix tests for every action and representative scope combination.
- Cross-tenant and cross-department denial.
- Lower-scope attempted privilege escalation denial.
- Self-approval and author-as-sole-approver denial.
- Supervisor handler/member/Agent separation tests.
- Deactivation and ownership-reassignment behavior.

