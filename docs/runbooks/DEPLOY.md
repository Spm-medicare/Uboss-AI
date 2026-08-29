# Runbook — deploying, and going back

**Status: written, never rehearsed.** Step 1.6.5's exit condition is *"a deploy and a rollback
have both been performed against staging"*, and there is no staging: the hosting decision
(`DR-003`, region and residency) is open. This procedure is therefore a plan, not a proven one,
and it stays marked 🟡 until it has been run.

That distinction matters. A deployment runbook nobody has followed is a document, and the first
time it is followed will be during a deployment.

---

## What has to exist first

`DR-003` decides where this runs. Until then these are unanswered, and each changes the procedure:

| | Why it changes things |
|---|---|
| **Managed or self-run PostgreSQL** | PLAN §26 asks for managed. Self-run means backup, point-in-time recovery, failover and patching become ours — PLAN §19's whole list |
| **Where object storage lives** | The API's S3 endpoint, and whether a bucket policy can be scoped per tenant |
| **Which secret store** | The contract below assumes one exists and is read at start-up |
| **How many replicas** | Decides whether a migration needs the expand/contract split, and it usually does |

---

## Environments

Three, and they differ only in configuration. The same images run in all of them — an image
built for one environment and not another is an image that was never tested where it runs.

| | Purpose |
|---|---|
| **dev** | A laptop. `infra/compose.yaml`, seeded data, `UBOSS_ENVIRONMENT=local` |
| **staging** | Production's shape at a smaller size. Real managed services, real secrets from the store, **never a copy of production data** |
| **production** | The one with customers in it |

Staging holding a copy of production data would put real personal information somewhere with
weaker access controls and a habit of being reset. Test data is generated, not copied.

### What differs

Only environment variables and the secret store they are read from. `backend/.env.example` lists
every one; `UBOSS_ENVIRONMENT` is what switches:

| | local | staging / production |
|---|---|---|
| `/docs` and `/openapi.json` | served | **off** — an unauthenticated description of every route |
| Session cookie | `uboss_session` | `__Host-uboss_session` — the browser refuses it without TLS |
| Logs | human-readable | JSON, for a collector |
| Traces | sampled at 100% | sampled at `UBOSS_TRACE_SAMPLE_RATIO` |

---

## Secrets

**No secret is ever in an image, a repository, or an environment file that is committed.** They
are read from the deployment's secret store at start-up, into the environment of the process.

| Secret | What it is | Rotation |
|---|---|---|
| `UBOSS_AUTH_SIGNING_KEY` | Signs session tokens | Rotating signs everyone out — which is the intended behaviour after a suspected leak |
| `UBOSS_DATABASE_URL` | The **application** role. Cannot disable a row-level security policy | With the database password |
| `UBOSS_MIGRATION_DATABASE_URL` | The **owner** role. Not present in the API's environment — only in the migration job's | With the database password |
| `UBOSS_RELAY_DATABASE_URL` | The relay. Reads `outbox_events` across tenants and nothing else | With the database password |
| `UBOSS_S3_ACCESS_KEY` / `_SECRET_KEY` | Object storage | Per the provider |
| `UBOSS_ANTHROPIC_API_KEY` | The AI gateway. Empty is supported — the product says no model is reachable | Per the provider |

**The API's environment must not contain the owner or migration credential.** A web process that
can alter the schema can drop a policy. That separation is the whole of DECISIONS 2, and a
deployment that passes every variable to every container quietly undoes it.

---

## Deploying

```bash
# 1. What is about to happen to the database.
uv run python -m scripts.migration_preflight
```

Exit 0 means reversible and non-blocking: continue. Anything else, read
`docs/runbooks/MIGRATIONS.md` before going further — an irreversible migration's only rollback is
a restore, and the backup has to be proved before it runs, not after it fails.

```bash
# 2. Back up, and know where the file is.
#    Managed PostgreSQL: take a snapshot and note its identifier.

# 3. Migrate. A separate job, before the new version starts.
#    Not on container start-up: several replicas would run it at once.
alembic upgrade head

# 4. Roll out the new images. One at a time, waiting for /health/ready between each.
#    /health/ready runs a real query; /health/live only says the process is up.

# 5. Verify the application, not the schema. Sign in, load a page that reads
#    the changed tables, and check /health/ready reports ready.
```

**A deploy is not done because the containers are running.** It is done when a person can sign in
and use the thing that changed.

### Two versions run at once

During a rolling deploy the old and new versions both serve traffic, so the schema must satisfy
both. Never rename or drop in one step:

```
expand    add the new column, nullable, with a default
          deploy code that writes both old and new
          backfill in batches
contract  make it NOT NULL, drop the old column
          deploy code that reads only the new
```

Each half is a separate deployment. `MIGRATIONS.md` has the detail.

---

## Going back

### The application

Redeploy the previous image tag. Images are immutable and tagged by commit, so this is exact
rather than a rebuild that might resolve a different dependency.

**Check whether the migration went with it.** New code on an old schema is a second outage. If
the deploy included a migration, roll that back first — or forward-fix, which is usually faster
and always safer than reversing a data change.

### The database

Reversible migration:

```bash
alembic downgrade <previous revision>
```

Irreversible — `0001`, `0004`, and anything else whose `downgrade()` refuses:

```
Stop the application first. A restore over a live database loses whatever
was written between the backup and now.

Then restore the snapshot from step 2.
```

**Everything written after the backup is gone.** That is the cost of an irreversible migration,
and it is why the preflight names them before anything runs.

---

## What is still missing

Honest list, not a plan to write one later:

- **This has never been run.** No staging exists.
- **No infrastructure-as-code.** PLAN §26 asks for it. It cannot be written before `DR-003` says
  what it is describing.
- **No CDN or WAF** in front of the edge (PLAN §26).
- **No point-in-time recovery, restore drill, or stated RPO/RTO** (PLAN §19). If hosting turns
  out to be self-run rather than managed, all of that becomes ours and is a substantial piece of
  work that is not in anyone's estimate yet.
- **No incident on-call rotation** wired to these steps — `docs/operations/INCIDENT_RESPONSE.md`
  describes the process; nobody is paged by it.

## Related

- `docs/runbooks/MIGRATIONS.md` — preflight, expand/contract, restore
- `docs/architecture/DECISIONS.md` — 2 (role split), 22 (row-level security), 30 (the relay role)
- `docs/product/contracts/LAUNCH_DECISIONS.md` — `DR-003`, which unblocks this
