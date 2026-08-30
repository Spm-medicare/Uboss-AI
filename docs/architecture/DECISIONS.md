# Decisions

One entry per decision that a future reader would otherwise have to reverse-engineer from the
code. Each says what was decided, why, and what it costs. Decisions are appended, never edited —
a superseded decision gets a new entry that names it.

---

## 1. Two application folders, not a workspace

**Decided:** `backend/` and `frontend/` are the only application folders. No `apps/`, no
`packages/`.

**Why:** PLAN §27 originally described the API twice — as `apps/api/` and again as
`backend/modules/` — and put the design system in a third top-level `packages/ui`. Two
"authoritative" structures is how the previous build drifted. The plan section has been rewritten
to match this, so there is one answer to "where does this file go?".

**Cost:** The design system cannot be versioned and published independently of the web
application. Nothing needs that today; if it ever does, the move is mechanical.

---

## 2. The API connects as a role that cannot disable row-level security

**Decided:** Two database roles. `uboss_owner` owns the schema and runs migrations.
`uboss_app` serves requests and holds only `SELECT/INSERT/UPDATE/DELETE`.

**Why:** A table's owner is exempt from its own RLS policies, and only the owner or a superuser
may alter them. An API connecting as the owner turns row-level security into decoration: one
forgotten `WHERE tenant_id = …` and a query returns every tenant's rows. Two roles make the
second boundary real rather than nominal.

**Cost:** Two connection strings to configure, and a migration cannot be run with the API's
credentials. Both are deliberate.

**Where:** `infra/postgres/init/01-roles.sql`, `backend/src/uboss/db/base.py`.

---

## 3. The tenant is bound per transaction, not per connection

**Decided:** `bind_tenant()` issues `set_config('app.tenant_id', …, true)` — the `true` makes it
transaction-local — and `current_context` calls it while resolving the session cookie, before
the route body runs.

**Why:** Connections are pooled. A setting that outlived its transaction would be inherited by
whichever request picked that connection up next, which is a cross-tenant read that no test
would catch because it depends on pool timing.

**Also decided:** the request session starts *unbound*. A route that takes it without also
requiring authentication therefore gets a session with no tenant bound, and row-level security
returns nothing to it. Forgetting to authenticate a route makes it useless, not dangerous.

**Where:** `backend/src/uboss/db/base.py`, `backend/src/uboss/db/session.py`,
`backend/src/uboss/core/dependencies.py`.

---

## 4. The permission ceiling is an intersection

**Decided:** `effective()` intersects the grants from company → department → resource → action.
A layer that grants nothing contributes nothing, so a missing company policy resolves to "no
actions", not "all actions".

**Why:** PLAN §14 requires that a lower scope can never grant more power than the scope above
it. A union would let a resource-level grant re-add a permission that company policy withheld,
which is precisely the escalation the ceiling exists to prevent.

**Refined while building Step 2.** The first version of this treated a scope with *no policy
configured* as an empty grant. Under intersection that meant a brand-new tenant could do nothing
at all, because nobody had written a company policy yet — which is not fail-closed, it is
unusable. The distinction that fixes it:

- **Roles grant.** Everything a person may do comes from the roles their organisation gave them.
- **Scope policies narrow.** A company or department policy is a *restriction*. A scope that has
  not written one has not taken anything away, so it is absent from the chain rather than
  contributing an empty set.

Failing closed still applies to a missing *grant*: a person with no roles is refused everything.
It does not mean treating an unwritten optional restriction as a total prohibition.

**Note:** `actions_for_roles()` deliberately *unions*, because one person may hold several roles
and holding both `builder` and `approver` should give both sets. Union across a person's roles,
intersection down the scope chain.

**Where:** `backend/src/uboss/core/permissions.py`,
`backend/src/uboss/core/context.py`.

---

## 5. Readiness runs a real query

**Decided:** `/health/ready` executes `SELECT 1` against the database with a timeout, reports
what it measured, and returns 503 when anything is down. `/health/live` touches nothing.

**Why:** A hard-coded `{"status": "ok"}` reports health it never measured, and the orchestrator
believes it. Separating live from ready matters too: a database outage should stop traffic, not
restart a healthy process.

**Where:** `backend/src/uboss/api/health.py`.

---

## 6. A mutation without an idempotency key is a programming error

**Decided:** The browser API client throws — at the call site, before any request is sent — if a
non-GET call has no `Idempotency-Key`.

**Why:** PLAN §28 requires idempotency keys where a client or workflow may retry. A key derived
per attempt (`crypto.randomUUID()` inside the call) makes the header decorative: the server
cannot recognise a retry, so a dropped connection becomes a duplicate command. Keys are derived
from the logical operation so a retry reuses them.

**Where:** `backend/src/uboss/…` will enforce the server half; `frontend/src/lib/api/client.ts`
holds the client half.

---

## 7. Mutations are never retried automatically

**Decided:** TanStack Query is configured with `mutations: { retry: false }`, and queries do not
retry a non-retryable `ApiError`.

**Why:** The client cannot know whether a mutation was applied before the connection dropped.
Retrying is a decision, made deliberately, with the same idempotency key. Retrying a 401, 403,
404 or 409 is simply wasted time — those will never succeed.

**Where:** `frontend/src/app/providers.tsx`.

---

## 8. The local stack uses 5433 and 6380

**Decided:** PostgreSQL is published on host port 5433 and Redis on 6380; the API runs on 8001.

**Why:** The previous UBOSS stack is still running on this machine and holds 5432, 6379 and 8000.
Taking those ports away from a running system to save a digit is not a trade worth making. Inside
the compose network the ports are unchanged.

**Where:** `infra/compose.yaml`, `backend/.env.example`, `frontend/.env.example`.

---

## 9. The theme is applied before React exists

**Decided:** A small script in the document head reads the stored choice and sets the `dark`
class before first paint. React subscribes to the document via `useSyncExternalStore` rather
than owning the theme in state.

