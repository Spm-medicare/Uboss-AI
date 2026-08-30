"""The run workflow — the shape of a governed execution.

A Temporal workflow is deterministic code that is **replayed** from its history after every worker
restart. Two consequences decide everything in this file:

**No I/O, no clock, no randomness here.** Every side effect is an activity. `datetime.now()` in a
workflow returns a different answer on replay and corrupts the history; `workflow.now()` is the
recorded one. Nothing in this module reads the database — it calls activities that do.

**Every input must be in the history.** Anything a workflow needs after a restart has to have
arrived as an argument or through a signal. That is why `RunRef` carries the tenant and the
correlation id rather than the workflow reaching for them.

## Why a loop rather than a chain

Steps are executed one at a time, in the version's order, by asking the database what is next
after each one. The alternative — reading the whole list once and iterating it in workflow memory
— would be faster and would go wrong the moment a step is retried, skipped or added by a person:
the workflow's copy and the database's would disagree, and the database is the one the screens
read.

## Waiting on a person

A human step does not sleep and does not poll. The workflow marks the run `waiting` and blocks on
a signal, indefinitely. Temporal holds that state on the server, so no worker, thread or
connection is held open — a run can wait a fortnight and cost nothing.

7.2 sends `step_completed` when somebody finishes their task. Until then a human step waits, which
is the honest behaviour: the alternative is a runtime that quietly skips the work people do.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from uboss.modules.runtime.activities import RunActivities, RunRef, StepRef

#: How hard a step tries before the run fails. Three attempts over roughly a minute: long enough
#: to ride out a restart or a brief outage at somebody else's service, short enough that a broken
#: step is reported rather than retried all afternoon.
STEP_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=30),
    maximum_attempts=3,
)

#: Bookkeeping — state changes against our own database. Retried more patiently, because failing
#: to *record* a step is not the same as failing to do it, and giving up would leave a run whose
#: history is wrong.
RECORD_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=60),
    maximum_attempts=10,
)

#: A step's own timeout. Generous: a model call or an integration can be slow, and a timeout that
#: fires before the work finishes turns a slow step into a failed one.
STEP_TIMEOUT = timedelta(minutes=10)
RECORD_TIMEOUT = timedelta(seconds=30)

#: The human step gets this long before the run gives up on it. A fortnight, which is longer than
#: a holiday and shorter than forever — a run waiting indefinitely is a run nobody notices is
#: stuck.
HUMAN_STEP_DEADLINE = timedelta(days=14)

HUMAN = "human"


@workflow.defn(name="JobRun")
class JobRunWorkflow:
    """One execution of one published Job version."""

    def __init__(self) -> None:
        #: Set by the `step_completed` signal. Not a queue: a run does one step at a time, so a
        #: second signal while nothing is waiting is a signal for a step that already finished,
        #: and dropping it is correct.
        self._continue = False

    @workflow.signal(name="step_completed")
    def step_completed(self) -> None:
        """Somebody finished the human step this run was waiting on.

        The signal carries nothing. What they did is already in the database — the task, the
        evidence, the approval — and passing it through the signal would be a second copy that
        could disagree with the first.
        """
        self._continue = True

    @workflow.run
    async def run(self, ref: RunRef) -> str:
        await workflow.execute_activity_method(
            RunActivities.mark_running,
            ref,
            start_to_close_timeout=RECORD_TIMEOUT,
            retry_policy=RECORD_RETRY,
        )

        while True:
            step = await workflow.execute_activity_method(
                RunActivities.next_step,
                ref,
                start_to_close_timeout=RECORD_TIMEOUT,
                retry_policy=RECORD_RETRY,
            )
            if step is None:
                break

            await workflow.execute_activity_method(
                RunActivities.begin_step,
                step,
                start_to_close_timeout=RECORD_TIMEOUT,
                retry_policy=RECORD_RETRY,
            )

            if step.mode == HUMAN:
                finished = await self._await_person(step)
                if not finished:
                    await workflow.execute_activity_method(
                        RunActivities.fail_step,
                        args=[
                            step,
                            (
                                "Nobody completed this step within two weeks, so the run was "
                                "stopped. Start it again when the work is ready to be done."
                            ),
                        ],
                        start_to_close_timeout=RECORD_TIMEOUT,
                        retry_policy=RECORD_RETRY,
                    )
                    return "failed"
                #  The person's completion is what advances the step; the loop simply asks for the
                #  next one. Marking it succeeded here would overwrite whatever they recorded.
                continue

            try:
                await workflow.execute_activity_method(
                    RunActivities.perform,
                    step,
                    start_to_close_timeout=STEP_TIMEOUT,
                    retry_policy=STEP_RETRY,
                )
            #  Broad on purpose: the workflow turns *any* step failure into a recorded one.
            #  Letting it escape would fail the workflow with the run still saying `running`, and
            #  every screen would show it going for ever.
            except Exception as failure:
                await workflow.execute_activity_method(
                    RunActivities.fail_step,
                    args=[step, str(failure)[:2000]],
                    start_to_close_timeout=RECORD_TIMEOUT,
                    retry_policy=RECORD_RETRY,
                )
                return "failed"

        await workflow.execute_activity_method(
            RunActivities.finish,
            ref,
            start_to_close_timeout=RECORD_TIMEOUT,
            retry_policy=RECORD_RETRY,
        )
        return "succeeded"

    async def _await_person(self, step: StepRef) -> bool:
        """Mark the run waiting and block on the signal. True if somebody came.

        `wait_condition` is the whole point: it costs nothing while it waits, survives every
        worker restart, and wakes on the signal rather than on a timer.
        """
        await workflow.execute_activity_method(
            RunActivities.wait_for_person,
            step,
            start_to_close_timeout=RECORD_TIMEOUT,
            retry_policy=RECORD_RETRY,
        )
        self._continue = False
        try:
            #  Raises on timeout rather than returning a value — the deadline is an exception,
            #  which is why this is a `try` and not a truthiness check on a return.
            await workflow.wait_condition(
                lambda: self._continue, timeout=HUMAN_STEP_DEADLINE
            )
        except TimeoutError:
            return False
        return True
