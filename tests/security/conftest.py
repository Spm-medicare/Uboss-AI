"""Fixtures shared by the Copilot's security tests.

The stub gateway lives here rather than in one test file that the other imports from. Two files
need it — grounding/injection and mutation preview — and a fixture reached for through another
module's namespace is the kind of coupling that breaks when somebody renames a test.
"""

from __future__ import annotations

from typing import Any

import pytest

from uboss.modules.ai_gateway.contract import Completion
from uboss.modules.copilot import service


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """Stand in for the gateway, and keep what it was asked.

    Patched at `service.ai.run` — the gateway's own front door — so the forced schema, the audit
    row the gateway writes, and every check above it are exercised exactly as in production.

    `calls` matters as much as the answer: the prompt is the artefact the injection tests read, and
    `model.answer["content"]` is how a test makes the model say something no real model would say
    on demand — such as complying fully with an injected instruction.
    """
    calls: list[Any] = []
    answer: dict[str, Any] = {"content": {}}

    async def fake_run(
        session: Any, settings: Any, context: Any, task: Any, **kwargs: Any
    ) -> Completion:
        calls.append(task)
        if "error" in answer:
            raise answer["error"]
        return Completion(
            content=answer["content"],
            model="claude-test",
            input_tokens=100,
            output_tokens=200,
            latency_ms=900,
        )

    monkeypatch.setattr(service.ai, "run", fake_run)
    return type("Model", (), {"calls": calls, "answer": answer})()
