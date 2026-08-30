"""Self-service sign-up — the one path that brings a tenant into existence.

DECISIONS 17 closed this door and priced opening it at *"a deliberate, separately-reviewed
path"*. Migration 0027 is that path. What these tests actually check is that the price was paid:

* the boundary did not move — `uboss_app` still holds no privilege on `tenants` or `users`, and
  the only thing that changed is that one `SECURITY DEFINER` function now exists;
* the function is all-or-nothing, so there is no such thing as a workspace with no owner;
* a taken address and a taken workspace name are indistinguishable from outside, because two
  distinguishable refusals would turn this form into an address-enumeration oracle;
* the founder can actually run the workspace they just made, and cannot administer the
  deployment.

The last one is not a security check but a product one, and it is here because it is the failure
that would be discovered last: an account that signs in perfectly and can do nothing.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from uboss.core.errors import ValidationFailed
from uboss.modules.identity import credentials, signup

pytestmark = pytest.mark.anyio


def _address() -> str:
    return f"founder-{uuid.uuid4().hex[:10]}@example.test"


def _workspace() -> str:
    return f"Northwind {uuid.uuid4().hex[:8]}"


PASSWORD = "a-passphrase-long-enough-to-pass"


async def test_a_workspace_and_its_first_member_are_created_together(
    app_session: AsyncSession,
) -> None:
    """The whole point: one call, and the workspace has somebody in it."""
    email = _address()
    created = await signup.create_workspace(
        app_session,
        email=email,
        password=PASSWORD,
        display_name="Priya Raman",
        workspace_name=_workspace(),
    )

    assert created.tenant_id != uuid.UUID(int=0)
    assert created.user_id and created.membership_id

    #  Read back through the same narrow function the sign-in path uses. If this returns nothing,
    #  the account exists in a way nothing in the product can reach.
    account = await credentials.find_by_id(app_session, created.user_id)
    assert account is not None
    assert account.email == email
    assert account.is_active
    assert account.password_hash, "a sign-up with no stored hash could never sign in"


async def test_the_founder_holds_every_action_in_their_own_workspace(
    app_session: AsyncSession,
) -> None:
    """§14's whole vocabulary, `administer` included — see migration 0028.

    This test used to assert the opposite. `administer` was withheld on the reasoning that it
    governs the deployment; it does not, it governs a workspace, and withholding it left a
    founder staring at a read-only Hierarchy screen with no way to create the structure the rest
    of the product is scoped by. What keeps organisations apart is the database role and
    row-level security, and `test_the_application_role_still_cannot_create_a_tenant_itself`
    below is the check that actually proves it.
    """
    created = await signup.create_workspace(
        app_session,
        email=_address(),
        password=PASSWORD,
        display_name="Priya Raman",
        workspace_name=_workspace(),
    )

    await app_session.execute(
        text("SELECT set_config('app.tenant_id', :tenant, true)"),
        {"tenant": str(created.tenant_id)},
    )
    granted = {
        row[0]
        for row in (
            await app_session.execute(
                text(
                    "SELECT rp.action FROM role_permissions rp "
                    "JOIN membership_roles mr ON mr.role_id = rp.role_id "
                    "WHERE mr.membership_id = :membership"
                ),
                {"membership": str(created.membership_id)},
            )
        ).all()
    }

    #  Every verb, named one at a time rather than compared to a set imported from the enum: a
    #  test that reads the same constant the code reads passes when both are wrong together.
    for action in (
        "view", "comment", "edit_draft", "publish", "run", "approve", "assign",
        "schedule", "manage_access", "export", "integrate", "administer", "audit",
    ):
        assert action in granted, f"a founder who cannot {action} cannot set the workspace up"


async def test_a_taken_address_and_a_taken_workspace_refuse_identically(
    app_session: AsyncSession,
) -> None:
    """The refusal must not say which half was taken.

    Two different messages would let anybody with this form ask "is this address registered?" and
    read the answer off the screen. The audit trail records which it was; the caller does not.
    """
    email = _address()
    workspace = _workspace()
    await signup.create_workspace(
        app_session,
        email=email,
        password=PASSWORD,
        display_name="First",
        workspace_name=workspace,
    )

    with pytest.raises(ValidationFailed) as taken_address:
        await signup.create_workspace(
            app_session,
            email=email,
            password=PASSWORD,
            display_name="Second",
            workspace_name=_workspace(),
        )

    with pytest.raises(ValidationFailed) as taken_workspace:
        await signup.create_workspace(
            app_session,
            email=_address(),
            password=PASSWORD,
            display_name="Third",
            workspace_name=workspace,
        )

    assert str(taken_address.value) == str(taken_workspace.value)


async def test_nothing_is_created_when_the_sign_up_is_refused(
    app_session: AsyncSession,
) -> None:
    """All or nothing.

    A refusal that had already inserted the tenant would leave an empty workspace nobody owns
    and nobody can reach — invisible, because the caller was told it failed.
    """
    workspace = _workspace()
    await signup.create_workspace(
        app_session,
        email=_address(),
        password=PASSWORD,
        display_name="First",
        workspace_name=workspace,
    )
    before = (
        await app_session.execute(text("SELECT count(*) FROM tenants"))
    ).scalar_one()

    with pytest.raises(ValidationFailed):
        await signup.create_workspace(
            app_session,
            email=_address(),
            password=PASSWORD,
            display_name="Second",
            workspace_name=workspace,
        )

    after = (await app_session.execute(text("SELECT count(*) FROM tenants"))).scalar_one()
    assert after == before


async def test_a_weak_password_is_refused_before_anything_is_written(
    app_session: AsyncSession,
) -> None:
    """A first password is checked by the same rule as a replacement.

    Checked *before* the function is called, so a refused sign-up costs one round trip and
    creates nothing — and so the strength rule cannot be skipped by a caller that forgets it.
    """
    before = (await app_session.execute(text("SELECT count(*) FROM tenants"))).scalar_one()

    with pytest.raises(ValidationFailed):
        await signup.create_workspace(
            app_session,
            email=_address(),
            password="short",
            display_name="Priya Raman",
            workspace_name=_workspace(),
        )

    after = (await app_session.execute(text("SELECT count(*) FROM tenants"))).scalar_one()
    assert after == before


async def test_the_application_role_still_cannot_create_a_tenant_itself(
    app_session: AsyncSession,
) -> None:
    """**The boundary did not move.**

    This is the test that makes the whole design worth having. Sign-up works, and `uboss_app`
    still cannot insert a `tenants` row — so the capability is one named door rather than a
    privilege a future route could reach by accident.
    """
    with pytest.raises(ProgrammingError) as refused:
        await app_session.execute(
            text("INSERT INTO tenants (slug, name, status) VALUES ('smuggled', 'X', 'active')")
        )
    #  Either refusal is the right one and both are `InsufficientPrivilege`: the row-level policy
    #  bites first here, and a table grant would bite if the policy were ever relaxed. Asserting
    #  the specific sentence would make this test fail on a *tightening* of the boundary, which
    #  is exactly backwards.
    assert "insufficientprivilege" in str(refused.value).lower()
    await app_session.rollback()


async def test_the_slug_is_derived_and_survives_being_typed() -> None:
    """A workspace name becomes a URL segment nobody had to invent.

    Accents are folded rather than dropped: *"Bäcker GmbH"* is `backer-gmbh`, which is what
    somebody would expect to see and to type. Dropping them gives `bcker-gmbh`, which is what a
    naive `encode("ascii", "ignore")` on the un-normalised string produces.
    """
    assert signup.slugify("Acme Operations") == "acme-operations"
    assert signup.slugify("Bäcker GmbH") == "backer-gmbh"
    assert signup.slugify("  Spaces   &&&  Symbols  ") == "spaces-symbols"
    assert len(signup.slugify("x" * 200)) <= signup.SLUG_MAX

    with pytest.raises(ValidationFailed):
        #  A name with nothing sluggable in it has to be refused here rather than producing an
        #  empty slug that collides with the next one.
        signup.slugify("!!! ???")
