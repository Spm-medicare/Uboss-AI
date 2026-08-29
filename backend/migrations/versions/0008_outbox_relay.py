"""The outbox relay: a lease, and the one cross-tenant role in the system.

`outbox_events` has been written since 0001 and read by nothing. DECISIONS 18 recorded that
deliberately: a relay needs a credential that reads across every tenant, and the right time for
the only such credential to appear is the moment something actually uses it. That moment is now,
because invite and password reset (1.2.6) cannot be built honestly without delivery.

**The role.** `uboss_relay` gets `SELECT` and `UPDATE` on `outbox_events` and **nothing else** —
no other table, no schema rights, no ability to create. A role-scoped policy lets it see every
tenant's due rows; the tenant-isolation policy still applies to `uboss_app`, which is unaffected.
PostgreSQL ORs permissive policies, and the relay policy names its role, so the two do not
interfere.

It is created `NOLOGIN` and with no password. A migration must never contain a credential: the
operator grants `LOGIN` and sets a password from the secret store, which is also the moment
somebody deliberately decides this credential should exist.

**The lease.** Claiming is a short transaction that stamps `leased_until` and `leased_by`;
publishing happens outside it; marking is a second short transaction. The alternative —
`SELECT ... FOR UPDATE SKIP LOCKED` held across the publish — keeps a database transaction open
for the length of a network call, which is how a connection pool runs out during an outage at
somebody else's service.

A worker that dies mid-publish leaves a lease that expires, and another worker picks the event
up. That means **at least once**, and the event may be published twice. Every consumer must
tolerate a duplicate. Nothing here provides, or claims, exactly-once.

Revision: 0008
Parent:   0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: A role name, not user input. Interpolated into DDL because PostgreSQL takes an identifier
#: there and not a parameter — there is no bind form of `CREATE ROLE`. The value is this
#: constant and nothing else, so ruff S608 is silenced per statement below rather than the rule
#: being switched off, which would hide a real one later.
RELAY_ROLE = "uboss_relay"


def upgrade() -> None:
    # ── the lease ────────────────────────────────────────────────────────────────────────
    op.add_column(
        "outbox_events",
        sa.Column("leased_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "outbox_events",
        sa.Column("leased_by", sa.String(length=100), nullable=True),
    )
    #  `leased_by` names the worker, for an operator looking at a stuck event. It is not a lock —
    #  the expiry is what releases the claim, so a worker that dies holds nothing.

    #  The relay's only query: what is due, and not currently claimed. Partial, so it stays small
    #  however many published rows accumulate behind it.
    op.execute("DROP INDEX IF EXISTS ix_outbox_events_due")
    op.execute(
        """
        CREATE INDEX ix_outbox_events_claimable
            ON outbox_events (next_attempt_at)
            WHERE status = 'pending';
        """
    )
    #  Dead letters are read by a person, not by the relay, so they get their own small index
    #  rather than sharing one tuned for the hot path.
    op.execute(
        """
        CREATE INDEX ix_outbox_events_dead
            ON outbox_events (tenant_id, created_at)
            WHERE status = 'dead';
        """
    )

    # ── the role ─────────────────────────────────────────────────────────────────────────
    #  The migration does not create the role, and `uboss_owner` deliberately cannot: it has no
    #  CREATEROLE attribute. A role is cluster-wide, and this is the only credential in the
    #  system that reads across every tenant — bringing it into existence should be a person's
    #  decision, taken once, in the same way provisioning a tenant is (DECISIONS 17).
    #
    #  So this checks, and stops with instructions. A migration that fails with a sentence
    #  somebody can act on is better than one that quietly grants itself the power to continue.
    connection = op.get_bind()
    exists = connection.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = :name"), {"name": RELAY_ROLE}
    ).scalar_one_or_none()
    if exists is None:
        raise RuntimeError(
            f"The role {RELAY_ROLE!r} does not exist. It is the only credential in this system "
            "that reads across every tenant, so it is created deliberately by an operator and "
            "not by a migration.\n\n"
            "  As a superuser:\n"
            f"    CREATE ROLE {RELAY_ROLE} LOGIN PASSWORD '<from the secret store>';\n\n"
            "Then run this migration again. On a fresh database the compose init script has "
            "already done it."
        )
    #  NOLOGIN, no password. The operator runs, from the secret store and not from here:
    #
    #      ALTER ROLE uboss_relay LOGIN PASSWORD '…';
    #
    #  A migration carrying a credential is a credential in version control.

    op.execute(f"GRANT USAGE ON SCHEMA public TO {RELAY_ROLE}")
    op.execute(f"GRANT SELECT, UPDATE ON TABLE outbox_events TO {RELAY_ROLE}")
    #  SELECT to find due rows, UPDATE to claim and to mark. No INSERT: the relay delivers events,
    #  it does not create them. No DELETE: a published row is history and a dead row is evidence.
    #  And no grant on any other table — this is the only cross-tenant credential in the system,
    #  so the smaller its reach the better.

    op.execute(
        f"""
        CREATE POLICY outbox_events_relay ON outbox_events
            FOR ALL
            TO {RELAY_ROLE}
            USING (true)
            WITH CHECK (true);
        """
    )
    #  Scoped to the role. `uboss_app` is not named, so it still sees only its own tenant —
    #  PostgreSQL ORs permissive policies, and this one simply does not apply to it.


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS outbox_events_relay ON outbox_events")
    op.execute(f"REVOKE ALL ON TABLE outbox_events FROM {RELAY_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {RELAY_ROLE}")
    #  The role itself is left in place. Dropping a role is cluster-wide and would fail if
    #  anything else in the cluster still depends on it — reversing a migration should not be
    #  able to take out a neighbouring database.

    op.execute("DROP INDEX IF EXISTS ix_outbox_events_dead")
    op.execute("DROP INDEX IF EXISTS ix_outbox_events_claimable")
    op.execute(
        """
        CREATE INDEX ix_outbox_events_due
            ON outbox_events (next_attempt_at)
            WHERE status = 'pending';
        """
    )
    op.drop_column("outbox_events", "leased_by")
    op.drop_column("outbox_events", "leased_until")
