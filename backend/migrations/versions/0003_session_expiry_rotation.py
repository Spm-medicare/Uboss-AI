"""Add idle-aware, race-safe session token rotation.

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