**Why:** Anything that waits for hydration is too late to prevent a white flash for someone who
chose dark. And the theme genuinely is external state: another tab can change it, and the
operating system can change underneath both.

**Cost:** `theme-script.ts` (no React, server-safe) is separate from `theme.ts` (`"use client"`),
because the root layout is a Server Component and cannot import a module that pulls in a hook.

**Where:** `frontend/src/lib/theme-script.ts`, `frontend/src/lib/theme.ts`.

---

## 10. Base UI is imported from `@base-ui/react`

**Decided:** The package published as `@base-ui-components/react` was renamed; the current
stable release is `@base-ui/react` 1.7.0, and that is what is installed.

**Why:** PLAN §26 locks "shadcn/ui with Base UI primitives". The old package name's latest
release is `1.0.0-rc.0` and is marked deprecated on the registry. Following the rename keeps the
locked choice while staying on a stable release rather than a release candidate.

---

## 11. Credentials and profile are separate tables

**Decided:** `users` holds an email address and a password hash. Everything about a person —
display name, job title, roles, position in the hierarchy — lives on `memberships`, which is
tenant-owned.

**Why:** two reasons that point the same way.

*Correctness:* the same person can belong to several organisations, and each knows them
differently. One row cannot hold two names.

*Security:* `users` has no `tenant_id`, so row-level security has nothing to compare against and
cannot protect it. Rather than pretend otherwise, the table is kept empty of anything worth
stealing. Everything an attacker would actually want is on `memberships`, behind the same
boundary as the rest of the product. No endpoint returns a `users` row.

**Where:** `backend/src/uboss/modules/identity/models.py`.

---

## 12. Two policies have a second branch, and each requires something already proved

**Decided:** `sessions` can also be read by matching `token_hash` against a bound
`app.session_token_hash`. `memberships` can also be read by matching `user_id` against a bound
`app.user_id`.

**Why:** both cases are chicken-and-egg. Finding a session is what *establishes* the tenant, so
the tenant cannot already be bound. Listing someone's workspaces has to happen before they have
picked one.

Neither is a bypass:

- The session branch requires the caller to already hold the token. Knowing its hash is
  equivalent to holding it, so nothing is revealed that was not already in their possession.
- The membership branch requires a user id that is set only *after* a password has been
  verified, and it appears in the `SELECT` policy only. The write policies carry no such branch,
  so a verified user id yields a list of workspaces and nothing more.

**Where:** `backend/migrations/versions/0001_identity_and_governance.py`,
`backend/src/uboss/db/base.py`.

---

## 13. Sessions live in the database, not in a signed token

**Decided:** a session is 32 random bytes in an http-only cookie, with its SHA-256 stored in a
`sessions` row that is re-read on every request.

**Why:** a self-contained token cannot be withdrawn before it expires. This product needs
withdrawal to be immediate — PLAN §19 requires workspace and integration kill switches, and
deactivating a person has to end their access now rather than in thirty minutes. Every request
therefore re-checks that the membership is active, the account is active and the tenant is not
suspended.

SHA-256 rather than Argon2 for the token, deliberately: a password is guessable and needs a slow
hash; a 256-bit random token is not, and a slow hash per request would cost real latency for
nothing. What matters is that the stored value is one-way, and it is.

**Cost:** one indexed lookup per request. That buys the ability to end a session.

**Where:** `backend/src/uboss/modules/identity/tokens.py`,
`backend/src/uboss/modules/identity/service.py`.

---

## 14. A failed sign-in reveals nothing, and is still recorded

**Decided:** every sign-in failure returns 401 with one message —
*"That email address and password do not match an account."* — whatever actually went wrong:
wrong password, unknown address, locked account, deactivated user, suspended tenant, or a
workspace the person is not in. A password verification runs even when no account exists, so the
response time does not answer the question either.

Meanwhile a denied audit row is written to **every** organisation the person is an active member
of, because a run of these is what an attack looks like from the inside and an organisation
cannot see one it was never told about.

**Why:** distinguishable failures turn the form into an account-existence oracle, which is how a
company's staff list gets enumerated. Saying "that account is locked" to someone with the right
password is worse still — it turns a lockout into a way to *test* passwords.

**Deliberate gap:** an attempt against an address with no account writes no audit row, because
there is no organisation to attribute it to. That attempt is in the security log. Attributing it
somewhere would mean inventing the attribution.

**Where:** `backend/src/uboss/modules/identity/service.py`.

---

## 15. Strict email validation belongs where an address is created, not where it is checked

**Decided:** the sign-in form takes a plain, normalised string. `EmailStr` is not used there.

**Why:** a 422 "not a valid address" and a 401 "wrong credentials" are distinguishable, so a
strict validator on the sign-in form reopens exactly the oracle decision 14 closes. It also locks
out a real person whose provisioned address the validator happens to dislike — which is not
hypothetical: `EmailStr` rejects the RFC 2606 `.test` domain, and it would reject any address a
future validator update disagrees with.

Strict validation goes where an address is *created* — an invite — because that is where a typo
has a cost and where telling the truth about it is safe.

**Where:** `backend/src/uboss/modules/identity/schemas.py`.

---

## 16. One entry point chooses the event loop

**Decided:** the API starts with `python -m uboss`, not a bare `uvicorn` command.

**Why:** Windows offers an event loop the database driver cannot use, and uvicorn selects it —
unless the reloader is running the server in a subprocess. So the fault appears only when reload
is *off*: the configuration closest to production. Setting the event-loop policy does not fix it,
because uvicorn passes an explicit loop factory and the factory wins.

`uboss.core.runtime` supplies the factory, and the API, the migrations and every script go
through it. Keeping this in a launch command instead would mean it breaks the first time someone
starts the process a different way.

On Linux — every deployed environment — none of this does anything.

**Where:** `backend/src/uboss/core/runtime.py`, `backend/src/uboss/__main__.py`.

