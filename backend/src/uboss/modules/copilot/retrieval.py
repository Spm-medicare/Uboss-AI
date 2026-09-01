"""What the Copilot is allowed to read, and how it proves it.

§12 asks for *"permission-filtered retrieval"* and *"source references"*, and §19 requires tenant
isolation to extend to AI context. Those two sentences describe the whole of this file.

## Stricter than a list endpoint, on purpose

`list_objectives` and its siblings gate on tenant-wide `view` and return every unarchived row.
That is a defensible choice for a list — `policies.py` says why: *"it is the resource layer's job to
narrow when it is configured"*, and the resource layer narrows at the point somebody opens an
object.

Retrieval cannot rely on that. A name in a list is a name; a snippet in a model prompt has left the
building. So every candidate here is checked **the way the detail route checks it** — through
`grant_for_resource` and the same `explain` the guard uses — and anything that check would refuse
never reaches the prompt. The result is that the Copilot can only ever quote something the asker
could have opened themselves.

## Quietly

The check is the guard's decision function, not the guard. `authorise` writes an audit row for every
refusal, which is right for a request and wrong for a search: one question touching two hundred
objects would write two hundred denial rows and bury the one that matters. What is audited is the
question and the sources it used — in `service.py` — not each row the filter declined.

## Two boundaries, not one

Every query names `tenant_id` **and** runs under row-level security. `CLAUDE.md`: *"Backend
authorization and PostgreSQL RLS are two independent tenant boundaries. Neither substitutes for the
other."*

The first version of this file had only the second, and the cross-tenant test caught it — on the
owner connection, where RLS does not apply unless a table is `FORCE`d, another workspace's objective
came straight back. In production the app role would have been narrowed by the policy and nothing
would have leaked, which is exactly what makes a single boundary dangerous: it works until the day
something runs as a role you did not expect.

## The snippet is data, never instruction

A `Source` carries `text` and nothing that looks like a command. The prompt-side rule — that
retrieved company data is fenced and labelled as untrusted — lives with the prompt in `service.py`,
because that is where it can be got wrong. What this file guarantees is narrower and necessary: the
text belongs to the person asking.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement, Select, func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from uboss.core.context import SecurityContext
from uboss.core.permissions import Action
from uboss.modules.agents.agent_models import Agent
from uboss.modules.agents.search import DICTIONARY, widen_to_any_word
from uboss.modules.hierarchy.models import OrgUnit, Position
from uboss.modules.identity import policies
from uboss.modules.jobs.models import Job
from uboss.modules.objectives.models import Objective
from uboss.modules.supervisors.models import Supervisor

#: How many candidates each kind may contribute before the filter runs. Bounded so one broad word
#: cannot turn a question into a table scan; the filter then narrows further.
PER_KIND = 8

#: How many sources reach the prompt. Small on purpose: a prompt stuffed with forty half-relevant
#: objects produces an answer that cites everything and grounds nothing.
MAX_SOURCES = 12


@dataclass(frozen=True, slots=True)
class Source:
    """One thing the Copilot read, and where the reader can go to check it.

    Every claim the Copilot makes has to be traceable to one of these. `UI_SPEC.md` §18: *"Shows
    sources/object references when using company data."*
    """

    #: The resource type as the guard names it — the same string `grant_for_resource` takes, so a
    #: source and a permission check can never disagree about what kind of thing this is.
    kind: str
    id: uuid.UUID
    label: str
    #: The words themselves, for grounding. Data, never instruction.
    text: str
    #: Where a person goes to read it in full. Built from the route, not stored.
    href: str


def _matches[RowsT: tuple[Any, ...]](
    statement: Select[RowsT],
    table: str,
    named: Sequence[InstrumentedAttribute[str | None] | InstrumentedAttribute[str]],
    words: str,
) -> Select[RowsT]:
    """Rank a question against one table, two ways in.

    **Full text, widened and ranked.** The first version of this matched the whole question as one
    `ILIKE '%…%'`, which finds an object only when somebody types its words verbatim: *"quotation
    turnaround"* worked and *"why is the quotation turnaround slow?"* found nothing at all. A test
    that asked the second kind of question is what caught it, which is the right way round — a
    Copilot whose retrieval only answers keyword searches is a Copilot that cannot be asked
    anything.

    So the question is widened to *any* of its words — `widen_to_any_word`, the same rule the skill
    resolver uses and now shared rather than copied — and the order comes from `ts_rank_cd`, which
    is Postgres computing relevance. That matters more than it looks: a wide net is only useful if
    the densest matches come first, and the alternative is a relevance number this product would be
    inventing from match counts. Migration 0042 carries the generated `tsvector` and its GIN index.

    **And a plain contains-match on the name.** Stemming does not do prefixes: somebody typing
    `quo` into the top bar means *quotation*, and `websearch_to_tsquery('quo')` matches nothing.
    `named` is the title-or-name column for that, so search-as-you-type behaves like a search box.
    Rows found only this way rank zero and sort last, which is honest — they matched a substring,
    not a word.
    """
    query = func.websearch_to_tsquery(DICTIONARY, widen_to_any_word(words))
    vector: ColumnElement[Any] = literal_column(f"{table}.search")
    needle = f"%{words.strip()}%"
    return statement.where(
        or_(vector.op("@@")(query), *[column.ilike(needle) for column in named])
    ).order_by(func.ts_rank_cd(vector, query).desc())


async def _allowed(
    session: AsyncSession, context: SecurityContext, kind: str, resource_id: uuid.UUID
) -> bool:
    """Whether this person could open this object — the detail route's own question.

    `context.explain` rather than `guard.authorise`: the same decision, without the audit row. See
    the note at the top of this file about two hundred denials.
    """
    grant = await policies.grant_for_resource(
        session,
        tenant_id=context.tenant_id,
        membership_id=context.membership_id,
        resource_type=kind,
        resource_id=resource_id,
        role_actions=context.granted_actions,
    )
    return context.explain(Action.VIEW, grant).allowed


def _snippet(*parts: str | None) -> str:
    """The fields worth quoting, joined, trimmed.

    Trimmed rather than summarised: a summary is a claim, and a source has to be quotable.
    """
    text = " · ".join(part.strip() for part in parts if part and part.strip())
    return text[:600]


async def search(
    session: AsyncSession, context: SecurityContext, words: str, *, limit: int = MAX_SOURCES
) -> list[Source]:
    """Everything matching, that this person may read.

    Returns an empty list for an empty query rather than everything — a search box that answers a
    blank question with the whole workspace is a search box that has misunderstood what was asked.
    """
    if not words.strip():
        return []

    found: list[Source] = []

    # ── objectives ───────────────────────────────────────────────────────────────────────
    for objective in (
        (
            await session.execute(
                _matches(
                    select(Objective).where(
                        Objective.tenant_id == context.tenant_id,
                        Objective.archived_at.is_(None),
                    ),
                    "objectives",
                    [Objective.title],
                    words,
                )
                .order_by(Objective.updated_at.desc())
                .limit(PER_KIND)
            )
        )
        .scalars()
        .all()
    ):
        if await _allowed(session, context, "objective", objective.id):
            found.append(
                Source(
                    kind="objective",
                    id=objective.id,
                    label=objective.title,
                    text=_snippet(objective.expected_result, objective.description),
                    href=f"/objective-builder/{objective.id}",
                )
            )

    # ── jobs ─────────────────────────────────────────────────────────────────────────────
    for job in (
        (
            await session.execute(
                _matches(
                    select(Job).where(
                        Job.tenant_id == context.tenant_id,
                        Job.archived_at.is_(None),
                    ),
                    "jobs",
                    [Job.name],
                    words,
                )
                .order_by(Job.updated_at.desc())
                .limit(PER_KIND)
            )
        )
        .scalars()
        .all()
    ):
        if await _allowed(session, context, "job", job.id):
            found.append(
                Source(
                    kind="job",
                    id=job.id,
                    label=job.name,
                    text=_snippet(job.purpose, job.high_level_work),
                    href=f"/job-builder/{job.id}",
                )
            )

    # ── agents ───────────────────────────────────────────────────────────────────────────
    for agent in (
        (
            await session.execute(
                _matches(
                    select(Agent).where(
                        Agent.tenant_id == context.tenant_id,
                        Agent.archived_at.is_(None),
                    ),
                    "agents",
                    [Agent.name],
                    words,
                )
                .order_by(Agent.updated_at.desc())
                .limit(PER_KIND)
            )
        )
        .scalars()
        .all()
    ):
        if await _allowed(session, context, "agent", agent.id):
            found.append(
                Source(
                    kind="agent",
                    id=agent.id,
                    label=agent.name,
                    text=_snippet(agent.purpose),
                    href=f"/agent-builder/{agent.id}",
                )
            )

    # ── supervisors ──────────────────────────────────────────────────────────────────────
    for supervisor in (
        (
            await session.execute(
                _matches(
                    select(Supervisor).where(
                        Supervisor.tenant_id == context.tenant_id,
                        Supervisor.archived_at.is_(None),
                    ),
                    "supervisors",
                    [Supervisor.name],
                    words,
                )
                .order_by(Supervisor.updated_at.desc())
                .limit(PER_KIND)
            )
        )
        .scalars()
        .all()
    ):
        if await _allowed(session, context, "supervisor", supervisor.id):
            found.append(
                Source(
                    kind="supervisor",
                    id=supervisor.id,
                    label=supervisor.name,
                    text=_snippet(supervisor.purpose),
                    href=f"/supervisor/{supervisor.id}",
                )
            )

    # ── the organisation ─────────────────────────────────────────────────────────────────
    #
    #  Departments and seats, because *"who does X report to"* is among the first things anybody
    #  asks. The hierarchy has no resource grants of its own — it is the structure everybody in the
    #  workspace works inside — so tenant-wide `view` is the whole answer here, and the check is
    #  run anyway rather than skipped, so a grant added later narrows this without an edit.
    for unit in (
        (
            await session.execute(
                _matches(
                    select(OrgUnit).where(
                        OrgUnit.tenant_id == context.tenant_id,
                        OrgUnit.archived_at.is_(None),
                    ),
                    "org_units",
                    [OrgUnit.name],
                    words,
                ).limit(PER_KIND)
            )
        )
        .scalars()
        .all()
    ):
        if await _allowed(session, context, "org_unit", unit.id):
            found.append(
                Source(
                    kind="org_unit",
                    id=unit.id,
                    label=unit.name,
                    text=_snippet(unit.location),
                    href="/hierarchy",
                )
            )

    for seat in (
        (
            await session.execute(
                _matches(
                    select(Position).where(
                        Position.tenant_id == context.tenant_id,
                        Position.archived_at.is_(None),
                    ),
                    "positions",
                    [Position.title, Position.designation],
                    words,
                ).limit(PER_KIND)
            )
        )
        .scalars()
        .all()
    ):
        if await _allowed(session, context, "position", seat.id):
            found.append(
                Source(
                    kind="position",
                    id=seat.id,
                    label=seat.title,
                    text=_snippet(seat.designation, seat.location),
                    href="/hierarchy",
                )
            )

    return found[:limit]
