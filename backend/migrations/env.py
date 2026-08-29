"""Alembic environment.

Two decisions worth stating, because both have bitten this kind of system before:

* **The URL comes from the environment, never from `alembic.ini`.** A checked-in connection
  string is a checked-in target, and the one thing worse than a migration that fails is a
  migration that succeeds against the wrong database.
* **Migrations run as the owner role; the API runs as the application role.** Row-level security
  is only a boundary if the role that serves requests cannot turn it off. The owner creates the
  policies, the application lives under them.

Autogenerate compares against `Base.metadata`, so every module's models must be imported below
before a revision is generated — a model that is not imported looks like a table to drop.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from uboss.core.runtime import run as run_async
from uboss.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

#  Every module's models are imported here so that autogenerate sees the complete schema. The
#  list grows as modules are built; an omission would generate a DROP for a live table.
from uboss.modules.audit import models as audit_models  # noqa: F401, E402
from uboss.modules.files import models as files_models  # noqa: F401, E402
from uboss.modules.identity import models as identity_models  # noqa: F401, E402
from uboss.modules.identity import policies as identity_policies  # noqa: F401, E402
from uboss.modules.tenancy import models as tenancy_models  # noqa: F401, E402

target_metadata = Base.metadata


def _database_url() -> str:
    """The migration connection, from the environment.

    `UBOSS_MIGRATION_DATABASE_URL` is preferred so the owner role can be used for schema changes
    while the API keeps the restricted application role. If it is absent the ordinary URL is
    used, which is correct on a laptop where both are the same.
    """
    url = os.environ.get("UBOSS_MIGRATION_DATABASE_URL") or os.environ.get(
        "UBOSS_DATABASE_URL"
    )
    if not url:
        raise RuntimeError(
            "Set UBOSS_MIGRATION_DATABASE_URL (preferred) or UBOSS_DATABASE_URL before "
            "running a migration. Alembic will not guess a target database."
        )
    return url


def run_migrations_offline() -> None:
    """Emit SQL without connecting — for a reviewed, hand-applied change window."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # Both comparisons on: a silently diverged column type is how a migration history stops
        # describing the database it is supposed to describe.
        compare_type=True,
        compare_server_default=True,
        # One transaction for the whole upgrade, so a failure half-way leaves nothing applied.
        transaction_per_migration=False,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()
    engine = async_engine_from_config(
        section, prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


def _main() -> None:
    if context.is_offline_mode():
        run_migrations_offline()
        return

    #  Through `runtime.run` so this shares the API's event-loop choice. Windows offers one the
    #  database driver cannot use, and every entry point has to avoid it the same way.
    run_async(run_migrations_online())


_main()
