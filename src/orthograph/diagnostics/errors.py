"""Project-wide exception hierarchy (dependency-free).

``OrthographError`` is the single root every Orthograph-raised error derives
from, directly or via one of the three mid-tier groups:

* :class:`OrthographUsageError`      — the caller misused the API/definitions/queries.
* :class:`OrthographValidationError` — a graph or data set failed validation.
* :class:`OrthographBackendError`    — a live-DB / driver / optional-dependency problem.

Self-logging: every error logs itself once on construction, at the class-level
``log_level`` (default ``DEBUG``). This guarantees a trace without the noise of
an unconditional ``ERROR``-on-construct. Subclasses override ``log_level`` to
raise or lower the level (see ``OrthographBackendError``).
"""

import logging

from orthograph.diagnostics.logging import get_logger


class OrthographError(Exception):
    """Root of every error Orthograph raises.

    Differentiation is by subclass and message — never by a docstring list of
    causes. The message carries the specifics.
    """

    #: Level at which this error logs itself on construction.
    log_level: int = logging.DEBUG

    def __init__(self, *args: object) -> None:
        super().__init__(*args)
        get_logger(type(self).__module__).log(
            self.log_level, "%s: %s", type(self).__name__, self
        )


class OrthographUsageError(OrthographError):
    """The caller misused the API, a model definition, or a query."""


class OrthographValidationError(OrthographError):
    """A graph or data set failed validation."""


class OrthographBackendError(OrthographError):
    """A live-database, driver, or optional-dependency problem."""

    log_level = logging.ERROR
