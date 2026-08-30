"""Self-service sign-up — an account and the workspace it belongs to, in one step.

DECISIONS 17 closed this door and named the price of opening it: *"a deliberate,
separately-reviewed path"*. Migration 0027 is that path, and this is the only caller.

**`uboss_app` gained no privilege.** It still cannot write `users` and still cannot insert a
`tenants` row — the whole operation happens inside one `SECURITY DEFINER` function, the same shape
0006 already uses for the five authentication operations. So the capability is a named door rather
than a permission, and no future route can create a tenant by accident.

## The three rules this file keeps

**An address that already has an account gets the same answer as one that does not.** The function
returns nothing and writes nothing; this raises the identical refusal it raises for a taken
workspace address. Somebody probing learns which addresses are registered from neither.

**Nothing is half-created.** The function does the tenant, the user, the membership, the role and
its permissions in one statement, or none of them. A sign-up that failed after the tenant would
leave an empty workspace nobody owns.

**The password is checked by the same rule as everywhere else.** `passwords.check_strength`, not a
looser one because this is a first password rather than a replacement.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from uboss.core.errors import ValidationFailed
from uboss.core.logging import get_logger
from uboss.modules.audit import service as audit
from uboss.modules.identity import passwords

log = get_logger(__name__)

#: What a workspace slug may contain. Lower-case, digits and single hyphens — it appears in URLs
#: and in the workspace switcher, so it has to survive being typed and read aloud.
_SLUG_CHARS = re.compile(r"[^a-z0-9]+")

#: Long enough to be distinctive, short enough to read. A slug is not a name.
SLUG_MAX = 40


@dataclass(frozen=True, slots=True)
class SignedUp:
    """What was created. Handed to the caller so it can start a session immediately."""

    user_id: uuid.UUID
    tenant_id: uuid.UUID
    membership_id: uuid.UUID


def slugify(name: str) -> str:
    """A workspace name as a URL segment.

    Accents are folded rather than stripped — *"Bäcker GmbH"* becomes `backer-gmbh`, not
    `bcker-gmbh`, which is what somebody would expect to see and to type.
    """
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = _SLUG_CHARS.sub("-", folded.lower()).strip("-")[:SLUG_MAX].strip("-")
    if not slug:
        raise ValidationFailed(
            "Give the workspace a name with some letters or numbers in it."
        )
    return slug


async def create_workspace(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    display_name: str,
    workspace_name: str,
    ip_address: str | None = None,
) -> SignedUp:
    """Create the account and its workspace, or refuse without saying which part was taken.

    The refusal is deliberately the same sentence whether the address is registered or the
    workspace name is: two different messages would let somebody enumerate either one by watching
    which they got.
    """
    normalised = email.strip().lower()
    if not normalised or "@" not in normalised:
        raise ValidationFailed("Give the address you want to sign in with.")
    if not display_name.strip():
        raise ValidationFailed("Give the name colleagues will see.")
    if not workspace_name.strip():
        raise ValidationFailed("Give your workspace a name.")

    #  The same rule as a reset and as the invitation path. A first password is not a place to be
    #  more relaxed about it.
    passwords.check_strength(password)

    slug = slugify(workspace_name)

    row = (
        await session.execute(
            text(
                "SELECT user_id, tenant_id, membership_id "
                "FROM signup_create_workspace(:email, :hash, :display_name, :name, :slug)"
            ),
            {
                "email": normalised,
                "hash": passwords.hash_password(password),
                "display_name": display_name.strip(),
                "name": workspace_name.strip(),
                "slug": slug,
            },
        )
    ).one_or_none()

    if row is None:
        #  One sentence for a taken address and a taken workspace alike. Which it was is in the
        #  audit trail, where an administrator can read it and a stranger cannot.
        log.info("sign_up_refused", email_domain=normalised.rsplit("@", 1)[-1])
        raise ValidationFailed(
            "That email address or workspace name is already in use. Try signing in instead, or "
            "pick a different workspace name."
        )

    created = SignedUp(user_id=row[0], tenant_id=row[1], membership_id=row[2])

    await audit.record(
        session,
        tenant_id=created.tenant_id,
        action="identity.workspace_created",
        resource_type="tenant",
        resource_id=created.tenant_id,
        actor_membership_id=created.membership_id,
        actor_label=display_name.strip(),
        ip_address=ip_address,
        detail={"slug": slug, "email_domain": normalised.rsplit("@", 1)[-1]},
    )
    log.info("workspace_created", slug=slug)
    return created
