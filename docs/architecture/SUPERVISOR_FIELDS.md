# The Supervisor's fields, and where they come from

Three places in the code cite this document — `supervisors/models.py`, migration
`0024_supervisor_policy.py`, and `test_supervisor_policy.py` — and until now it did not exist. This
records what they were citing.

## There is only one source, and that is the point

The other three Builders resolve two sources against each other: an approved workbook form and a
`PLAN.md` section. The Supervisor has **no workbook form**. The workbook's sheets are Form 1 —
Hierarchy, Form 2 — Objective, Form 3 — Job Method, Form 4 — Agent, and the shared Dropdown Lists.
There is no Form 5.

So the Supervisor's field set comes from `PLAN.md` §10 alone, and there is nothing to reconcile.
That is probably why this file was cited and never written: with one source it can look as though
there is no decision to record.

There is. §10 is prose — ten form groups, six handler roles, two mandatory scopes and a list of
capabilities — and turning prose into columns *is* the decision. Written down, the next screen
reads it instead of interpreting §10 again.

## The two scopes are separate on purpose

§10: *"Two independent scopes are mandatory"*.

1. **Supervised members and Agents** — whose work is watched. `supervisor_supervised`.
2. **Allowed handlers** — who may control this Supervisor. `supervisor_handlers`.

They are different questions and they are different tables. A person can be supervised without
being able to touch the Supervisor, and a handler need not be supervised by it. Collapsing them
into one list of "people involved" would make the second question unanswerable, which is the
question that decides who may pause a run.

## The handler roles

§10 lists six, and the order is increasing authority. `HandlerRole` keeps that order because
`rank()` compares roles to refuse granting above your own — a list reordered for tidiness would
quietly change who may do what.

| Role | §10's words |
|---|---|
| Viewer | |
| Operator | pause/resume and safe retry |
| Reviewer | review output/request changes |
| Approver | |
| Manager | manage scope/policy |
| Owner | |

A handler role is a permission **on this Supervisor**, never a workspace permission. `GOVERNED`
bounds what any role can confer, which is what stops a Supervisor becoming a route to workspace
administration — the check `guard.authorise_handler` makes against both boundaries.

## Where each field lives

§10's ten form groups, mapped:

| §10 group | Table |
|---|---|
| 1. Identity, owner, department, linked Objective scope | `supervisors` — `name`, `kind`, `owner_membership_id`, `org_node_id`, `objective_id`, `purpose` |
| 2. Supervised members and Agent versions | `supervisor_supervised` |
| 3. Human handlers and granular permissions | `supervisor_handlers`, with `roles.py` |
| 4. Trigger/schedule and execution order | `supervisors.trigger`, `supervisor_schedules`, and `supervisor_supervised.position` for the order |
| 5. Dependency, concurrency and routing policy | `supervisor_dependencies`, `supervisors.max_concurrency`, `routing_policy` |
| 6. Quality and evidence gates | `supervisor_quality_gates` |
| 7. Budget, SLA and retry limits | `supervisors.cost_cap_minor_units`, `cost_cap_currency`, `token_cap`, `sla_minutes`, `deadline_minutes`, `max_retries`, `retry_backoff_seconds` |
| 8. Approval and escalation | `supervisors.approver_membership_id`, `escalation_membership_id`, `supervisor_escalations` |
| 9. Notifications and reports | `supervisor_notifications` |
| 10. Sandbox/failure simulation and Publish | `supervisor_simulations`, `supervisor_versions` |

## The kinds

§10 names three and admits two. `SupervisorKind` carries **personal** and **department**;
workspace-wide is *"restricted and may be added later"* and is deliberately not a value — an enum
member nothing can create is a promise the schema makes and the product does not keep.

`supervisor_supervised` has a trigger refusing a row whose membership is not the owner's on a
**personal** Supervisor, which is §10's *"supervises that user's permitted Job Agents"* held in the
database rather than in a service that could be bypassed.

## A person, not a label

`approver_membership_id` and `escalation_membership_id` are the fields that matter;
`approver_label` and `escalation_label` sit beside them and are notes. An approval has to be
*performed*: `can_approve` compares the named approver against the signed-in membership, so a role
name can never satisfy it. The label records who the approver stands for where a sheet named a
role. See `DECISIONS.md` §39, where the same question was settled for the Agent.

## Execution order is a position, not a second field

§10 group 4 asks for trigger, schedule **and execution order**. The order is
`supervisor_supervised.position` — the sequence of the supervised rows themselves — rather than a
column of its own. A separate ordering field would be a second answer to one question, and the two
would disagree the first time somebody reordered one and not the other.

## What this does not settle

**Workspace-wide Supervisors.** §10 defers them explicitly. Nothing here anticipates one.

**What a "report" is.** §10 group 9 says *"Notifications and reports"* and
`supervisor_notifications` carries the notification half — event, channel, recipient. A report is
named and never described: not its format, its schedule, its contents, or where it goes. That is a
question for the client rather than something to infer from the word.

**Routing policy has no approved vocabulary, so it is free text.**

This is the open question the code cites this file for — in `models.py`, in migration
`0024_supervisor_policy.py`, and in `test_routing_policy_accepts_anything_because_no_vocabulary_is_approved`.
§10 group 5 says *"routing policy"* and never says what the choices are. A closed list here would
be a set of options somebody invented and the product then enforced, which is the failure
`ORDER.md` names: *"where `PLAN.md` is silent, the answer is a question to the client, not a
guess."* `agents.model_policy_key` is free text for the same reason.

So the field accepts anything, a test pins that it does, and the question stays here until a
vocabulary is approved. When one is, it becomes a served list like every other closed list in this
system — never a constant in the frontend.

## Fields that exist and have no control

The gap here is not the field set — it is the form. Six of the ten groups have no editor at all, so
the Supervisor cannot record what the plan requires of it, and three publish warnings are
permanently unfixable because the thing that would clear them cannot be entered.

* **Group 4** — the whole schedule. `setSupervisorSchedule` has zero call sites; `trigger` is
  echoed and not editable.
* **Group 5** — `dependencies` is never written or read.
* **Group 6** — `quality_gates` is always an empty array, so `no_quality_gates` cannot be cleared.
* **Group 7** — `cost_cap_minor_units` and `cost_cap_currency` are echoed on save and absent from
  the limits fieldset.
* **Group 8** — `escalations` is always empty, so `no_escalations` cannot be cleared.
  `escalation_membership_id` has no control.
* **Group 9** — `notifications` is always empty. Reports do not exist.
* **Group 1** — `kind` is hard-coded to personal, so a Department Supervisor cannot be created at
  all; `org_node_id` and `objective_id` have no control.
* **Group 10** — the monitoring view `UI_SPEC.md` §14 describes does not exist.
