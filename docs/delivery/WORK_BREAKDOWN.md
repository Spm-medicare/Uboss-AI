# Work breakdown

**Subordinate to** `PLAN.md` and `docs/delivery/IMPLEMENTATION_PLAN.md`.

Same Gate and Step numbers as the implementation plan — no second scheme. `1.3` here is `1.3`
there. This file only breaks each step into sub-steps small enough to finish and check in one
sitting.

Every sub-step has a **done when** — a command to run or a behaviour to observe. "It compiles"
and "the page opens" are not evidence. A sub-step without a passing check is not finished.

**Status: 0 of 8 Gates passed. 0 of 28 steps complete. 9 in progress. 19 not started.**

Within them: **1.1, 1.3, 1.4 and 1.5 are complete**, 1.2.1–1.2.5 are done, and the automated
suite that was blocking every Gate runs **55 tests**.

Legend: ✅ done and verified · 🟡 partly done · ⬜ not started

---

# Step 0 — Protect the work

| | | |
|---|---|---|
| 0A.1 | Git repository and baseline commit | ✅ |
| 0A.2 | Private remote, clean clone reproduces the build | ⬜ **waiting on client** |
| 0A.3 | Protected `main`, pull request review required | ⬜ |
| 0A.4 | Secret scanning and a pre-commit hook | ⬜ |
| 0B.1 | `PLAN.md` §38 points at the real design-system paths | ✅ |
| 0B.2 | Privacy and incident-response documents exist | ✅ |
| 0B.3 | Company onboarding decision | ⬜ **waiting on client** |

**0A.2 done when** `git clone <url> /tmp/check && cd /tmp/check/backend && uv sync && uv run ruff check .` passes in a directory that has never seen this project.
**0A.3 done when** a direct `git push origin main` is refused by the server.
**0A.4 done when** committing a file with a fake AWS key is refused locally *and* by the host.

---

# Gate 0 — Product Contract  ·  4 steps, all drafts, none approved

| | | |
|---|---|---|
| 0.1 | Canonical field dictionary — every workbook field mapped | 🟡 draft in `SOURCE_TRACEABILITY.md` |
| 0.2 | Roles, permission ceiling, sharing, entitlements | 🟡 draft in `ACCESS_MODEL.md` |
| 0.3 | Launch decisions — region, identity, integrations, privacy | 🟡 register open, nothing decided |
| 0.4 | Clickable first-slice prototype | 🟡 acceptance contract written, no Figma |

**Role names are no longer blocked on this.** They used to be hard-coded in a Python dictionary
and a CHECK constraint. Migration 0004 made roles a table (PLAN §17), so the eight names in `0.2`
are seeded as data from `backend/seeds/access_model_draft.json`, every one marked
`is_draft = true`. When the client approves the matrix it is a seed change — no migration, no
code change, no redeploy.

**Still open for `0.2`:** `ACCESS_MODEL.md` lists fifteen rows; PLAN §14 names thirteen actions.
*Analyze with AI* and *Billing/plan management* have no action in the approved specification and
are deliberately not seeded. Either PLAN §14 gains them, or the draft folds them into an existing
action. A client decision, not one to invent a name for.

**Gate 0 passes when** Product, Design and Engineering sign the same field, permission, lifecycle
and first-slice contracts.

---

# Gate 1 — Minimum Platform Foundation

## 1.1 — Database and tenant-boundary hardening  ✅

| | | |
|---|---|---|
| 1.1.1 | Composite tenant foreign keys | ✅ |
| 1.1.2 | Tenant RLS on every tenant-owned table | ✅ |
| 1.1.3 | **Narrow the credentials table** | ✅ |
| 1.1.4 | Migration preflight, rollback and restore procedure | ✅ |

**1.1.3 — done.** Migration 0006 revoked every privilege on `users` from `uboss_app` and
replaced them with five `SECURITY DEFINER` functions, one per operation authentication performs.
`modules/identity/credentials.py` is the only caller. DECISIONS 23 records what this protects
and what it does not.

Checked:
```
uboss_app: SELECT password_hash FROM users  ->  ERROR: permission denied
sign-in 200 - /me 200 - step-up wrong 401 / right 200 - stepped_up true
ten failures -> account locks -> correct password refused 401 -> unlock works
multi-workspace challenge -> select-workspace without a password -> 200
```

