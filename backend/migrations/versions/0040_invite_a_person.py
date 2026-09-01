"""Adding somebody to a workspace had no way in.

The pieces for an invitation have all been here since Gate 2: `ActionTokenPurpose.INVITE_SETUP`,
`POST /auth/invite/accept`, and a publisher registered for `identity.invite_issued`. **Nothing
ever issued one.** So a workspace's people were whatever a provisioning script had inserted, and
the org chart could only ever place somebody who was already there — which is what a person hits
the moment they type a colleague's name into it.

The missing piece is one function, and it is missing for a reason worth keeping. Migration 0006
took `users` away from `uboss_app` entirely:

> the application role cannot read `users`

That is why every credential path goes through a `SECURITY DEFINER` function with a pinned
`search_path` — a narrow, auditable hole rather than a table grant. Creating an invited account is
the same shape of operation and gets the same treatment.

## What this function will and will not do

* It creates an account **with no password at all** — `password_hash` is NULL, which is the state
  `verify_password` documents as "an invited person who has not set a password" and now fails
  closed on. Not an empty string: `''` reads as *present* to anything testing `IS NOT NULL`, and
  the only way in stays the invite link that `POST /auth/invite/accept` already handles.
* Its status is `active`, and the invitation lives on the **membership** instead. `users.status`
  has admitted only `active` and `deactivated` since 0001, and that is right: an account is one
  person across every workspace, so "has not accepted yet" is a fact about their place in *this*
  organisation. `MembershipStatus.INVITED` is where 0001 put it. An account with no password can
  do nothing until it has one, so nothing is loosened by saying it exists.
* An address that already exists returns the existing row rather than raising. Inviting somebody
  twice is an ordinary thing to do, and the caller needs the id either way; whether the invitation
  was new is answered by the returned `created` flag, so the route can decide without a second
  query and without guessing from an exception.
* It returns the id and nothing else about the account. Email confirmation, lockout state and the
  hash stay where they are.

Revision: 0040
Parent:   0039
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0040"
down_revision: str | None = "0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "uboss_app"
SIGNATURE = "auth_create_invited_user(text)"


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION auth_create_invited_user(p_email text)
        RETURNS TABLE (id uuid, created boolean)
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        DECLARE
            v_email text := lower(btrim(p_email));
            v_id uuid;
        BEGIN
            IF v_email = '' OR position('@' in v_email) = 0 THEN
                RAISE EXCEPTION 'auth_create_invited_user needs an email address';
            END IF;

            SELECT u.id INTO v_id FROM users u WHERE u.email = v_email;
            IF v_id IS NOT NULL THEN
                --  Already here. The caller gets the id and is told it is not new, so inviting
                --  the same person twice is idempotent rather than an error to interpret.
                RETURN QUERY SELECT v_id, false;
                RETURN;
            END IF;

            --  No password: NULL, not an empty string. `verify_password` treats both as "no
            --  password" and refuses them, but NULL is the one that also reads as absent to a
            --  plain IS NOT NULL check, so nothing downstream can mistake it for a credential.
            INSERT INTO users (email, password_hash, status)
            VALUES (v_email, NULL, 'active')
            RETURNING users.id INTO v_id;

            RETURN QUERY SELECT v_id, true;
        END;
        $$;
        """
    )
    #  PUBLIC gets EXECUTE on a new function by default. Revoked first, then granted to the one
    #  role that needs it — the same order 0006 uses, for the same reason.
    op.execute(f"REVOKE ALL ON FUNCTION {SIGNATURE} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {SIGNATURE} TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"DROP FUNCTION IF EXISTS {SIGNATURE}")
