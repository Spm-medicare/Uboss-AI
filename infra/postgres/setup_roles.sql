-- Create the three roles and their grants. Safe to run more than once.
--
-- `infra/postgres/init/01-roles.sql` does this too, but only on a **fresh data volume** — that is
-- how PostgreSQL's entrypoint works. So it never runs in CI, never runs on a database that
-- already exists, and never runs again after somebody adds a role. This file is the version that
-- can be run at any time, against any of them.
--
-- Run as a superuser:
--     psql -U postgres -d uboss -f infra/postgres/setup_roles.sql
--
-- The passwords here are for a laptop and for CI. A real deployment injects them from its secret
-- store and never from a file in version control.

\set ON_ERROR_STOP on

-- ── the three roles ──────────────────────────────────────────────────────────────────────
--
-- Two of them are the tenant boundary; the third is the one thing that crosses it.

DO $$
BEGIN
    -- Owns the schema and runs migrations. CREATEDB so the test suite can build its own
    -- throwaway database without a superuser credential sitting in a developer's environment.
    -- No CREATEROLE: creating the cross-tenant relay role stays a deliberate act by a person.
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'uboss_owner') THEN
        CREATE ROLE uboss_owner LOGIN PASSWORD 'uboss_owner' CREATEDB;
    ELSE
        ALTER ROLE uboss_owner CREATEDB;
    END IF;

    -- Serves every API request. Bound by row-level security, and deliberately holds no role
    -- attribute at all — it cannot create anything, and it cannot turn a policy off.
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'uboss_app') THEN
        CREATE ROLE uboss_app LOGIN PASSWORD 'uboss_app';
    END IF;

    -- The outbox relay: the only credential that reads across every tenant. Migration 0008
    -- grants it SELECT and UPDATE on outbox_events and nothing else.
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'uboss_relay') THEN
        CREATE ROLE uboss_relay LOGIN PASSWORD 'uboss_relay';
    END IF;
END
$$;

-- ── the schema and its grants ────────────────────────────────────────────────────────────

ALTER DATABASE uboss OWNER TO uboss_owner;
ALTER SCHEMA public OWNER TO uboss_owner;

REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO uboss_app;

-- The application may use the tables that exist and any created later, but it may not create,
-- drop or alter them. Schema change is a migration, run deliberately, by the owner.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO uboss_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO uboss_app;

ALTER DEFAULT PRIVILEGES FOR ROLE uboss_owner IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO uboss_app;
ALTER DEFAULT PRIVILEGES FOR ROLE uboss_owner IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO uboss_app;

-- Migration 0006 revokes `users` from uboss_app again, on top of the blanket grant above. Run
-- after this file, `alembic upgrade head` restores that revocation — which is why this script
-- grants broadly and the migration narrows, rather than the other way round.

-- `app.tenant_id` is set per transaction by the API and read by every RLS policy. A blank
-- default means a policy comparing against it finds an empty string rather than erroring when it
-- was never set — and an empty string matches no tenant, so a connection that forgot to bind
-- sees nothing rather than everything.
ALTER DATABASE uboss SET app.tenant_id = '';

CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "btree_gist";

-- ── the credentials table, taken back ────────────────────────────────────────────────────
--
-- The blanket `GRANT ON ALL TABLES` above hands `users` to the application role, and `users`
-- holds every Argon2 hash in the system (DECISIONS 23). Migration 0006 revokes it — but only
-- when that migration *runs*, and on a database already at head it does not run again.
--
-- So this script takes it back itself. A setup script must leave the database in the state it
-- is meant to be in, not in one that depends on a migration happening to re-run afterwards.
-- Without this, repairing roles on a live database would quietly reopen the credentials table.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_class WHERE relname = 'users'
               AND relnamespace = 'public'::regnamespace) THEN
        REVOKE ALL ON TABLE public.users FROM uboss_app;
    END IF;
END
$$;