**1.1.4 — done.** `docs/runbooks/MIGRATIONS.md` holds the procedure;
`scripts/migration_preflight.py` reports pending revisions, which of them can be reversed, and
any statement that takes a blocking lock — exiting non-zero when a human has to decide.

Rehearsed on a restored copy: 0006 rolled back to 0005 (auth functions gone, `users` grant
restored), then forward to head again (functions back, grant revoked, 3 users / 4 memberships /
25 roles unchanged). Recorded in the runbook.

## 1.2 — Authentication and session completion  🟡

| | | |
|---|---|---|
| 1.2.1 | Redis rate limiting by address, address+IP and IP | ✅ verified |
| 1.2.2 | Single-use browser-bound workspace challenge | ✅ verified |
| 1.2.3 | CSRF / Origin validation on every unsafe method | ✅ verified |
| 1.2.4 | Absolute and idle expiry, token rotation with grace | ✅ verified |
| 1.2.5 | Step-up re-authentication, time-boxed | ✅ verified |
| 1.2.6 | Invite, password set, reset, recovery | ⬜ **needs a mail provider** |

**1.2.6 rules that do not bend:** requesting a reset answers identically whether or not the
account exists · no reusable plaintext password is ever sent · completing a reset revokes every
session in every tenant · the screen never says "email sent" unless an email was accepted for
delivery.

**The outbox is no longer the blocker** — 1.5.3 delivers. What is missing is a mail provider and
its credentials, which is a client decision. Until one is registered, an invite event is
dead-lettered as undeliverable rather than reported as sent.

## 1.3 — Real permission ceiling  ✅

All four links of PLAN §14 now exist and are enforced by one path — `modules/identity/guard.py`.
Verified by direct exercise (no product route uses it yet; those arrive in Gate 2):

```
permitted action allowed                      view
high-risk needs step-up                       publish refused, step_up_required
high-risk allowed after step-up               publish
ungranted action refused                      approve
unshared object leaves the layer absent       None, not empty
a grant narrows to what it names              [view]
resource layer refuses what it did not grant  edit_draft on a view-only grant
widening grant refused at write time          approve
unresolvable principal refused                team
self-approval refused                         author cannot approve
someone else's work may be approved           not refused
refusals written to the audit trail           4 denied rows, each with a reason
```

| | | |
|---|---|---|
| 1.3.1 | Persist company and department policies | ✅ |
| 1.3.2 | Resolve them into the request context | ✅ |
| 1.3.3 | Resource-level grants, narrowing only | ✅ |
| 1.3.4 | One guard API; separation of duty; step-up on high-risk | ✅ |
| 1.3.5 | Audit denials with the scope that withheld the action | ✅ |

A policy is a **restriction** — it lists actions withheld from every role beneath it. It cannot
grant.

**1.3.2 done when** the admin who holds all 13 actions loses `publish` from `/auth/me` the moment
a company policy withholds it — no code change, no sign-out.
**1.3.3 done when** a grant naming an action the role does not hold is refused at save time.
**1.3.4 done when** the author of a version cannot approve it, and publishing without a step-up in
the last 15 minutes is refused.
**1.3.5 done when** the refusal is in `audit_events` with a reason, while the HTTP response still
says only "You do not have permission to do this."

## 1.4 — Server idempotency and optimistic concurrency  ✅

`core/idempotency.py` was 10 KB with zero callers. It is wired now.

| | | |
|---|---|---|
| 1.4.1 | Apply idempotency to every mutating `/api/v1` route | ✅ |
| 1.4.2 | Expiry and cleanup | ✅ |
| 1.4.3 | Optimistic concurrency — `expected_version` on every draft write | ✅ |

Sign-in is deliberately excluded: it uses rate limits and the challenge, and an email address
must never become an idempotency key.

**1.4.1 — done**, on `DELETE /auth/sessions/{id}`, the one genuinely retryable business command
Gate 1 has. Revoking a session is naturally repeatable; the *audit row* is not, so without this a
retry after a dropped connection would record two revocations where one happened.

```
first call                     200 {"status":"revoked","session_id":"0a8aac13-..."}
same key, same request         200 identical body — replayed
same key, different request    409 idempotency_key_reused
no Idempotency-Key             422
audit rows after the retry     1
```

