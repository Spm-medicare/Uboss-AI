"""An account with no password is not an account anybody can sign in to.

`hierarchy.invite.add_person` creates an account before its owner has ever chosen a password, so
for the first time the system holds rows in `users` whose `password_hash` carries no credential.
That made a latent bug in `verify_password` reachable, and it was the worst kind:

```python
_hasher.verify(password_hash or DUMMY_HASH, normalise(password))
return password_hash is not None          # <- the bug
```

`DUMMY_HASH` is a hash of a literal spelled out in `passwords.py`. Verifying against it *succeeds*
for anybody who types that literal, and `'' is not None` is `True` — so an invited account stored
with an empty hash would have signed in to a stranger who read the source. NULL happened to be
safe and `''` was not, which is not a distinction any caller should have to know about.

So the outcome is now decided before the comparison rather than read off it, and these tests hold
that line: every shape of "no password" refuses every password, including the one the dummy hash
was made from.
"""

from __future__ import annotations

import pytest

from uboss.modules.identity import passwords

#: The plaintext behind `DUMMY_HASH`. Hard-coded here on purpose — an attacker reading the
#: repository has it too, and a test that re-derived it from the module would pass even if the
#: module started hashing something the attacker also knows.
DUMMY_PLAINTEXT = "a password that matches nothing"

#: Every way a caller can express "this account has no password". A NULL column, the empty string
#: an ORM or a plpgsql `VALUES ('')` writes into it, and whitespace that looks like content and
#: is not.
NO_PASSWORD = [None, "", "   ", "\t\n"]


@pytest.mark.parametrize("stored", NO_PASSWORD)
@pytest.mark.parametrize(
    "attempt",
    [
        DUMMY_PLAINTEXT,
        "",
        "   ",
        "uboss-admin-2026",
        "a password that matches nothing ",
    ],
)
def test_an_account_with_no_password_refuses_every_password(
    stored: str | None, attempt: str
) -> None:
    assert passwords.verify_password(stored, attempt) is False


def test_the_dummy_passphrase_is_the_one_that_used_to_work() -> None:
    """The specific bypass, named, so nobody re-introduces it by simplifying the guard.

    Before the fix this exact call returned True for `stored=""`. It is kept separate from the
    parametrised sweep above so a regression reads as *this* failure rather than one of twenty.
    """
    assert passwords.verify_password("", DUMMY_PLAINTEXT) is False
    assert passwords.verify_password(None, DUMMY_PLAINTEXT) is False


def test_a_real_password_still_verifies() -> None:
    """The guard fails closed without failing shut — a set password still works."""
    stored = passwords.hash_password("a long enough passphrase for the rules")
    assert passwords.verify_password(stored, "a long enough passphrase for the rules") is True
    assert passwords.verify_password(stored, "a long enough passphrase for the rule") is False


def test_a_stored_hash_of_the_dummy_passphrase_is_not_special() -> None:
    """Hashing the dummy plaintext deliberately is an ordinary password, not a skeleton key.

    Distinguishes "the hash is unusable" from "the plaintext is forbidden". Only the first is
    true; a person whose password happens to be that sentence signs in with it and nobody else's
    empty hash accepts it.
    """
    stored = passwords._hasher.hash(passwords.normalise(DUMMY_PLAINTEXT))
    assert passwords.verify_password(stored, DUMMY_PLAINTEXT) is True
    assert passwords.verify_password("", DUMMY_PLAINTEXT) is False
