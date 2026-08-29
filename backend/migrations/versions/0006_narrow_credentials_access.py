"""Take the credentials table away from the application role.

**The problem this closes.** `uboss_app` — the role every API request runs as — could read every
row of `users`: every email address and every Argon2 hash, across every tenant.

    $ psql -U uboss_app -d uboss -c "SELECT count(*) FROM users;"
     4

`users` carries no `tenant_id`, so row-level security has nothing to compare against and cannot
protect it. `DECISIONS.md` #11 argued the table therefore held nothing worth stealing. That was
wrong: a password hash is exactly what an offline attacker wants, and the address list is a staff
roster. One SQL injection anywhere in the application, or one leaked application password, and
the whole set is available.

**What replaces it.** Five `SECURITY DEFINER` functions — one per operation the authentication
code actually performs, and no more. The application role gets `EXECUTE` on those and no table
privilege at all.

**What this buys, stated precisely.** Argon2 verification happens in Python, so a hash still
reaches the application for the one account it names. What becomes impossible is *enumeration*:
there is no call that returns more than one row, and no way to ask "give me every hash". An
injection in an unrelated query can no longer dump the table, because the role has no rights on
it to abuse.

That is a smaller claim than "the hash never leaves the database", and it is the true one.

**Why `SECURITY DEFINER` rather than a second role and pool.** A second pool means a second
connection string, a second failure mode and a second thing to configure wrongly — and it still
leaves a role that can `SELECT *`. A function is a reviewed surface: to widen what authentication
can reach, someone has to change a function, in a migration, where it is read.

Each function pins `search_path` to `pg_catalog, public`. Without that, a caller can create a
schema earlier in the path, shadow a table the function names, and have it run against their own
object with the owner's rights — the classic `SECURITY DEFINER` escalation.

Revision: 0006
Parent:   0005
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── the five operations authentication actually performs ─────────────────────────────

    #  1. Find one account by address. The sign-in path's entry point.
    op.execute(
        """
        CREATE FUNCTION auth_find_by_email(p_email text)
        RETURNS TABLE (
            id uuid,
            email text,
            password_hash text,
            status text,
            failed_sign_in_count integer,
            locked_until timestamptz
        )
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            SELECT u.id, u.email, u.password_hash, u.status,
                   u.failed_sign_in_count, u.locked_until
            FROM users u
            WHERE u.email = lower(btrim(p_email))
            LIMIT 1;
        $$;
        """
    )
    #  `LIMIT 1` and an equality on a unique column: there is no argument that returns two rows,
    #  and no pattern match that could be widened into a scan.

    #  2. Find one account by id. Used by the workspace challenge and by step-up, both of which
    #     already hold a verified identity.
    op.execute(
        """
        CREATE FUNCTION auth_find_by_id(p_user_id uuid)
        RETURNS TABLE (
            id uuid,
            email text,
            password_hash text,
            status text
        )
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            SELECT u.id, u.email, u.password_hash, u.status
            FROM users u
            WHERE u.id = p_user_id
            LIMIT 1;
        $$;
        """
    )

    #  3. Count a failed attempt, and close the account if there have been too many.
    op.execute(
        """
        CREATE FUNCTION auth_record_failure(
            p_user_id uuid,
            p_max_attempts integer,
            p_lockout interval
        )
        RETURNS void
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        BEGIN
            UPDATE users
            SET failed_sign_in_count =
                    CASE WHEN failed_sign_in_count + 1 >= p_max_attempts
                         THEN 0 ELSE failed_sign_in_count + 1 END,
                locked_until =
                    CASE WHEN failed_sign_in_count + 1 >= p_max_attempts
                         THEN now() + p_lockout ELSE locked_until END
            WHERE id = p_user_id;
        END;
        $$;
        """
    )
    #  The increment happens in one statement against the stored value, so ten parallel attempts
    #  count as ten rather than as one. The threshold and the lockout window are arguments rather
    #  than constants here: they are policy, and policy belongs with the application.

    #  4. A password has just been proved. Reset the counters, and take a fresh hash if Argon2's
    #     cost has been raised since this one was written.
    op.execute(
        """
        CREATE FUNCTION auth_record_verified(p_user_id uuid, p_new_hash text)
        RETURNS void
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            UPDATE users
            SET failed_sign_in_count = 0,
                locked_until = NULL,
                password_hash = COALESCE(p_new_hash, password_hash)
            WHERE id = p_user_id;
        $$;
        """
    )
    #  A null `p_new_hash` leaves the stored hash alone. There is deliberately no function that
    #  sets a hash without a proof having just succeeded — a password change goes through the
    #  reset flow, which is a different thing with its own token.

    #  5. A sign-in completed — a session now exists. Separate from step 4 because proving a
    #     password is not the same as signing in: the workspace chooser sits between them.
    op.execute(
        """
        CREATE FUNCTION auth_record_sign_in(p_user_id uuid)
        RETURNS void
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            UPDATE users SET last_sign_in_at = now() WHERE id = p_user_id;
        $$;
        """
    )

    # ── hand out execute, take away everything else ──────────────────────────────────────
    functions = (
        "auth_find_by_email(text)",
        "auth_find_by_id(uuid)",
        "auth_record_failure(uuid, integer, interval)",
        "auth_record_verified(uuid, text)",
        "auth_record_sign_in(uuid)",
    )
    for signature in functions:
        #  PUBLIC gets EXECUTE on a new function by default. Revoked first, then granted to the
        #  one role that needs it — otherwise every future role inherits access to the
        #  credentials table through the back door.
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC;")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO uboss_app;")

    op.execute("REVOKE ALL ON TABLE users FROM uboss_app;")
    #  And stop the default-privilege grant from handing it back on a future migration.
    op.execute(
        """
        ALTER DEFAULT PRIVILEGES FOR ROLE uboss_owner IN SCHEMA public
            REVOKE ALL ON TABLES FROM uboss_app;
        """
    )
    op.execute(
        """
        ALTER DEFAULT PRIVILEGES FOR ROLE uboss_owner IN SCHEMA public
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO uboss_app;
        """
    )
    #  Re-stated rather than dropped: every *other* table still needs the default grant. The
    #  revoke above is on `users` specifically and is not undone by this.


def downgrade() -> None:
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE users TO uboss_app;")
    for signature in (
        "auth_find_by_email(text)",
        "auth_find_by_id(uuid)",
        "auth_record_failure(uuid, integer, interval)",
        "auth_record_verified(uuid, text)",
        "auth_record_sign_in(uuid)",
    ):
        op.execute(f"DROP FUNCTION IF EXISTS {signature};")
