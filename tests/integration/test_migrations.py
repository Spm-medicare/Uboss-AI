"""The migrations are the schema, and this checks they still say so.

The test database in `conftest` is built by running every migration against an empty database, so
the whole suite already proves they apply. What is checked here is the two ways that can be true
and still be wrong:

* the models have drifted from the migrations, so `create_all` and `alembic upgrade` would build
  different databases;
* a migration claims to reverse and does not.
"""

from __future__ import annotations

import os
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from scripts.migration_preflight import reversible
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

BACKEND = Path(__file__).resolve().parents[2] / "backend"


def _scripts() -> ScriptDirectory:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    return ScriptDirectory.from_config(config)


async def test_the_database_is_at_head(owner_session: AsyncSession) -> None:
    """The fixture ran every migration. This confirms it got to the end."""
    applied = (
        await owner_session.execute(text("SELECT version_num FROM alembic_version"))
    ).scalar_one()
    assert applied == _scripts().get_current_head()


async def test_there_is_one_head() -> None:
    """Two heads means two people branched the history and nobody merged it.

    `alembic upgrade head` then fails, or worse, picks one.
    """
    heads = _scripts().get_heads()
    assert len(heads) == 1, f"the migration history has branched: {heads}"


async def test_the_models_have_not_drifted_from_the_migrations(
    owner_session: AsyncSession,
) -> None:
    """Every table and column the models declare exists in the migrated database.

    Autogenerate compares the models to the database; this compares them the other way, from a
    database built only by migrations. A model with a column no migration creates passes type
    checking and fails at the first query.

    Deliberately one-directional: a *database* column with no model is allowed. Migrations add
    things the ORM does not map — the `alembic_version` table, and columns a later step will
    use — and failing on those would make the check noise.
    """
    import uboss.modules.audit.models
    import uboss.modules.identity.models
    import uboss.modules.identity.policies
    import uboss.modules.tenancy.models  # noqa: F401
    from uboss.db.base import Base

    rows = (
        await owner_session.execute(
            text(
                """
                SELECT table_name, column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                """
            )
        )
    ).all()
    in_database: dict[str, set[str]] = {}
    for table_name, column_name in rows:
        in_database.setdefault(table_name, set()).add(column_name)

    missing: list[str] = []
    for table in Base.metadata.sorted_tables:
        if table.name not in in_database:
            missing.append(f"{table.name} (whole table)")
            continue
        for column in table.columns:
            if column.name not in in_database[table.name]:
                missing.append(f"{table.name}.{column.name}")

    assert missing == [], (
        "these are declared by a model but no migration creates them: " + ", ".join(missing)
    )


async def test_every_migration_is_honest_about_reversing() -> None:
    """A migration either reverses, or refuses and says why.

    The third state is the dangerous one: an empty `pass` that claims to reverse and does
    nothing. Someone runs `alembic downgrade`, it reports success, and the schema has not moved.
    """
    dishonest: list[str] = []
    for revision in _scripts().walk_revisions():
        path = Path(revision.path)
        can_reverse, why = reversible(path)
        if not can_reverse and "refuses on purpose" not in why:
            dishonest.append(f"{path.stem}: {why}")

    assert dishonest == [], (
        "these neither reverse nor refuse: " + "; ".join(dishonest)
    )


async def test_every_migration_explains_itself() -> None:
    """A docstring that says only what it does leaves the next person guessing whether it was
    safe. The runbook asks for why; this checks somebody wrote one."""
    thin: list[str] = []
    for revision in _scripts().walk_revisions():
        path = Path(revision.path)
        source = path.read_text(encoding="utf-8")
        start = source.find('"""')
        end = source.find('"""', start + 3)
        docstring = source[start + 3 : end] if start >= 0 and end > start else ""
        if len(docstring.split()) < 40:
            thin.append(path.stem)

    assert thin == [], (
        "these migrations have no real explanation in their docstring: " + ", ".join(thin)
    )


async def test_the_application_role_has_no_schema_privileges(
    owner_session: AsyncSession,
) -> None:
    """DECISIONS 2: row-level security is only a boundary if the API role cannot alter it.

    A role that can `ALTER TABLE` can drop a policy.
    """
    can_create = (
        await owner_session.execute(
            text("SELECT has_schema_privilege('uboss_app', 'public', 'CREATE')")
        )
    ).scalar_one()
    assert can_create is False, (
        "uboss_app can create objects in the public schema, so it can alter the boundary"
    )


async def test_the_environment_is_never_read_from_alembic_ini() -> None:
    """A checked-in connection string is a checked-in target.

    The one thing worse than a migration that fails is a migration that succeeds against the
    wrong database.
    """
    ini = (BACKEND / "alembic.ini").read_text(encoding="utf-8")
    assert "sqlalchemy.url" not in ini or "sqlalchemy.url =" not in ini
    assert "postgresql" not in ini.lower(), (
        "alembic.ini names a database; the URL must come from the environment"
    )


async def test_the_preflight_agrees_with_the_database(owner_session: AsyncSession) -> None:
    """The preflight is what gates a deploy, so it has to be right about the current revision.

    It once reported an empty database that was in fact at head, because `runtime.run` discarded
    its coroutine's return value — silently, with no error. This is that bug's regression test.
    """
    from scripts.migration_preflight import current_revision

    previous = os.environ.get("UBOSS_MIGRATION_DATABASE_URL")
    from tests.conftest import _owner_test_url

    os.environ["UBOSS_MIGRATION_DATABASE_URL"] = _owner_test_url()
    try:
        import asyncio

        reported = await asyncio.to_thread(
            lambda: __import__(
                "uboss.core.runtime", fromlist=["run"]
            ).run(current_revision())
        )
    finally:
        if previous is not None:
            os.environ["UBOSS_MIGRATION_DATABASE_URL"] = previous

    in_database = (
        await owner_session.execute(text("SELECT version_num FROM alembic_version"))
    ).scalar_one()
    assert reported == in_database, (
        f"preflight reported {reported!r} but the database is at {in_database!r}"
    )
