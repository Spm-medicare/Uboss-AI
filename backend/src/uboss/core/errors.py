"""One error shape for the whole API.

PLAN section 28: "Error envelope contains stable code, safe message, field errors, correlation ID
and retryability."

The envelope exists so the frontend can behave correctly without parsing prose:

* `code` is stable and machine-readable. The UI branches on it; the wording may change freely.
* `message` is safe to show a person. It never contains a stack trace, a SQL fragment, a row id
  from another tenant, or anything that would tell an attacker whether a record exists.
* `field_errors` lets a form put the message next to the input that caused it, so entered data is
  never thrown away -- PLAN line 162.
* `correlation_id` is the same id in the logs, so support can find the exact request.
* `retryable` says whether repeating the request could succeed. A client must never guess this:
  retrying a non-retryable command is how duplicates are created.

A failure is always an error. Nothing in this file turns a failure into a success with an empty
body -- the frontend rule is that an API failure renders a real error state.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from uboss.core.logging import correlation_id, get_logger

log = get_logger(__name__)


class FieldError(BaseModel):
    field: str
    code: str
    message: str


class ErrorEnvelope(BaseModel):
    code: str = Field(description="Stable machine-readable code, safe to branch on.")
    message: str = Field(description="Safe to display to a person.")
    field_errors: list[FieldError] = Field(default_factory=list)
    correlation_id: str = ""
    retryable: bool = False


class UbossError(Exception):
    """The base for every deliberate failure.

    Anything raised that is not one of these is a bug, and is reported as an unhandled internal
    error with no detail -- because a message we did not write is a message we cannot promise is
    safe to show.
    """

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "bad_request"
    retryable: bool = False

    def __init__(
        self,
        message: str,
        *,
        field_errors: list[FieldError] | None = None,
        code: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.field_errors = field_errors or []
        self.headers = headers or {}
        if code:
            self.code = code


class NotAuthenticated(UbossError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "not_authenticated"


class StepUpFailed(UbossError):
    """Recent credential proof was not accepted; the existing session remains valid."""

    status_code = status.HTTP_401_UNAUTHORIZED
    code = "step_up_failed"


class PermissionDenied(UbossError):
    """The caller is known but is not allowed to do this.

    Deliberately carries no detail about the target. Telling a caller *why* they were refused
    tells them the record exists.
    """

    status_code = status.HTTP_403_FORBIDDEN
    code = "permission_denied"


class NotFound(UbossError):
    """Also returned when a record exists but belongs to another tenant.

    A 404 and a 403 must be indistinguishable across a tenant boundary, or the response itself
    becomes a way to enumerate other tenants' data.
    """

    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class Conflict(UbossError):
    """The record moved since the caller read it.

    Raised by the optimistic-concurrency check. Not retryable as-is: the caller must re-read,
    see what changed, and decide again. Retrying blindly is a silent overwrite.
    """

    status_code = status.HTTP_409_CONFLICT
    code = "version_conflict"


class IdempotencyKeyReused(UbossError):
    """The same client key was attached to a different logical request."""

    status_code = status.HTTP_409_CONFLICT
    code = "idempotency_key_reused"


class OperationInProgress(UbossError):
    """Another request currently owns this logical operation."""

    status_code = status.HTTP_409_CONFLICT
    code = "operation_in_progress"
    retryable = True


class UnsafeReplayResponse(UbossError):
    """A route attempted to persist a response that may contain a credential."""

    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    code = "unsafe_idempotency_response"


class ValidationFailed(UbossError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "validation_failed"


class DependencyUnavailable(UbossError):
    """A service this request needed did not answer. Retrying may well succeed."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "dependency_unavailable"
    retryable = True


class RateLimited(UbossError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "rate_limited"
    retryable = True

    def __init__(self, message: str, *, retry_after_seconds: int) -> None:
        super().__init__(
            message,
            headers={"Retry-After": str(max(1, retry_after_seconds))},
        )


def _envelope(
    code: str,
    message: str,
    *,
    status_code: int,
    retryable: bool,
    field_errors: list[FieldError] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = ErrorEnvelope(
        code=code,
        message=message,
        field_errors=field_errors or [],
        correlation_id=correlation_id.get(),
        retryable=retryable,
    )
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json"),
        headers=headers,
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(UbossError)
    async def _handle_uboss(_request: Request, exc: UbossError) -> JSONResponse:
        return _envelope(
            exc.code,
            exc.message,
            status_code=exc.status_code,
            retryable=exc.retryable,
            field_errors=exc.field_errors,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Turn pydantic's report into per-field messages the form can place.

        The input value itself is not echoed back: a rejected field may hold a password or
        personal data, and an error response is a place it should never appear.
        """
        fields = [
            FieldError(
                field=".".join(str(part) for part in error["loc"][1:]) or "body",
                code=str(error["type"]),
                message=str(error["msg"]),
            )
            for error in exc.errors()
        ]
        return _envelope(
            "validation_failed",
            "Some of the information sent was not accepted. See the highlighted fields.",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            retryable=False,
            field_errors=fields,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http(
        _request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        return _envelope(
            f"http_{exc.status_code}",
            str(exc.detail),
            status_code=exc.status_code,
            retryable=exc.status_code in (502, 503, 504),
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        """A bug. Logged in full, reported with nothing.

        The correlation id is the bridge: the person sees an id, support finds the stack trace.
        """
        log.exception(
            "unhandled_error",
            path=request.url.path,
            method=request.method,
            error_type=type(exc).__name__,
        )
        return _envelope(
            "internal_error",
            "Something went wrong on our side. Nothing was changed by this request.",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            retryable=True,
        )


def as_field_error(field: str, message: str, code: str = "invalid") -> list[FieldError]:
    """Small helper so a service can raise a form-placeable error in one line."""
    return [FieldError(field=field, code=code, message=message)]


def problem(exc: UbossError) -> dict[str, Any]:
    """The envelope as a plain dict, for places that build a response by hand."""
    return ErrorEnvelope(
        code=exc.code,
        message=exc.message,
        field_errors=exc.field_errors,
        correlation_id=correlation_id.get(),
        retryable=exc.retryable,
    ).model_dump(mode="json")
