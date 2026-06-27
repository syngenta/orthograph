"""Discover which backends exist, are installed, and can do what.

Backends are selected by name (``backend: str``). The legal name strings are
exactly those returned by :func:`available` — there is deliberately no
hand-written enum, because the name set has a single source of truth in
``backends/loader._BACKENDS``. This module adds only the *join* between that
wiring table and the optional-dependency availability probe.

Verbs:

* ``available``    — the installed backends a consumer may select right now.
* ``is_available`` — whether one named backend's dependencies are installed.
* ``can_inspect``  — whether a backend has an inspection adapter.
* ``can_execute``  — whether a backend has a typed-query executor.

``available`` is the source of legal ``backend`` strings for
:mod:`orthograph.profile` and :mod:`orthograph.execution`.
"""

from orthograph import dependencies
from orthograph.backends import loader


def available() -> list[str]:
    """Return the wired backends whose dependencies are installed.

    A subset of :func:`loader.backend_names`; the strings here name the
    inspectable/executable backends behind ``profile`` / ``execution``.
    """
    return [n for n in loader.backend_names() if dependencies.is_available(n)]


def is_available(backend: str) -> bool:
    """Return True if ``backend``'s dependencies are installed.

    Unknown names return ``False`` (delegates to
    :func:`dependencies.is_available`).
    """
    return dependencies.is_available(backend)


def can_inspect(backend: str) -> bool:
    """Return True if ``backend`` has an inspection adapter.

    Raises
    ------
    MissingDependencyError
        If ``backend`` is not a wired backend.
    """
    return loader.capabilities(backend).can_inspect


def can_execute(backend: str) -> bool:
    """Return True if ``backend`` has a typed-query executor.

    Raises
    ------
    MissingDependencyError
        If ``backend`` is not a wired backend.
    """
    return loader.capabilities(backend).can_execute


__all__ = ["available", "is_available", "can_inspect", "can_execute"]
