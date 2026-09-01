"""Gate 7.6 — what a run read, did, produced and who decided, in one document.

The tables existed in pieces: a run, its steps, its events, the tasks people completed, the
approvals with their reasons. What did not exist was a way to ask for all of it at once, an
attributable record of what a run asked a model, or any record at all of what a run **produced** —
`RunStep.result` is a JSONB blob nothing can list, count or open, and a file somebody attached as
proof lived only on the task.

These tests are about the account rather than the tables: a person completes work with a note and
a file, and the evidence says what was produced, under the name the *published version* gave it,
with the person's name against it.

The last one is the one worth having. §17 names `tool_calls` and `integrations/` is empty until
Gate 8, so the bundle says so instead of returning an empty list — *"this run used no tools"* and
*"this system cannot record that yet"* are different facts.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.conftest import Workspace
from tests.integration.test_tasks import _run_to_first_step
from uboss.db.base import build_sessionmaker, tenant_scope
from uboss.modules.files.models import File
from uboss.modules.runtime import evidence
from uboss.modules.runtime.models import RunOutput
from uboss.modules.tasks import service as tasks

STEPS = [
    {
        "position": 1,
        "what_exact_work": "Reconcile the ledger",
        "how_exact_method": "Match against the bank file",
        #  The design names the output. The evidence should use this name, not the step's title.
        "output": "A signed reconciliation",
        "output_destination": "Finance shared drive",
        "mode": "human",
    }
]


def _rules(workspace: Workspace) -> list[dict[str, object]]:
    return [
        {"position": 1, "who_type": "user", "target_id": str(workspace.membership_id)}
    ]


async def _file(session: AsyncSession, workspace: Workspace) -> uuid.UUID:
    """A stored file to attach, so the produced-file path is exercised rather than assumed."""
    row = File(
        tenant_id=workspace.tenant_id,
        #  Tenant-prefixed, which `ck_files_key_is_tenant_prefixed` requires: a storage key that
        #  does not start with the tenant is a key another tenant's path could collide with.
        storage_key=f"t/{workspace.tenant_id}/test/{uuid.uuid4()}",
        original_name="reconciliation.pdf",
        content_type="application/pdf",
        size_bytes=1024,
        sha256="0" * 64,
    )
    session.add(row)
    await session.flush()
    return row.id


async def test_the_bundle_is_the_whole_account_of_a_run(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """One document: the run, its steps, what happened, who decided and what came out."""
    left, _right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            run, step, context = await _run_to_first_step(
                session, left, steps=STEPS, rules=_rules(left)
            )
            task = await tasks.create_for_step(session, run, step)
            await session.flush()

            await tasks.complete(
                session,
                context,
                task,
                outcome="completed",
                note="Reconciled to the penny; two entries reclassified.",
            )
            await session.flush()

            document = await evidence.bundle(session, context, run.id)

            assert document["run"]["job_name"]
            assert document["run"]["started_by"], "a run says who started it, by name"
            assert len(document["steps"]) == 1
            assert document["steps"][0]["title"]
            #  Attempts are in the record, so a retry is visible rather than smoothed over.
            assert "attempt" in document["steps"][0]

            assert document["events"], "what happened, in order"
            assert any(event["kind"] == "step.started" for event in document["events"])

            recorded = document["tasks"][0]
            assert recorded["outcome"] == "completed"
            assert "reclassified" in (recorded["outcome_note"] or "")
            assert recorded["completed_by"], "who did it, by name rather than by id"

            await session.rollback()


async def test_what_a_person_produced_is_recorded_under_the_designed_name(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """The note and the attached file become outputs, named the way the version named them.

    `RunStep.result` still holds what happened at the step and is still the activity's own
    bookkeeping. This is the separate question — *what did this run produce* — which used to be
    answerable only by reading JSON out of every step and knowing which keys meant what.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            run, step, context = await _run_to_first_step(
                session, left, steps=STEPS, rules=_rules(left)
            )
            task = await tasks.create_for_step(session, run, step)
            await session.flush()

            file_id = await _file(session, left)
            await tasks.attach(session, context, task, file_id=file_id, note=None)
            await session.flush()

            await tasks.complete(
                session, context, task, outcome="completed", note="Reconciled to the penny."
            )
            await session.flush()

            document = await evidence.bundle(session, context, run.id)
            outputs = document["outputs"]

            assert len(outputs) == 2, "the note and the file are two things produced"
            #  The name is the design's, not the step's title. Form 3 named it before it existed.
            assert all(output["name"] == "A signed reconciliation" for output in outputs)
            assert all(output["destination"] == "Finance shared drive" for output in outputs)

            values = [output["value_text"] for output in outputs if output["value_text"]]
            files = [output["file_id"] for output in outputs if output["file_id"]]
            assert values == ["Reconciled to the penny."]
            assert files == [str(file_id)]

            await session.rollback()


async def test_a_task_completed_with_nothing_records_no_output(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """An empty note and no attachment produce nothing, and the record says nothing.

    A row for it would be a run claiming to have produced something it cannot show, which is the
    same fault as a screen displaying a number nobody counted.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            run, step, context = await _run_to_first_step(
                session, left, steps=STEPS, rules=_rules(left)
            )
            task = await tasks.create_for_step(session, run, step)
            await session.flush()

            await tasks.complete(session, context, task, outcome="completed", note="   ")
            await session.flush()

            document = await evidence.bundle(session, context, run.id)
            assert document["outputs"] == []
            await session.rollback()


async def test_the_bundle_says_tool_calls_are_not_recordable_yet(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """An empty list and an unavailable capability are different facts.

    §17 names `tool_calls`; `integrations/` is an empty package until Gate 8. Returning `[]` alone
    would read as *"this run used no tools"*, which is a claim about the run. `available: false` is
    a claim about the system, and it is the true one.
    """
    left, _right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            run, step, context = await _run_to_first_step(
                session, left, steps=STEPS, rules=_rules(left)
            )
            await tasks.create_for_step(session, run, step)
            await session.flush()

            document = await evidence.bundle(session, context, run.id)
            assert document["tool_calls"] == []
            assert document["tool_calls_available"] is False
            #  Model calls are recordable, so their empty list is a fact about the run.
            assert document["model_calls"] == []
            await session.rollback()


async def test_an_output_cannot_be_edited_once_written(
    owner_engine: AsyncEngine, two_workspaces: tuple[Workspace, Workspace]
) -> None:
    """Evidence that can be changed is a record of what somebody last decided it should say.

    The same treatment `run_events` gets: append-only by trigger and by withheld privilege, so the
    application role cannot rewrite history even by mistake.
    """
    import pytest
    from sqlalchemy import text

    left, _right = two_workspaces
    async with build_sessionmaker(owner_engine)() as session:
        async with tenant_scope(session, left.tenant_id):
            run, step, context = await _run_to_first_step(
                session, left, steps=STEPS, rules=_rules(left)
            )
            task = await tasks.create_for_step(session, run, step)
            await session.flush()
            await tasks.complete(
                session, context, task, outcome="completed", note="Reconciled."
            )
            await session.flush()

            written = (
                await session.execute(
                    text("SELECT id FROM run_outputs WHERE run_id = :run"), {"run": run.id}
                )
            ).scalar_one()

            await session.begin_nested()
            with pytest.raises(Exception) as refused:
                await session.execute(
                    text("UPDATE run_outputs SET value_text = 'something else' WHERE id = :id"),
                    {"id": written},
                )
            assert "append-only" in str(refused.value).lower() or "refuse" in str(
                refused.value
            ).lower()
            await session.rollback()
            assert RunOutput is not None
            await session.rollback()
