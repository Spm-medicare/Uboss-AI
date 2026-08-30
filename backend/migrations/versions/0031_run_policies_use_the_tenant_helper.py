"""The run tables' policies raised where every other table's returns nothing.

0029 wrote the three policies with the expression spelled out:

    tenant_id = current_setting('app.tenant_id', true)::uuid

Every other tenant-owned table in the schema calls `app_current_tenant()` instead, which is

    nullif(current_setting('app.tenant_id', true), '')::uuid

The difference is the `nullif`, and it is not cosmetic. `set_config(..., is_local => true)` reverts
at the end of a transaction — but reverting means going back to the setting's *default*, which is
the empty string, not "undefined". So the second transaction on a pooled connection reads `''`,
and `''::uuid` is an error rather than a NULL:

    invalid input syntax for type uuid: ""

A policy that raises is not a policy that fails closed. It fails *loudly*, on a query that should
simply have returned nothing — and on a connection that has served one request already, which is
every connection in production after the first minute. `test_nothing_is_visible_without_a_bound_tenant`
caught it, and only when it ran after a test that had bound a tenant on the same connection.

Nothing about who can see what changes. An unbound connection saw no rows before this and sees no
rows after it; it simply stops raising to say so.

Revision: 0031
Parent:   0030
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("runs", "run_steps", "run_events")


def upgrade() -> None:
    for table in TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant ON {table}")
        op.execute(
            f"""
            CREATE POLICY {table}_tenant ON {table}
            USING (tenant_id = app_current_tenant())
            WITH CHECK (tenant_id = app_current_tenant())
            """
        )


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant ON {table}")
        op.execute(
            f"""
            CREATE POLICY {table}_tenant ON {table}
            USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid)
            """
        )
