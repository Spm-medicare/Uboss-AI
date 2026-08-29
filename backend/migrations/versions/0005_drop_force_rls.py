"""Stop forcing row-level security on the owner; keep it on the application.

`ENABLE ROW LEVEL SECURITY` and `FORCE ROW LEVEL SECURITY` are two separate switches, and the
distinction is the whole point of this migration:

* **ENABLE** binds every role that is not the table's owner. `uboss_app` — the role every API
  request runs as — is not the owner, so ENABLE alone protects every request. This stays.
* **FORCE** additionally binds the owner. `uboss_owner` runs migrations and operator scripts and
  nothing else. This is what is being dropped.

**Why.** FORCE cost real work and delivered little. A migration has no bound tenant, so under
FORCE every tenant-owned table looked empty to it: migration 0004 read zero rows, created zero
roles and failed two steps later on a `NOT NULL` — a silent no-op that surfaced as an unrelated
error. The seed script failed the same way. Each one needed a lift-and-restore dance around its
own data, which is an easy thing to forget and a hard thing to notice forgetting.

**What is actually lost.** An operator script run as `uboss_owner` that forgets a `WHERE
tenant_id = …` will see every tenant. That is a real exposure, and it is bounded: the owner
credential is not in the API, not in the workers, and not in any process that serves a request.
It is used deliberately, by a person, for migrations and provisioning.

**What is kept.** Everything that protects a request. `uboss_app` with no tenant bound still
reads nothing from any tenant-owned table, and a write aimed at another tenant is still refused.
That is the boundary PLAN §18 and §19 ask for, and Gate 1's cross-tenant exit tests still have
something to test.

`tenants` was already ENABLE without FORCE, for exactly this reason — provisioning has to be able
to create an organisation. This migration makes the rest consistent with it rather than leaving
one table quietly different from the others.

**Note for future migrations:** the lift-and-restore pattern documented in 0004 is no longer
needed. `db.base.tenant_scope()` is still required for any code running as `uboss_app` that
writes rows for more than one tenant, because ENABLE still binds it — see DECISIONS 20.

Revision: 0005
Parent:   0004
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: Every tenant-owned table. `tenants` is absent because it never had FORCE.
FORCED_TABLES: tuple[str, ...] = (
    "memberships",
    "membership_roles",
    "roles",
    "role_permissions",
    "sessions",
    "audit_events",
    "outbox_events",
    "idempotency_records",
)


def upgrade() -> None:
    for table in FORCED_TABLES:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
    #  ENABLE is deliberately untouched. Dropping it would remove the boundary from the API,
    #  which is the one place it does the work.


def downgrade() -> None:
    """Reversible, and safe to reverse.

    Restoring FORCE takes nothing away and loses no data — it only re-binds the owner. Anything
    that then needs to rewrite tenant data has to lift it around that rewrite again, as 0004 did.
    """
    for table in FORCED_TABLES:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
