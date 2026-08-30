"""Give a workspace's founder `administer` — the verb they were missing to use their workspace.

Migration 0027 created the `workspace_owner` role with §14's vocabulary **minus `administer`**,
on this reasoning:

> `administer` is withheld because it is the verb that governs the deployment rather than the
> workspace, and nothing about signing up should confer it.

**That reasoning was wrong, and the screenshot proved it.** A founder signed up, landed on
Hierarchy — the first thing any workspace needs — and got the read-only empty state: *"Nobody has
set up the structure for this workspace yet"*, with no way to set one up. The product's very
first step was closed to the only person in the workspace.

## What `administer` actually is here

It is a **workspace-scoped** action, like every other verb in §14. `hierarchy/service.py` says so
in its own words:

> drawing a reporting line — is `administer`. Structure decides reporting scope, and reporting
> scope decides who can see whose work.

That is a decision about *this organisation*, made by somebody senior in it. It is not a
deployment capability, and there is no verb in §14 that is: the vocabulary is tenant-scoped from
end to end, and every check runs inside one tenant's boundary.

## What actually stops a founder from touching the deployment

Not this permission — the layers underneath it, which 0027 left exactly as it found them:

* `uboss_app` holds no privilege on `tenants` or `users`, so no route can create or read across
  organisations regardless of what a role says;
* row-level security scopes every query to the bound tenant, and the token is the only thing that
  binds it;
* `signup_create_workspace` is the one door into `tenants`, it takes no role or permission
  argument, and it is the only thing this migration's grant can be reached through.

So a founder with `administer` can administer *their own workspace* and nothing else — which is
what the word means, and what somebody who just created a workspace expects to be able to do.

`administer` is also high-risk, so the step-up rule still applies: hierarchy changes need a recent
password proof. The permission opens the door; it does not remove the lock.

## Existing rows

Back-filled rather than left for new sign-ups only. Every workspace created between 0027 and this
migration has a founder who cannot administer it, and telling those customers to create a second
workspace is not a fix.

Revision: 0028
Parent:   0027
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    #  Back-fill for workspaces already created. `ON CONFLICT DO NOTHING` rather than a `NOT
    #  EXISTS` sub-query: the unique constraint is the authority on whether the row is already
    #  there, and a check that duplicates it is a check that can disagree with it.
    op.execute(
        """
        INSERT INTO role_permissions (tenant_id, role_id, action)
        SELECT r.tenant_id, r.id, 'administer'
          FROM roles r
         WHERE r.key = 'workspace_owner'
           AND r.is_system
        ON CONFLICT DO NOTHING
        """
    )

    #  And for every workspace created from here on. The function is replaced rather than
    #  altered, because a `CREATE OR REPLACE` keeps its grants and its `search_path` pin — the
    #  two things a hand-written re-grant would eventually forget.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION signup_create_workspace(
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

            INSERT INTO roles (tenant_id, key, name, description, is_system, is_draft)
                 VALUES (
                     v_tenant_id,
                     'workspace_owner',
                     'Workspace owner',
                     'Created with the workspace. Holds every action in the workspace.',
                     true,
                     false
                 )
              RETURNING id INTO v_role_id;

            --  Every verb in §14, `administer` included. All of them are workspace-scoped; the
            --  boundary between organisations is the database role and row-level security, not
            --  this list. See this migration's docstring.
            INSERT INTO role_permissions (tenant_id, role_id, action)
            SELECT v_tenant_id, v_role_id, action
              FROM (VALUES
                  ('view'), ('comment'), ('edit_draft'), ('publish'), ('run'), ('approve'),
                  ('assign'), ('schedule'), ('manage_access'), ('export'), ('integrate'),
                  ('administer'), ('audit')
              ) AS granted(action);

            INSERT INTO membership_roles (tenant_id, membership_id, role_id)
                 VALUES (v_tenant_id, v_membership_id, v_role_id);

            RETURN QUERY SELECT v_user_id, v_tenant_id, v_membership_id;
        END;
        $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM role_permissions rp
         USING roles r
         WHERE rp.role_id = r.id
           AND rp.action = 'administer'
           AND r.key = 'workspace_owner'
           AND r.is_system
        """
    )
