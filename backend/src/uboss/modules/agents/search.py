"""Searching the registry — the half of §39 that discovers rather than decides.

    Agent requirement → Search Skill Registry → Deterministic compatibility gates

The split is the point. This module ranks by resemblance and is allowed to be wrong; `gates.py`
decides and is not. Nothing here filters on a rule a gate is responsible for, because a candidate
silently dropped here is a candidate nobody can be told about — and *"why was this skill not
used"* is the question the registry exists to answer.

**Postgres does the ranking, not a model.** Migration 0019 stores a generated `tsvector` on every
skill, weighted name → purpose → trigger → primary IF, with a GIN index over it. A hosted
embedding call for a search that runs inside the Builder would put a network round trip and a
provider between a person and a list, and would make the same query return different results on
different days. Full-text search here is repeatable, and a decision recorded today can be
re-derived tomorrow.

**Inactive skills are returned, not hidden.** `docs/product/SKILL_REGISTRY.md` says to search
*"allowed active"* skills, and that requirement is met — by the lifecycle gate, which refuses them
and is not configurable, so an inactive skill can never be selected. Enforcing it by *omission*
instead would be weaker in the way that matters: "no skill does this" and "one does, and it was
retired in March" are different answers, and only one of them is true. The resolver asks for both
and the decision record shows which it found.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from uboss.modules.agents.gates import ANY_INDUSTRY, Candidate
from uboss.modules.agents.models import Skill, SkillArchetype, SkillExactnessGate

#: How many candidates a search returns. Enough that a real alternative is visible, few enough
#: that a person reads the list rather than scrolling past it.
DEFAULT_LIMIT = 20

#: The ceiling a caller may ask for. Past this the answer is a better requirement, not more rows.
MAX_LIMIT = 100

#: The dictionary the generated column was built with. Searching with a different one would match
#: against stems the index does not hold.
DICTIONARY = "english"

#: The characters that mean the caller used the search syntax deliberately: a quoted phrase, an
#: excluded word, or an explicit OR. When any of them is present the string is passed through
#: untouched — somebody who typed an operator meant it.
_OPERATORS = ('"', "-")


@dataclass(frozen=True, slots=True)
class Hit:
    """One search result: the skill, where it ranked, and how well the text matched.

    `text_match` is Postgres's `ts_rank_cd` value, reported as it comes. It is deliberately not
    turned into a percentage — a number like "87% confident" would be an invention, and the
    frontend rule against displaying a value the backend did not return exists because that is
    exactly what the previous build did.
    """

    skill: Skill
    rank: int
    text_match: float

    def as_candidate(self) -> Candidate:
        """The gates' view of this skill — only the columns a refusal may depend on."""
        return Candidate(
            skill_id=str(self.skill.id),
            name=self.skill.name,
            tenant_id=str(self.skill.tenant_id) if self.skill.tenant_id else None,
            catalogue_id=self.skill.catalogue_id,
            status=self.skill.status,
            autonomy=self.skill.autonomy,
            layer=self.skill.layer,
            department=self.skill.department,
            industry=self.skill.industry,
            archetype_id=self.skill.archetype_id,
            purpose=self.skill.purpose,
            minimum_inputs=self.skill.minimum_inputs,
            exclusions=self.skill.exclusions,
            source_ids=self.skill.source_ids,
            approved_by_membership_id=(
                str(self.skill.approved_by_membership_id)
                if self.skill.approved_by_membership_id
                else None
            ),
            approved_at=(
                self.skill.approved_at.isoformat() if self.skill.approved_at else None
            ),
        )


def _filtered(
    statement: Select[tuple[Skill]] | Select[tuple[Skill, float]],
    *,
    layer: str | None,
    department: str | None,
    industry: str | None,
    archetype_id: str | None,
) -> Select[tuple[Skill]] | Select[tuple[Skill, float]]:
    """Structured narrowing only — never a rule a gate owns.

    An industry filter keeps `All Industries` alongside the named one, because the catalogue uses
    that value as a wildcard and dropping it would hide the 208 Universal Department skills from
    every industry-scoped search.
    """
    if layer:
        statement = statement.where(Skill.layer == layer)
    if department:
        statement = statement.where(Skill.department == department)
    if industry:
        statement = statement.where(
            or_(Skill.industry == industry, Skill.industry == ANY_INDUSTRY)
        )
    if archetype_id:
        statement = statement.where(Skill.archetype_id == archetype_id)
    return statement