---

## 17. Creating an organisation is an operator action, not an API call

**Decided:** `tenants` has no INSERT policy for the application role, so no request can create
one. Provisioning is `scripts/provision_tenant.py`, which connects as the owner.

**Why:** it removes a whole class of question. There is no privilege escalation path to
"create a tenant" because the capability does not exist in the API, at any role.

The same script will not reset an existing account's password: if the address already has one,
the existing password stands. A provisioning command that can reset a password is a provisioning
command that can take over an account.

**Consequence:** self-service sign-up would need a deliberate, separately-reviewed path. That is
the correct amount of friction for the operation that brings a new customer's data boundary into
existence.

**Where:** `backend/scripts/provision_tenant.py`,
`backend/migrations/versions/0001_identity_and_governance.py`.

---

## 18. The outbox relay does not exist yet, and needs a role that does not exist yet

**Recorded, not decided.** `outbox_events` is written with the business data it describes, and
tenant-scoped RLS applies to it like everything else.

Nothing reads it yet. A relay is a system process, not a tenant request, and it legitimately
needs to read across tenants — which under RLS means a dedicated role with a role-scoped policy
on that one table and grants on nothing else.

That role is **not created**. It will be added with the relay, so that the only cross-tenant
credential in the system arrives at the moment something actually uses it, rather than sitting
unused and forgotten in a schema.

**Where:** `backend/src/uboss/modules/audit/models.py`.

---

## 19. Copied tenant identity columns are enforced as one database tuple

**Decided:** a role row must reference a membership from its own tenant, and a session's
`tenant_id`, `membership_id` and `user_id` must match one membership tuple. Composite unique keys
on `memberships` and composite foreign keys on dependent tables enforce this in PostgreSQL.

**Why:** three individually valid identifiers can still describe three different records. RLS
checks the dependent row's tenant; it does not prove that a referenced membership or user belongs
to that same relationship. Application checks are useful error handling, not an integrity
boundary.

**Cost:** the candidate-key indexes duplicate part of the primary/unique-key coverage and every
future tenant-owned relationship must choose an appropriate composite FK. The extra storage and
write cost buy a database-verifiable tenant invariant.

**Where:** `backend/migrations/versions/0002_tenant_relationship_integrity.py`,
`backend/src/uboss/modules/identity/models.py`.

---

## 20. Idempotent commands use transaction advisory locks and atomic replay records

**Decided:** eligible tenant business commands acquire a non-waiting, transaction-scoped
PostgreSQL advisory lock derived from tenant + operation + client key. A new replay record, the
business mutation and the successful response commit in one transaction.

**Why:** inserting a nullable “in progress” row inside the same transaction is invisible to other
transactions until commit. A concurrent duplicate could wait on the unique index or produce an
integrity error instead of a controlled API result. The advisory lock prevents the duplicate
from entering business logic and returns a stable retryable conflict immediately.

The database unique key is still authoritative. A rare advisory-hash collision only causes
temporary false contention; it cannot replay another operation because the table lookup uses the
full tenant, operation and key.

**Boundary:** sign-in, passwords, tokens, secrets, streams and large responses do not use stored
JSON replay. Credential-like response keys are rejected rather than redacted, because a redacted
retry would not equal the first response.

**Cost:** this is PostgreSQL-specific, every successful route must explicitly complete its replay
response, and expired records need tenant-scoped cleanup. Those constraints are deliberate and
checked by the shared execution context.

**Where:** `backend/src/uboss/core/idempotency.py`,
`backend/src/uboss/modules/audit/models.py`.

---

## 21. Workspace choice uses a single-use Redis proof, not the password again

**Decided:** the initial sign-in request verifies the password once. When several active
workspaces are available, Redis stores a hashed 256-bit challenge for three minutes with the
verified user id, allowed workspace snapshot and a keyed browser binding. Selection consumes the
challenge atomically with `GETDEL`, then re-checks current user, membership and tenant status
before creating the database session.

Anonymous sign-in is rate-limited independently by hashed IP, hashed account input and their
pair. Every supplied address receives the same counters whether or not an account exists. Redis
keys never contain raw email/IP values.

**Why:** keeping a password in browser component state and submitting it twice expands the time
and number of code paths that handle the credential. A random short-lived proof preserves the
verified step without turning it into a reusable session. Layered buckets slow distributed and
targeted guessing without relying only on account lockout, which an attacker can abuse for
denial of service.

**Failure policy:** if Redis is unavailable, new sign-in/challenge actions return a retryable 503;
existing database sessions continue independently. If a challenge is expired, consumed,
browser-mismatched or no longer authorized, the public response is the ordinary sign-in refusal.

**Cost:** workspace selection depends on Redis availability and a consumed challenge cannot be
reused after a downstream failure; the person must sign in again. This fail-closed behavior is
preferable to replaying a credential proof.

**Where:** `backend/src/uboss/core/rate_limit.py`,
`backend/src/uboss/modules/identity/challenges.py`,
`backend/src/uboss/modules/identity/api.py`, `frontend/src/app/sign-in/page.tsx`.

---

## 22. Browser mutations require an exact origin; sessions rotate inside fixed lifetimes

**Decided:** every unsafe `/api/v1` request, authenticated or anonymous, must present an Origin
that exactly matches the configured web origins. Referer origin is accepted only as a fallback;
missing, opaque (`null`) and cross-origin requests are refused. CORS and SameSite=Lax remain
additional browser controls, not substitutes for server verification.

Database sessions have three independent time controls: absolute expiry, idle expiry and token
rotation. Rotation keeps the original absolute expiry, moves the old hash into a two-minute grace
slot and sets a new opaque cookie. The RLS lookup policy may read the previous hash only during
that grace period; all session writes still require the tenant to be bound.

