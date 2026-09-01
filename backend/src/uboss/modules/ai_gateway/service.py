"""The gateway's front door.

Domain code calls `run()` with a `Task` and gets a `Completion`. It never chooses a model, never
sees an API key, and never learns which provider answered.

Every call writes an audit event — before the answer is used, in the caller's transaction. PLAN
§19 requires tenant isolation to extend to AI context, and PLAN §16 requires responsible-AI
evidence; a model call with no record is a decision nobody can account for later.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from uboss.core.context import SecurityContext
from uboss.core.settings import Settings
from uboss.modules.ai_gateway import anthropic_adapter, openai_adapter
from uboss.modules.ai_gateway.contract import Completion, ModelUnavailableError, Task, TaskKind
from uboss.modules.audit import service as audit
from uboss.modules.runtime.models import ModelCall


def model_for(settings: Settings, kind: TaskKind) -> str:
    """Which model serves this kind of task, on whichever provider is configured.

    The one place the question is answered. A caller that wanted to pass a model name would be a
    caller that has to be edited when the model changes — which is what PLAN's forbidden
    shortcuts are about, and the reason the provider swap below is a `match` here rather than a
    branch at each call site.
    """
    if settings.resolved_ai_provider == "openai":
        match kind:
            case TaskKind.COLUMN_MAPPING:
                return settings.openai_model_column_mapping
            case TaskKind.OBJECTIVE_PROPOSAL:
                return settings.openai_model_proposal
            case TaskKind.COPILOT_ANSWER:
                return settings.openai_model_copilot
    match kind:
        case TaskKind.COLUMN_MAPPING:
            return settings.ai_model_column_mapping
        case TaskKind.OBJECTIVE_PROPOSAL:
            return settings.ai_model_proposal
        case TaskKind.COPILOT_ANSWER:
            return settings.ai_model_copilot


async def run(
    session: AsyncSession,
    settings: Settings,
    context: SecurityContext,
    task: Task,
    *,
    run_id: uuid.UUID | None = None,
    run_step_id: uuid.UUID | None = None,
) -> Completion:
    """Ask a model, record that it was asked, and return what it said.

    `run_id` and `run_step_id` attribute the call to the work that made it. Both default to none
    and both are none for every caller today — the hierarchy importer and the objective analysis
    are the only two, and neither happens inside a run. They are here for the runtime steps that
    will use a model, so the cost of a run is answerable the day one does.

    Raises `ModelUnavailableError` when there is no answer — including when no model is
    configured at all, which is a supported state. The caller falls back to what it can do
    without one and the interface says so; it must never present a deterministic result as a
    model's work, or the reverse.

    The refusal is recorded too. "We asked and got nothing" and "we never asked" are different
    facts, and only one of them is a reason to try again.
    """
    model = model_for(settings, task.kind)

    #  The one line that chooses a provider. Everything above and below speaks `Task` and
    #  `Completion` and cannot tell which one answered — which is the property the gateway
    #  exists to have, and was untested while there was only one adapter.
    provider = settings.resolved_ai_provider
    complete = openai_adapter.complete if provider == "openai" else anthropic_adapter.complete

    try:
        completion = await complete(settings, task, model)
    except ModelUnavailableError as unavailable:
        session.add(
            ModelCall(
                tenant_id=context.tenant_id,
                run_id=run_id,
                run_step_id=run_step_id,
                task_kind=task.kind.value,
                provider=provider,
                model=model,
                outcome="unavailable",
                #  Why, in the words the caller will show. A refusal with no reason is a row that
                #  says a call failed and gives nobody anything to do about it.
                detail=str(unavailable),
                actor_membership_id=context.membership_id,
            )
        )
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

    session.add(
        ModelCall(
            tenant_id=context.tenant_id,
            run_id=run_id,
            run_step_id=run_step_id,
            task_kind=task.kind.value,
            provider=provider,
            #  What answered, not what was asked for. A provider can return a dated variant of the
            #  model requested, and the evidence should say which one actually ran.
            model=completion.model,
            outcome="completed",
            input_tokens=completion.input_tokens,
            output_tokens=completion.output_tokens,
            latency_ms=completion.latency_ms,
            actor_membership_id=context.membership_id,
        )
    )
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
