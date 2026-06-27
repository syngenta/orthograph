"""Single authority for optional-dependency availability.

The full backend registry lives in :mod:`orthograph.backends.registry`.
This module exposes the public ``require`` / ``is_available`` API.
"""

from __future__ import annotations

import importlib.util
import sys

from orthograph.backends.registry import BACKENDS, Kind


# Re-export Kind for backward compatibility
__all__ = ["Kind", "MissingDependencyError", "is_available", "require"]


class MissingDependencyError(ImportError):
    """Raised when an optional dependency required for a backend is absent."""


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
    entry = BACKENDS.get(name)
    if entry is None:
        return False
    return _probe(entry.probe_modules)


def require(name: str) -> None:
    """Ensure the named backend's dependencies are installed.

    Raises
    ------
    MissingDependencyError
        If ``name`` is unknown or its probe modules are not importable.
        The error message includes the pip install command.
    """
    entry = BACKENDS.get(name)
    if entry is None:
        raise MissingDependencyError(
            f"Unknown backend {name!r}. Known backends: {', '.join(sorted(BACKENDS))}."
        )
    if not _probe(entry.probe_modules):
        missing = ", ".join(m for m in entry.probe_modules if not _module_present(m))
        raise MissingDependencyError(
            f"The {name!r} backend requires the {missing} package, which is not "
            f"installed. Install it with: pip install orthograph[{entry.pip_extra}]"
        )
