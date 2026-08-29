"""Password hashing and the checks around it.

Argon2id, with the parameters the library recommends rather than ones invented here. The
algorithm and its cost are encoded inside the hash string, so raising the cost later re-hashes
people transparently at their next successful sign-in — no migration, no forced reset.
"""

from __future__ import annotations

import unicodedata

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from uboss.core.errors import ValidationFailed, as_field_error

#  Defaults from argon2-cffi, which tracks the RFC 9106 recommendations. Deliberately not
#  hand-tuned: a number chosen here to "make sign-in feel fast" is a number that weakens every
#  password in the system, and the tuning would have to be revisited on every hardware change.
_hasher = PasswordHasher()

#: The length below which a passphrase is too easy to guess offline. Long minimum, no character
#: classes: forcing a symbol produces `Password1!` and nothing else.
MINIMUM_LENGTH = 12

#: bcrypt's 72-byte problem does not apply to Argon2, but an unbounded input does — hashing a
#: megabyte of text is a cheap way to exhaust the server's CPU.
MAXIMUM_LENGTH = 256

#: A hash of a value nothing will ever match. Verified against when the account does not exist,
#: so a wrong address and a wrong password cost the same time and cannot be told apart.
DUMMY_HASH = _hasher.hash("a password that matches nothing")


def normalise(password: str) -> str:
    """Unicode-normalise so the same typed passphrase always produces the same bytes.

    A non-ASCII character can be encoded two ways that look identical on screen. Without this, a
    password set on one keyboard layout can fail to verify when typed on another.
    """
    return unicodedata.normalize("NFKC", password)


def hash_password(password: str) -> str:
    check_strength(password)
    return _hasher.hash(normalise(password))


def verify_password(password_hash: str | None, password: str) -> bool:
    """True when the password matches.

    A missing hash — an invited person who has not set a password — still runs a verification
    against the dummy hash. Returning early would make "this account has no password yet"
    measurably faster than "wrong password", which is a way to enumerate accounts.
    """
    try:
        _hasher.verify(password_hash or DUMMY_HASH, normalise(password))
        return password_hash is not None
    except (VerifyMismatchError, InvalidHashError):
        return False


def rehash(password: str) -> str:
    """Re-hash an already-verified password at the current cost.

    Separate from `hash_password` because it deliberately skips the strength rules. The rules
    may have tightened since this password was set, and refusing a password that has *just*
    verified correctly would lock someone out at the moment they signed in successfully.
    Tightened rules apply when a password is next set, which is the right moment to ask.
    """
    return _hasher.hash(normalise(password))


def needs_rehash(password_hash: str) -> bool:
    """True when the stored hash used weaker parameters than the current ones."""
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        # Unreadable hash. Treating it as needing a rehash is the safe answer — it can never
        # verify, so the person will have to reset it anyway.
        return True


def check_strength(password: str) -> None:
    """Refuse a password that is too short or too long, with a message that says what to do."""
    candidate = normalise(password)
    if len(candidate) < MINIMUM_LENGTH:
        raise ValidationFailed(
            f"Use at least {MINIMUM_LENGTH} characters. A short sentence you will remember is "
            "stronger than a short word with symbols in it.",
            field_errors=as_field_error("password", "This password is too short.", "too_short"),
        )
    if len(candidate) > MAXIMUM_LENGTH:
        raise ValidationFailed(
            f"Use at most {MAXIMUM_LENGTH} characters.",
            field_errors=as_field_error("password", "This password is too long.", "too_long"),
        )
