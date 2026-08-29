"""Session tokens: how one is minted, and how one is recognised again.

A token is 32 random bytes. The browser holds it; the database holds only its SHA-256. A stolen
database backup therefore contains nothing that can be used to sign in as anyone.

SHA-256 rather than Argon2 here, and that is deliberate rather than an oversight. A password is
low-entropy and guessable, so it needs a slow hash to make guessing expensive. A 256-bit random
token is not guessable at any speed, and a slow hash on every single request would cost real
latency for no security. What matters is that the stored value is one-way, and it is.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

#: 32 bytes, url-safe. Long enough that guessing is not a threat model.
TOKEN_BYTES = 32

#: The cookie the browser holds. `__Host-` is a prefix the browser itself enforces: it refuses
#: the cookie unless it is Secure, has no Domain attribute and is scoped to `/`. That means a
#: subdomain — including one an attacker manages to stand up — cannot overwrite it.
COOKIE_NAME = "__Host-uboss_session"

#: On plain HTTP the browser rejects a `__Host-` cookie outright, so local development uses a
#: plain name. The two never coexist: the name is chosen once, from the environment.
COOKIE_NAME_INSECURE = "uboss_session"


@dataclass(frozen=True, slots=True)
class MintedToken:
    """A newly created token.

    `raw` exists only in memory, only long enough to be written into a `Set-Cookie` header. It is
    never logged, never returned in a response body, and never stored.
    """

    raw: str
    hashed: str
    expires_at: datetime


def mint(lifetime: timedelta) -> MintedToken:
    raw = secrets.token_urlsafe(TOKEN_BYTES)
    return MintedToken(
        raw=raw,
        hashed=hash_token(raw),
        expires_at=datetime.now(UTC) + lifetime,
    )


def mint_until(expires_at: datetime) -> MintedToken:
    """Rotate a token without extending the session's absolute lifetime."""
    now = datetime.now(UTC)
    if expires_at <= now:
        raise ValueError("Cannot mint a token for an expired session.")
    raw = secrets.token_urlsafe(TOKEN_BYTES)
    return MintedToken(raw=raw, hashed=hash_token(raw), expires_at=expires_at)


def hash_token(raw: str) -> str:
    """The value stored and looked up. Hex, 64 characters, matching the column."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def cookie_name(secure: bool) -> str:
    return COOKIE_NAME if secure else COOKIE_NAME_INSECURE


def cookie_settings(secure: bool, max_age_seconds: int) -> dict[str, object]:
    """The attributes every session cookie carries.

    - `httponly` — JavaScript cannot read it, so a script injected into the page cannot take it.
    - `samesite="lax"` — not sent on a cross-site POST, which is what makes CSRF hard. Lax rather
      than strict so that following a link from an email still lands the person signed in.
    - `path="/"` — one session for the whole application.
    """
    return {
        "httponly": True,
        "secure": secure,
        "samesite": "lax",
        "path": "/",
        "max_age": max_age_seconds,
    }