**Why:** same-site is broader than same-origin, so a compromised sibling subdomain may receive a
SameSite cookie on a cross-origin request. Exact origin enforcement closes that gap and also
prevents login CSRF. Idle expiry limits unattended access; rotation limits the useful life of a
copied browser token; fixed absolute expiry prevents activity from keeping a session forever.

**Concurrency:** only a request presenting the current token may initiate routine rotation. A
row lock re-checks that token and the due time. Requests already carrying the previous token may
finish during grace but do not rotate again, preventing token churn and random concurrent logout.

**Boundary:** non-browser integrations will use a separate bearer/service-account contract; they
cannot bypass the cookie API by omitting Origin. A lost rotation response can require sign-in
again after grace, but never extends or weakens the session.

**Where:** `backend/src/uboss/core/origin.py`,
`backend/migrations/versions/0003_session_expiry_rotation.py`,
`backend/src/uboss/modules/identity/service.py`,
`backend/src/uboss/core/dependencies.py`.

---

## 23. Step-up is recent session proof; recovery is not exposed before its boundaries exist

**Decided:** password step-up re-verifies the already authenticated identity under separate
Redis membership/IP limits and marks only the current database session. The proof expires after
15 minutes by default. High-risk routes require both their ordinary permission and a separate
step-up dependency; recent proof cannot grant an action the role ceiling denied.

Invite setup and password recovery use purpose-bound, expiring, single-use 256-bit tokens whose
hashes—not raw values—are held in Redis. The primitives exist, but the public API will not claim
to send or complete recovery until authorised issuance, audited notification delivery and
identity-wide session revocation are implemented. Password reset is a global identity event;
revoking sessions only in the currently selected tenant would leave other workspace sessions
alive and is therefore not an acceptable partial implementation.

**Why:** a non-expiring `step_up_at` silently turns one old proof into permanent high-risk access.
Requiring the password again without its own abuse limit turns a stolen session into an online
password oracle. Separately, a “reset email sent” response with no relay is false product
behaviour, while changing a global credential without revoking every session gives a stolen
session continued access.

**Failure policy:** a wrong password records tenant denial evidence but does not end the valid
session. Redis outage fails new step-up and action-token operations closed. A consumed, expired,
corrupt or wrong-purpose action token is rejected and cannot be replayed.

**Where:** `backend/src/uboss/modules/identity/action_tokens.py`,
`backend/src/uboss/modules/identity/api.py`,
`backend/src/uboss/modules/identity/service.py`,
`backend/src/uboss/core/dependencies.py`.

---

## 19. Roles are rows, not code — and the six names in the code were invented

**Superseded:** the role handling described in decisions 4 and 11's neighbourhood.

**What was wrong.** `core/permissions.py` held a `ROLE_MATRIX` dictionary naming six roles —
`viewer, contributor, builder, approver, manager, admin` — and migration 0001 wrote the same six
into a `CHECK` constraint. **Those names appear nowhere in `PLAN.md`.** They were invented while
implementing Step 2. The client caught it.

**What PLAN actually says.**

- §17: "Identity: tenants, users, memberships, teams, **roles**, **permissions**, resource
  grants, sessions, guests and service accounts." Roles are a table.
- §14: thirteen actions — view, comment, edit Draft, Publish, run, approve, assign, schedule,
  manage access, export, integrate, administer, audit. These *are* specified, and the `Action`
  enum already matched them.
- §25, first implementation deliverable #2: "Final role, sharing, Supervisor-handler and
  entitlement matrix." The matrix is a deliverable that has not been produced.

So PLAN specifies the actions and does not specify the role names. Putting role names in code
was the invention; putting actions in code was correct.

**Decided.** Migration 0004 creates `roles` and `role_permissions`, both tenant-owned and
RLS-forced. `membership_roles.role` (a string) becomes `role_id` (a foreign key). The `CHECK`
constraint listing the invented names is dropped. `ROLE_MATRIX` is deleted; `actions_from_rows`
resolves a caller's permissions from their role rows instead.

The thirteen actions stay constrained in the database, because unlike role names they are in the
approved specification.

**What this buys.** When the client approves the matrix it is a **seed change** — replace
`backend/seeds/access_model_draft.json`, run `scripts/seed_roles.py`. No migration, no code
change, no redeploy. Under the old shape it was all three.

**Seeded, and honest about it.** The rows loaded today are transcribed from
`docs/product/contracts/ACCESS_MODEL.md`, which is marked "Working Draft — not approved". Every
seeded role carries `is_draft = true` so no screen can present a draft as settled. `is_conditional`
preserves the draft's `C` cells — permitted only with an explicit resource grant — rather than
flattening them to allow or deny.

**Two rows were not seeded.** ACCESS_MODEL.md lists fifteen; PLAN §14 names thirteen actions.
"Analyze with AI" and "Billing/plan management" have no action in the approved specification.
They are recorded in the seed file as a Gate 0 question. Inventing action names for them would
have repeated the exact mistake this decision exists to undo.

---

## 20. `FORCE ROW LEVEL SECURITY` makes tenant data invisible to migrations

**Found while writing 0004, twice in two hours in different forms.**

`FORCE ROW LEVEL SECURITY` binds a table's owner to its own policies. That is why it is set — it
stops a maintenance script run as the owner from quietly reading every tenant.

It also means **a migration sees nothing.** A migration has no bound tenant, so every
tenant-owned table looks empty to it. 0004's first attempt read zero rows from
`membership_roles`, created zero roles, and then failed two steps later on a `NOT NULL` — a
silent no-op that surfaced as an unrelated error.

**The pattern for a data migration:** lift FORCE, rewrite, restore FORCE, all in one transaction
so there is never a committed moment where the table is unforced. `SET row_security = off` is
*not* an alternative — under FORCE it raises an error rather than granting a bypass. Iterating
tenant by tenant also works and is the right shape when a migration must respect per-tenant
policy.

