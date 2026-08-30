"""Federated sign-in — Google, Microsoft and Apple.

`PLAN.md`'s decision table: *"Identity | Managed provider with MFA now; SAML/OIDC and SCIM for
enterprise."* This is the first half — OIDC against the three providers a customer will actually
ask for. SAML and SCIM are the enterprise half and are Gate 8.

## One table, and why it is not a column on `users`

A person may sign in with a password *and* with Google, or with Google today and Microsoft after
their company migrates. Three nullable columns on `users` would make "which providers can this
account use" a question with three answers, and adding a fourth provider would be a migration on
the busiest table in the schema.

## The rules the columns encode

**The pair `(provider, subject)` is the identity, not the email address.** Google's `sub` is
stable; an email address is not — people change theirs, and a provider that let an address be
re-registered would let somebody inherit an account. The unique constraint is on the pair.

**No tenant.** A user is workspace-independent — `users` has no `tenant_id` either, and a person
in three workspaces signs in once. So this table carries none, and no row-level security: like
`users`, it is reachable only through the authentication path, which runs before a tenant is
known.

**The email is stored but never trusted for matching.** It is kept so an administrator can see
which address a provider asserted, and so an unverified one can be told apart from a verified
one. Linking by email is what the `email_verified` flag exists to make an explicit decision
rather than an accident.

Revision: 0026
Parent:   0025
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The three §21 names. A fourth is a migration plus a client registration, in that order — the
#: set is closed here so an unrecognised value cannot be written by a bug or a bad payload.
PROVIDERS: tuple[str, ...] = ("google", "microsoft", "apple")


def upgrade() -> None:
    providers = ", ".join(f"'{value}'" for value in PROVIDERS)

    op.create_table(
        "federated_identities",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        #  The provider's own stable identifier for this person — OIDC's `sub`. Never the email.
        sa.Column("subject", sa.String(length=255), nullable=False),
        #  What the provider asserted, kept for an administrator to read rather than to match on.
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column(
            "email_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("display_name", sa.String(length=200), nullable=True),
        sa.Column("last_sign_in_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_federated_identities"),
        #  Removing a person removes their federated links with them. Unlike a version or an
        #  audit row, a link is not evidence of anything that happened — it is a credential.
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_federated_user", ondelete="CASCADE"
        ),
        #  The identity is the pair. Two accounts claiming the same Google `sub` is precisely the
        #  account-takeover this constraint exists to make impossible.
        sa.UniqueConstraint("provider", "subject", name="uq_federated_provider_subject"),
        #  One link per provider per account. A second Google link on one user would leave two
        #  answers to "which Google account is this", and nothing says which wins.
        sa.UniqueConstraint("user_id", "provider", name="uq_federated_user_provider"),
        sa.CheckConstraint(f"provider IN ({providers})", name="ck_federated_provider_known"),
        sa.CheckConstraint("length(btrim(subject)) > 0", name="ck_federated_subject_present"),
    )
    op.create_index("ix_federated_user", "federated_identities", ["user_id"])

    #  `SELECT, INSERT, UPDATE` and no `DELETE`. Unlinking a provider is an account decision with
    #  a consequence — an account whose only credential was that link becomes unreachable — and
    #  it is not built yet, so the privilege is withheld rather than left available for a bug to
    #  reach. `users` is handled the same way and for the same reason.
    op.execute("GRANT SELECT, INSERT, UPDATE ON federated_identities TO uboss_app;")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS federated_identities CASCADE")
