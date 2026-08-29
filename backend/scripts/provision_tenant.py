"""Create an organisation and its first administrator.

An operator command, not an API. It connects as `uboss_owner` because creating a tenant is the
one thing the API role deliberately cannot do — `tenants` has no INSERT policy for it, so no
request, however privileged, can bring an organisation into existence.

    cd backend
    uv run python -m scripts.provision_tenant --slug acme --name "Acme" --email you@acme.com

The password is asked for interactively. Passing it as an argument would put it in the shell
history and in the process list, where every other user on the machine can read it.
"""

from __future__ import annotations

import argparse
import getpass
import os
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine

from scripts.seed_roles import load_seed, seed_tenant
from uboss.core.runtime import run as run_async
from uboss.db.base import build_sessionmaker
from uboss.modules.identity import passwords
from uboss.modules.identity.models import (
    Membership,
    MembershipRole,
    MembershipStatus,
    Role,
    User,
)
from uboss.modules.tenancy.models import Tenant

#: The key of the role given to the first person in an organisation. It has to be one the seed
#: file defines, and it is looked up in `roles` rather than written as a string — role names are
#: data now (PLAN §17), not constants.
#:
#: Everyone after them is invited with whatever roles the administrator chooses. This is the only
#: account the system creates on its own, and it exists so somebody can let the others in.
FIRST_ADMIN_ROLE_KEY = "admin"


def _owner_url() -> str:
    url = os.environ.get("UBOSS_MIGRATION_DATABASE_URL")
    if not url:
        raise SystemExit(
            "Set UBOSS_MIGRATION_DATABASE_URL to the owner connection. This script must not "
            "run as the application role."
        )
    return url


async def provision(slug: str, name: str, email: str, display_name: str, password: str) -> None:
    engine = create_async_engine(_owner_url())
    factory = build_sessionmaker(engine)

    try:
        async with factory() as session:
            existing = (
                await session.execute(select(Tenant).where(Tenant.slug == slug))
            ).scalar_one_or_none()
            if existing is not None:
                raise SystemExit(f"A workspace with the slug '{slug}' already exists.")

            tenant = Tenant(slug=slug, name=name, status="active")
            session.add(tenant)
            await session.flush()

            #  The tenant has to be bound before anything tenant-owned is written: row-level
            #  security is forced on `memberships`, and it applies to this script exactly as it
            #  applies to the API.
            await session.execute(
                text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                {"tenant_id": str(tenant.id)},
            )

            email = email.strip().lower()
            user = (
                await session.execute(select(User).where(User.email == email))
            ).scalar_one_or_none()

            if user is None:
                user = User(
                    email=email,
                    password_hash=passwords.hash_password(password),
                    status="active",
                )
                session.add(user)
                await session.flush()
                created_account = True
            else:
                #  The address already has an account — the same person joining a second
                #  organisation. Their existing password stands; this script does not change it,
                #  because a provisioning command that can reset an existing password is a
                #  provisioning command that can take over an existing account.
                created_account = False

            membership = Membership(
                tenant_id=tenant.id,
                user_id=user.id,
                display_name=display_name,
                status=MembershipStatus.ACTIVE,
            )
            session.add(membership)
            await session.flush()

            #  Roles are seeded from the Gate 0 access-model draft before anyone is given one,
            #  so the first administrator's role is a row that already exists rather than a
            #  string this script decides on.
            await seed_tenant(session, tenant, load_seed())
            await session.flush()

            admin_role = (
                await session.execute(
                    select(Role).where(
                        Role.tenant_id == tenant.id, Role.key == FIRST_ADMIN_ROLE_KEY
                    )
                )
            ).scalar_one_or_none()
            if admin_role is None:
                raise SystemExit(
                    f"The seed file defines no role with the key '{FIRST_ADMIN_ROLE_KEY}', so "
                    "this organisation would have no administrator. Nothing was created."
                )

            session.add(
                MembershipRole(
                    tenant_id=tenant.id,
                    membership_id=membership.id,
                    role_id=admin_role.id,
                )
            )

            await session.commit()

        print(f"Workspace '{name}' created with the slug '{slug}'.")
        print("Roles seeded from the Gate 0 access-model draft (not approved).")
        print(f"Administrator: {display_name} <{email}>")
        if not created_account:
            print(
                "That address already had an account, so its existing password still applies."
            )
        print(f"Sign in at the workspace '{slug}'. ({datetime.now(UTC).isoformat()})")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an organisation and its first admin.")
    parser.add_argument("--slug", required=True, help="URL name, e.g. acme")
    parser.add_argument("--name", required=True, help="Display name, e.g. Acme Manufacturing")
    parser.add_argument("--email", required=True, help="The administrator's email address")
    parser.add_argument(
        "--display-name", help="Their name as this organisation knows them"
    )
    args = parser.parse_args()

    display_name = args.display_name or args.email.split("@")[0]

    #  An environment variable is accepted so the command can run unattended in a provisioning
    #  pipeline. Interactive use goes through getpass, which does not echo and does not reach
    #  the shell history.
    password = os.environ.get("UBOSS_PROVISION_PASSWORD")
    if not password:
        password = getpass.getpass("Password for the administrator: ")
        if password != getpass.getpass("Repeat it: "):
            raise SystemExit("The two passwords did not match. Nothing was created.")

    passwords.check_strength(password)

    run_async(provision(args.slug, args.name, args.email, display_name, password))


if __name__ == "__main__":
    main()