**And the related trap, which has now appeared three times:** `session.add()` only stages a row.
The INSERT happens at the next flush, under whichever tenant is bound *then*. A loop that stages
rows for several tenants writes them all under the last tenant bound, and RLS correctly refuses
them — with an error naming a row and a tenant that look unrelated to the bug.

`db.base.tenant_scope()` exists to end this: it binds on entry and flushes on exit, so each
tenant's rows are written while that tenant is bound. Any loop writing across tenants uses it.

---

## 21. `op.drop_constraint` re-applies the naming convention

**Small, and it cost a failed migration.**

The metadata naming convention turns a constraint named `role_known` into
`ck_membership_roles_role_known` at creation. `op.drop_constraint("ck_membership_roles_role_known",
...)` then applies the convention *again*, asking PostgreSQL to drop
`ck_membership_roles_ck_membership_roles_role_known` — which does not exist.

Create with the convention; drop with raw SQL using the name PostgreSQL actually holds. Check it
with `\d <table>` rather than deriving it.

---

## 22. `FORCE` dropped, `ENABLE` kept — two switches, not one

**Supersedes the FORCE half of decisions 2 and 20.**

`ENABLE ROW LEVEL SECURITY` and `FORCE ROW LEVEL SECURITY` are separate, and conflating them cost
real time:

- **ENABLE** binds every role that is not the table's owner. `uboss_app` — the role every API
  request runs as — is not the owner. **This stays on every tenant-owned table.**
- **FORCE** additionally binds the owner. `uboss_owner` runs migrations and operator scripts and
  nothing else. **This is dropped** by migration 0005.

**Why.** FORCE made tenant data invisible to migrations, because a migration has no bound tenant.
Migration 0004 read zero rows, created zero roles, and failed two steps later on a `NOT NULL`.
The seed script failed the same way. Each needed a lift-and-restore dance around its own writes —
easy to forget, hard to notice forgetting, and the failure always surfaced somewhere unrelated.

**What is lost.** An operator script run as `uboss_owner` that omits a `WHERE tenant_id = …` sees
every tenant. Bounded: the owner credential is not in the API, not in the workers, not in any
process that serves a request. It is used deliberately, by a person.

**What is kept — measured after the change:**

```
uboss_app, no tenant bound      memberships 0 · roles 0 · audit_events 0
uboss_app, bound to acme        only acme's rows
uboss_app, write into globex    ERROR: violates row-level security policy
uboss_app, UPDATE audit_events  ERROR: append-only

uboss_owner, no tenant bound    4 memberships   ← intended; this is the change
```

That is the boundary PLAN §18 and §19 ask for, and Gate 1's cross-tenant exit tests still have
something real to test.

`tenants` was already ENABLE-without-FORCE so that provisioning could create an organisation.
This makes the rest consistent rather than leaving one table quietly different.

**Still required:** `db.base.tenant_scope()`, for any code running as `uboss_app` that writes
rows for more than one tenant. ENABLE still binds it, so the flush-ordering trap in decision 20 is
unchanged for API code. Only migrations and owner-run scripts got easier.

---

## 23. The credentials table is no longer reachable by the application role

**Supersedes decision 11's security argument.** Decision 11 split credentials from profile and
then argued that `users` therefore "holds nothing worth leaking". That was wrong. It holds every
Argon2 hash in the system and every address — a staff roster with the hashes attached — and
`uboss_app` could read all of it:

```
$ psql -U uboss_app -d uboss -c "SELECT count(*) FROM users;"
 4
```

The table split was still right. The conclusion drawn from it was not.

**Decided.** Migration 0006 revokes every privilege on `users` from `uboss_app` and replaces them
with five `SECURITY DEFINER` functions, one per operation the authentication code performs:

| Function | Used by |
|---|---|
| `auth_find_by_email(text)` | sign-in, failed-attempt audit |
| `auth_find_by_id(uuid)` | workspace challenge, step-up, session resolution |
| `auth_record_failure(uuid, integer, interval)` | failed sign-in |
| `auth_record_verified(uuid, text)` | password proved; optional rehash |
| `auth_record_sign_in(uuid)` | session created |

`src/uboss/modules/identity/credentials.py` is the only module that calls them, and each call is
a thin wrapper. The moment one grows a filter or a second query, the narrow surface stops being
narrow — new behaviour goes in a new database function, in a migration, where it is reviewed.

**What this buys, precisely.** Enumeration is gone. No function returns more than one row; each
takes an exact address or an exact id; there is no call that returns a list. An injection
elsewhere in the application cannot dump the table, because the role has no rights on it to
abuse.

**What it does not buy, said plainly.** Argon2 verification happens in Python, so a hash for the
one account being named still reaches the process. The protection is that you must already know
the exact address to get it. Moving verification into the database would remove that too, and is
not possible: PostgreSQL has no Argon2.

**Two details that make `SECURITY DEFINER` safe here.** Every function pins
`SET search_path = pg_catalog, public` — without it a caller can create a schema earlier in the
path, shadow the table the function names, and have it run against their own object with the
owner's rights. And `EXECUTE` is revoked from `PUBLIC` before being granted to `uboss_app`,
because PostgreSQL grants it to `PUBLIC` by default and every future role would otherwise inherit
a path to the credentials table.

**Consequence in the code.** `resolve_session` used to read the account with a SQL join. The
application role can no longer join `users`, so it is two queries: the membership and its
organisation from tenant-owned tables, then the account by id through the function.

**Verified after the change:**

```
uboss_app: SELECT password_hash FROM users  →  ERROR: permission denied for table users
uboss_app: SELECT count(*) FROM users       →  ERROR: permission denied for table users

sign-in 200 · /me 200 · step-up wrong 401 / right 200 · stepped_up true
wrong password 401 · unknown account 401 (identical)
multi-workspace challenge → select-workspace without a password → 200
ten recorded failures → counter resets, account locks, correct password refused 401
auth_record_verified → unlocked, counter zero
```

---

## 24. Roles grant; scopes only narrow — and they are different things in the code

