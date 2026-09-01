# UBOSS AI

Governed human and AI work. People and agents run the same objectives, jobs and approvals under
one permission model, one audit trail and one set of tenant boundaries.

`PLAN.md` is the authoritative specification. Where this file and the plan disagree, the plan
wins and this file is wrong.

## Layout

```
backend/    FastAPI application, migrations, workers
frontend/   Next.js application and the design system it owns
infra/      local development stack (PostgreSQL, Redis)
docs/       product, architecture, security, delivery
scripts/    developer entry points
```

Two application folders, one each side. The API is a modular monolith: each module under
`backend/src/uboss/modules/` owns its own tables and exposes an application interface, and no
other module reads or writes those tables directly.

## Running it locally

**Requirements:** Docker, Node 20+, and [uv](https://docs.astral.sh/uv/). Python is installed by
`uv`; you do not need one on the machine.

```bash
# 1. Data services. Postgres is published on 5433 and Redis on 6380, so this stack can run
#    alongside the previous UBOSS stack without either taking the other's ports.
docker compose -f infra/compose.yaml up -d

# 2. API — http://localhost:8001
cd backend
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"   # paste into UBOSS_AUTH_SIGNING_KEY
uv sync --all-groups --python 3.12
uv run alembic upgrade head
uv run python -m uboss --reload

# 3. An organisation and someone to sign in as
#    Asks for the password; it is never passed as an argument.
uv run python -m scripts.provision_tenant \
    --slug acme --name "Acme" --email you@acme.com --display-name "Your Name"

# 4. Web — http://localhost:3000
cd ../frontend
cp .env.example .env.local
npm install
npm run dev
```

Open <http://localhost:3000> and sign in with the account you just created.

`python -m uboss` rather than a bare `uvicorn` command: the server has to be told which event
loop to use, and a launch command is the wrong place to keep that — see decision 16.

<http://localhost:3000/environment> reports whether the API is answering and what it measured.
If the API is not running it says so, rather than showing a placeholder.

### Checking your work

```bash
# backend (cwd: backend/)
uv run ruff check . ../tests   # must be clean — CI lints the tests too
uv run mypy src                # must be clean

# tests (cwd: the repository root, not backend/)
backend/.venv/Scripts/python -m pytest        # Windows
backend/.venv/bin/python -m pytest            # everything else

# frontend (cwd: frontend/)
npm run lint
npm run typecheck
npm test
npm run build
```

**The tests run from the root**, which `pytest.ini` explains: they exercise the schema — policies,
triggers, grants — as much as the Python, so they need the repo root on the path for `tests` and
`backend/src` for `uboss`. Run them from `backend/` and pytest finds no tests and says so cheerfully.

They need `UBOSS_MIGRATION_DATABASE_URL` and the rest of `backend/.env` in the environment, because
a throwaway database is built by running the migrations. On Git Bash: `set -a; . ./backend/.env; set
+a`. Anything in that file becomes a real environment variable, which is worth knowing — a test that
asserts what the product concludes from *unset* configuration has to pass the values it means
explicitly, or it ends up asserting against your machine. Decision 58 is the one that got caught.

## Secrets

`backend/.env` and `frontend/.env.local` are git-ignored and must stay that way.

The Claude API key goes into `backend/.env` as `UBOSS_ANTHROPIC_API_KEY`. Leaving it empty is a
supported state: the product says on screen that no model is reachable and falls back to its
deterministic rules. It never claims a model was consulted when one was not.

Nothing named `NEXT_PUBLIC_*` is a secret — those values are compiled into the JavaScript the
browser downloads.

## The two tenant boundaries

A tenant's rows are protected twice, and neither check substitutes for the other:

1. The application resolves the caller's permissions from the verified session token — never
   from a request body, a query parameter or the `Host` header.
2. PostgreSQL row-level security refuses rows from any other tenant, whatever the application
   believes.

The API connects as `uboss_app`, which cannot disable a policy. Migrations connect as
`uboss_owner`, which creates them. That split is what makes the second boundary real.

You can see it hold. As `uboss_app` with no tenant bound, every tenant-owned table returns zero
rows; bound to one organisation, it returns that organisation's rows and refuses a write aimed
at any other; and `audit_events` refuses an `UPDATE` outright, because append-only is enforced
by a trigger rather than by a promise about the code.

## Signing in

A session is 32 random bytes in an http-only cookie. The database stores only its SHA-256, and
the row is re-read on every request — so deactivating someone, removing them from an
organisation or suspending a tenant takes effect immediately rather than whenever a token
happens to expire.

Sessions have a fixed 14-day absolute lifetime and an 8-hour idle lifetime by default. The
browser token rotates hourly without extending either boundary; one prior hash remains valid for
two minutes so requests already in flight do not fail randomly. Unsafe browser API requests must
carry an exact allowlisted Origin (or same-origin Referer fallback), including sign-in. SameSite
cookies remain defense in depth, not the only CSRF control.

Every credential refusal returns the same 401 with the same wording, and a password check runs
even when the address matches no account. The endpoint does not claim exact constant-time HTTP
responses: attributable tenant audit work can differ. Redis limits every supplied address,
address/IP pair and IP whether or not the account exists, without storing raw addresses in keys.

The same person can belong to several organisations, with a different name, title and set of
roles in each. After one password verification, the API returns a three-minute single-use,
browser-bound workspace challenge. The chooser submits only that challenge and the selected
workspace; it never retains or resubmits the password.