**1.4.2 — done.** `scripts/cleanup_idempotency.py`, per tenant, inside the tenant boundary. Run
hourly by cron; Temporal takes it over in Gate 7, when there is a scheduler.

**1.4.3 — done.** `core/concurrency.py` — the update carries `WHERE version = :expected` and
raises 409 when it matches nothing. Verified against `memberships`; no product route edits a
versioned draft yet, those arrive in Gate 3.

```
two people open the same record, both see version 1
first save succeeds                     version 1 -> 2
second save from the same stale read    409, refused
the first edit survived                 version 2, first person's text
a re-read then succeeds                 version 3
cross-tenant update refused             same 409, nothing about the row
```

## 1.5 — Audit and minimum outbox  ✅

| | | |
|---|---|---|
| 1.5.1 | Append-only audit, atomic with the change it describes | ✅ verified |
| 1.5.2 | Least-privilege relay role | ✅ |
| 1.5.3 | The relay — lease, publish, retry, dead-letter | ✅ |

Delivery is **at least once**; every consumer tolerates a duplicate. Nothing claims exactly-once.

**1.5.2 — done.** `uboss_relay` holds `SELECT` and `UPDATE` on `outbox_events` and nothing else:

```
outbox_events    SELECT ✔  UPDATE ✔  INSERT ✗  DELETE ✗
the other 13 tables      all four ✗
```

No `INSERT` — it delivers events, it does not invent them. No `DELETE` — a published row is
history and a dead row is evidence.

**A migration cannot create this role, and `uboss_owner` has no `CREATEROLE`.** It is the only
credential in the system that reads across every tenant, so bringing it into existence is an
operator action taken once, like provisioning a tenant. The migration checks and stops with
instructions rather than granting itself the power to continue.

**1.5.3 — done.** `modules/audit/relay.py`. Claim under a lease, publish outside the
transaction, mark in a second one. Holding a database transaction open across a network call is
how a pool runs out during an outage at somebody else's service.

**Delivery is at least once**, and the test proves it rather than the design claiming it:
`test_an_event_survives_a_worker_killed_mid_publish` claims an event, publishes it, abandons the
worker, and asserts the next one delivers it **exactly one more time** — not zero, not three.

**No publisher is registered.** Email waits on a provider the client has not supplied, so every
event is dead-lettered with `no publisher is registered` and the worker says so on start-up. A
placeholder that logged and returned would mark everything delivered and send nothing — the
exact failure the outbox exists to prevent.

16 tests. One found a real bug: the backoff capped its exponent at `2**10 = 1024`, so the stated
one-hour ceiling was unreachable.

## 1.6 — Files, observability and delivery pipeline  ⬜

| | | |
|---|---|---|
| 1.6.1 | S3-compatible files — tenant-prefixed keys, hash, scan state, signed URLs | ✅ |
| 1.6.2 | OpenTelemetry traces and metrics on the existing correlation id | ✅ |
| 1.6.3 | **Automated test suite** | ✅ 74 tests |
| 1.6.4 | CI — lint, types, migrations, secret scan, tests, both builds | 🟡 written, unproven |
| 1.6.5 | Environments, secret manager, rehearsed deploy and rollback | 🟡 written, never run |

**1.6.3 — done. 74 tests, `pytest tests/`.**

Every run builds a throwaway database by running the migrations, and drops it afterwards. Built
by alembic rather than `create_all`, because `create_all` produces the tables the models
describe and **none of the row-level security policies, triggers or grants** — which are exactly
what the security suite exists to test.

| Suite | Tests | |
|---|---:|---|
| `security/test_cross_tenant.py` | 10 | isolation, provisioning, credentials, append-only audit |
| `security/test_permission.py` | 12 | role matrix, ceiling, step-up, separation of duty, denials |
| `integration/test_idempotency.py` | 9 | replay, conflict, concurrent duplicate, concurrency |
| `integration/test_migrations.py` | 8 | head, drift, honest downgrades, role privileges |
| `integration/test_outbox_relay.py` | 16 | relay role reach, lease, retry, dead-letter, crash recovery |

**The security suite runs as `uboss_app`**, the role every API request uses. Running it as the
owner would prove nothing: FORCE is off (DECISIONS 22), so the owner sees everything by design.