**Corrects a shortcut in decisions 4 and 19.**

PLAN §14's chain is company → department → resource → action, with one rule: a lower scope can
never grant more power than the parent policy. PLAN §14 also lists roles under *Principals*, not
under scopes.

The implementation had the role entering the chain **as the department layer**. That worked only
because no real department policy existed. Migration 0007 creates them, and the two would have
collided — the role grant would have overwritten a genuine department restriction, or been
overwritten by it. Neither is a small bug.

**Decided.** They are separated:

```python
effective(baseline: frozenset[Action], grants: list[Grant]) -> frozenset[Action]
decide(action, baseline, grants) -> Decision
```

`baseline` is the union of what the caller's roles hold — the only thing that *grants*. `grants`
are the configured links of the chain, each holding what that link permits, intersected so a link
can only take away. A scope with no policy is skipped, not treated as empty.

**A second bug this exposed.** `SecurityContext.actions` returned the baseline. So `/auth/me`
reported `publish` to an administrator whose company policy withheld it — a button that every
attempt to press would refuse. It now returns the narrowed set, and `explain()` passes the
baseline separately so a refusal can still name the layer that caused it.

**Verified:**

```
Initech, company policy "Release freeze" withholding publish + integrate
  → 8 actions

Acme, no policy, identical `admin` role
  → 10 actions
```

No code change and no sign-out between them — the policy is read when the session is resolved.

---

## 25. What a policy is, and what a grant is

**`scope_policies` withholds.** A row lists an action taken away from every role beneath that
scope. There is no column that could add one, which is what makes the chain safe to leave
unconfigured: a company that has written no policy has not taken anything away, so a brand-new
tenant works.

**`resource_grants` narrows too.** It answers "may this principal do this on this object" and is
PLAN §17's "resource grants". It cannot hand out an action the principal's roles do not already
hold, because the chain is intersected — a grant naming something the role lacks resolves to
nothing.

**One thing modelled ahead of its dependency, deliberately.** `scope_policies.org_node_id` names
the hierarchy node a department policy covers. The hierarchy arrives in Gate 2, so there is no
foreign key yet and no department policy can be created. The column exists now because the
*company* half is needed now, and adding it later would be a second migration over the same
table. A department policy scoped to a node nobody occupies applies to nobody — correct, not a
gap.

**Two decisions deferred to the client, not invented:** `resource_grants.principal_kind` accepts
all five principals from PLAN §14, but only `user` can be resolved today. Teams, guests and
service accounts have no tables yet; the application refuses the others rather than guessing.

---

## 26. One guard, and what it does in what order

**Decided.** Every permission question goes through `modules/identity/guard.authorise`. A check
written separately into a screen, a service and a workflow is three checks that will eventually
disagree, and the one that disagrees quietly is the one that lets something through.

Four things happen, and the order is the design:

1. **Resolve the resource layer**, if the action names an object.
2. **The chain decides** — roles narrowed by company, department and resource.
3. **High-risk actions need a live step-up.** Checked *after* the permission, so someone who does
   not hold the action is refused outright rather than invited to re-enter their password for
   nothing.
4. **The refusal is recorded before it is raised**, naming the layer that caused it. The caller
   gets none of that.

`StepUpRequired` subclasses `PermissionDenied` so a route that forgets to handle it still fails
closed, but carries its own code so the interface can offer the password prompt instead of a
dead end.

**One refusal deliberately explains itself.** Self-approval says *"You submitted this, so someone
else has to approve it."* The person already knows the record exists — they wrote it — so there
is nothing left to protect, and silence would leave them pressing a button that never works.

**None and an empty resource grant mean opposite things.** `grant_for_resource` returns None when
nothing was granted, and the chain skips the layer — so a person with `view` from their role can
still see an object nobody explicitly shared. An empty grant would mean "this layer permits
nothing", refusing everything on every object, which is not what a sharing model means.

**A widening grant is refused at write time as well as being inert at read time.** Intersection
already makes it powerless, but a row that looks like access and behaves like nothing is worse
than an error: someone believes access was given. `check_grant_is_narrowing` refuses it where the
mistake is made.

**Verified by direct exercise**, twelve checks, all passing — including that a denial reason
reaches the audit trail and never the response:

```
access.publish.denied      permitted, but no password proof within the step-up window
access.approve.denied      no role held by this principal grants approve
access.edit_draft.denied   edit_draft is withheld by resource policy (resource grant)
access.approve.denied      separation of duty: the author of a change cannot approve it
```

No product route calls the guard yet — the routes that will are Gate 2 and later. That is stated
rather than hidden: the mechanism is built and proven, and it is not yet load-bearing.

---

## 27. Idempotency is wired, on the one command that has it

**`core/idempotency.py` had zero callers.** It was a well-built 10 KB module — advisory locks,
canonical fingerprinting, a refusal to replay credential-shaped responses — that nothing used.
Dead code rots into something nobody trusts, so it is either wired or deleted.

**Wired, on `DELETE /auth/sessions/{id}`.** That is the only genuinely retryable business command
Gate 1 has; the rest of the mutating routes are sign-in, workspace selection and step-up, all
deliberately excluded because they carry credentials and have their own replay design.

**Why an idempotent route for a naturally-repeatable action.** Revoking a session twice changes
nothing — the second revoke is a no-op. The *audit row* is not repeatable: without this, a retry
after a dropped connection records two revocations where one happened, and an investigation reads
two events. The command is idempotent; the evidence would not have been.

**The route now returns a body instead of 204.** A stored replay of "no content" cannot be told
apart from a request that never ran, so there would be nothing to replay.

**Measured:**

```
first call                     200 {"status":"revoked","session_id":"..."}
same key, same request         200 identical body — replayed
same key, different request    409 idempotency_key_reused
no Idempotency-Key             422
audit rows after the retry     1
```

