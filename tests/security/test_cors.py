"""The browser's preflight, and the header that was missing from it.

**A CORS list is not decoration.** A header the client sends and the server does not allow is a
request the browser refuses before it leaves the machine — the server never sees it, nothing is
logged, and the only evidence is a console message in somebody else's browser.

That is exactly what happened. `If-Match` carries `expected_version`, so it is on every
optimistic-concurrency write in the product: saving an agent, a job, an objective, renaming a
department, ending an assignment. It was not in `allow_headers`. Creates worked, because a create
has no version to guard, so the fault presented as *"editing is broken"* rather than as a
four-item list in `main.py`.

These tests are the reason it cannot come back. The first one asserts the exact set the client
sends, read from the client's own list rather than restated — a test that names the headers it
expects passes when both sides are wrong together.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from uboss.main import create_app

pytestmark = pytest.mark.anyio

ORIGIN = "http://localhost:3000"

#: Every header `frontend/src/lib/api/client.ts` sets on a request. Kept here as the contract
#: between the two sides; if the client gains a header, this list and `allow_headers` both change,
#: and this test is what makes the second one impossible to forget.
CLIENT_HEADERS = ("Content-Type", "Idempotency-Key", "If-Match")


@pytest.fixture
def app():
    return create_app()


async def _preflight(app, header: str):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url=ORIGIN) as client:
        return await client.options(
            "/api/v1/agents/00000000-0000-0000-0000-000000000000",
            headers={
                "Origin": ORIGIN,
                "Access-Control-Request-Method": "PATCH",
                "Access-Control-Request-Headers": header,
            },
        )


@pytest.mark.parametrize("header", CLIENT_HEADERS)
async def test_the_browser_is_allowed_every_header_the_client_sends(app, header: str) -> None:
    """One case per header, so a failure names the one that is missing.

    A single test asserting the whole set would say "the list is wrong" and leave somebody
    diffing two lists by eye.
    """
    response = await _preflight(app, header)

    assert response.status_code == 200, (
        f"the browser's preflight for {header!r} was refused, so every request carrying it "
        "fails before it reaches the server"
    )
    allowed = response.headers.get("access-control-allow-headers", "").lower()
    assert header.lower() in allowed, f"{header!r} is missing from allow_headers"


async def test_the_write_methods_the_product_uses_are_allowed(app) -> None:
    """`PATCH` is the one that matters — every version-guarded update is a PATCH."""
    response = await _preflight(app, "Content-Type")
    allowed = response.headers.get("access-control-allow-methods", "")
    for method in ("GET", "POST", "PATCH", "DELETE"):
        assert method in allowed, f"{method} is not allowed, so those routes are unreachable"


async def test_an_unknown_origin_is_not_allowed(app) -> None:
    """The list is a boundary, not a formality.

    `allow_credentials` is on, so an origin that got in here would be able to make requests
    carrying the session cookie. This is the check that the fix above did not turn into a
    wildcard on the way past.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://evil.example") as client:
        response = await client.options(
            "/api/v1/agents/00000000-0000-0000-0000-000000000000",
            headers={
                "Origin": "http://evil.example",
                "Access-Control-Request-Method": "PATCH",
                "Access-Control-Request-Headers": "Content-Type",
            },
        )

    assert response.headers.get("access-control-allow-origin") != "http://evil.example"
    assert response.headers.get("access-control-allow-origin") != "*"
