"""CSRF protection for the cookie-authenticated browser API.

SameSite cookies are useful but insufficient on their own: a malicious subdomain is cross-origin
while still same-site. Every unsafe browser request therefore has to name an exact trusted web
origin. Browser fetch sends ``Origin``; ``Referer`` is a fallback for clients that omit it.

Non-browser integrations will use a separate bearer-authenticated API contract. They must not
silently bypass the browser cookie boundary by omitting both headers.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import Request

from uboss.core.dependencies import SettingsDep
from uboss.core.errors import PermissionDenied

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _canonical_origin(value: str) -> str | None:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    if parsed.username or parsed.password:
        return None
    default_port = 80 if parsed.scheme == "http" else 443
    try:
        port = parsed.port
    except ValueError:
        return None
    authority = parsed.hostname.lower()
    if port is not None and port != default_port:
        authority = f"{authority}:{port}"
    return f"{parsed.scheme.lower()}://{authority}"


def require_trusted_origin(request: Request, settings: SettingsDep) -> None:
    """Refuse unsafe API calls that did not come from an approved web origin."""
    if request.method.upper() in SAFE_METHODS:
        return

    supplied = request.headers.get("Origin")
    if supplied == "null":
        supplied = None
    if supplied is None:
        supplied = request.headers.get("Referer")

    candidate = _canonical_origin(supplied) if supplied else None
    trusted = {
        origin
        for configured in settings.cors_origin_list
        if (origin := _canonical_origin(configured)) is not None
    }
    if candidate is None or candidate not in trusted:
        raise PermissionDenied("This request origin is not allowed.")
