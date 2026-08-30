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
| 4 | ✅ Job Builder — Form 3 header plus all 16 repeatable step fields, schedules | 3–4 weeks |

## Gate 4, broken down

Read from the approved workbook's **Form 3 — Job Method** sheet and `PLAN.md` §8, which agree:
the sheet's sixteen step columns are exactly the sixteen §8 lists by name. Nothing here is
invented, and the seventeen dropdown lists come from the workbook's own "Dropdown Lists" sheet.

| | | |
|---|---|---|
| 4.1 | ✅ Job schema, Form 3's header, and the sixteen-field step card |  |
| 4.2 | ✅ WHO assignment rules (§8's six types) and typed INPUT definitions |  |
| 4.3 | ✅ Schedules — auto-run, timezone, recurrence, DST, overlap, missed runs, concurrency |  |
| 4.4 | ✅ Publish — immutable `JobVersion`, approval route, reusing Gate 3.3's separation of duty |  |
| 4.5 | ✅ The Job Builder screen, on the shared Builder frame |  |

**Passes when** a Job publishes an immutable version, its schedule previews correctly across a
DST boundary, and every one of Form 3's fields round-trips.

| 5 | Agent Builder and Skill Registry — 400 skills / 2,400 rules, resolver, hard gates | 4–5 weeks |

## Gate 5, broken down

Read from `Universal_Enterprise_Skill_Catalog_IF_THEN (1).xlsx` and `PLAN.md` §9 and §39. The
workbook holds 12 archetypes, **400 skills**, **2,400 IF-THEN rules** and **12 exactness gates** —
and those gates are §39's *"deterministic compatibility gates"* by another name, already written
down with their own failure states.

§39 fixes the flow, and every arrow in it is a step here:

```
Agent requirement → Search Skill Registry → Deterministic compatibility gates
→ Reuse | Configure | Compose | Create private Skill Draft
→ Sandbox tests → Human approval → Versioned active Skill
```

| | | |
|---|---|---|
| 5.1 | Skill Registry schema and the seed import — archetypes, skills, rules, gates | ✅ |
| 5.2 | Search and the deterministic gates — similarity discovers, gates decide | ✅ |
| 5.3 | Agent schema and §9's ten form groups, with skill selection | ✅ |
| 5.4 | Sandbox tests and publish — immutable `AgentVersion`, tests as a publish gate | ✅ |
| 5.5 | The Agent Builder screen, with the Registry inside it | ✅ |

**Passes when** a search returns candidates a gate then refuses for a stated reason, an Agent
publishes only after its tests pass, and no skill can publish itself.

**Not a sidebar module.** §39: *"Skill Registry is internal to Agent Builder."* Nothing here adds
a menu item — §3 forbids it.

**5.1 — done.** Migration `0019_skill_registry`, four tables.

The shape is the design. `skill_archetypes` (T01–T12) and `skill_exactness_gates` (E01–E12) carry
no tenant at all: shared reference data, `GRANT SELECT` and nothing else, corrected by a migration
rather than by the product. `skills` holds **both** the 400 catalogue rows and a tenant's own
drafts in one table, because a search has to return both and the resolver has to gate both
identically. `skill_rules` is the 2,400 IF-THEN rules, each keeping the `failure_state` the sheet
gives it — which is what makes the answer to *"why was this refused"* a row rather than somebody's
judgement.

The catalogue is **one copy, shared**. `tenant_id IS NULL` means the seed, and the read policy has
a branch for it that the write policy does not:

```sql
CREATE POLICY skills_read  ON skills FOR SELECT
    USING (tenant_id IS NULL OR tenant_id = app_current_tenant());
CREATE POLICY skills_write ON skills FOR ALL
    USING (tenant_id = app_current_tenant()) WITH CHECK (tenant_id = app_current_tenant());
```

Every tenant reads the same 400 rows; none can write them. Copying the catalogue per tenant would
have meant 400 copies of every correction, and a catalogue that had diverged before anybody
noticed.

Two checks are held by the schema rather than by whichever service happens to write the row:

- `ck_skills_catalogue_or_private` — a row is one or the other, never both, so no row exists that
  nobody could classify.
- `ck_skills_published_was_approved` — §39's *"Skills cannot self-publish."* A published private
  skill must name who approved it and when.

**The import is idempotent, and reports rather than drops.** `modules/agents/seed.py` matches on
the workbook's own ids, so re-importing a corrected sheet updates in place instead of leaving two
`U-001`s. Rows it cannot use go into `Report.skipped` — a skipped row is something somebody has to
decide about, not a number to watch drift. Against the approved workbook: **12 archetypes, 12
gates, 400 skills, 2,400 rules, nothing skipped**; a second run reports `0 new, 400 updated`.

Autonomy is stored as the code alone (`A1`…`A4`), not the sheet's `"A1 — Read / analyze"`, because
a ceiling has to be comparable without parsing a sentence on every check. A generated `tsvector`
column with a GIN index is in place for 5.2, weighted name → purpose → trigger.

**`db/registry.py` came out of this step and matters beyond it.** `migrations/env.py` was missing
four model modules from its import list — and its own comment said an omission *"would generate a
DROP for a live table"*. There is now one import list, used by everything that needs the full
metadata, and `test_the_model_registry_lists_every_table_in_the_database` compares it against
`pg_tables`. A module that forgets it fails a test instead of a database.

Eleven tests in `tests/integration/test_skill_registry.py`. The five that import the real workbook
skip with a stated reason when it is absent — a suite that passed quietly without the catalogue
would prove nothing about the thing it is named after. The boundary tests seed one row of their
own rather than the whole sheet, and always run.

**5.2 — done.** `search.py` discovers, `gates.py` decides, `resolver.py` routes and records.

§39 names six things similarity may not override. Five are enforced by a gate, and the sixth is
reported rather than passed:

| §39 says similarity cannot override | Gate | Quotes |
|---|---|---|
| permissions | `authority` | E03 `BLOCKED — authority unresolved` |
| jurisdiction | `applicability` | its own words |
| data classification | `data_classification` | **unevaluated** — no skill declares one yet |
| required approval | `approval` | E12 `CANDIDATE ONLY — approval pending` |
| version status | `lifecycle` | its own words |
| stale evidence | `evidence` | E06 `UNVERIFIED — no trace` |

Two more run: `visibility`, and `minimum_inputs` (E02 `DRAFT — missing input`) — the only
**configurable** gate, and therefore the only one that produces *Configure* rather than *Block*. A
requirement naming no department, industry or layer is refused before anything is searched, with
E01's `BLOCKED — ambiguous scope` and the one question to answer.

**A refusal quotes the catalogue, or gives its own reason and quotes nothing.** The wording is read
from `skill_exactness_gates.failure_state` at evaluation time, so correcting the workbook corrects
the message. Where none of the twelve says what a gate means — "wrong department" is not
`STALE — refresh required` — the gate speaks for itself. A message that looked like it came from
the approved sheet and did not is a message nobody can check.

**Four gates cannot run yet and are recorded as `unevaluated`, never as passed.** Data
classification, tool scope and schema compatibility read tables the Skill Factory brings; a
resolution carrying any of them returns `requires_confirmation`, so it is offered to a person
rather than applied. `scope_exclusions` is a permanent exception, not a gap: in the workbook an
exclusion is a *sentence*, and a sentence is something a person reads. It is carried verbatim onto
every candidate card instead.

**Search widens, gates narrow.** Full-text over 0019's generated `tsvector`, ranked by
`ts_rank_cd` — no embedding call, because a decision recorded today has to be re-derivable
tomorrow. A plain sentence matches **any** of its words rather than all of them: no skill contains
every word of a requirement, and an AND search returned nothing, which made *Compose* unreachable.
Inactive skills are returned and then refused rather than hidden — "no skill does this" and "one
does, and it was retired" are different answers.

**Migration 0020, `skill_resolver_decisions`, append-only.** Trigger *and* withheld privilege. Each
row keeps the requirement verbatim, every candidate with its rank, its score, its exclusions and
every gate that judged it — passes included — plus the gates that did not run. Results are stored,
not recomputed: re-running today's gates against last quarter's decision would produce today's
answer and present it as history.

Six routes on `/api/v1/skills`: search, the registry's own vocabulary, one skill, resolve, and the
decisions this workspace has recorded. Nothing adds a sidebar item — §39 keeps the Registry inside
Agent Builder and §3 forbids a menu entry.

34 tests. `test_skill_gates.py` runs the gates with no database at all, so *similarity never
overrides a hard gate* is proved directly rather than inferred from an HTTP response;
`test_skill_resolver.py` proves it again end to end, against a catalogue row deliberately built to
outrank everything and fail E03.

**5.3 — done.** Migration 0021, eight tables, and `docs/architecture/AGENT_FIELDS.md` recording
which field came from where.

**Two sources, both kept whole.** The approved workbook's **Form 4** — read directly from
`UBOSS_Agent_Builder_Forms.xlsx` — is the business form: a header, twelve design rows of nine
columns, six printed error situations and five sandbox tests. §9 adds what a governed runtime
needs and a paper form has no column for: model policy, knowledge retention, explicit tool scopes,
cost and concurrency limits, an audience. Neither is a superset of the other, so neither was
trimmed. Nine of §9's ten groups are here; group 10 is the publish gate and belongs with 5.4.

Form 4 section A's nine columns are `agent_steps`, in the sheet's own order and none merged.
`test_every_column_of_form_4_section_a_survives_a_round_trip` names all of them, so a column
dropped from the schema fails a test rather than disappearing from a form nobody re-read.

**Section B is closed; everything else from the sheet is a suggestion.** Every workbook dropdown
ends in `Other`, so a value outside one is something the approved form itself allows — they are
published by `GET /agents/lists` and never validated against. Section B is different: the sheet
*prints* all six situations, so an unanswered one is not a value outside a list, it is a decision
nobody took. It is an enum, one answer per situation, and `situations_unanswered` reports what is
left rather than refusing the save — a form is filled in over time.

**§9's three extra sentences, each held somewhere a form cannot get around:**

- *"Tool suggestions never grant access."* There is no `granted` field on the tool input at all,
  so it is not a rule the service defends against a hostile payload — it is one the contract makes
  unstatable. Granting is a separate call behind `manage_access`, not `edit_draft`: designing an
  agent and deciding what it may reach are different authorities. A grant survives an ordinary
  edit and is dropped when the scopes widen, so editing a form can neither revoke access by
  accident nor expand it on purpose.
- *"Access choices: Only me, selected users, teams, department, role/subtree or workspace."* Six,
  exactly, defaulting to `only_me` because the plan's decision table says so. `only_me` sent with
  a share list is refused rather than half-applied — two answers to one question, and preferring
  either would discard somebody's intention without telling them.
- **An Agent runs an approved version.** `job_version_id` points at the immutable `job_versions`
  row, and a check constraint refuses a published, active or paused Agent that names none.

**A skill is attached with the decision that chose it.** `agent_skills.resolver_decision_id` links
5.2's record, and the route is copied *from* the decision rather than supplied by the caller — a
caller who could name the route could record a candidate as reused when the resolver had blocked
it. A decision that blocked is refused as a reason to use a skill at all.

**Model policy is a key, and its vocabulary is not invented.** v3.2 approves *"Claude first through
provider-neutral Gateway"* and names no policy catalogue, so `model_policy_key` is free text until
one is approved. Recorded as an open question in `AGENT_FIELDS.md` rather than filled with guesses.

Two real defects were caught rather than argued about. The submission check was first written as
*"status = 'draft' OR an approver is named"*, which made an abandoned draft impossible to archive;
it now applies from `ready_to_publish` onward. And the new tables were missing the `tenant_id`
index every other tenant-owned table has — the mixin declares it, so the models and the schema
genuinely disagreed, and every RLS policy on them would have been a sequential scan.

23 tests, 247 total.

**5.4 — done.** Migration 0022: `agent_tests` (Form 4 section C) and `agent_versions`.

**Two gates, and only two.** §9 says *"Tests and permission review are publish gates."* Both are
enforced at submission **and** re-checked at publish, because a test result can be cleared by an
edit between the two and a publish that trusted the earlier check would approve a design nobody
tested. Everything else is a warning — shown, never hidden, never in the way. A gate this build
invented would be a rule nobody approved.

- **Tests.** All five of section C must exist and read `Pass`. A refusal names which one and what
  state it is in. There is no sandbox runtime until Gate 7, so a status is recorded by the person
  who ran the test — `run_by` and `run_at` are stamped by the server, never accepted from the
  caller, and a status other than `Not Run` must carry what actually happened. A `Pass` with no
  observation is a claim nobody can check, and the schema refuses one.
- **Permission review.** Every tool must be granted or removed. A tool sitting ungranted at
  publish is a permission nobody reviewed — *"we'll sort the access out later"* is precisely what
  this gate exists to prevent.

**A test result belongs to a design.** Saving the Agent clears every recorded result back to
`Not Run`. Without it, somebody tests an agent, changes what it does, and publishes on the strength
of the old pass — with every gate reporting green. Deciding which edits "do not count" is exactly
the judgement that lets a stale pass through, so none of them do. The test itself survives: its
sample situation and expected result are part of the design, and only what was observed is cleared.

**Section B warns, it does not block.** Form 4 prints the six error situations *without* the
asterisk it puts on the four fields it does require, and §9 names only two gates. So an unanswered
situation is surfaced loudly and publishes anyway. Making it block is a business decision the
client can take; taking it here would have been inventing a rule.

`agent_versions` is immutable twice over — trigger and withheld privilege — with gapless
`version_no` from an advisory lock, and the snapshot holds the whole design including the tool
grants and the five results as they stood.

**Three real defects, two of them already shipped.**

1. `ck_agents_running_has_job_version` required a Job version on every running Agent. Form 4 marks
   *Job* without an asterisk, so an Agent that serves no Job was made unpublishable by a rule the
   approved form does not state. Now: only when there is a Job.
2. `ck_agents_submitted_has_approver` covered `published`. Removing a person clears that column, so
   a published Agent could **prevent somebody from being deleted at all** — an offboarding blocked
   by a foreign key and a right-to-erasure request that cannot be honoured. What was approved is
   recorded immutably on the version; the column only says who approves the next change. Scoped to
   `ready_to_publish`, with a publish-summary warning when a running Agent has lost its contact.
3. **`job_versions` had the same defect and it was already live.** `ON DELETE SET NULL` pointing
   into an append-only table is a contradiction: Postgres tries to rewrite the row, the trigger
   refuses, and anybody who has ever approved a Job becomes undeletable. `audit_events` already
   solved this by carrying **no** foreign key on `actor_membership_id`. `agent_versions` follows
   that, and 0022 drops the two constraints from `job_versions` — dropping a foreign key loses no
   data, and leaving a known offboarding block in place is worse than touching a shipped table.

**A contract test now catches the collision that bit twice.** FastAPI names an OpenAPI component
after the class, so two modules defining `PublishSummary` make the generator fully qualify **both**
— the new module's collision renames the existing one, and the frontend fails to compile in a file
nobody edited. It happened with `Visibility` in 5.3 and `PublishSummary`/`WarningRead` here.
`tests/integration/test_contract.py` asserts no schema name is fully qualified, and checks two
other contract-wide rules while it is there: every mutating route carries `Idempotency-Key`, and
the error envelope is published.

20 tests, 267 total.

**The test suite was not linted — now it is.** CI ran `ruff check .` with `working-directory:
backend`, and `tests/` sits at the repository root, so no test file had ever been linted through
twenty-two migrations. Twenty-one findings had accumulated. The CI step is now
`ruff check . ../tests`, and each finding was judged rather than blanket-silenced:

- **Two async functions were doing filesystem work inside the event loop** (`ASYNC240`). Both were
  moved rather than suppressed — the migrations' docstring check now reads its twenty-two files
  from a plain synchronous helper, and the backend path is computed once at import.
- **Three `S608` and one `S106`** are false positives on a test's own literal table list and on a
  column called `pass_evidence`. Each carries a `# noqa` **with the reason written next to it**,
  because a bare suppression is indistinguishable from a real one somebody stopped reading.
- The rest — unused imports, two long lines, two discarded unpack targets, one uppercase test
  name — were fixed outright.

A gate that covers only half the Python is a gate that teaches people the other half does not
matter.

**5.5 — done.** `/agent-builder` and `/agent-builder/[id]`, on the same frame as the Objective and
Job Builders — same section rail, same save states, same sticky footer, same autosave rules. §6
calls it the *shared* Builder experience and a person who has filled in one should not have to
learn a third.

**The Registry is a section, not a place.** §39: *"Skill Registry is internal to Agent Builder."*
There is no `/skills` route in the application and no menu entry — §3 forbids one. It sits in the
rail between Design and Situations, and it offers **browse** and **resolve** as two separate acts,
because they are two separate acts in the design: one ranks by resemblance, the other runs the
gates. A single box doing both would let a ranking read as a verdict.

**The screen cannot get around a gate.** A refused candidate has no attach button — the rule is
enforced in the backend and proved there, so what a screen can still get wrong is offering a
control that ignores it. Every refusal is rendered with the gate's own sentence, and with the
catalogue's `failure_state` where one of the twelve says exactly that. The one refusal with a
named remedy — missing inputs — is the only one carrying a button, and it fills the requirement's
input list rather than asking somebody to retype the catalogue's wording.

**The truthfulness rules, applied deliberately:**

- No invented numbers. `ts_rank_cd` is shown as an ordinal position (`#1`), never as a percentage.
  A test asserts the panel renders no `\d+%` anywhere. The publish screen says *"2 of 5 tests
  pass"* rather than *"40% ready"*, because a percentage needs a definition of "ready" nobody has
  agreed and would be read as one.
- No control that does not do what it says. The grant button is replaced by a sentence when the
  tool is unsaved, when the person lacks `manage_access`, or when the scopes were changed after
  the grant. A test status other than *Not Run* is disabled until an observation is written,
  because the schema refuses one without.
- No success reported for a failure. Every mutation on the screen renders its error; none of them
  toast.

**`is_editable` moved to the server.** The Job already sends it. Deriving it on the client would
have been a second copy of a rule the service owns, and the copy on screen is the one people
would trust.

**A sidebar test was rewritten rather than deleted.** It asserted the Agent Builder was disabled
and labelled *"Not built yet — Gate 5"*. That is now false, so the assertion moved to Supervisor
(Gate 6) and a new test asserts the Agent Builder links. A disabled row and a working link are the
same rule read at two moments.

6 tests, 29 on the frontend. `tsc`, `eslint`, `vitest` and `next build` clean.
| 6 | Supervisor — personal and department scopes, handler grants | 4–5 weeks |

## Gate 6, broken down

`PLAN.md` §10. A Supervisor *"monitors and coordinates published Job Agents"* — it does not perform
business actions itself. CLAUDE.md states the boundary in one line: **Supervisor coordinates;
bounded Job/Synced workers perform business actions.**

**Two independent scopes, and the word is the requirement.** §10 makes both mandatory:

1. **Supervised members and Agents** — whose Agents are watched?
2. **Allowed handlers** — who may control this Supervisor?

They are separate questions with separate answers, and the whole gate turns on their staying that
way. A department head may control a Supervisor watching Agents whose outputs they may not read; a
person may have their Agents supervised without any say over the Supervisor. A design that let one
scope imply the other would collapse both into "the manager sees everything", which is the thing an
Org Node hierarchy exists to avoid.

**Six handler roles, each a real ceiling** — Viewer, Operator (pause/resume and safe retry),
Reviewer, Approver, Manager (scope and policy), Owner.

**What Claude may not do**, verbatim from §10: *"Claude cannot bypass policy, grant permission,
perform uncontrolled retries or approve high-risk actions."* Four prohibitions, each of which has
to be something the schema or the guard refuses rather than something a prompt asks for.

**Where the runtime boundary falls.** Half of §10's capability list — heartbeat, starting
dependency-ready work, pause/resume/cancel, safe retry — needs the Temporal runtime, which is
Gate 7. Gate 6 delivers the **governed design**: the scopes, the handler grants, the policies, the
budgets and the publish gate. The same split Gate 5 made between a designed Agent and a run one,
and the same rule about saying so: a control that cannot act yet is disabled and labelled, never
shown working.

§10's form groups, mapped to the steps:

| | | |
|---|---|---|
| 6.1 | Supervisor schema and the two independent scopes — supervised set, handler set | ✅ |
| 6.2 | Handler roles as a ceiling — six roles, granular permissions, no self-grant | ✅ |
| 6.3 | §10's form groups 4–9 — order, dependency, quality gates, budget, SLA, escalation | ✅ |
| 6.4 | Failure simulation and publish — immutable `SupervisorVersion` | ⬜ |
| 6.5 | The Supervisor screen | ⬜ |

**Passes when** the two scopes can be set to disjoint sets and both hold, a handler is refused an
action above their role with the reason recorded, a Supervisor publishes only after its failure
simulation passes, and nothing in it can grant a permission.

**Not a second permission system.** §14's `Action` vocabulary and the existing guard decide what a
person may do in the workspace. A handler role narrows that *further* for one Supervisor; it never
widens it. Gate 6 adds no verb to `Action` — if it needs one, that is a change to §14 and to the
plan, not to a table.

**6.1 — done.** Migration 0023: `supervisors`, `supervisor_supervised`, `supervisor_handlers`.

**The two scopes are independent, and a test states it as a requirement rather than describing it.**
`test_the_two_scopes_can_be_disjoint_and_both_hold` sets them to disjoint sets — a department head
controlling a Supervisor that watches somebody else's Agents, nobody in both — and asserts both
hold. There is no foreign key between the two tables, no shared column and no rule that reads a
department and produces a handler. If a future convenience ever derives one from the other, that
test fails, which is why it exists before anything reads either scope.

**Two kinds, and the third is absent on purpose.** §10: *"Workspace-wide Supervisor is restricted
and may be added later."* `kind` has two values, and a test proves `'workspace'` cannot be written.
A value nobody approved is a value somebody eventually sets.

**Personal means personal, and a trigger says so.** §10: *"supervises that user's permitted Job
Agents."* A supervised row naming anybody but the owner is refused in the database rather than by
a service — it is what the word means, and an import or a future bulk route must not get around it.

**The owner is `NOT NULL` and its foreign key is `RESTRICT`.** A Supervisor with no owner is one
nobody is answerable for. Removing somebody who owns one makes you reassign it first, which is a
decision rather than a cascade — the opposite choice from `agent_versions`, and for the opposite
reason: that column is history, this one is responsibility.

10 tests, 277 total.

**6.2 — done.** `supervisors/roles.py`, `supervisors/guard.py`, `supervisors/handlers.py`.

**A role narrows; it never grants.** Every Supervisor action goes through two independent checks
and neither substitutes for the other — the workspace guard first (does this person hold the verb
at all, after the company → department → resource chain), then the handler role. The workspace
check runs first deliberately: somebody who holds `run` nowhere is told that, rather than being
told they are not a handler, which would have implied they would be fine if only somebody added
them.

Two tests state the rule from both sides. `test_a_role_never_widens_what_the_workspace_withheld`
makes somebody **Owner** of a Supervisor, removes `publish` from their workspace role, and asserts
they are still refused. `test_the_workspace_grant_alone_is_not_enough` gives somebody `view`
across the workspace and no handler row, and asserts the same.

**The mapping onto §14's verbs is a reading, and it is written down.** §10 names six roles and
describes four of them; `roles.py` derives each role's verbs from those words and nothing more —
Operator gets `run` because §10 says *"pause/resume and safe retry"*, Reviewer gets `comment`
because it says *"review output/request changes"*, Manager gets `manage_access` because it says
*"manage scope/policy"*. The list is treated as **cumulative** because §10 gives it in increasing
authority and ends with Owner; the alternative would mean an Approver who cannot read what they
are approving.

**No role confers a workspace-wide verb.** `administer`, `audit`, `export` and `integrate` are
refused for every role including Owner. A Supervisor's Owner is not a workspace administrator, and
without this a Supervisor would be a route to becoming one.

**"Claude cannot grant permission"** — §10's own words, and a handler list is one bad rule away
from being exactly that. Four refusals close it: nobody grants a role above their own, nobody
changes their own role, nobody removes somebody who outranks them, and the owner has no row to
remove at all. Removing *yourself* is allowed — walking away from a responsibility is not an
escalation, and refusing it would strand somebody who no longer wants it.

**The owner is Owner without a row.** Requiring them in their own handler list would mean a
Supervisor could be locked out of by deleting one row, and would make the row the source of truth
for something `owner_membership_id` already says.

Every refusal is written to the audit trail with the layer that caused it, before it is raised.
The caller gets one message either way — *"you are not a handler"* and *"your role does not go
that far"* describe an organisation's arrangements to somebody outside them.

13 tests, 290 total.

**6.3 — done.** Migration 0024: five tables and thirteen columns, covering §10's groups 4 to 9.
§10's capability list corroborates every one — *"start eligible dependency-ready work … track SLA,
deadline, cost, tokens and concurrency … detect quality/policy problems … escalate to configured
people … notify handlers and stakeholders."*

**Execution order needed no column.** §10 group 4 asks for it and `supervisor_supervised.position`
already is it. A second column would have been a second answer to one question.

**Two things a run could otherwise contradict itself over are refused by the schema.** A
dependency cycle — proved three deep, so the test exercises the recursive walk rather than a
self-reference the check constraint would have caught anyway — and a deadline falling inside its
own SLA, which would make every run late the moment it started.

**A real defect, caught by writing the test after the migration.** The migration claimed
`supervisor_schedules` carries *"the same columns as `job_schedules`, so the same code reads
them"* — and then allowed `yearly`, `strict`, `second` and `queue_one`, four values
`jobs/recurrence.py` cannot parse. A column that can hold a value its reader chokes on is worse
than a separate implementation, because it fails at the clock change rather than at the point
somebody wrote it. Corrected, and `test_the_schedule_columns_admit_exactly_what_recurrence_parses`
now asks **the constraint** rather than comparing two Python constants — which would have passed
while the column stayed wrong.

**The row → `Recurrence` conversion now has one home.** It was private to the Job's schedule
service; a second copy in the Supervisor's would have been a second copy of the field names, and
they drift the first time somebody renames one. It moved into the pure module as
`recurrence.from_row`, typed against a `Protocol` so both tables satisfy it and neither is named.

**One divergence worth raising.** The plan's decision table recommends *"Schedule overlap | Queue
one run."* `supervisor_schedules` defaults to `queue`, which is that. `job_schedules` defaults to
`skip`, which is not — a pre-existing difference from the plan's recommendation, left alone here
because changing a shipped default is a decision rather than a tidy-up.

**Nothing here executes anything.** The runtime is Gate 7. These are the settings a run will be
bound by; 6.5 shows every control that cannot act yet as disabled and labelled.

23 tests, 313 total.
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
