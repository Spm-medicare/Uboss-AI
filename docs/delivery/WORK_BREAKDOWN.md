# Work breakdown

**Subordinate to** `PLAN.md` and `docs/delivery/IMPLEMENTATION_PLAN.md`. This file breaks their
steps into tasks small enough to finish and check in one sitting. It sequences work; it never
changes scope, permissions, workbook contracts or Gate exit criteria.

Every task has an **exit check** — a command to run or a behaviour to observe. "It compiles" and
"the page opens" are not exit checks. A task without a passing exit check is not finished, and
saying otherwise is the failure mode this whole document exists to prevent.

Task ids are stable. `T-1.1.3` is always the same task, even if it moves in the order.

## Status at the time of writing

| | Count |
|---|---|
| Gates passed | 0 of 8 |
| Steps complete | 0 of 28 |
| Steps in progress | 9 |
| Steps not started | 19 |

Detail is at task level for the next two blocks, because we can be precise about them. Later
Gates stay at step level and are broken down when they are reached — writing forty tasks for
Gate 6 today would be guessing, and a plan full of guesses is worse than a short one.

---

# Block A — Finish protecting the work

Three tasks. None is large; all of them are the difference between a recoverable mistake and a
lost week.

#### T-0A.2 — Private remote

**Do:** Create a private repository on the approved host. Push `main`. Confirm a fresh clone into
an empty directory reproduces the build with no reference to the old project.

**Blocked on:** the client — the repository has to be created under their account, not ours.

**Done when:** `git clone <url> /tmp/check && cd /tmp/check/backend && uv sync && uv run ruff check .`
passes from a directory that has never seen this project.

#### T-0A.3 — Branch protection

**Do:** Protect `main`: no direct pushes, pull request required, at least one review, and the CI
checks from T-1.6.4 required to pass before merge.

**Why now rather than later:** protection added after a team is already pushing to `main` is
protection people route around. It costs nothing while there is one contributor.

**Done when:** a direct `git push origin main` is refused by the server.

#### T-0A.4 — Secret scanning

**Do:** Enable the host's secret scanning with push protection, and add a pre-commit hook that
refuses a commit containing a key-shaped string.

**Why:** a committed secret is not fixed by the next commit. It stays in the history, and every
credential in it must be rotated.

**Done when:** an attempt to commit a file containing a fake AWS key is refused locally, and the
same push is refused by the host.

---

# Block B — Close Gate 1's open security items

These come before anything visible. Each one is a hole that gets more expensive to close after
more code depends on the current shape.

## Step 1.1 — Database and tenant-boundary hardening

#### T-1.1.3 — Narrow the credentials table ⟵ **next**

**The problem, measured:** the application role can read every row of `users` — every email
address and every Argon2 hash, across every tenant.

```
$ psql -U uboss_app -d uboss -c "SELECT count(*) FROM users;"
 2
```

One SQL injection, or one leaked application password, and every hash in the system is available
for offline cracking, with the staff roster attached. `DECISIONS.md` #11 argued this table "holds
nothing worth stealing". That argument was too generous and is superseded here.

**Do:** Remove the application role's direct access to `users`. Authentication reaches it through
a narrow, reviewed interface instead. Two candidate mechanisms, to be settled in an ADR before
any code changes:

- `SECURITY DEFINER` functions owned by the migration owner, granted to the application role, each
  doing exactly one thing: `auth_find_by_email`, `auth_record_failure`, `auth_record_success`.
  Every function is a reviewed surface; nothing else in the table is reachable.
- A separate least-privilege role and connection pool used only by the authentication module.

**Recommendation:** the functions. A second pool is a second connection string, a second failure
mode and a second thing to configure wrongly, and it still leaves a role that can `SELECT *`.

**Done when:** `psql -U uboss_app -c "SELECT password_hash FROM users"` is refused, **and** sign-in,
lockout, rehash-on-sign-in and step-up all still work end to end.

#### T-1.1.4 — Migration safety procedure

**Do:** Write and rehearse the procedure: preflight check, forward migration, compatibility window
for a running old version, and a documented rollback or restore path per migration. Record which
migrations are irreversible and why (`0001` already is — it says so and refuses).

**Done when:** the procedure is in a runbook, and one migration has been applied and rolled back
against a copy of the database following it exactly.

## Step 1.2 — Authentication completion

#### T-1.2.4 — Invite, password set and reset

**Do:** Build the flows on top of the existing hashed, expiring, single-use action tokens in
`modules/identity/action_tokens.py` — which currently exist and are unused.

Rules that are not negotiable:

- Requesting a reset returns the same response whether or not the address has an account.
- No reusable plaintext password is ever sent.
- Completing a reset revokes every session for that person **in every tenant**.
- The screen never says "email sent" unless an email was actually accepted for delivery.

**Blocked on:** T-1.5.2. Without a working outbox and a real mail provider, the only honest
implementation is one that tells the person delivery is unavailable — which is not a usable
invite flow. Codex was right not to fake this.

