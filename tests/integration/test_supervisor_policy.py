"""`PLAN.md` §10's form groups 4 to 9 — the settings a run will be bound by.

Nothing here executes anything. The runtime is Gate 7, so these tests prove the **governed
design** holds: a dependency cannot form a cycle, a deadline cannot fall inside its own SLA, a
notification cannot reach nobody, and a schedule reads with the Job's own recurrence rather than a
second copy of it.

That last one is the point of the schedule tests. `jobs/recurrence.py` already solves DST gaps and
ambiguity, and it is pure. A second implementation would be a second set of bugs that appear at
the clock change, when nobody is looking — so these assert the Supervisor's rows go through the
same function, not that a copy of it behaves the same way.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.conftest import Workspace
from uboss.db.base import build_sessionmaker
from uboss.modules.jobs import recurrence
from uboss.modules.supervisors.models import (
    OnFailure,
    Supervisor,
    SupervisorDependency,
    SupervisorEscalation,
    SupervisorKind,
    SupervisorNotification,
    SupervisorQualityGate,
    SupervisorSchedule,
    SupervisorSupervised,
)

pytestmark = pytest.mark.anyio

NEW_YORK = "America/New_York"


async def _bind(session: AsyncSession, workspace: Workspace) -> None:
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(workspace.tenant_id)}
    )


async def _supervisor(session: AsyncSession, workspace: Workspace, **fields: object) -> Supervisor:
    supervisor = Supervisor(
        tenant_id=workspace.tenant_id,
        name="Finance supervisor",
        kind=SupervisorKind.PERSONAL,
        owner_membership_id=workspace.membership_id,
        **fields,  # type: ignore[arg-type]
    )
    session.add(supervisor)
    await session.flush()
    return supervisor


async def _watch(
    session: AsyncSession, workspace: Workspace, supervisor: Supervisor, position: int
) -> SupervisorSupervised:
    row = SupervisorSupervised(
        tenant_id=workspace.tenant_id,
        supervisor_id=supervisor.id,
        membership_id=workspace.membership_id,
        position=position,
    )
    session.add(row)
    await session.flush()
    return row


# ------------------------------------------------------------------ group 5: dependencies


async def _agent(session: AsyncSession, workspace: Workspace, name: str) -> uuid.UUID:
    """One Agent row, written directly. The Agent Builder's own paths are tested elsewhere."""
    return (
        await session.execute(
            text(
                "INSERT INTO agents (tenant_id, name, owner_membership_id) "
                "VALUES (:t, :n, :m) RETURNING id"
            ),
            {"t": workspace.tenant_id, "n": name, "m": workspace.membership_id},
        )
    ).scalar_one()


async def _watch_agent(
    session: AsyncSession,
    workspace: Workspace,
    supervisor: Supervisor,
    agent_id: uuid.UUID,
    position: int,
) -> SupervisorSupervised:
    row = SupervisorSupervised(
        tenant_id=workspace.tenant_id,
        supervisor_id=supervisor.id,
        membership_id=workspace.membership_id,
        agent_id=agent_id,
        position=position,
    )
    session.add(row)
    await session.flush()
    return row