def _recall_query(words: str) -> str:
    """A plain sentence, widened to match any of its words rather than all of them.

    `websearch_to_tsquery` ANDs bare terms, which is right for a web search and wrong here. A
    requirement is usually a sentence — *"vendor statement reconciliation and payment run
    preparation"* — and no single skill contains every word of it, so an AND search returns nothing
    and the Compose route becomes unreachable. Recall is what this step owes the resolver: the
    gates refuse what does not belong, and `ts_rank_cd` puts the denser matches first, so a wide
    net costs ordering rather than correctness.

    A caller who typed an operator — a quoted phrase, `-word`, an explicit `or` — meant it, and
    their string is passed through exactly as written.
    """
    lowered = words.lower()
    if any(token in words for token in _OPERATORS) or " or " in lowered:
        return words
    terms = words.split()
    return " or ".join(terms) if len(terms) > 1 else words


async def search(
    session: AsyncSession,
    *,
    need: str = "",
    layer: str | None = None,
    department: str | None = None,
    industry: str | None = None,
    archetype_id: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> list[Hit]:
    """Rank the registry against a requirement.

    Row-level security decides what is visible: the 400 shared catalogue rows plus this
    workspace's own skills, and nothing belonging to anybody else. That boundary is not repeated
    here — a second copy of a security rule is a copy that eventually disagrees with the first.

    With no `need`, this is a browse: the structured filters alone, ordered by name. A caller who
    supplied only a department wants the department's skills, not an empty list.
    """
    limit = max(1, min(limit, MAX_LIMIT))
    words = need.strip()

    if not words:
        browse = _filtered(
            select(Skill),
            layer=layer,
            department=department,
            industry=industry,
            archetype_id=archetype_id,
        ).order_by(Skill.name)
        rows = (await session.execute(browse.limit(limit))).scalars().all()
        return [Hit(skill=skill, rank=n, text_match=0.0) for n, skill in enumerate(rows, start=1)]

    query = func.websearch_to_tsquery(DICTIONARY, _recall_query(words))
    vector: ColumnElement[Any] = literal_column("skills.search")
    ranked = func.ts_rank_cd(vector, query).label("text_match")

    statement = _filtered(
        select(Skill, ranked).where(vector.op("@@")(query)),
        layer=layer,
        department=department,
        industry=industry,
        archetype_id=archetype_id,
    ).order_by(ranked.desc(), Skill.name)

    rows = (await session.execute(statement.limit(limit))).all()
    return [
        Hit(skill=row[0], rank=n, text_match=float(row[1]))
        for n, row in enumerate(rows, start=1)
    ]


async def gate_wording(session: AsyncSession) -> dict[str, str]:
    """Each exactness gate's `failure_state`, in the catalogue's own words.

    Read every time rather than cached at import: the twelve are seed data a client corrects, and
    a message cached at process start would keep quoting last week's wording until a restart.
    Twelve rows from a primary-key-ordered table is not the cost worth optimising here.
    """
    rows = (
        await session.execute(select(SkillExactnessGate.id, SkillExactnessGate.failure_state))
    ).all()
    return {gate_id: failure_state for gate_id, failure_state in rows}


async def by_id(session: AsyncSession, skill_id: uuid.UUID) -> Skill | None:
    """One skill, if this workspace may see it. Row-level security answers the second half."""
    return (
        await session.execute(select(Skill).where(Skill.id == skill_id))
    ).scalar_one_or_none()


async def registry_lists(session: AsyncSession) -> tuple[
    list[str], list[str], list[str], list[tuple[str, str]]
]:
    """The catalogue's own vocabulary — the distinct values actually present in it.

    Read from the rows rather than kept as a constant, so a filter can never offer a value that
    matches nothing and a corrected seed corrects the filters with it.
    """
    layers = list(
        (await session.execute(select(Skill.layer).distinct().order_by(Skill.layer)))
        .scalars()
        .all()
    )
    departments = [
        value
        for value in (
            await session.execute(
                select(Skill.department)
                .where(Skill.department.is_not(None))
                .distinct()
                .order_by(Skill.department)
            )
        )
        .scalars()
        .all()
        if value is not None
    ]
    industries = [
        value
        for value in (
            await session.execute(
                select(Skill.industry)
                .where(Skill.industry.is_not(None))
                .distinct()
                .order_by(Skill.industry)
            )
        )
        .scalars()
        .all()
        if value is not None
    ]
    archetypes = [
        (str(row[0]), str(row[1]))
        for row in (
            await session.execute(
                select(SkillArchetype.id, SkillArchetype.name).order_by(SkillArchetype.position)
            )
        ).all()
    ]
    return layers, departments, industries, archetypes