**Done when:** an invited person can set a password and sign in; a reset ends every other
session; and with mail delivery switched off the screen says so rather than claiming success.

## Step 1.3 — Real permission ceiling

Today the ceiling algorithm exists and is correct, but nothing above the role layer is ever
loaded — so in practice a role is the whole answer.

#### T-1.3.1 — Persist policies

**Do:** Tables for company-scope and department-scope policy. A policy is a **restriction**: it
lists actions withheld from every role beneath it. It cannot grant.

**Done when:** a company policy withholding `publish` is stored and visible.

#### T-1.3.2 — Resolve policies into the request

**Do:** Load the applicable policies while the security context is built, into `policy_grants`.

**Done when:** the admin who currently holds all 13 actions loses `publish` from `/auth/me` the
moment a company policy withholds it — with no code change and no sign-out.

#### T-1.3.3 — Resource grants

**Do:** Per-object grants (this Objective, this Agent), narrowing only. A resource grant that
tries to widen is rejected at write time, not silently ignored at read time.

**Done when:** a grant naming an action the role does not hold is refused when saved.

#### T-1.3.4 — Guard API and separation of duty

**Do:** One `require(action, resource)` path used by every route. Self-approval refused by
`SelfApprovalRule` wherever an approval is recorded. High-risk actions require a live step-up.

**Done when:** the author of a version cannot approve it, and publishing without a step-up in the
last 15 minutes is refused.

#### T-1.3.5 — Audit denials

**Do:** Write a `denied` audit row naming the scope that withheld the action — for the
administrator, never for the refused caller.

**Done when:** a refusal appears in `audit_events` with `denial_reason`, while the HTTP response
still says only "You do not have permission to do this."

## Step 1.4 — Idempotency and concurrency

`core/idempotency.py` is 10 KB with **zero callers**. It is dead code today. Either it gets wired
or it gets deleted; leaving it is how a file rots into something nobody trusts.

#### T-1.4.1 — Wire the middleware

**Do:** Apply it to every mutating `/api/v1` route. Same key + same body replays the stored
response. Same key + different body is refused. A duplicate arriving while the first is still
running gets a deterministic retry answer, not a second execution.

**Note:** sign-in is deliberately excluded — it uses rate limits and the challenge instead, and
an email address must never become an idempotency key.

**Done when:** the same POST sent twice creates one row and returns the same body twice; with a
changed body it returns 409.

#### T-1.4.2 — Expiry and cleanup

**Done when:** records past `expires_at` are removed by a scheduled job, and the table does not
grow without bound.

#### T-1.4.3 — Optimistic concurrency

**Do:** Mutating routes take the version the caller read and refuse if the row moved. The
`OptimisticVersion` mixin exists; nothing uses it.

**Done when:** two saves from two stale reads produce one success and one 409 — never two
successes.

## Step 1.5 — Outbox

#### T-1.5.1 — The relay role

**Do:** Create the dedicated cross-tenant role with a role-scoped policy on `outbox_events` only,
and grants on nothing else. This is the single cross-tenant credential in the system; it arrives
now because something is finally about to use it.

**Done when:** the role can read due outbox rows and is refused on every other table.

#### T-1.5.2 — The relay

**Do:** Claim with a lease, publish, mark, retry with backoff, dead-letter after exhaustion.
Delivery is **at least once**; every consumer tolerates a duplicate. Nothing anywhere claims
exactly-once.

**Done when:** an event survives a relay kill mid-publish and is delivered exactly one more time —
and a permanently failing event lands in the dead-letter view instead of disappearing.

## Step 1.6 — Files, observability, delivery

#### T-1.6.1 — File storage
S3-compatible, tenant-prefixed keys, stored hash and classification, short-lived signed URLs, and
a scan state that blocks download until it is clean.
**Done when:** a file uploaded in one tenant is unreachable from another, including by direct key.

#### T-1.6.2 — Telemetry
OpenTelemetry traces and metrics correlated across web, API, database and worker by the
correlation id already threaded through the logs.
**Done when:** one browser action can be followed end to end by its correlation id, and no span
carries a secret.

#### T-1.6.3 — Automated tests ⟵ **the one that unblocks every Gate**

There is no `tests/` directory. Not one automated test exists. `IMPLEMENTATION_PLAN.md` is
explicit: without automated evidence a Gate stays open however good the code is.

First suite, in this order:

1. **Cross-tenant** — for every tenant-owned table: unbound reads nothing; bound reads only its
   own; a write aimed at another tenant is refused. This is the test that must never be allowed
   to fail.
2. **Session and security** — the sign-in refusals are indistinguishable; rate limits engage;
   Origin is enforced; a rotated token's grace window works and then does not; idle and absolute
   expiry both end a session.
3. **Permission** — role matrix, ceiling narrowing, self-approval refused, step-up required.
4. **Idempotency** — replay, conflict, concurrent duplicate.
5. **Migration** — every migration applies to an empty database and the schema matches the models.

