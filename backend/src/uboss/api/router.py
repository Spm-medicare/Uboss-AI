"""The versioned API surface.

Every module hangs one router here. Mounting is explicit — a module is reachable because this
file says so, not because a directory scan found it. A scan would eventually mount something
half-finished.

The prefix comes from settings (`/api/v1`, PLAN §28), so a future `/api/v2` is a second mount
rather than a rewrite.
"""

from __future__ import annotations

from fastapi import APIRouter

from uboss.core.errors import ErrorEnvelope
from uboss.modules.hierarchy.api import router as hierarchy_router
from uboss.modules.hierarchy.import_api import router as hierarchy_import_router
from uboss.modules.identity.api import router as identity_router
from uboss.modules.jobs.api import router as jobs_router
from uboss.modules.jobs.schedule_api import router as job_schedule_router
from uboss.modules.objectives.api import router as objectives_router
from uboss.modules.objectives.proposal_api import router as objective_plan_router
from uboss.modules.objectives.publish_api import router as objective_publish_router

#: Every failure any route can produce, declared once.
#
#  PLAN §28 makes the error envelope part of the contract, so it belongs in the published schema
#  and in the generated client — not only in the exception handlers that happen to produce it.
#  Without this the frontend keeps a hand-written copy, and a hand-written copy of a contract is
#  a copy that drifts.
#
#  Declared on the router rather than per route because any of these can arrive on any route: a
#  session can expire, a policy can refuse, a dependency can be down.
ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorEnvelope, "description": "Not signed in, or the session ended."},
    403: {"model": ErrorEnvelope, "description": "Refused. The reason is in the audit trail."},
    404: {"model": ErrorEnvelope, "description": "No such record, for this caller."},
    409: {"model": ErrorEnvelope, "description": "The record moved, or the key was reused."},
    422: {"model": ErrorEnvelope, "description": "Some field was not accepted."},
    429: {"model": ErrorEnvelope, "description": "Too many attempts. See Retry-After."},
    500: {"model": ErrorEnvelope, "description": "A fault on our side. Nothing was changed."},
    503: {"model": ErrorEnvelope, "description": "A dependency did not answer. Retryable."},
}


def build_v1_router() -> APIRouter:
    router = APIRouter(responses=ERROR_RESPONSES)

    #  Modules are added here as each step of the build completes. Nothing is listed before it
    #  works end to end: a route that returns a placeholder is a route that lies to the frontend.
    router.include_router(identity_router)
    router.include_router(hierarchy_router)
    router.include_router(hierarchy_import_router)
    router.include_router(objectives_router)
    router.include_router(objective_plan_router)
    router.include_router(objective_publish_router)
    router.include_router(jobs_router)
    router.include_router(job_schedule_router)

    return router
