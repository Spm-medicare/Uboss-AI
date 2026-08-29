"""Add idle-aware, race-safe session token rotation.

A session token that never changes is a token that stays useful for as long as the session
lasts. Rotating it periodically shrinks the window in which a copied token is worth anything,
and it is the difference between a leak that ends and a leak that lasts a fortnight.

Three columns, and the reason for each:

* **`token_rotated_at`** — when the current token was minted, so the API knows when the next
  rotation is due without guessing from `created_at`.
* **`previous_token_hash`** and **`previous_valid_until`** — the grace window, and the reason
  this is not a two-line change.

Rotation has a race that only appears under real use. A browser fires several requests at once;
one of them rotates the token and sets a new cookie; the others are already in flight carrying
the old one. Without a grace window every one of those is refused, and the person is signed out
for doing nothing but loading a page with three panels on it.

So the previous hash stays valid for a short, explicit period. The session policy in
`sessions_access` matches on it only inside that window, which is why the window has to be a
column and not a constant — a policy cannot read the application's configuration.

Rotation never extends the session. `expires_at` is untouched here: absolute and idle expiry are
decided by the session's own age and use, and a rotation is neither. A token that renewed the
session every time it rotated would be a session that never ends.

Revision ID: 0003
Revises: 0002
Created: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("previous_token_hash", sa.String(64), nullable=True))
    op.add_column(
        "sessions",
        sa.Column("previous_valid_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "sessions",
        sa.Column(
            "token_rotated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        op.f("ck_sessions_previous_token_pair"),
        "sessions",
        "(previous_token_hash IS NULL) = (previous_valid_until IS NULL)",
    )
    op.create_check_constraint(
        op.f("ck_sessions_previous_token_differs"),
        "sessions",
        "previous_token_hash IS NULL OR previous_token_hash <> token_hash",
    )
    op.create_index(
        "ix_sessions_previous_token_hash",
        "sessions",
        ["previous_token_hash"],
    )

    # The previous token may establish only this same session during its short grace window.
    # Writes always require the tenant to be bound first.
    op.execute("DROP POLICY sessions_access ON sessions;")
    op.execute(
        """
        CREATE POLICY sessions_access ON sessions
            FOR ALL
            USING (
                tenant_id = app_current_tenant()
                OR (
                    app_current_session_hash() IS NOT NULL
                    AND (
                        token_hash = app_current_session_hash()
                        OR (
                            previous_token_hash = app_current_session_hash()
                            AND previous_valid_until > now()
                        )
                    )
                )
            )
            WITH CHECK (tenant_id = app_current_tenant());
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY sessions_access ON sessions;")
    op.execute(
        """
        CREATE POLICY sessions_access ON sessions
            FOR ALL
            USING (
                tenant_id = app_current_tenant()
                OR (
                    app_current_session_hash() IS NOT NULL
                    AND token_hash = app_current_session_hash()
                )
            )
            WITH CHECK (
                tenant_id = app_current_tenant()
                OR (
                    app_current_session_hash() IS NOT NULL
                    AND token_hash = app_current_session_hash()
                )
            );
        """
    )
    op.drop_index("ix_sessions_previous_token_hash", table_name="sessions")
    op.drop_constraint(
        op.f("ck_sessions_previous_token_differs"), "sessions", type_="check"
    )
    op.drop_constraint(
        op.f("ck_sessions_previous_token_pair"), "sessions", type_="check"
    )
    op.drop_column("sessions", "token_rotated_at")
    op.drop_column("sessions", "previous_valid_until")
    op.drop_column("sessions", "previous_token_hash")
