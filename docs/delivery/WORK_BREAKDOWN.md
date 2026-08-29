# Work breakdown

**Subordinate to** `PLAN.md` and `docs/delivery/IMPLEMENTATION_PLAN.md`.

Same Gate and Step numbers as the implementation plan — no second scheme. `1.3` here is `1.3`
there. This file only breaks each step into sub-steps small enough to finish and check in one
sitting.

Every sub-step has a **done when** — a command to run or a behaviour to observe. "It compiles"
and "the page opens" are not evidence. A sub-step without a passing check is not finished.

**Status: 0 of 8 Gates passed. 0 of 28 steps complete. 9 in progress. 19 not started.**

Within them: 1.1.1–1.1.3 and 1.2.1–1.2.5 are done and verified.

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

## 1.1 — Database and tenant-boundary hardening  🟡

| | | |
|---|---|---|
| 1.1.1 | Composite tenant foreign keys | ✅ |
| 1.1.2 | Tenant RLS on every tenant-owned table | ✅ |
| 1.1.3 | **Narrow the credentials table** | ✅ |
| 1.1.4 | Migration preflight, rollback and restore procedure | ⬜ ⟵ **next** |

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

**1.1.4 done when** the procedure is in a runbook and one migration has been applied *and* rolled
back against a copy of the database by following it exactly.

## 1.2 — Authentication and session completion  🟡

| | | |
|---|---|---|
| 1.2.1 | Redis rate limiting by address, address+IP and IP | ✅ verified |
| 1.2.2 | Single-use browser-bound workspace challenge | ✅ verified |
| 1.2.3 | CSRF / Origin validation on every unsafe method | ✅ verified |
| 1.2.4 | Absolute and idle expiry, token rotation with grace | ✅ verified |
| 1.2.5 | Step-up re-authentication, time-boxed | ✅ verified |
| 1.2.6 | Invite, password set, reset, recovery | ⬜ **blocked on 1.5.2** |

**1.2.6 rules that do not bend:** requesting a reset answers identically whether or not the
account exists · no reusable plaintext password is ever sent · completing a reset revokes every
session in every tenant · the screen never says "email sent" unless an email was accepted for
delivery.

**Blocked because** without a working outbox and a real mail provider the only honest build is
one that tells the person delivery is unavailable — which is not a usable invite flow.

## 1.3 — Real permission ceiling  ⬜

The algorithm exists and is correct. Nothing above the role layer is ever loaded, so today a role
is the entire answer.

| | | |
|---|---|---|
| 1.3.1 | Persist company and department policies | ⬜ |
| 1.3.2 | Resolve them into the request context | ⬜ |
| 1.3.3 | Resource-level grants, narrowing only | ⬜ |
| 1.3.4 | One guard API; separation of duty; step-up on high-risk | ⬜ |
| 1.3.5 | Audit denials with the scope that withheld the action | ⬜ |

A policy is a **restriction** — it lists actions withheld from every role beneath it. It cannot
grant.

**1.3.2 done when** the admin who holds all 13 actions loses `publish` from `/auth/me` the moment
a company policy withholds it — no code change, no sign-out.
**1.3.3 done when** a grant naming an action the role does not hold is refused at save time.
**1.3.4 done when** the author of a version cannot approve it, and publishing without a step-up in
the last 15 minutes is refused.
**1.3.5 done when** the refusal is in `audit_events` with a reason, while the HTTP response still
says only "You do not have permission to do this."

## 1.4 — Server idempotency and optimistic concurrency  ⬜

`core/idempotency.py` is 10 KB with **zero callers**. Dead code. Wire it or delete it.

| | | |
|---|---|---|
| 1.4.1 | Apply idempotency to every mutating `/api/v1` route | ⬜ |
| 1.4.2 | Expiry and cleanup | ⬜ |
| 1.4.3 | Optimistic concurrency — `expected_version` on every draft write | ⬜ |

Sign-in is deliberately excluded: it uses rate limits and the challenge, and an email address
must never become an idempotency key.

**1.4.1 done when** the same POST sent twice creates one row and returns the same body twice; with
a changed body it returns 409.
**1.4.3 done when** two saves from two stale reads produce one success and one 409 — never two
successes.

## 1.5 — Audit and minimum outbox  🟡

| | | |
|---|---|---|
| 1.5.1 | Append-only audit, atomic with the change it describes | ✅ verified |
| 1.5.2 | Least-privilege relay role | ⬜ |
| 1.5.3 | The relay — lease, publish, retry, dead-letter | ⬜ |

Delivery is **at least once**; every consumer tolerates a duplicate. Nothing claims exactly-once.

**1.5.2 done when** the role reads due outbox rows and is refused on every other table.
**1.5.3 done when** an event survives a relay kill mid-publish and is delivered exactly one more
time, and a permanently failing event lands in the dead-letter view instead of disappearing.

## 1.6 — Files, observability and delivery pipeline  ⬜

