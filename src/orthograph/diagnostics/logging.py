"""Library logging helper (dependency-free).

Orthograph is a library, not an application: it never configures logging,
sets levels, or adds handlers. It only obtains named loggers under the
``orthograph.*`` tree via :func:`get_logger`. The consuming application owns
all sink/level/format configuration. A ``NullHandler`` is attached to the
top-level ``orthograph`` logger in ``orthograph/__init__.py`` so the library
emits nothing unless the application opts in.
"""

import logging


def get_logger(name: str) -> logging.Logger:
    """Return the stdlib logger named ``name``.

    Call as ``get_logger(__name__)`` so the logger sits under the
    ``orthograph.*`` name tree (e.g. ``orthograph.cypher.validation``).
    """
    return logging.getLogger(name)
