"""Public logging surface for Orthograph.

Thin re-export shim (mirrors the capability-module pattern, ADR-041). The real
helper lives in :mod:`orthograph.diagnostics.logging`.

Orthograph is a library, not an application: it attaches a ``NullHandler`` to
the top-level ``orthograph`` logger and never configures levels, handlers, or
formatting. To see Orthograph's operational logs, the consuming application
configures the ``orthograph`` logger, e.g.::

    import logging
    logging.getLogger("orthograph").setLevel(logging.DEBUG)

Level convention used by the library:

* ``DEBUG``   — internal steps (query compiled, backend round-trip, cache hit),
                and every raised :class:`~orthograph.errors.OrthographError` by
                default.
* ``INFO``    — user-meaningful milestones (profile inspected, catalogue loaded).
* ``WARNING`` — library-level concerns (deprecated argument, fallback path taken).
* ``ERROR``   — backend/driver failures (raised ``OrthographBackendError`` logs here).
"""

from orthograph.diagnostics.logging import get_logger


__all__ = ["get_logger"]
