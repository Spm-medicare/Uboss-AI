"""The versioned API surface.

Every module hangs one router here. Mounting is explicit — a module is reachable because this
file says so, not because a directory scan found it. A scan would eventually mount something
half-finished.

The prefix comes from settings (`/api/v1`, PLAN section 28), so a future `/api/v2` is a second
mount rather than a rewrite.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from uboss.core.origin import require_trusted_origin
from uboss.modules.identity.api import router as identity_router


def build_v1_router() -> APIRouter:
    router = APIRouter(dependencies=[Depends(require_trusted_origin)])

    #  Modules are added here as each step of the build completes. Nothing is listed before it
    #  works end to end: a route that returns a placeholder is a route that lies to the frontend.
    router.include_router(identity_router)

    return router