**Done when:** `uv run pytest` passes from a clean clone against a throwaway database, and
deliberately breaking one RLS policy makes the cross-tenant suite fail.

#### T-1.6.4 — CI
Lint, strict types, migration check, secret and dependency scan, the T-1.6.3 suite, and both
builds — from a clean clone.
**Done when:** a pull request that breaks any of them cannot be merged.

#### T-1.6.5 — Environments and deploy
Dev, staging and production configuration; a secret manager; a rehearsed deploy and rollback.
**Done when:** a deploy and a rollback have both been performed against staging.

## Step 1.7 — Frontend foundation

Both of these get harder with every screen added. They come before the App Shell for that reason.

#### T-1.7.1 — Generated API types
`frontend/src/lib/api/schema.d.ts` does not exist; the response types are hand-written and will
drift from the API silently. Generate from the exported OpenAPI, and fail CI when they differ.
**Done when:** changing a response model without regenerating breaks the build.

#### T-1.7.2 — Translation keys
No i18n library is installed and every string is hard-coded English. Keys from the first screen,
English messages now, Hindi pack when approved. Retrofitting this across forty screens is a week;
doing it across five is an afternoon.
**Done when:** no user-visible literal remains outside the message catalogue.

#### T-1.7.3 — Locale and time
Timezone, date and number formatting driven by the person's setting, falling back to the
tenant's. Instants are UTC; display is local.
**Done when:** the same timestamp renders correctly for two people in different timezones.

#### T-1.7.4 — Shared primitives and universal states
Button, input, select, dialog, table, badge, toast — from `frontend/src/ui/`, tokens only, with
keyboard and focus behaviour. Every route implements loading, empty, error, denied and offline.
**Done when:** no page component declares its own button styling or a literal colour.

**Gate 1 exit:** cross-tenant, session, permission, idempotency, migration and rollback evidence
all pass in CI from a clean clone.

---

# Block C — The App Shell

Only after Gate 1. Navigation is fixed by `PLAN.md` §3 and nothing may be added to it.

| Task | What |
|---|---|
| T-AS.1 | Dark sidebar — expanded and collapsed, remembered, Agents group with 01–04 |
| T-AS.2 | Top bar — breadcrumb, search, context action, notifications, Copilot |
| T-AS.3 | Role-based menu visibility, server still authoritative on every route |
| T-AS.4 | Shell states — loading, empty, denied, offline, error |
| T-AS.5 | Keyboard, focus order, reduced motion, mobile drawer |
| T-AS.6 | Profile, workspace switcher, sign-out |

Search shows an honest unavailable state until Gate 7. Notifications and Copilot show governed
empty states. **No fake activity, no invented counts, no disconnected dashboard cards.**

---

# Blocks D onwards — the product

Step level only. Each is broken into tasks when it is reached.

| Block | Gate | Content | Plan estimate |
|---|---|---|---|
| D | 2 | Company onboarding · manual hierarchy · CSV/XLSX import | 2–3 weeks |
| E | 3 | Objective builder · Claude proposal · human editor · publish | 5–6 weeks |
| F | 4 | Job Builder — Form 3's header and all 16 step fields | 3–4 weeks |
| G | 5 | Agent Builder · Skill Registry · 400 skills / 2,400 rules | 4–5 weeks |
| H | 6 | Supervisor — personal and department scopes | 4–5 weeks |
| I | 7 | Temporal runtime · to-do · approvals · notifications · Copilot | 3–4 weeks |
| J | 8 | Settings · privacy/DPDP · enterprise identity · final campaign | 4–6 weeks |

Gate 3 is the first block where the client sees the product they asked for working end to end.

---

# Order of work

```
NOW  ─┬─ T-1.1.3  narrow the credentials table
      └─ T-1.1.4  migration safety procedure

THEN ─┬─ T-1.3.1 → T-1.3.5   the real permission ceiling
      ├─ T-1.4.1 → T-1.4.3   idempotency and concurrency
      └─ T-1.6.3             the first automated test suite

THEN ─┬─ T-1.5.1, T-1.5.2    outbox relay
      ├─ T-1.2.4             invite and reset (needs the relay)
      ├─ T-1.6.4, T-1.6.5    CI and deployment
      └─ T-1.7.1 → T-1.7.4   frontend foundation

      ── Gate 1 closes here ──

THEN ─── T-AS.1 → T-AS.6     the App Shell
THEN ─── Blocks D → J        the product
```

Waiting on the client: **T-0A.2** (private repository), and the open Gate 0 decisions —
company onboarding, region, identity strategy, first integrations, privacy roles.

## Two things worth saying plainly

**Nothing in Block B is visible.** It is all boundary, evidence and correctness. It is also the
part that cannot be added afterwards without rewriting the schema, the API and the screens on top
of them — which is exactly what happened to the previous build.

**T-1.6.3 is the one that changes the reporting.** Until an automated suite exists, every claim
in this repository rests on a check somebody ran by hand once. That is why nine steps read
"in progress" rather than "done", and why no Gate can pass yet.
