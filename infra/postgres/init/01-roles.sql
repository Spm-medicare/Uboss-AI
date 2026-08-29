-- Two roles, and the difference between them is the tenant boundary.
--
-- `uboss_owner` owns the schema. Alembic connects as this role to create tables and, critically,
-- the row-level-security policies.
--
-- `uboss_app` is what the API connects as. It can read and write rows, and it CANNOT turn RLS
-- off, because a table's owner is exempt from its own policies unless FORCE is set and because
-- only a superuser or the owner may alter them. If the API connected as the owner, row-level
-- security would be decoration: one forgotten WHERE clause and a query returns every tenant.
--
-- Runs once, on first start of an empty data volume. Passwords here are for a laptop; a real
-- deployment injects them from its secret store and never from a file in version control.

\set ON_ERROR_STOP on

CREATE ROLE uboss_owner LOGIN PASSWORD 'uboss_owner';
CREATE ROLE uboss_app LOGIN PASSWORD 'uboss_app';

ALTER DATABASE uboss OWNER TO uboss_owner;

\connect uboss

-- The public schema belongs to the owner; the application only uses what it is granted.
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

-- `app.tenant_id` is set per transaction by the API and read by every RLS policy. Declaring a
-- blank default here means a policy comparing against it finds an empty string rather than
-- erroring when the setting was never set — and an empty string matches no tenant, so a
-- connection that forgot to bind its tenant sees nothing rather than everything.
ALTER DATABASE uboss SET app.tenant_id = '';

-- Extensions the schema relies on. Created by the owner, usable by everyone.
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "btree_gist";