**The table list is read from the catalogue, not hand-written.** A hand-written list stops
mentioning the table somebody added last week, and the first anyone knows is a breach.

**Both halves of the exit check pass.** The second one — "deliberately breaking one RLS policy
makes the suite fail" — is itself a test rather than a manual ritual:
`test_the_isolation_checks_would_actually_catch_a_broken_policy` disables row-level security on
one table, asserts the isolation check then *fails*, and restores it in a `finally`. Without it,
every isolation assertion would still pass if someone dropped a policy — they would all be
reading zero rows for the wrong reason.

`scripts/check.sh` runs everything CI will (1.6.4), in the order that fails fastest.
**1.6.1 — done.** MinIO locally, the same S3 API a deployment uses — no local branch in the code.
Keys are `t/<tenant>/<uuid>`, and the database CHECKs the shape, because row-level security
cannot look inside a string and object storage has no idea what a tenant is.

A file is not served until it has been scanned clean. No scanner is configured, so every upload
stays `pending` and stays undownloadable — visible, rather than a silent allow.

12 tests. Two found real bugs: a composite `SET NULL` foreign key was nulling `tenant_id` too, so
removing a person who had uploaded anything would have failed; and the relay compared a Python
clock against database timestamps, which fails whenever the two disagree.
**1.6.2 — done.** The correlation id that has been on every log line since the first commit is
now on every span too, with the tenant and the actor, so a trace and a log join on any of them.

Off unless `UBOSS_OTLP_ENDPOINT` is set — spans are still created and then dropped, so the code
path that runs on a laptop is the one that runs in production. A product that needs a telemetry
backend in order to start is a product nobody can run locally.

7 tests, including one that fails if any span attribute ever looks like a secret or contains an
email address. That half of the exit check needs a guard, not an assertion: a span reaches a
collector, a vendor and a shared dashboard, and nothing stops somebody adding a request body to
one except a test that fails when they do.
**1.6.4 — written, and honestly incomplete.** `.github/workflows/ci.yml` runs four jobs: lint and
types, then tests, build and the security scan in parallel. `scripts/check.sh` runs the same set
locally, so a pull request cannot pass on a laptop and fail there.

`infra/postgres/setup_roles.sql` creates the three roles and can run against any database — the
compose init script only runs on a fresh volume, so it never runs in CI. Writing it found a real
bug: its blanket `GRANT ON ALL TABLES` reopened `users` to the application role, and migration
0006 does not re-run to take it back. The script now revokes it itself.

**Not done, and it cannot be until there is a remote:** the exit condition is that a pull request
which breaks a check *cannot be merged*, and that is branch protection (0A.3). The workflow has
never run. It stays 🟡 until it has.

## 1.7 — Frontend foundation  ⬜

Both of these get harder with every screen. They come before the App Shell for that reason.

| | | |
|---|---|---|
| 1.7.1 | Generated OpenAPI types — `schema.d.ts` does not exist | ⬜ |
| 1.7.2 | Translation keys | ✅ |
| 1.7.3 | Locale, timezone, date and number formatting | ✅ 10 tests |
| 1.7.4 | Shared primitives and the five universal route states | ✅ |

**1.7.1 done when** changing a response model without regenerating breaks the build.
**1.7.2 done when** no user-visible literal remains outside the message catalogue. Retrofitting
this across forty screens is a week; across five it is an afternoon.
**1.7.4 done when** no page component declares its own button styling or a literal colour.

**Gate 1 passes when** cross-tenant, session, permission, idempotency, migration and rollback
evidence all pass in CI from a clean clone.

---

# App Shell — sidebar, topbar, navigation  ✅

Only after Gate 1. Navigation is fixed by `PLAN.md` §3; nothing may be added to it.

| | |
|---|---|
| AS.1 | ✅ Dark sidebar — expanded and collapsed, remembered, Agents 01–04 |
| AS.2 | ✅ Top bar — breadcrumb, search, context action, notifications, Copilot |
| AS.3 | ✅ Role-based menu visibility; the server stays authoritative on every route |
| AS.4 | ✅ Shell states — loading, empty, denied, offline, error |
| AS.5 | ✅ Keyboard, focus order, reduced motion, mobile drawer |
| AS.6 | ✅ Profile, workspace switcher, sign-out |

