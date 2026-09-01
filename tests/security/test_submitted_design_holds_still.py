"""A design sent for approval cannot change while somebody is reviewing it.

`is_editable` is the flag `service.update` checks before writing, and the Job and the Objective
both counted `ready_to_publish` — the state after somebody presses *Send for approval* — as
editable. So between submission and approval the design stayed writable, the approver read one
thing and approved another, and the immutable version published at the end was not the version
anybody reviewed. That is the single guarantee the publish path exists to make.

Two of the four forms already excluded it (`agents.EDITABLE`, `Supervisor.is_editable`), so this
is a test that the other two now agree with them rather than a new rule invented here.

The integration test also asserts what must **still** work, because the cheap way to pass the
first half is to freeze the record entirely: withdrawing has to remain possible from exactly this
state, and editing has to resume the moment it is withdrawn. A design nobody can take back is a
worse failure than one that can drift.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.conftest import Workspace
from tests.integration.test_job_publish import _complete_job, _context
from uboss.core.errors import ValidationFailed
from uboss.db.base import build_sessionmaker
from uboss.modules.agents import agent_service
from uboss.modules.jobs import models as job_models
from uboss.modules.jobs import publish as job_publish
from uboss.modules.jobs import service as job_service
from uboss.modules.jobs.schemas import JobUpdate
from uboss.modules.objectives import models as objective_models
from uboss.modules.supervisors import models as supervisor_models


def test_all_four_forms_agree_on_what_editable_means() -> None:
    """The four state sets, compared directly, with no database.

    A unit check rather than an integration one because the defect was a membership question — is
    `ready_to_publish` in this tuple — and it drifted apart across four modules precisely because
    nothing ever compared them to each other.
    """
    expected = {job_models.JobStatus.DRAFT.value, job_models.JobStatus.NEEDS_REVIEW.value}

    editable = {
        "job": {
            status.value
            for status in job_models.JobStatus
            if job_models.Job(status=status).is_editable
        },
        "objective": {
            status.value
            for status in objective_models.ObjectiveStatus
            if objective_models.Objective(status=status).is_editable
        },
        "supervisor": {
            status.value
            for status in supervisor_models.SupervisorStatus
            if supervisor_models.Supervisor(status=status).is_editable
        },
        "agent": {status.value for status in agent_service.EDITABLE},
    }

    for name, states in editable.items():
        assert states == expected, f"{name} is editable in {sorted(states)}"
        assert "ready_to_publish" not in states, (
            f"{name} treats a submitted design as editable, so it can be changed while it is "
            "being approved"
        )
        assert "published" not in states


async def test_a_submitted_job_cannot_be_edited_and_can_still_be_taken_back(
    app_engine: AsyncEngine,
    two_workspaces: tuple[Workspace, Workspace],
    colleague: uuid.UUID,
) -> None:
    """Submit it, try to change it, take it back, change it.

    The middle step is the guarantee. The last two are the proof that the guarantee was not bought
    by freezing the record — which would trade a correctness bug for a deadlock, and is exactly
    what the screen was already suffering: a submitted job offered its author no submit, no
    withdraw, no approve and no explanation, because the Withdraw control asks for
    `ready_to_publish` **and** not-editable, and nothing could ever be both.
    """
    left, _ = two_workspaces
    async with build_sessionmaker(app_engine)() as session:
        context = await _context(session, left, actions=("edit_draft", "publish"))
        job_id = await _complete_job(session, context, colleague)

        job = await session.get(job_models.Job, job_id)
        assert job is not None
        original_name = job.name

        await job_publish.submit(session, context, job_id, job.version)
        await session.flush()
        await session.refresh(job)
        assert job.status == job_models.JobStatus.READY_TO_PUBLISH
        assert job.is_editable is False

        with pytest.raises(ValidationFailed) as refused:
            await job_service.update(
                session,
                context,
                job_id,
                JobUpdate(name="Renamed while under review", expected_version=job.version),
            )
        assert "ready to publish" in str(refused.value)

        await session.refresh(job)
        assert job.name == original_name, "the refusal must not have written anyway"

        #  Taking it back works from exactly the state that just refused an edit.
        await job_publish.withdraw(session, context, job_id, job.version)
        await session.flush()
        await session.refresh(job)
        assert job.status == job_models.JobStatus.NEEDS_REVIEW
        assert job.is_editable is True

        await job_service.update(
            session,
            context,
            job_id,
            JobUpdate(name="Renamed after taking it back", expected_version=job.version),
        )
        await session.flush()
        await session.refresh(job)
        assert job.name == "Renamed after taking it back"
        await session.rollback()
