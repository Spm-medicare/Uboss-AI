"""Seed an organisation's roles from the Gate 0 access-model draft.

    uv run python -m scripts.seed_roles --slug acme
    uv run python -m scripts.seed_roles --all

Roles are data (PLAN §17), so this is a data load rather than a migration. When the client
approves the role matrix — PLAN §25 first implementation deliverable #2 — the seed file
is replaced with the approved version and this command runs again. No schema change, no code
change, no redeploy.

Every role written here carries `is_draft = true`, because the source document says "Working
Draft — not approved" and the database should not claim otherwise.

Runs as the migration owner: it writes tenant-owned rows for a tenant it selects itself, which is
an operator action rather than a request.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from uboss.core.runtime import run as run_async
from uboss.db.base import build_sessionmaker, tenant_scope
from uboss.modules.identity.models import Role, RolePermission
from uboss.modules.tenancy.models import Tenant

SEED_FILE = Path(__file__).resolve().parent.parent / "seeds" / "access_model_draft.json"


def _owner_url() -> str:
    url = os.environ.get("UBOSS_MIGRATION_DATABASE_URL")
    if not url:
        raise SystemExit(
            "Set UBOSS_MIGRATION_DATABASE_URL to the owner connection. This script must not "
            "run as the application role."
        )
    return url


def load_seed() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    return data


async def seed_tenant(session: AsyncSession, tenant: Tenant, seed: dict[str, Any]) -> None:
    """Write the draft roles into one organisation.

    Idempotent: a role that already exists has its permissions replaced, so re-running after the
    matrix is approved updates in place rather than duplicating. A role the tenant added itself
    is left alone — this only touches keys the seed file names.

    The caller binds the tenant through `tenant_scope`, which also flushes on the way out —
    `roles` and `role_permissions` are forced under row-level security, which applies to this
    script exactly as it applies to the API.
    """
    written = 0
    for definition in seed["roles"]:
        key = definition["key"]
        role = (
            await session.execute(
                select(Role).where(Role.tenant_id == tenant.id, Role.key == key)
            )
        ).scalar_one_or_none()

        if role is None:
            role = Role(
                tenant_id=tenant.id,
                key=key,
                name=definition["name"],
                description=definition["description"],
                is_system=True,
                is_draft=True,
            )
            session.add(role)
            await session.flush()
        else:
            role.name = definition["name"]
            role.description = definition["description"]
            role.is_draft = True

        #  Replaced wholesale rather than merged. A permission removed from the approved matrix
        #  has to actually disappear; merging would leave it granted forever.
        existing = (
            await session.execute(
                select(RolePermission).where(RolePermission.role_id == role.id)
            )
        ).scalars().all()
        for row in existing:
            await session.delete(row)
        await session.flush()

        for action, mark in definition["permissions"].items():
            if mark not in ("A", "C"):
                continue
            session.add(
                RolePermission(
                    tenant_id=tenant.id,
                    role_id=role.id,
                    action=action,
                    #  `C` grants nothing on its own — the resource layer decides. Seeded as a
                    #  row rather than dropped, so the approved matrix is stored faithfully
                    #  instead of flattened into allow/deny.
                    is_conditional=(mark == "C"),
                )
            )
        written += 1

    print(f"  {tenant.slug}: {written} roles seeded")


async def main_async(slug: str | None, everything: bool) -> None:
    seed = load_seed()
    engine = create_async_engine(_owner_url())

    try:
        async with build_sessionmaker(engine)() as session:
            if everything:
                tenants = (await session.execute(select(Tenant))).scalars().all()
            else:
                tenant = (
                    await session.execute(select(Tenant).where(Tenant.slug == slug))
                ).scalar_one_or_none()
                if tenant is None:
                    raise SystemExit(f"No workspace with the slug '{slug}'.")
                tenants = [tenant]

            print(f"Seeding from {SEED_FILE.name} ({seed['_source']['status']})")
            for tenant in tenants:
                #  Bound and flushed per tenant. Staging rows for several tenants and letting
                #  them all insert at commit writes each under the last tenant bound.
                async with tenant_scope(session, tenant.id):
                    await seed_tenant(session, tenant, seed)
            await session.commit()

        unmapped = seed["_unmapped_rows"]["rows"]
        if unmapped:
            print()
            print("Not seeded — no matching action in PLAN §14:")
            for row in unmapped:
                print(f"  - {row}")
            print("  These are a Gate 0 question, not something to invent a name for.")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed roles from the access-model draft.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--slug", help="One workspace")
    group.add_argument("--all", action="store_true", help="Every workspace")
    args = parser.parse_args()

    run_async(main_async(args.slug, args.all))


if __name__ == "__main__":
    main()
