# The Agent's fields, and where they come from

`PLAN.md` §9 and the approved workbook describe the same object from two sides. This records how
both are kept, because the resolution is a decision and not an obvious one — the same situation as
the Objective, and resolved the same way.

## The two sources

**`PLAN.md` §9** lists ten form groups:

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

and adds three sentences that behave like requirements:

> Access choices: Only me, selected users, teams, department, role/subtree or workspace.
> Tool suggestions never grant access. Tests and permission review are publish gates.

**`UBOSS_Agent_Builder_Forms.xlsx`, sheet "Form 4 - Agent"** — the approved workbook, read directly
rather than summarised — has a header, three lettered sections and nothing else:

| Header | |
|---|---|
| Agent Name | required |
| Agent Owner | required |
| Completion Time | |
| Objective, Job | carried from Forms 2 and 3 |
| Trigger, Frequency | |
| Main Approver | required |
| Error Escalation To | required |

**A. Agent design confirmation** — twelve numbered rows, nine columns each:

```
Step · Input Used · Input Source · Tool / System · Agent Action
Output · Output Destination · Approval · Agent Must Never Do
```

**B. Error, approval & escalation rules** — six printed situations, each with a *Required Agent
Action* and an *Escalation To*:

```
Mandatory input missing · Information is unclear · Information conflicts
Tool or system fails · Approval is rejected · Prohibited action requested
```

**C. Simple tests** — five printed tests, each with a *Sample Situation*, an *Expected Result* and
a *Status*:

```
Normal case · Missing input · Conflicting input · Prohibited action · System failure
```

## The resolution: both, whole

Neither source is a superset of the other, so neither was dropped.

| §9 group | Where it lives | From |
|---|---|---|
| 1 Identity and linked Job version | `agents.name`, `objective_id`, `job_id`, **`job_version_id`**, `trigger`, `frequency`, `completion_time_*` | both — the sheet's header, and §9's *linked Job version* |
| 2 Purpose, instructions, boundaries, prohibited actions | `agents.purpose`, `instructions`, `boundaries`, `prohibited_actions`; `agent_steps.must_never_do` | §9; the sheet's *Agent Must Never Do* is the per-step half |
| 3 Owner, audience, sharing | `agents.owner_membership_id`, `visibility`, `agent_shares` | sheet (owner) + §9 (the six access choices) |
| 4 Multiple input/output schemas | `agent_io_schemas` | §9 |
| 5 Claude/model policy | `agents.model_policy_key` | §9 |
| 6 Knowledge sources and retention | `agent_knowledge_sources` | §9 |
| 7 Tools and explicit scopes | `agent_tools` | §9; the sheet's *Tool / System* is the per-step half |
| 8 Human approval and escalation | `agents.main_approver_*`, `escalation_*`; `agent_escalation_rules` | both — the sheet's header and its whole section B |
| 9 Cost, token, time, concurrency, retries | `agents.cost_cap_*`, `token_cap`, `time_limit_seconds`, `max_concurrency`, `max_retries` | §9; the sheet has only *Completion Time* |
| 10 Sandbox tests and publishing | 5.4 | both — the sheet's section C, and §9's publish gates |

Form 4 section A's nine columns are `agent_steps`, in the sheet's own order and none merged.
`test_every_column_of_form_4_section_a_survives_a_round_trip` names all of them, so a column
dropped from the schema fails a test rather than disappearing from a form nobody re-read.

## Decisions taken along the way

**Section B is a closed set; everything else from the workbook is a suggestion.** The sheet's
dropdown lists all end in `Other`, so a value outside one is something the approved form itself
allows — they are published by `GET /agents/lists` and never validated against. Section B is
different: the sheet *prints* all six situations as fixed rows, so leaving one unanswered is not a
value outside a list, it is a decision nobody took. It is an enum, and 5.4 makes the six a publish
gate.

**An unanswered situation is a checklist, not a refusal.** A form is filled in over time, and
refusing the first save would be refusing to let somebody start. `AgentRead.situations_unanswered`
reports what is left.

**`must_never_do` is per step, not per agent.** What an agent must never do at step 4 is not what
it must never do at step 9. `agents.prohibited_actions` holds the agent-wide statement §9 asks for;
the per-step column is the sheet's.

**Model policy is a key, and its vocabulary is not invented here.** CLAUDE.md forbids a hard-coded
model name in domain logic. v3.2 approves *"Claude first through provider-neutral Gateway"* and
names **no policy catalogue**, so `model_policy_key` is free text until an approved list exists.
This is an open question, not a finished field — see below.

**Main Approver and Error Escalation To are required from submission, not from the first save.**
The sheet marks both with an asterisk. The check constraint applies from `ready_to_publish`
onward, which also means an abandoned draft can be archived without ever having needed one — a
constraint written as "not a draft" got that wrong and a test caught it.

**A share list contradicting the visibility is refused.** `only_me` with people listed is two
answers to one question; preferring either would discard somebody's intention without telling them.

**A grant survives an edit, but not a scope change.** A save that dropped grants would make
re-granting a habit rather than a decision. A save that kept one across a widening of scopes would
let somebody expand an agent's access by editing a form. So `agent_tools.granted` is carried over
only while the scopes are exactly what was granted.

## What is still open

**No approved model-policy catalogue exists.** `agents.model_policy_key` accepts any string. Until
the client approves a policy list, a screen cannot offer a closed choice here and this document is
the record of why. Nothing in the schema depends on a particular value.

## Not here

Form 4 section C — the five sandbox tests — is in 5.4 with `agent_versions`. §9 says *"Tests and
permission review are publish gates"*, and a gate belongs with the thing it guards rather than
with the form it reads.
