# Runbook — applying a database migration

Follow this every time, including for a migration that looks trivial. The ones that cause
outages look trivial; that is why they get applied without a window.

**Who runs it.** An operator, connected as `uboss_owner`. The API runs as `uboss_app`, which has
no rights to alter the schema — see DECISIONS 2.

---

## Before: preflight

```bash
cd backend
uv run python -m scripts.migration_preflight
```

It reports the current revision, what is pending, whether each pending migration can be reversed,
and any statement that takes a lock blocking reads and writes. **It exits non-zero when something
needs a decision**, so it can gate a deployment.

Exit 0 means reversible, no blocking statements: safe for a routine deploy. Anything else, read
on.

### If it names an irreversible migration

`downgrade()` refuses on purpose. Reversing it would destroy data or re-create something the
migration existed to remove.

| Revision | Why it refuses |
|---|---|
| `0001` | Creates the identity and audit tables. Reversing erases every tenant, membership and audit event. |
| `0004` | Removes six invented role names. Reversing re-creates them and drops every role definition seeded since. |

For these the rollback path is **restore from backup**, and the backup has to be proved before
the migration runs, not after it fails. See *Rehearsal* below.

### If it names a locking statement

`ALTER COLUMN ... SET NOT NULL`, a type change, a non-concurrent `CREATE INDEX`, a `DROP COLUMN`.
On an empty table these are instant; on a large one they hold an `ACCESS EXCLUSIVE` lock and
every request waits. Choose one:

- Apply it inside a stated maintenance window, or
- Split it into **expand** and **contract** — see below.

### Expand and contract

Two application versions run at once during any rolling deploy, so the schema must satisfy both.
Never do a rename or a drop in one step.

```
expand    add the new column, nullable, with a default
          deploy the code that writes both old and new
          backfill in batches
contract  make it NOT NULL, drop the old column
          deploy the code that reads only the new
```

Each half is a separate migration in a separate deployment. Migration 0004 followed this shape
inside one transaction because there were three memberships; at scale the backfill is batched and
the halves are days apart.

---

## Applying it

```bash
# 1. Back up, and know where the file is.
docker exec uboss-postgres-1 pg_dump -U postgres -d uboss -Fc -f /tmp/uboss-$(date +%F-%H%M).dump

# 2. Confirm what is about to run.
uv run python -m scripts.migration_preflight

# 3. Apply.
uv run alembic upgrade head

# 4. Confirm.
uv run alembic current
```

Then check the application, not just the schema: sign in, load a page that reads the changed
tables, and confirm `/health/ready` reports ready.

**A migration is not done because it applied.** It is done when the running application still
works against the new schema.

---

## Rolling back

### Reversible migration

```bash
uv run alembic downgrade <previous revision>
```

Then redeploy the application version that matches that schema. A rollback that leaves new code
running against an old schema is a second outage.

### Irreversible migration

```bash
# Stop the application first — a restore over a live database loses whatever
# was written between the backup and now.
docker compose -f infra/compose.yaml stop         # local
# production: scale the API to zero, then restore.

docker exec uboss-postgres-1 psql -U postgres -tAc \
  "DROP DATABASE uboss; CREATE DATABASE uboss OWNER uboss_owner;"
docker exec uboss-postgres-1 pg_restore -U postgres -d uboss /tmp/uboss-<stamp>.dump
```

**Everything written after the backup is gone.** That is the cost of an irreversible migration,
and it is why the backup is taken and *proved* before the migration runs.

---

## Rehearsal

Do this for any migration the preflight flags, on a copy of production-shaped data. Never on the
database itself.

```bash
export MSYS_NO_PATHCONV=1     # Git Bash only; stops /tmp being rewritten to a Windows path

# Copy the live database.
docker exec uboss-postgres-1 pg_dump -U postgres -d uboss -Fc -f //tmp/uboss.dump
docker exec uboss-postgres-1 psql -U postgres -tAc "DROP DATABASE IF EXISTS uboss_rehearsal;"
docker exec uboss-postgres-1 psql -U postgres -tAc "CREATE DATABASE uboss_rehearsal OWNER uboss_owner;"
docker exec uboss-postgres-1 sh -c 'pg_restore -U postgres -d uboss_rehearsal /tmp/uboss.dump'

# Point alembic at the copy — never at the real database.
REHEARSAL="postgresql+psycopg://uboss_owner:uboss_owner@localhost:5433/uboss_rehearsal"

UBOSS_MIGRATION_DATABASE_URL="$REHEARSAL" uv run alembic upgrade head
UBOSS_MIGRATION_DATABASE_URL="$REHEARSAL" uv run alembic downgrade <previous>
UBOSS_MIGRATION_DATABASE_URL="$REHEARSAL" uv run alembic upgrade head

# Clean up.
docker exec uboss-postgres-1 psql -U postgres -tAc "DROP DATABASE uboss_rehearsal;"
```

Check after the rollback that what the migration added is actually gone, and after rolling
forward that it is back and the data is unchanged.

### Rehearsal record — 0006, 2026-08-29

Ran exactly the above against a restored copy at revision 0006 holding 3 users, 4 memberships and
25 roles.

| Step | Result |
|---|---|
| `pg_dump` | 70,854 bytes |
| `pg_restore` into `uboss_rehearsal` | 0 errors, copy at 0006 |
| `downgrade 0005` | applied |
| — auth functions | 0 remaining ✅ |
| — `uboss_app` grant on `users` | restored ✅ |
| `upgrade head` | applied |
| — auth functions | 5 back ✅ |
| — `uboss_app` grant on `users` | revoked again ✅ |
| — data | users 3, memberships 4, roles 25 — unchanged ✅ |

The procedure works as written.

---

## Writing a migration

- **Say why in the docstring**, not just what. A migration that only says what it does leaves the
  next person guessing whether it was safe.
- **Refuse in `downgrade()`** when reversing would destroy data, and say what to do instead. An
  empty `pass` claims to reverse and does not — the preflight flags that, because it is worse
  than an honest refusal.
- **Drop constraints with raw SQL**, using the name PostgreSQL actually holds. `op.drop_constraint`
  re-applies the metadata naming convention and produces a doubly-prefixed name that does not
  exist. Check with `\d <table>`. — DECISIONS 21
- **Row-level security is `ENABLE`, not `FORCE`** (DECISIONS 22), so a migration running as the
  owner sees tenant data. If FORCE is ever restored on a table, a data migration touching it must
  lift and restore it inside one transaction — DECISIONS 20.
- **Writing rows for several tenants** uses `db.base.tenant_scope()`. `session.add()` stages a
  row; the INSERT happens at the next flush, under whichever tenant is bound *then*.

## Related

- `docs/architecture/DECISIONS.md` — 2 (role split), 20–23 (row-level security, naming, credentials)
- `backend/scripts/migration_preflight.py` — the checks, and what each one means
