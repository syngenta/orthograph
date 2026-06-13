"""Single authority for optional-dependency availability.

All optional backends are declared in ``_BACKENDS``. Use ``require`` to raise
on a missing dependency, or ``is_available`` for a non-raising probe.
"""

from __future__ import annotations

import importlib.util
import sys
from typing import Literal


Kind = Literal["db-driver", "orm", "in-memory", "tool"]


class MissingDependencyError(ImportError):
    """Raised when an optional dependency required for a backend is absent."""


# name -> (pip-extra, kind, probe-modules)
#
# ``memgraph`` deliberately shares the neo4j Bolt driver (documented in
# pyproject.toml); both probe the ``neo4j`` package.
_BACKENDS: dict[str, tuple[str, Kind, tuple[str, ...]]] = {
    "neo4j": ("neo4j", "db-driver", ("neo4j",)),
    "memgraph": ("memgraph", "db-driver", ("neo4j",)),
    "networkx": ("networkx", "in-memory", ("networkx",)),
    "gqlalchemy": ("gqlalchemy", "orm", ("gqlalchemy",)),
    "cypher": ("cypher", "tool", ("graphglot",)),
    "ipython": ("notebook", "tool", ("IPython",)),
}


def _module_present(name: str) -> bool:
    """Return True if ``name`` is importable or already in ``sys.modules``.

    Catches errors from partially-initialised or mocked modules.
    """
    if name in sys.modules:
        return True
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _probe(modules: tuple[str, ...]) -> bool:
    """Return True if every probe module can be located."""
    return all(_module_present(m) for m in modules)


def is_available(name: str) -> bool:
    """Return True if the named backend's dependencies are installed.

    Unknown names return ``False``.
    """
    entry = _BACKENDS.get(name)
    if entry is None:
        return False
    _, _, modules = entry
    return _probe(modules)


def require(name: str) -> None:
    """Ensure the named backend's dependencies are installed.

    Raises
    ------
    MissingDependencyError
        If ``name`` is unknown or its probe modules are not importable.
        The error message includes the pip install command.
    """
    entry = _BACKENDS.get(name)
    if entry is None:
        raise MissingDependencyError(
            f"Unknown backend {name!r}. Known backends: {', '.join(sorted(_BACKENDS))}."
        )
    extra, _, modules = entry
    if not _probe(modules):
        missing = ", ".join(m for m in modules if not _module_present(m))
        raise MissingDependencyError(
            f"The {name!r} backend requires the {missing} package, which is not "
            f"installed. Install it with: pip install orthograph[{extra}]"
        )