Search shows an honest unavailable state until Gate 7. Notifications and Copilot show governed
empty states. **No fake activity, no invented counts, no disconnected dashboard cards.**

---

# Gate 2 — Company onboarding and Hierarchy  ⬜  ·  2–3 weeks

| | |
|---|---|
| 2.1 | ⛔ Company onboarding per the Gate 0 decision; defaults, provisioning audit, rollback — **blocked on 0B.3** |
| 2.2 | ✅ Manual hierarchy — add, edit, move, position status, reporting type, effective dates, revisions |
| 2.3 | ✅ CSV/XLSX import — upload → scan → mapping → staging preview → validation → approved atomic apply |

Position is stable; person assignment is effective-dated. No AI and no import writes into the
live hierarchy without preview and approval.

**Passes when** cycle, orphan, duplicate-position, atomicity and subtree-permission evidence pass.

---

# Gate 3 — Objective end to end  ✅  ·  5–6 weeks

| | |
|---|---|
| 3.1 | ✅ Objective cards and Draft form — every approved field and conditional rule, autosave |
| 3.2 | ✅ Claude proposal through the AI Gateway — versioned prompt, schema-validated output |
| 3.3 | ✅ Human editor and Publish — immutable version, approval route, audit evidence |

The AI produces a **proposal**. It never writes to governed state. Run events are real:
validate → context → workstreams → propose → policy → review.

**Passes when** one pilot Objective completes the real journey with no mock production logic.
**This is the first Gate where the client sees the product working end to end.**

---

# Gates 4 to 8  ⬜

| Gate | Content | Estimate |
|---|---|---|
| 4 | Job Builder — Form 3 header plus all 16 repeatable step fields, schedules | 3–4 weeks |

## Gate 4, broken down

Read from the approved workbook's **Form 3 — Job Method** sheet and `PLAN.md` §8, which agree:
the sheet's sixteen step columns are exactly the sixteen §8 lists by name. Nothing here is
invented, and the seventeen dropdown lists come from the workbook's own "Dropdown Lists" sheet.

| | | |
|---|---|---|
| 4.1 | ✅ Job schema, Form 3's header, and the sixteen-field step card |  |
| 4.2 | ✅ WHO assignment rules (§8's six types) and typed INPUT definitions |  |
| 4.3 | Schedules — auto-run, timezone, recurrence, DST, overlap, missed runs, concurrency | ⬜ |
| 4.4 | Publish — immutable `JobVersion`, approval route, reusing Gate 3.3's separation of duty | ⬜ |
| 4.5 | The Job Builder screen, on the shared Builder frame | ⬜ |

**Passes when** a Job publishes an immutable version, its schedule previews correctly across a
DST boundary, and every one of Form 3's fields round-trips.

| 5 | Agent Builder and Skill Registry — 400 skills / 2,400 rules, resolver, hard gates | 4–5 weeks |
| 6 | Supervisor — personal and department scopes, handler grants | 4–5 weeks |
| 7 | Temporal runtime, to-do, approvals, notifications, governed Copilot | 3–4 weeks |
| 8.1 | Settings | |
| 8.2 | Privacy / DPDP | |
| 8.3 | Enterprise identity, security, reliability | |
| 8.4 | Final test campaign — E2E, security, load, DR, AI evaluation, pilot UAT | 4–6 weeks |

Broken into sub-steps when each is reached. Forty invented sub-steps for Gate 6 today would read
as a plan and behave as a guess.

---

# Order

```
NOW    1.6.4, 1.6.5     CI and deployment

THEN   1.2.6            invite and reset  (waiting on a mail provider)
       1.7.1 → 1.7.4    frontend foundation

       ══ Gate 1 closes ══

THEN   AS.1 → AS.6      App Shell
THEN   Gate 2 → Gate 8  the product
```

**Waiting on the client:** `0A.2` private repository, and the Gate 0 decisions — company
onboarding, region, identity strategy, first integrations, privacy roles.

## Two things worth saying plainly

**Nothing before the App Shell is visible.** It is all boundary, evidence and correctness — and
it is the part that cannot be added afterwards without rewriting the schema, the API and every
screen on top of them. That is exactly what happened to the previous build.

**1.6.3 is what changes the reporting.** Until an automated suite exists, every claim in this
repository rests on a check somebody ran by hand, once.