| | | |
|---|---|---|
| 1.6.1 | S3-compatible files — tenant-prefixed keys, hash, scan state, signed URLs | ⬜ |
| 1.6.2 | OpenTelemetry traces and metrics on the existing correlation id | ⬜ |
| 1.6.3 | **Automated test suite** | ⬜ ⟵ **unblocks every Gate** |
| 1.6.4 | CI — lint, types, migrations, secret scan, tests, both builds | ⬜ |
| 1.6.5 | Environments, secret manager, rehearsed deploy and rollback | ⬜ |

**1.6.3 — there is no `tests/` directory. Not one automated test exists.** The implementation plan
is explicit: without automated evidence a Gate stays open however good the code is. This is why
nine steps read *in progress* rather than *done*.

First suite, in this order:

1. **Cross-tenant** — every tenant-owned table: unbound reads nothing, bound reads only its own, a
   write aimed at another tenant is refused. This one must never be allowed to fail.
2. **Session and security** — refusals indistinguishable, rate limits engage, Origin enforced,
   rotation grace works then stops, idle and absolute expiry both end a session.
3. **Permission** — role matrix, ceiling narrowing, self-approval refused, step-up required.
4. **Idempotency** — replay, conflict, concurrent duplicate.
5. **Migration** — every migration applies to an empty database; schema matches the models.

**Done when** `uv run pytest` passes from a clean clone against a throwaway database, and
deliberately breaking one RLS policy makes the cross-tenant suite fail.

**1.6.1 done when** a file uploaded in one tenant is unreachable from another, including by direct
key.
**1.6.2 done when** one browser action can be followed end to end by its correlation id, and no
span carries a secret.
**1.6.4 done when** a pull request that breaks any check cannot be merged.

## 1.7 — Frontend foundation  ⬜

Both of these get harder with every screen. They come before the App Shell for that reason.

| | | |
|---|---|---|
| 1.7.1 | Generated OpenAPI types — `schema.d.ts` does not exist | ⬜ |
| 1.7.2 | Translation keys — no i18n library, all strings hard-coded | ⬜ |
| 1.7.3 | Locale, timezone, date and number formatting | ⬜ |
| 1.7.4 | Shared primitives and the five universal route states | ⬜ |

**1.7.1 done when** changing a response model without regenerating breaks the build.
**1.7.2 done when** no user-visible literal remains outside the message catalogue. Retrofitting
this across forty screens is a week; across five it is an afternoon.
**1.7.4 done when** no page component declares its own button styling or a literal colour.

**Gate 1 passes when** cross-tenant, session, permission, idempotency, migration and rollback
evidence all pass in CI from a clean clone.

---

# App Shell — sidebar, topbar, navigation  ⬜

Only after Gate 1. Navigation is fixed by `PLAN.md` §3; nothing may be added to it.

| | |
|---|---|
| AS.1 | Dark sidebar — expanded and collapsed, remembered, Agents 01–04 |
| AS.2 | Top bar — breadcrumb, search, context action, notifications, Copilot |
| AS.3 | Role-based menu visibility; the server stays authoritative on every route |
| AS.4 | Shell states — loading, empty, denied, offline, error |
| AS.5 | Keyboard, focus order, reduced motion, mobile drawer |
| AS.6 | Profile, workspace switcher, sign-out |

Search shows an honest unavailable state until Gate 7. Notifications and Copilot show governed
empty states. **No fake activity, no invented counts, no disconnected dashboard cards.**

---

# Gate 2 — Company onboarding and Hierarchy  ⬜  ·  2–3 weeks

| | |
|---|---|
| 2.1 | Company onboarding per the Gate 0 decision; defaults, provisioning audit, rollback |
| 2.2 | Manual hierarchy — add, edit, move, position status, reporting type, effective dates, revisions |
| 2.3 | CSV/XLSX import — upload → scan → mapping → staging preview → validation → approved atomic apply |

Position is stable; person assignment is effective-dated. No AI and no import writes into the
live hierarchy without preview and approval.

**Passes when** cycle, orphan, duplicate-position, atomicity and subtree-permission evidence pass.

---

# Gate 3 — Objective end to end  ⬜  ·  5–6 weeks

| | |
|---|---|
| 3.1 | Objective cards and Draft form — every approved field and conditional rule, autosave |
| 3.2 | Claude proposal through the AI Gateway — versioned prompt, schema-validated output |
| 3.3 | Human editor and Publish — immutable version, approval route, audit evidence |

The AI produces a **proposal**. It never writes to governed state. Run events are real:
validate → context → workstreams → propose → policy → review.

**Passes when** one pilot Objective completes the real journey with no mock production logic.
**This is the first Gate where the client sees the product working end to end.**

---

# Gates 4 to 8  ⬜

| Gate | Content | Estimate |
|---|---|---|
| 4 | Job Builder — Form 3 header plus all 16 repeatable step fields, schedules | 3–4 weeks |
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
NOW    1.1.4    migration safety procedure

THEN   1.3.1 → 1.3.5    real permission ceiling
       1.4.1 → 1.4.3    idempotency and concurrency
       1.6.3            first automated test suite

THEN   1.5.2, 1.5.3     outbox relay
       1.2.6            invite and reset  (needs the relay)
       1.6.4, 1.6.5     CI and deployment
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