**Cleanup is a cron script, and that is stated rather than assumed.**
`scripts/cleanup_idempotency.py` runs per tenant inside the tenant boundary. Temporal takes it
over in Gate 7 when there is a scheduler; until then it is cron, or a person. A table written to
by every mutating command grows without bound if nobody says who prunes it.

---

## 28. Optimistic concurrency, and why the client may not retry it

PLAN §28: "Optimistic concurrency prevents silent overwrite." PLAN §30: "A Draft is mutable with
optimistic concurrency."

The failure has no error message of its own, which is what makes it dangerous. Two people open
the same draft, both save, and the second write lands on top. No exception, no warning, nothing
in a log. The first person finds out days later, if at all.

**Decided.** `core/concurrency.py`. The update carries the version the caller read:

```sql
UPDATE ... SET ... WHERE id = :id AND tenant_id = :tenant AND version = :expected
```

Zero rows changed means someone else got there first, and the caller gets a 409 telling them to
re-read. The version is incremented by the helper, not by the caller — a caller that had to
remember would eventually forget, and a row whose version stops moving is a row that has quietly
stopped being protected.

**The client must not retry a 409 automatically.** Re-sending a stale write with a fresh version
is the silent overwrite, performed by hand. The frontend's TanStack Query configuration already
refuses to retry a non-retryable `ApiError` (DECISIONS 7), and `Conflict` is not retryable.

**Zero rows means two things and reports one.** The row moved on, or it never existed for this
tenant. The caller is told the first, because distinguishing them would confirm that a record
they cannot see exists.

**Verified** against `memberships`, which carries the column. No product route edits a versioned
draft yet; those arrive in Gate 3.

```
first save succeeds                     version 1 -> 2
second save from the same stale read    409, refused
the first edit survived                 version 2
a re-read then succeeds                 version 3
cross-tenant update refused             same 409, nothing about the row
```

---

## 29. The test suite builds its database from the migrations, and runs as the application role

**Two choices that decide whether the suite proves anything.**

**Built by alembic, not `create_all`.** `create_all` produces the tables the models declare and
**none of the row-level security policies, the triggers, or the grants**. Those are exactly what
the security suite exists to test. A schema built a different way from production is a schema
that proves nothing about production.

**Run as `uboss_app`, not the owner.** FORCE is off since DECISIONS 22, so `uboss_owner` sees
every tenant by design. A cross-tenant test connected as the owner would pass whatever the
policies said — and would keep passing after somebody dropped one.

`conftest` therefore exposes two engines and names the difference, so no test can pick the wrong
one by accident.

**The table list comes from the catalogue.** `test_nothing_is_visible_without_a_bound_tenant`
queries `pg_attribute` for every table carrying a `tenant_id`. A hand-written list stops
mentioning the table somebody added last week, and the first anyone hears about it is a breach.
`test_every_tenant_owned_table_has_row_level_security` closes the same gap from the other side.

**The suite proves it has teeth.** `test_the_isolation_checks_would_actually_catch_a_broken_policy`
disables row-level security on one table, asserts the isolation check then *fails*, and restores
it in a `finally`. Without it every isolation assertion would still pass if a policy were
dropped — they would all be reading zero rows for the wrong reason. This is the second half of
1.6.3's exit condition, written as a test rather than left as a ritual somebody performs once.

**One test found a real gap the moment it ran.** `test_every_migration_explains_itself` failed on
`0003`, whose docstring said what it did and not why. The grace window it introduces exists to
stop concurrent in-flight requests being signed out mid-rotation — which is not obvious from
three `add_column` calls. It is written down now.

**Two behaviours the suite pins that are easy to break silently:**

- `test_the_preflight_agrees_with_the_database` is the regression test for `runtime.run`
  discarding its coroutine's return value. That bug reported an empty database that was in fact
  at head, with no error at all.
- `test_every_migration_is_honest_about_reversing` refuses the third state: a `downgrade()` with
  an empty `pass`, which claims to reverse and does nothing. `alembic downgrade` reports success
  and the schema has not moved.

**39 tests.** `scripts/check.sh` runs them with everything else CI will.

---

## 30. The outbox relay, and the only cross-tenant credential in the system

**Supersedes DECISIONS 18**, which recorded that the relay role was deliberately *not* created
because nothing used it yet. Something does now: invite and password reset (1.2.6) cannot be
built honestly without delivery.

**The role's reach is one table.** `uboss_relay` has `SELECT` and `UPDATE` on `outbox_events`.
Not `INSERT` — it delivers events, it does not invent them. Not `DELETE` — a published row is
history and a dead row is evidence. Nothing at all on the other thirteen tables.

A role-scoped policy (`FOR ALL TO uboss_relay USING (true)`) lets it see every tenant's due rows.
`uboss_app` is unaffected: PostgreSQL ORs permissive policies, and this one names a role
`uboss_app` is not.

**A migration cannot create it, and that is the design.** `uboss_owner` has no `CREATEROLE`. The
migration checks for the role and stops with instructions if it is absent, rather than granting
itself the power to continue. Bringing the system's only cross-tenant credential into existence
is a person's decision taken once — the same shape as provisioning a tenant (DECISIONS 17).

**Three short transactions, not one long one.** Claim under a lease, publish outside any
transaction, mark in a second. `SELECT ... FOR UPDATE SKIP LOCKED` held across the publish would
keep a database transaction open for the length of a network call, which is how a connection pool
runs out during an outage at somebody else's service.

**`attempts` is incremented when an event is claimed, not when it fails.** A worker that dies
mid-publish never reaches the failure path. Counting there would let a poisonous event be retried
for ever by a succession of workers it kept killing.

**Delivery is at least once, and the suite proves it rather than the design asserting it.**
`test_an_event_survives_a_worker_killed_mid_publish` claims an event, publishes it, abandons the
worker, and asserts the next one delivers it **exactly one more time** — not zero, not three.
That is the whole meaning of the guarantee, and it is the kind of claim that is easy to write in
a docstring and never check.

