"""The gateway's front door.

Domain code calls `run()` with a `Task` and gets a `Completion`. It never chooses a model, never
sees an API key, and never learns which provider answered.

Every call writes an audit event — before the answer is used, in the caller's transaction. PLAN
§19 requires tenant isolation to extend to AI context, and PLAN §16 requires responsible-AI
evidence; a model call with no record is a decision nobody can account for later.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from uboss.core.context import SecurityContext
from uboss.core.settings import Settings
from uboss.modules.ai_gateway import anthropic_adapter
from uboss.modules.ai_gateway.contract import Completion, ModelUnavailableError, Task, TaskKind
from uboss.modules.audit import service as audit


def model_for(settings: Settings, kind: TaskKind) -> str:
    """Which model serves this kind of task.

    The one place the question is answered. A caller that wanted to pass a model name would be a
    caller that has to be edited when the model changes — which is what PLAN's forbidden
    shortcuts are about.
    """
    match kind:
        case TaskKind.COLUMN_MAPPING:
            return settings.ai_model_column_mapping
        case TaskKind.OBJECTIVE_PROPOSAL:
            return settings.ai_model_proposal


async def run(
    session: AsyncSession,
    settings: Settings,
    context: SecurityContext,
    task: Task,
) -> Completion:
    """Ask a model, record that it was asked, and return what it said.

    Raises `ModelUnavailableError` when there is no answer — including when no model is
    configured at all, which is a supported state. The caller falls back to what it can do
    without one and the interface says so; it must never present a deterministic result as a
    model's work, or the reverse.

    The refusal is recorded too. "We asked and got nothing" and "we never asked" are different
    facts, and only one of them is a reason to try again.
    """
    model = model_for(settings, task.kind)

    try:
        completion = await anthropic_adapter.complete(settings, task, model)
    except ModelUnavailableError as unavailable:
        await audit.record(
            session,
            tenant_id=context.tenant_id,
            action="ai.call.unavailable",
            resource_type="model_call",
            actor=context,
            detail={
                "task": task.kind.value,
                "model": model,
                #  The reason as the person will see it. No prompt content: it can carry
                #  personal data, and an audit trail is not the place to duplicate it.
                "reason": str(unavailable),
            },
        )
        raise

    await audit.record(
        session,
        tenant_id=context.tenant_id,
        action="ai.call.completed",
        resource_type="model_call",
        actor=context,
        detail={
            "task": task.kind.value,
            "model": completion.model,
            "input_tokens": completion.input_tokens,
            "output_tokens": completion.output_tokens,
            "latency_ms": completion.latency_ms,
        },
    )
    return completion
