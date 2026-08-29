# The order of work

**One rule: top to bottom. Nothing is skipped, nothing is reordered.**

This file exists because I twice decided on my own that an item could wait — once skipping
`1.6.1`, `1.6.2` and `1.6.5` to reach `1.7`, once reordering inside `1.5`. Both times the
reasoning was defensible and both times it was not mine to make. The plan decides the order; this
file writes it down so there is nothing left to judge.

Numbers are `PLAN.md` and `docs/delivery/IMPLEMENTATION_PLAN.md`'s own. No second scheme.

**When an item is blocked**, it is marked ⛔ with who it is blocked on, and the *next* item is
started. A blocked item is not "skipped" — it is waiting, it stays in place, and it is picked up
the moment the block clears.

**When an item is finished**, its exit check in `WORK_BREAKDOWN.md` has passed and it is
committed. Not before.

---

## Done

| | | |
|---|---|---|
| ✅ | 0A.1 | Git repository and baseline commit |
| ✅ | 0B.1 | `PLAN.md` §38 points at the real design-system paths |
| ✅ | 0B.2 | Privacy and incident-response documents exist |
| ✅ | 1.1.1 | Composite tenant foreign keys |
| ✅ | 1.1.2 | Tenant RLS on every tenant-owned table |
| ✅ | 1.1.3 | Narrow the credentials table |
| ✅ | 1.1.4 | Migration preflight, rollback and restore procedure |
| ✅ | 1.2.1 | Redis rate limiting |
| ✅ | 1.2.2 | Single-use browser-bound workspace challenge |
| ✅ | 1.2.3 | CSRF / Origin validation |
| ✅ | 1.2.4 | Absolute and idle expiry, token rotation |
| ✅ | 1.2.5 | Step-up re-authentication |
| ✅ | 1.3.1 | Persist company and department policies |
| ✅ | 1.3.2 | Resolve them into the request context |
| ✅ | 1.3.3 | Resource-level grants, narrowing only |
| ✅ | 1.3.4 | One guard API; separation of duty; step-up |
| ✅ | 1.3.5 | Audit denials with the scope that withheld |
| ✅ | 1.4.1 | Idempotency on mutating routes |
| ✅ | 1.4.2 | Idempotency expiry and cleanup |
| ✅ | 1.4.3 | Optimistic concurrency |
| ✅ | 1.5.1 | Append-only audit, atomic with its change |
| ✅ | 1.5.2 | Least-privilege relay role |
| ✅ | 1.5.3 | The relay — lease, publish, retry, dead-letter |
| ✅ | 1.6.3 | Automated test suite — 74 tests |
| 🟡 | 1.6.4 | CI pipeline — written; unprovable without a remote |
| ✅ | 1.7.1 | Generated OpenAPI types — *done out of order* |

---

## Next, in this order

### Gate 1 — finish it

| # | | Exit check |
|---|---|---|
| ✅ | **1.6.1** Files / S3 | done — 12 tests |
| ✅ | **1.6.2** OpenTelemetry | done — 7 tests |
| 🟡 | **1.6.5** Environments, secrets, deploy and rollback | Images, config and runbook written. **Exit check unmet: there is no staging** — DR-003 is open |
| ✅ | **1.7.2** Translation keys | done |
| ✅ | **1.7.3** Locale, timezone, date and number formatting | done — 10 tests |
| **6** | **1.7.4** Shared primitives and the five universal route states | No page component declares its own button styling or a literal colour |
| ⛔ | **1.2.6** Invite, password set, reset | **Blocked: a mail provider.** The outbox delivers; nothing is registered to send |
| ⛔ | **0A.2** Private remote | **Blocked: the client.** 14 commits exist on one laptop |
| ⛔ | **0A.3** Protected `main` | Needs 0A.2 |
| ⛔ | **0A.4** Secret scanning with push protection | Needs 0A.2 |

**Gate 1 closes when** cross-tenant, session, permission, idempotency, migration and rollback
evidence all pass in CI from a clean clone.

### Gate 0 — the contracts, in parallel and blocked on the client

| ⛔ | 0.1 | Canonical field dictionary — draft written, approval pending |
| ⛔ | 0.2 | Role and permission matrix — draft written; two of its rows have no action in PLAN §14 |
| ⛔ | 0.3 | Launch decisions — region, identity, integrations, privacy |
| ⛔ | 0B.3 | Company onboarding: operator-provisioned, admin control-plane, or self-service |
| ⛔ | 0.4 | Clickable first-slice prototype |

### App Shell — only after Gate 1

| # | | |
|---|---|---|
| **7** | AS.1 | Dark sidebar — expanded and collapsed, remembered, Agents 01–04 |
| **8** | AS.2 | Top bar — breadcrumb, search, context action, notifications, Copilot |
| **9** | AS.3 | Role-based menu visibility; the server stays authoritative |
| **10** | AS.4 | Shell states — loading, empty, denied, offline, error |
| **11** | AS.5 | Keyboard, focus order, reduced motion, mobile drawer |
| **12** | AS.6 | Profile, workspace switcher, sign-out |

`IMPLEMENTATION_PLAN` §17: *"production shell code should use the approved i18n, permission and
component contracts rather than hard-coded temporary patterns."* That is why `1.7` comes first —
retrofitting i18n across five screens is an afternoon, across forty it is a week.

### Gate 2 — company onboarding and hierarchy

| # | | |
|---|---|---|
| **13** | 2.1 | Company onboarding — **needs 0B.3 decided first** |
| **14** | 2.2 | Manual hierarchy — tree, positions, effective dates, revisions |
| **15** | 2.3 | CSV/XLSX import — upload → scan → mapping → preview → validation → atomic apply |

### Gate 3 — the Objective slice

| # | | |
|---|---|---|
| **16** | 3.1 | Objective cards and Draft form |
| **17** | 3.2 | Claude proposal through the AI Gateway |
| **18** | 3.3 | Human editor and Publish |

**This is the first Gate where the client sees the product they asked for, working end to end.**

### Gates 4 to 8

| # | | |
|---|---|---|
| **19** | Gate 4 | Job Builder |
| **20** | Gate 5 | Agent Builder and Skill Registry |
| **21** | Gate 6 | Supervisor |
| **22** | Gate 7 | Runtime, to-do, notifications, Copilot |
| **23** | Gate 8 | Settings, privacy, enterprise identity, final test campaign |

Each is broken into sub-steps when it is reached, not before.

---

## What I do not decide

- **The order.** It is above. If an item looks like it should wait, I say so and ask — I do not
  move it.
- **Anything the plan does not specify.** Role names were invented once, in code. That will not
  happen again: where `PLAN.md` is silent, the answer is a question to the client, not a guess.
- **Whether something is done.** Its exit check passes, or it is not done.