**No publisher is registered, and the worker says so on start-up.** Email waits on a provider and
credentials the client has not supplied. Until one is registered every event is dead-lettered
with `no publisher is registered for …`. A placeholder that logged and returned would mark
everything delivered and send nothing — precisely the failure the outbox pattern exists to make
impossible.

**One test found a real bug.** `backoff_for` capped its exponent at `2**10 = 1024`, so the
documented one-hour ceiling was unreachable — the exponent cap bound before the seconds cap. The
exponent is now capped above where the seconds cap bites.

## 31. Self-service sign-up, and why `administer` came back with it

Decision 17 closed self-service registration and priced re-opening it exactly:

> Consequence: self-service sign-up would need a deliberate, separately-reviewed path. That is
> the correct amount of friction for the operation that brings a new customer's data boundary
> into existence.

The product owner asked for sign-up twice. This is that path, and this entry is the review.

**`uboss_app` gained no privilege.** It still cannot insert `tenants` and still cannot write
`users`. Everything happens inside one `SECURITY DEFINER` function, `signup_create_workspace`
(migration 0027) — the same shape migration 0006 already uses for the five authentication
operations. So the capability is a **named door**, not a permission: there is one function, it
does one thing, and no future route can create a tenant by accident because nothing else can
insert one. `EXECUTE` is revoked from `PUBLIC` before it is granted, and `search_path` is pinned.

**A taken address and a taken workspace name refuse identically.** The function returns nothing
and writes nothing for either, and `signup.create_workspace` raises one sentence covering both.
Two distinguishable refusals would turn the form into an address-enumeration oracle. Which it
actually was is in the audit trail, where an administrator can read it and a stranger cannot.

**Signed in immediately, and only because they just chose the password.** There is no email
confirmation step: confirming an address needs mail, and a screen saying "check your inbox" on a
deployment that cannot send would be the plainest possible version of reporting a success that
did not happen. When mail is configured, verification belongs after the first sign-in.

### The part that was wrong, and what it cost

0027 originally withheld `administer` from the founder, reasoning that it *"governs the
deployment rather than the workspace"*. **That was wrong.** Every verb in §14 is workspace-scoped;
`hierarchy/service.py` says so itself — drawing a reporting line is `administer`, and that is a
decision about one organisation made by somebody senior in it.

The cost was visible the first time anybody looked at the screen: a founder signed up, opened
Hierarchy — the first thing any workspace needs, and what everything else is scoped by — and got
the read-only empty state, with no way to create a structure. **The product's first step was shut
to the only person in the workspace.** Migration 0028 grants the verb and back-fills the
workspaces created in between.

What actually keeps organisations apart was never this list. It is `uboss_app` holding no
privilege on `tenants` or `users`, row-level security scoping every query to the bound tenant, and
the token being the only thing that binds it. A founder with `administer` can administer *their
own workspace* and nothing else — which is what the word means.

**A screenshot found it, not a test.** Every test passed, including one asserting `administer`
was absent: the suite was checking that the design was implemented, and the design was wrong.
That is the class of fault only looking at the running product catches.

## 32. Mail goes out over SMTP, and the sender refuses to downgrade

Decision 30 recorded that no publisher was registered and every event was dead-lettered. Mail
credentials now exist, so `notifications/mail.py` and `notifications/publishers.py` deliver, and
`uboss.outbox_worker` is the process that runs the relay.

**SMTP rather than a provider API.** Every organisation already has a mailbox, and a reset link is
one small transactional message — not a campaign needing deliverability tooling. `smtplib` on a
worker thread rather than a new async dependency: the outbox provides the durability, so the
client only has to be correct.

**TLS is not negotiable, and this is the whole security value of the module.** Port 465 opens an
implicit TLS socket; every other port runs `STARTTLS`, and `starttls()` raises when the server
does not offer it — nothing catches that. `smtplib` will happily put a live password-reset token
on a plaintext socket if you let it, and an SMTP server that quietly stops offering `STARTTLS`
reads every reset link that passes through it. `test_the_sender_refuses_a_server_that_will_not_do_starttls`
drives a real socket that greets and offers nothing, and asserts the send fails.

**A publisher that returns means delivered.** The relay marks the row on a return, so every
`smtplib` error propagates and the event is retried with backoff. Swallowing one would mark a
reset as sent that never left the building.

**Two bugs the tests found, both silent in production.** `recovery.request_reset` read
`memberships` with no tenant bound — row-level security correctly returned nothing, so
`_any_tenant` answered "no tenant" for *every* account and no reset was ever queued, while the
screen said a link was on its way. And `oauth.find_user` and three lookups in `recovery` read
`users` directly, which `uboss_app` has no privilege on; the fix was the narrow `auth_find_by_*`
functions, not a grant.

## 33. Two model providers, because one adapter never proved the gateway

`model_gateway`'s claim has always been that swapping provider is one line of policy and no
change above it. With a single adapter that claim was untested. `openai_adapter.py` is the
sibling, and `service.run` now picks between them on `settings.resolved_ai_provider` — one line,
as advertised.

**`auto` prefers Anthropic when both keys are present**, because the prompts were written against
the models named in settings. An explicit `UBOSS_AI_PROVIDER` is honoured even when its key is
missing: the caller then gets "no model is configured", which is truthful for a deployment that
named a provider it cannot reach and far easier to diagnose than a silent fallback.

**Both adapters answer through a forced tool call.** OpenAI's `strict: true` makes the schema
enforced rather than suggested. The shape differences — system as a message, `parameters` rather
than `input_schema`, arguments returned as a JSON *string* — are all inside the one file, which is
the point of having it.

**A 429 is two different situations.** `insufficient_quota` will never succeed; "try again
shortly" on an exhausted balance is advice that cannot come true and sends an operator looking
for a traffic spike instead of a billing page. The two are told apart by the error *code*, and
anything unreadable falls through to the temporary reading.
