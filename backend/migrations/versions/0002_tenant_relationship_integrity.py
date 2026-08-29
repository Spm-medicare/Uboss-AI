"""Make tenant identity relationships internally consistent.

Revision ID: 0002
Revises: 0001
Created: 2026-08-29

RLS protects a row according to that row's ``tenant_id``. It cannot prove that a referenced
membership belongs to the same tenant, or that a session's copied ``user_id`` is the user behind
that membership. Before this revision, each individual foreign key could be valid while their
combination was false.

Composite candidate keys and foreign keys make these invariants database-enforced:

* a membership role and its optional grantor belong to the role row's tenant;
* a session's tenant, membership and user describe one membership tuple.

The original single-column foreign keys remain. They preserve precise delete semantics and make
the global identity relationships explicit; the composite keys add tenant integrity rather than
replacing them.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Referenced column sets must be unique before PostgreSQL accepts composite FKs.
    op.create_unique_constraint(
        "uq_memberships_tenant_id_id",
        "memberships",
        ["tenant_id", "id"],
    )
    op.create_unique_constraint(
        "uq_memberships_tenant_id_id_user_id",
        "memberships",
        ["tenant_id", "id", "user_id"],
    )

    op.create_foreign_key(
        "fk_membership_roles_tenant_membership",
        "membership_roles",
        "memberships",
        ["tenant_id", "membership_id"],
        ["tenant_id", "id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_membership_roles_tenant_grantor",
        "membership_roles",
        "memberships",
        ["tenant_id", "granted_by_membership_id"],
        ["tenant_id", "id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_sessions_tenant_membership_user",
        "sessions",
        "memberships",
        ["tenant_id", "membership_id", "user_id"],
        ["tenant_id", "id", "user_id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_sessions_tenant_membership_user",
        "sessions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_membership_roles_tenant_grantor",
        "membership_roles",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_membership_roles_tenant_membership",
        "membership_roles",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_memberships_tenant_id_id_user_id",
        "memberships",
        type_="unique",
    )
    op.drop_constraint(
        "uq_memberships_tenant_id_id",
        "memberships",
        type_="unique",
    )
