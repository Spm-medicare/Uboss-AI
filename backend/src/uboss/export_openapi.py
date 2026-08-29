"""Write the API contract to a file.

    uv run python -m uboss.export_openapi

`backend/openapi.json` is a committed artefact, and `frontend/src/lib/api/schema.d.ts` is
generated from it. Both are checked in CI: a route change that does not regenerate them fails,
because the alternative is a frontend that type-checks against a contract the server stopped
honouring months ago.

The file is written with sorted keys and a trailing newline so that regenerating it produces a
diff of what actually changed, rather than a reordering of every line.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import SecretStr

from uboss.core.settings import Settings
from uboss.main import create_app

TARGET = Path(__file__).resolve().parents[2] / "openapi.json"


def build() -> dict[str, object]:
    #  Built with a fixed, obviously-fake configuration. The schema must not depend on the
    #  machine that generated it — a contract that differs between a laptop and CI is not a
    #  contract.
    settings = Settings(
        environment="test",
        database_url=SecretStr("postgresql+psycopg://schema:schema@localhost:5432/schema"),
        auth_signing_key=SecretStr("schema-export-only"),
    )
    app = create_app(settings)
    return app.openapi()


def main() -> None:
    TARGET.write_text(
        json.dumps(build(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Wrote {TARGET.relative_to(TARGET.parents[1])}")


if __name__ == "__main__":
    main()
