# The Job's fields, and where they come from

`PLAN.md` §8 and the approved workbook describe two field sets for the same object. This records
how both are kept, in the same shape as `OBJECTIVE_FIELDS.md`, because the resolution is a decision
and not an obvious one — and because without it written down, each screen decides again.

## The two sources

**`PLAN.md` §8** lists ten form groups:

1. Identity and linked Objective step/version
2. Purpose and expected output
3. WHEN trigger
4. Multiple WHO assignment rules
5. Multiple typed INPUT definitions
6. Human/AI/Hybrid steps and dependencies
7. Tools/integrations
8. Evidence, quality, SLA and completion
9. Retry, failure, escalation and approval
10. Schedule, access, sharing and publishing

**`UBOSS_Complete_Builder_Forms_Organogram (1).xlsx`, sheet "Form 3 - Job Method"** — read from the
file rather than summarised — has a header block and a step table.

| Header | |
|---|---|
| Objective Name | linked from Form 2 |
| Department | linked from Form 2 |
| Job ID / Name | required |
| Job Owner | required, from the hierarchy |
| Current Person | required, from the hierarchy |
| Role | required |
| Trigger | required, closed list |
| Frequency | required, closed list |
| High-Level Work | required |
| Job Start Requirement | |
| Job Completion Evidence | |
| Normal Completion Time | with a unit |
| Time Unit | closed list |

and twenty numbered step rows with sixteen columns each:

```
Step · WHO — Person Name · WHO — Role · WHEN — Trigger · WHEN — Frequency · WHAT — Exact Work
INPUT — Exact Input · WHERE — Input Is Found · HOW — Exact Method · WHERE — Work Is Performed
Rule / Formula / Check · Output · Output Destination · Approval · If Missing / Wrong · Time
```

§8 lists those sixteen by name and requires them: *"The Job Builder must preserve and map every
approved field from … Form 3 — Job Method."*

### The closed lists, and which column each one belongs to

Five columns of the step table are validated against the workbook's own "Dropdown Lists" sheet.
The mapping is recorded here because getting one wrong is invisible: both lists are approved, so a
column offering the other form's vocabulary looks authoritative while recording the answer to a
different question.

| Sheet cells | Column | List |
|---|---|---|
| `D10:D29` | WHEN — Trigger | `Trigger` |
| `E10:E29` | WHEN — Frequency | `Frequency` |
| `J10:J29` | WHERE — Work Is Performed | `Where` |
| `N10:N29` | **Approval** | **`Approval Timing`** — *when* the sign-off happens |
| `O10:O29` | **If Missing / Wrong** | **`Missing Action`** |

`Approval Timing` is *No approval · Before this step · After this step · Only for exceptions ·
Always*. It is **not** the `Approval` list on Form 2, which answers *who* signs off — *Team Lead,
Department Head, Quality, Regulatory…* The step table offered Form 2's list for most of this
module's life; see `DECISIONS.md` §42.

Three header cells are validated too: Trigger and Frequency against the same lists, Time Unit
against `Time Unit`, and Job Owner and Current Person against the hierarchy's own names.

`HOW — Exact Method` has **no** validation on Form 3 and is free text, despite a `Method` list
existing on the Dropdown Lists sheet for another form. It is left free here because the sheet
leaves it free.

## What was decided

**Both are kept. Nothing from the workbook is dropped.** `PLAN.md` §6: *"All approved fields from
existing Builder forms remain until the field-dictionary review approves a change. New UI
reorganizes fields; it does not silently remove business requirements."*

So §8's ten groups are **how the interface is organised**, and Form 3 is **the floor of what must
be captured**. They describe one object from two directions: Form 3 is how the job is done today,
in the words of the person who does it; §8 adds what running it under governance needs — typed
inputs, assignment rules, tools, evidence, retry and escalation policy, a schedule and a published
version.

**The step's `mode` is §8's, not the workbook's.** Human / AI / Hybrid is group 6, and it is the
one column on the step card that Form 3 has no cell for. It is additive: a row filled in from the
sheet is a human step until somebody says otherwise.

## Where each field lives

| Source | Table |
|---|---|
| Form 3 header, §8 groups 1, 2, 3, 8, 9 | `jobs` |
| Form 3 step table (all sixteen), §8 group 6 `mode` | `job_steps` |
| §8 group 6 — dependencies between steps | `job_step_dependencies` |
| §8 group 4 — WHO rules, repeatable | `job_assignment_rules` |
| §8 group 5 — typed inputs, repeatable | `job_inputs` |
| §8 group 7 — tools and permissions | `job_tools` |
| §8 group 10 — auto-run and its policies | `job_schedules` |
| Published snapshot, immutable | `job_versions` |

The five dropdown columns keep the workbook's own lists, including their `Other` option, and are
served from the API rather than copied into the frontend — a second copy of an approved list is a
copy that drifts.

## The WHO types

§8 names six: User, Team, Department, Role, Hierarchy position/subtree, Dynamic eligible group.

`WhoType` carries **seven**, because the fifth of those is a pair and the two halves mean different
things: `hierarchy_position` is one seat, `hierarchy_subtree` is a seat and everybody under it.
Assigning work to a manager and assigning it to a manager's whole department are not the same
instruction, and a single value would have made the difference unrecordable.

## The INPUT fields

§8: *"name, schema/type, source, required status, validation, classification, retention and
AI-access permission"* — all eight are columns on `job_inputs`.

## What this does not settle

**`objective_version_id` has no column.** §8 group 1 says *"linked Objective step/version"*.
`jobs.objective_id` and `jobs.objective_step_id` exist; the version does not, anywhere. Pinning a
Job to the Objective *version* it was written against is a real requirement and is not implemented.

**Sharing has no table.** §8 group 10 says *"access, sharing"*. `jobs.visibility` covers access;
there is no `job_shares` to name individual people or teams, though the Agent has `agent_shares`
for the same purpose. Whether a Job needs one is a question for the field-dictionary review rather
than something to invent here.

**The twenty-row limit is not enforced**, and deliberately: `MAX_STEPS = 60` in the service. The
sheet's twenty rows are a paper constraint, and a job with twenty-five steps is a job, not an
error. Recorded so the difference is a decision rather than a discrepancy somebody finds later.

## Fields that exist and have no control

Recorded because this is where the gap actually is. Every one of these is a column the API accepts
and the screen never offers, so the Job Builder cannot capture an approved field that the database
is waiting for. They are not missing from the field set; they are missing from the form.

* `objective_id` / `objective_step_id` — never sent, so a Job can never be linked to its Objective.
* `job_inputs.validation_note`, `job_inputs.retention_note` — §8 names both.
* `job_schedules.skip_dates` (the calendar) and `pinned_version_id` — both hard-coded empty.
* `job_step_dependencies` — the client strips `depends_on`, the schema forbids it, and the model is
  constructed nowhere. §8 group 6 requires it.
* `visibility` — sent with no control on screen.
* `job_schedules.last_error`, `next_run_at`, `last_run_at` — served, never rendered, though the
  schema comment for the first says it is shown *"so a schedule that has quietly stopped working is
  visible rather than silent"*.
