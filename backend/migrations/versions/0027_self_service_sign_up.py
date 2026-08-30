"""Self-service sign-up — the *"deliberate, separately-reviewed path"* DECISIONS 17 asked for.

DECISIONS 17 closed this door and said exactly what it would take to open it:

> Consequence: self-service sign-up would need a deliberate, separately-reviewed path. That is
> the correct amount of friction for the operation that brings a new customer's data boundary
> into existence.

This is that path, opened on the product owner's instruction and recorded as its own decision.
**What is not done is as important as what is.** `uboss_app` gains no new table privilege: it
still cannot write `users`, and it still cannot insert a `tenants` row. Both remain exactly as
migration 0006 left them.

## How it works instead

One `SECURITY DEFINER` function, `signup_create_workspace`, following the pattern 0006 already
established for the five authentication operations. The function runs with the owner's rights and
does the whole thing in one statement — tenant, user, membership, an owner role and its
permissions — or none of it.

That shape is what keeps the boundary honest:

* **The capability is a named door, not a privilege.** There is one function, it does one thing,
  and it is the only way `uboss_app` can reach either table. A future route cannot accidentally
  create a tenant, because nothing else can insert one.
* **It refuses rather than overwrites.** An address that already has an account gets `null` back
  and nothing is written — no password reset, no membership added to somebody else's workspace.
  0006 made the same choice for the provisioning script and for the same reason: *"a provisioning
  command that can reset a password is a provisioning command that can take over an account."*
* **`search_path` is pinned** and `EXECUTE` is revoked from `PUBLIC` before it is granted, which
  is what stops the classic `SECURITY DEFINER` escalation.

## What the new workspace gets

The person who creates it becomes its first member with a role holding **every action in §14's
vocabulary**. Somebody has to be able to run the workspace they just made, or the sign-up
produces an account that cannot do anything.

> **Superseded.** This migration originally withheld `administer`, on the reasoning that it
> governs the deployment rather than the workspace. That was wrong — it is workspace-scoped like
> every other verb in §14, and withholding it left a founder unable to build their own org tree,
> which is the product's first step. Migration **0028** grants it and replaces the function
> below; it also explains what actually keeps one organisation out of another's data, which was
> never this list.

Revision: 0027
Parent:   0026
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: §14's vocabulary minus `administer`, as it stood when this migration ran. Left as-is because
#: a migration must keep meaning what it meant when it ran — 0028 is where the list changes.
FOUNDER_ACTIONS: tuple[str, ...] = (
    "view",
    "comment",
    "edit_draft",
    "publish",
    "run",
    "approve",
    "assign",
    "schedule",
    "manage_access",
    "export",
    "integrate",
    "audit",
)


def upgrade() -> None:
    actions = ", ".join(f"('{action}')" for action in FOUNDER_ACTIONS)

    #  S608 flags the interpolation below. `actions` is built from the literal tuple at the top
    #  of this file — a `CREATE FUNCTION` body cannot take a bind parameter, and there is no
    #  caller input anywhere near it. Assigned to a name so the suppression sits on one line
    #  rather than over the whole statement.
    create_function = f"""
        CREATE FUNCTION signup_create_workspace(
            p_email text,
            p_password_hash text,
            p_display_name text,
            p_workspace_name text,
            p_workspace_slug text
        ) RETURNS TABLE (user_id uuid, tenant_id uuid, membership_id uuid)
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        DECLARE
            v_user_id uuid;
            v_tenant_id uuid;
            v_membership_id uuid;
            v_role_id uuid;
        BEGIN
            --  An address that already has an account gets nothing back and nothing written.
            --  Not an error: the caller answers identically either way, so that a stranger
            --  cannot learn which addresses are registered by watching which ones fail.
            IF EXISTS (SELECT 1 FROM users WHERE email = lower(btrim(p_email))) THEN
                RETURN;
            END IF;
            IF EXISTS (SELECT 1 FROM tenants WHERE slug = p_workspace_slug) THEN
                RETURN;
            END IF;

            INSERT INTO tenants (slug, name, status)
                 VALUES (p_workspace_slug, p_workspace_name, 'active')
              RETURNING id INTO v_tenant_id;

            INSERT INTO users (email, password_hash, status)
                 VALUES (lower(btrim(p_email)), p_password_hash, 'active')
              RETURNING id INTO v_user_id;

            INSERT INTO memberships (tenant_id, user_id, display_name, status)
                 VALUES (v_tenant_id, v_user_id, p_display_name, 'active')
              RETURNING id INTO v_membership_id;

            --  A workspace nobody can run is a workspace nobody wanted. `is_system` marks this as
            --  a role the product created rather than one a customer designed.
            INSERT INTO roles (tenant_id, key, name, description, is_system, is_draft)
                 VALUES (
                     v_tenant_id,
                     'workspace_owner',
                     'Workspace owner',
                     'Created with the workspace. Holds every action except administer.',
                     true,
                     false
                 )
              RETURNING id INTO v_role_id;

            INSERT INTO role_permissions (tenant_id, role_id, action)
            SELECT v_tenant_id, v_role_id, action
              FROM (VALUES {actions}) AS granted(action);

            INSERT INTO membership_roles (tenant_id, membership_id, role_id)
                 VALUES (v_tenant_id, v_membership_id, v_role_id);

            RETURN QUERY SELECT v_user_id, v_tenant_id, v_membership_id;
        END;
        $$;
        """  # noqa: S608
    op.execute(create_function)

    #  Revoked before granted. Without this the function is executable by every role in the
    #  database, which is the escalation `SECURITY DEFINER` is famous for.
    op.execute(
        "REVOKE EXECUTE ON FUNCTION signup_create_workspace(text, text, text, text, text) "
        "FROM PUBLIC;"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION signup_create_workspace(text, text, text, text, text) "
        "TO uboss_app;"
    )


def downgrade() -> None:
    op.execute(
        "DROP FUNCTION IF EXISTS signup_create_workspace(text, text, text, text, text)"
    )
