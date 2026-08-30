"""Every model in the product, imported once.

SQLAlchemy only knows about a table if the module defining it has been imported. That makes the
import list a piece of correctness, not bookkeeping: `migrations/env.py` compares `Base.metadata`
against the live database, so a module missing from the list looks like a table that should not
exist — and autogenerate would write a `DROP` for it.

That comment was already in `env.py`, and four modules had drifted off the list anyway. Keeping
the list in one place used by everything that needs the full metadata is the fix: there is now one
thing to update rather than one per caller, and forgetting it breaks a test rather than a
database.

`import_all()` is a function rather than bare imports so the intent survives a formatter and a
linter — a file of unused imports invites somebody to tidy it.
"""

from __future__ import annotations

from uboss.db.base import Base

__all__ = ["Base", "import_all", "metadata"]


def import_all() -> None:
    """Import every module that defines a table.

    Deliberately noisy about why the imports are unused: they are not, they are registrations.
    """
    #  Ordered by the layer they belong to rather than alphabetically, so a reader can see the
    #  shape of the product from the list.
    from uboss.modules.agents import agent_models  # noqa: F401
    from uboss.modules.agents import models as agents_models  # noqa: F401
    from uboss.modules.audit import models as audit_models  # noqa: F401
    from uboss.modules.files import models as files_models  # noqa: F401
    from uboss.modules.hierarchy import import_models as hierarchy_imports  # noqa: F401
    from uboss.modules.hierarchy import models as hierarchy_models  # noqa: F401
    from uboss.modules.identity import models as identity_models  # noqa: F401
    from uboss.modules.identity import policies as identity_policies  # noqa: F401
    from uboss.modules.jobs import models as jobs_models  # noqa: F401
    from uboss.modules.objectives import models as objectives_models  # noqa: F401
    from uboss.modules.objectives import proposal_models as objectives_proposals  # noqa: F401
    from uboss.modules.supervisors import models as supervisors_models  # noqa: F401
    from uboss.modules.tenancy import models as tenancy_models  # noqa: F401


def metadata() -> object:
    """`Base.metadata`, with every model registered. The one safe way to reach it."""
    import_all()
    return Base.metadata