async def test_a_dependency_cycle_is_refused_at_the_point_of_writing(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """A set that each waits for the next can never start.

    Refused when it is written rather than found by a run that hangs — the same rule the Job's
    steps and the Objective's plan already apply, for the same reason. Three deep, so the test
    exercises the recursive walk rather than a single self-reference the check constraint would
    have caught anyway.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, left)
        supervisor = await _supervisor(session, left)

        watched = [
            await _watch_agent(
                session, left, supervisor, await _agent(session, left, f"Agent {n}"), n
            )
            for n in (1, 2, 3)
        ]

        #  1 → 2 → 3, which is fine.
        for downstream, upstream in ((1, 0), (2, 1)):
            session.add(
                SupervisorDependency(
                    tenant_id=left.tenant_id,
                    supervisor_id=supervisor.id,
                    supervised_id=watched[downstream].id,
                    depends_on_id=watched[upstream].id,
                )
            )
        await session.flush()

        #  Now 1 → 3, which closes the loop.
        session.add(
            SupervisorDependency(
                tenant_id=left.tenant_id,
                supervisor_id=supervisor.id,
                supervised_id=watched[0].id,
                depends_on_id=watched[2].id,
            )
        )
        with pytest.raises((IntegrityError, DBAPIError)) as refused:
            await session.flush()
        assert "cycle" in str(refused.value)
        await session.rollback()


async def test_a_chain_of_dependencies_that_does_not_loop_is_allowed(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """The other half. Without it the trigger could refuse everything and still pass."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, left)
        supervisor = await _supervisor(session, left)
        watched = [
            await _watch_agent(
                session, left, supervisor, await _agent(session, left, f"Agent {n}"), n
            )
            for n in (1, 2, 3)
        ]
        for downstream, upstream in ((1, 0), (2, 1), (2, 0)):
            session.add(
                SupervisorDependency(
                    tenant_id=left.tenant_id,
                    supervisor_id=supervisor.id,
                    supervised_id=watched[downstream].id,
                    depends_on_id=watched[upstream].id,
                )
            )
        await session.flush()

        count = len(
            (
                await session.execute(
                    select(SupervisorDependency).where(
                        SupervisorDependency.supervisor_id == supervisor.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert count == 3
        await session.rollback()


async def test_a_dependency_cannot_point_at_itself(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, left)
        supervisor = await _supervisor(session, left)
        watched = await _watch(session, left, supervisor, 1)

        session.add(
            SupervisorDependency(
                tenant_id=left.tenant_id,
                supervisor_id=supervisor.id,
                supervised_id=watched.id,
                depends_on_id=watched.id,
            )
        )
        #  The cycle trigger fires first — a BEFORE INSERT trigger runs ahead of the check
        #  constraint — so the refusal arrives as a raised exception rather than a violation.
        #  Both are refusals; which one wins is Postgres's business.
        with pytest.raises((IntegrityError, DBAPIError)):
            await session.flush()
        await session.rollback()


# ------------------------------------------------------------------ group 7: budget and SLA


async def test_a_deadline_cannot_fall_inside_its_own_sla(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Two promises that contradict each other.

    §10 asks a Supervisor to track both. A deadline earlier than the SLA it is measured against
    would make every run late the moment it started.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, left)
        with pytest.raises(IntegrityError):
            await _supervisor(session, left, sla_minutes=120, deadline_minutes=60)
        await session.rollback()

    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, left)
        supervisor = await _supervisor(session, left, sla_minutes=60, deadline_minutes=120)
        assert supervisor.deadline_minutes == 120
        await session.rollback()


async def test_a_cost_cap_is_a_number_and_a_currency_or_neither(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """"12" with no currency is not a cap."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, left)
        with pytest.raises(IntegrityError):
            await _supervisor(session, left, cost_cap_minor_units=5000)
        await session.rollback()


async def test_every_limit_is_optional_and_means_the_workspace_policy_decides(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """A Supervisor with no limits is bounded by the workspace, not unbounded.

    Written down because the alternative reading — null means unlimited — is the one somebody
    would assume, and it is wrong.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, left)
        supervisor = await _supervisor(session, left)
        for field in (
            "max_concurrency",
            "token_cap",
            "sla_minutes",
            "deadline_minutes",
            "max_retries",
            "retry_backoff_seconds",
            "cost_cap_minor_units",
        ):
            assert getattr(supervisor, field) is None, field
        await session.rollback()


async def test_a_retry_count_of_zero_is_allowed_but_a_negative_one_is_not(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Zero retries is a real answer — try once and stop. Minus one is not."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, left)
        supervisor = await _supervisor(session, left, max_retries=0)
        assert supervisor.max_retries == 0
        await session.rollback()

    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, left)
        with pytest.raises(IntegrityError):
            await _supervisor(session, left, max_retries=-1)
        await session.rollback()


# ------------------------------------------------------------------ group 6: quality gates


async def test_a_quality_gate_states_what_happens_when_it_does_not_hold(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """A gate with no consequence is an observation.

    `escalate` is the default because §10 lists escalation as a capability and silence is not one.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, left)
        supervisor = await _supervisor(session, left)
        gate = SupervisorQualityGate(
            tenant_id=left.tenant_id,
            supervisor_id=supervisor.id,
            name="Every output cites a source",
            condition="No claim without a citation",
            evidence="Claim-to-source map on each output",
            position=1,
        )
        session.add(gate)
        await session.flush()
        assert gate.on_failure == OnFailure.ESCALATE
        await session.rollback()


async def test_a_quality_gate_needs_a_condition(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, left)
        supervisor = await _supervisor(session, left)
        session.add(
            SupervisorQualityGate(
                tenant_id=left.tenant_id,
                supervisor_id=supervisor.id,
                name="Nameless rule",
                condition="   ",
                position=1,
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()


# ------------------------------------------------------------------ groups 8 and 9


async def test_an_escalation_must_name_somebody(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """A rule with no addressee is a rule nobody acts on."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, left)
        supervisor = await _supervisor(session, left)
        session.add(
            SupervisorEscalation(
                tenant_id=left.tenant_id,
                supervisor_id=supervisor.id,
                situation="An agent has not reported in an hour",
                required_action="Page the on-call",
                position=1,
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()


async def test_a_notification_must_reach_somebody(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """§10: *"notify handlers and stakeholders"*. Neither is a setting that does nothing."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, left)
        supervisor = await _supervisor(session, left)
        session.add(
            SupervisorNotification(
                tenant_id=left.tenant_id,
                supervisor_id=supervisor.id,
                event="run failed",
                to_handlers=False,
                position=1,
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()


async def test_a_notification_reaches_the_handlers_by_default(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Handlers are who §10 says to notify, so that is what a bare row means."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, left)
        supervisor = await _supervisor(session, left)
        row = SupervisorNotification(
            tenant_id=left.tenant_id,
            supervisor_id=supervisor.id,
            event="run failed",
            position=1,
        )
        session.add(row)
        await session.flush()
        assert row.to_handlers is True
        await session.rollback()


# ------------------------------------------------------------------ group 4: the schedule


async def test_a_supervisor_schedule_is_off_until_somebody_turns_it_on(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """A schedule that starts firing because a form was saved is one nobody agreed to."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, left)
        supervisor = await _supervisor(session, left)
        schedule = SupervisorSchedule(
            tenant_id=left.tenant_id,
            supervisor_id=supervisor.id,
            timezone=NEW_YORK,
            frequency=recurrence.Frequency.DAILY,
            at_time=time(9, 0),
        )
        session.add(schedule)
        await session.flush()
        assert schedule.auto_run is False
        #  The plan's decision table: *"Schedule overlap | Queue one run."*
        assert schedule.overlap_policy == recurrence.OverlapPolicy.QUEUE
        assert schedule.missed_run_policy == recurrence.MissedRunPolicy.SKIP
        await session.rollback()


async def test_one_schedule_per_supervisor(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Two would be two answers to "when does this run"."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, left)
        supervisor = await _supervisor(session, left)
        for _ in range(2):
            session.add(
                SupervisorSchedule(
                    tenant_id=left.tenant_id,
                    supervisor_id=supervisor.id,
                    timezone=NEW_YORK,
                    frequency=recurrence.Frequency.DAILY,
                    at_time=time(9, 0),
                )
            )
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()


async def test_the_supervisors_schedule_reads_with_the_jobs_own_recurrence(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """The columns are the Job's, so the Job's pure module reads them unchanged.

    Proved across a real DST boundary rather than on an ordinary day: 2 a.m. on the spring-forward
    Sunday does not exist in New York, and `shift` is what decides what happens instead. A second
    implementation of that is a second set of bugs at the clock change.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, left)
        supervisor = await _supervisor(session, left)
        schedule = SupervisorSchedule(
            tenant_id=left.tenant_id,
            supervisor_id=supervisor.id,
            timezone=NEW_YORK,
            frequency=recurrence.Frequency.DAILY,
            at_time=time(2, 30),
            dst_policy=recurrence.DstPolicy.SHIFT,
        )
        session.add(schedule)
        await session.flush()

        #  The shared converter, not a copy of it. `from_row` is what the Job's schedule uses
        #  too, so a renamed column breaks both at once instead of silently diverging.
        rule = recurrence.from_row(schedule)
        recurrence.validate(rule)

        #  8 March 2026 is the spring-forward Sunday in New York.
        moments = recurrence.occurrences(
            rule, after=datetime(2026, 3, 7, 0, 0, tzinfo=UTC), count=3
        )
        local = [
            moment.astimezone(ZoneInfo(NEW_YORK)) for moment in moments
        ]
        on_the_gap_day = [m for m in local if m.date() == date(2026, 3, 8)]
        assert len(on_the_gap_day) == 1
        #  02:30 does not exist that morning, so `shift` moves it forward by the offset change.
        assert on_the_gap_day[0].hour == 3
        await session.rollback()


async def test_supervisor_policy_is_invisible_to_another_workspace(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Every one of the five new tables, not just the parent."""
    left, right = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, left)
        supervisor = await _supervisor(session, left)
        session.add(
            SupervisorQualityGate(
                tenant_id=left.tenant_id,
                supervisor_id=supervisor.id,
                name="A gate",
                condition="Something holds",
                position=1,
            )
        )
        session.add(
            SupervisorNotification(
                tenant_id=left.tenant_id,
                supervisor_id=supervisor.id,
                event="run failed",
                position=1,
            )
        )
        session.add(
            SupervisorSchedule(
                tenant_id=left.tenant_id,
                supervisor_id=supervisor.id,
                timezone=NEW_YORK,
                frequency=recurrence.Frequency.DAILY,
                at_time=time(9, 0),
            )
        )
        await session.commit()

    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, right)
        for model in (
            SupervisorQualityGate,
            SupervisorNotification,
            SupervisorSchedule,
            SupervisorEscalation,
            SupervisorDependency,
        ):
            rows = (await session.execute(select(model))).scalars().all()
            assert rows == [], model.__name__
        await session.rollback()


async def test_routing_policy_accepts_anything_because_no_vocabulary_is_approved(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """§10 says *"routing policy"* and names no choices.

    A closed set here would be choices somebody invented. Recorded as an open question in
    `docs/architecture/SUPERVISOR_FIELDS.md` rather than quietly decided — the same treatment
    `agents.model_policy_key` got, for the same reason.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, left)
        supervisor = await _supervisor(
            session, left, routing_policy="Round-robin across the two available analysts"
        )
        assert supervisor.routing_policy is not None
        await session.rollback()


async def test_a_dependency_only_links_things_this_supervisor_watches(
    app_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Both sides are rows of the supervised set, so there is nothing else they could name."""
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, left)
        supervisor = await _supervisor(session, left)
        watched = await _watch(session, left, supervisor, 1)

        session.add(
            SupervisorDependency(
                tenant_id=left.tenant_id,
                supervisor_id=supervisor.id,
                supervised_id=watched.id,
                depends_on_id=uuid.uuid4(),
            )
        )
        with pytest.raises((IntegrityError, DBAPIError)):
            await session.flush()
        await session.rollback()


@pytest.mark.parametrize(
    ("column", "parser"),
    [
        ("frequency", recurrence.Frequency),
        ("dst_policy", recurrence.DstPolicy),
        ("ambiguous_policy", recurrence.AmbiguousPolicy),
        ("missed_run_policy", recurrence.MissedRunPolicy),
        ("overlap_policy", recurrence.OverlapPolicy),
    ],
)
async def test_the_schedule_columns_admit_exactly_what_recurrence_parses(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    column: str,
    parser: type[enum.StrEnum],
) -> None:
    """The drift this table exists to prevent, asked of the constraint itself.

    Migration 0024's first draft allowed `yearly`, `strict`, `second` and `queue_one` — four
    values `jobs/recurrence.py` cannot parse. A column that can hold a value its reader chokes on
    is worse than a separate implementation, because it fails at the clock change rather than at
    the point somebody wrote it.

    Asked of the database rather than of two Python constants: the constraint is the thing that
    would drift, and comparing constants would pass while the column stayed wrong.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        await _bind(session, left)
        supervisor = await _supervisor(session, left)
        session.add(
            SupervisorSchedule(
                tenant_id=left.tenant_id,
                supervisor_id=supervisor.id,
                timezone=NEW_YORK,
                frequency=recurrence.Frequency.DAILY,
                at_time=time(9, 0),
            )
        )
        await session.flush()

        #  Every value the module can parse is a value the column accepts.
        for member in parser:
            await session.execute(
                #  S608: `column` is one of five names this test's own parametrize list supplies,
                #  and a column name cannot be a bind parameter. The value is bound.
                text(
                    f"UPDATE supervisor_schedules SET {column} = :v "  # noqa: S608
                    f"WHERE supervisor_id = :s"
                ),
                {"v": member.value, "s": supervisor.id},
            )

        #  And nothing else is.
        with pytest.raises((IntegrityError, DBAPIError)):
            await session.execute(
                text(
                    #  S608: the same five names, from the same list.
                    f"UPDATE supervisor_schedules SET {column} = 'not-a-real-policy' "  # noqa: S608
                    f"WHERE supervisor_id = :s"
                ),
                {"s": supervisor.id},
            )
        await session.rollback()
