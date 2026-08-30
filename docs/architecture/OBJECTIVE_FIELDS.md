# The Objective's fields, and where they come from

`PLAN.md` §7 and the approved workbook describe two different field sets for the same object.
This records how both are kept, because the resolution is a decision and not an obvious one.

## The two sources

**`PLAN.md` §7** lists eight form groups: Identity, Outcome, Scope, Time, Constraints,
Context/inputs, Governance, AI preferences.

**`UBOSS_Complete_Builder_Forms_Organogram (1).xlsx`, sheet "Form 2 - Objective"** — the approved
workbook, read directly rather than summarised — has a header and a step table:

| Header | |
|---|---|
| Objective Name | required |
| Department | required |
| Objective Owner | required |
| Expected Final Result | required |
| Current Workload | with a unit |
| Target Completion Time | with a unit |
| Prepared By, Date | |

and twenty numbered step rows with fourteen columns each:

```
Step · WHO–Person Name · WHO–Role · WHEN–Trigger · WHEN–Frequency · WHAT–Exact Work
INPUT–What Is Used · INPUT–Received From · WHERE–Work Is Done
OUTPUT–What Is Produced · OUTPUT–Sent To · Time Taken · Current Problem · Approval
```

Seven of those columns are closed lists, defined on the workbook's "Dropdown Lists" sheet.

## What was decided

**Both are kept. Nothing from the workbook is dropped.**

`PLAN.md` §6 settles it: *"All approved fields from existing Builder forms remain until the
field-dictionary review approves a change. New UI reorganizes fields; it does not silently remove
business requirements."*

So §7's eight groups are **how the new interface is organised**, and the workbook's fields are
**the floor of what must be captured**. Read together rather than as alternatives, they describe
one coherent object:

* The workbook's Form 2 captures **how the work is done today** — a person walks through their
  existing process, one row per step, in the vocabulary their team already uses.
* §7's groups add what governing that work needs and the workbook never had: an owner and
  approver, a visibility and sensitive-data policy, AI preferences and human checkpoints, a
  measurable outcome, scope, and constraints.
* §7's *execution graph* is not the workbook's step table. The step table is the **current**
  process; the graph is what Claude proposes in its place (§7: *"Claude proposes an execution
  graph with Human, AI Agent, Hybrid, Approval and Output blocks"*). Both exist at once, and
  comparing them is the point of the product.

That last distinction is the one worth being explicit about. Collapsing the two into one table
would make "what we do now" and "what the AI suggests" the same rows — and the whole review step
in §7, where a person compares AI and human changes, would have nothing to compare.

## Where each field lives

| Source | Table |
|---|---|
| Workbook header, §7 groups 1, 2, 4, 5, 7, 8 | `objectives` |
| §7 group 2 — KPI / success measures, repeatable | `objective_measures` |
| §7 group 4 — milestones, repeatable | `objective_milestones` |
| Workbook step table — the current process | `objective_current_steps` |
| §7 execution graph — Claude's proposal, after a person accepts it | `objective_steps` (Gate 3.2) |
| Published snapshot, immutable | `objective_versions` |

The seven dropdown columns keep the workbook's own lists, including its `Other` option. Replacing
them with tidier values would silently change what a team can record about their own process, and
the lists were approved.

## What this does not settle

The workbook has no field for §7's **Scope** group — included and excluded work, teams, geography
and stakeholders — and no **Governance** or **AI preferences** fields. Those are new, and they are
implemented as §7 describes them.

The reverse gap is smaller but real: the workbook's `Prepared By` and `Date` are captured by the
audit trail instead. A person cannot be trusted to type who they are, and the row already knows.
