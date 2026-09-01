"""Let the relay role *find* schedules — and nothing more.

The scheduler worker has a bootstrap problem the outbox already solved: it serves every
workspace, but `uboss_app`'s policies correctly show an unbound connection nothing at all, so an
app-role worker cannot even learn which workspaces have a schedule switched on. `uboss_relay` is
the system's one cross-tenant credential, created deliberately by an operator in 0008.

This grants it `SELECT` on `job_schedules` — discovery, and only discovery. The worker reads
*which tenants* have `auto_run` schedules over the relay connection, then does each tenant's
actual work over the ordinary application connection with that tenant bound, where every
row-level policy applies as usual. The relay role gets no INSERT, no UPDATE, and nothing on
`schedule_firings`, `runs` or anything else: widening the one cross-tenant credential is the
thing 0008 warned about, and a scheduler that could *write* across tenants would be a much worse
thing to leak than one that can read a timetable.

Revision: 0035
Parent:   0034
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RELAY_ROLE = "uboss_relay"


def upgrade() -> None:
    op.execute(f"GRANT SELECT ON TABLE job_schedules TO {RELAY_ROLE}")
    op.execute(
        f"""
        CREATE POLICY job_schedules_relay ON job_schedules
            FOR SELECT
            TO {RELAY_ROLE}
            USING (true)
        """
    )
    #  Scoped to the role, exactly as the outbox policy is. PostgreSQL ORs permissive policies
    #  and this one names its role, so `uboss_app` still sees only its own tenant.


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS job_schedules_relay ON job_schedules")
    #  The suppression below is safe: the interpolated value is this module's own constant, not
    #  input. S608 fires on the word SELECT inside an f-string, which REVOKE unavoidably contains.
    op.execute(f"REVOKE SELECT ON TABLE job_schedules FROM {RELAY_ROLE}")  # noqa: S608
