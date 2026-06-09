"""Cypher backend base classes for the typed query catalogue.

These are the abstract Cypher bases over the typed contract defined in
``orthograph.catalogue.typed``. Applications using this library subclass them to
define their own concrete queries; the bases themselves define no query. They
fix ``backend = Backend.CYPHER`` and narrow the ``build()`` return contract to
``(cypher: str, params: dict)``.

Two authoring styles are supported:

  * **Declarative (preferred)** — set a ``cypher_template`` ClassVar (the
    parameterized query string with ``$name`` placeholders). The base validates
    it at class-definition time (dialect parse + ``$param`` ↔ ``Params`` field
    alignment) and supplies a default ``build()`` that returns
    ``(cls.cypher_template, params.model_dump())``. Subclasses only implement
    ``materialize()`` / ``interpret_result()``.

    For optional filters, use the ``$param IS NULL OR`` pattern to keep the
    query static::

        cypher_template = '''
            MATCH (m:Movie)
            WHERE ($released IS NULL OR m.released = $released)
              AND ($genre IS NULL OR m.genre = $genre)
            RETURN m
        '''

  * **Imperative (escape hatch)** — leave ``cypher_template`` unset and
    implement ``build()`` directly. Use ONLY when the query *shape* genuinely
    changes at runtime — e.g. conditionally adding ``MATCH``/``OPTIONAL MATCH``
    clauses, choosing different relationship types, or changing ``RETURN``
    columns.

    **Trade-offs of imperative style:**

    - No definition-time Cypher validation (syntax checked only at runtime by
      the executor via ``parse_cypher()``).
    - Cannot be statically introspected by ``validate_cypher(q, model)`` or the
      catalogue's ``describe()`` — the query text is unknown until ``build()``
      runs.
    - A ``UserWarning`` is emitted at class-definition time to surface these
      trade-offs. Suppress with ``warnings.filterwarnings`` if intentional.

Lives alongside ``generator.py`` and ``parser.py`` — it does not replace them.

No database driver is imported here: ``build()`` and ``materialize()`` stay
pure. The only I/O seam is ``CypherExecutor`` (see ``query_executor.py``).
"""

import re
import warnings
from abc import abstractmethod
from typing import Any, ClassVar, Generic, cast

from pydantic import BaseModel

from orthograph.catalogue.typed import Backend, D, P, R, ReadQuery, WriteQuery
from orthograph.extensions.cypher.parser import parse_cypher


CypherQuery = tuple[str, dict[str, Any]]
"""A built Cypher query: the Cypher string and its parameter dict."""


class CypherQueryDefinitionError(TypeError):
    """Raised at class-definition time when a declarative query's contract is violated.

    Possible causes:

    - ``cypher_template`` is empty or not a string.
    - ``cypher_template`` does not parse under the Cypher dialect.
    - ``cypher_template`` uses ``$param`` placeholders not declared on ``Params``.
    - ``Params`` declares a field with no matching ``$param`` placeholder.

    Inherits ``TypeError`` for backward compatibility with code that catches
    definition-time type errors generically.
    """


# A Cypher named parameter: ``$name`` where name is an identifier.
_PARAM_PATTERN = re.compile(r"\$(\w+)")


def extract_cypher_params(cypher: str) -> set[str]:
    """Return the set of ``$name`` parameter placeholders used in a Cypher string."""
    return set(_PARAM_PATTERN.findall(cypher))


def _validate_declarative_cypher(cls: type) -> None:
    """Validate a query class that declares a ``cypher_template`` ClassVar.

    Runs at class-definition time so problems fail fast, before any database is
    touched:

      1. ``cypher_template`` must be a non-empty string.
      2. The Cypher must parse under the dialect (syntax / dialect compliance).
      3. Every ``$param`` placeholder must correspond to a field on ``Params``,
         and every ``Params`` field must correspond to a ``$param`` placeholder
         (a strict 1:1 mapping).

    Raises ``CypherQueryDefinitionError`` listing every problem found.
    """
    cypher = getattr(cls, "cypher_template", None)
    if cypher is None:
        # Imperative style — build() is implemented manually.
        # Emit a warning so consumers are aware they lose definition-time
        # validation. Suppress with warnings.filterwarnings if intentional.
        warnings.warn(
            f"{cls.__name__} uses imperative style (no 'cypher_template' "
            "ClassVar). Definition-time Cypher validation is skipped; syntax "
            "will only be checked at runtime by the executor. Prefer "
            "declarative style with a 'cypher_template' ClassVar for static "
            "guarantees. Use '$param IS NULL OR n.prop = $param' for optional "
            "filters.",
            UserWarning,
            # stacklevel=4: warn() -> _validate_declarative_cypher ->
            # __init_subclass__ -> ABCMeta.__new__ -> user's class-definition
            # site. The ABCMeta frame is present because these bases subclass ABC.
            stacklevel=4,
        )
        return

    problems: list[str] = []

    if not isinstance(cypher, str) or not cypher.strip():
        raise CypherQueryDefinitionError(
            f"{cls.__name__}: cypher_template must be a non-empty string"
        )

    try:
        parse_cypher(cypher)
    except Exception as exc:  # graphglot raises various parse errors
        problems.append(f"cypher does not parse: {exc}")

    params_model = getattr(cls, "Params", None)
    if isinstance(params_model, type) and issubclass(params_model, BaseModel):
        declared = set(params_model.model_fields.keys())
        used = extract_cypher_params(cypher)
        missing = used - declared
        if missing:
            problems.append(
                f"cypher_template uses parameter(s) "
                f"{sorted('$' + m for m in missing)} not declared on "
                f"{params_model.__name__}"
            )
        # Params fields map 1:1 to $placeholders. A declared field with no
        # matching placeholder is dead input — usually a rename/typo where the
        # placeholder changed but the field did not — and is silently ignored
        # at runtime. Fail fast.
        unused = declared - used
        if unused:
            problems.append(
                f"{params_model.__name__} declares field(s) "
                f"{sorted('$' + u for u in unused)} with no matching placeholder "
                f"in cypher_template"
            )

    if problems:
        raise CypherQueryDefinitionError(f"{cls.__name__}: " + "; ".join(problems))


class CypherReadQuery(ReadQuery[P, D], Generic[P, D]):
    """Abstract base for typed Cypher read queries.

    Declarative style — set ``cypher_template`` and the base supplies ``build()``::

        class MoviesByYear(CypherReadQuery[ReleasedYearParams, Movie]):
            Params = ReleasedYearParams
            Output = Movie
            name = "movies_by_year"
            cypher_template = "MATCH (m:Movie {released: $released}) RETURN m"

            def materialize(self, raw): ...

    Imperative style — leave ``cypher_template`` unset and implement ``build()``.

    ``build()`` returns ``(cypher, params)`` — a Cypher string and the parameter
    dict the driver substitutes. ``materialize()`` maps a single graph record
    dict (keys like ``"m.title"``) to the declared ``Output`` model.

    ``backend`` is fixed to ``CYPHER`` here.
    """

    backend = Backend.CYPHER
    cypher_template: ClassVar[str]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        _validate_declarative_cypher(cls)

    def build(self, params: P) -> CypherQuery:
        """Default declarative build: ``(cls.cypher_template, params.model_dump())``.

        Subclasses that set ``cypher_template`` get this for free. Subclasses
        that build the query conditionally override this method (and need not
        set ``cypher_template``).
        """
        cypher = getattr(type(self), "cypher_template", None)
        if cypher is None:
            raise NotImplementedError(
                f"{type(self).__name__} sets no 'cypher_template' and does not "
                "override build()"
            )
        return cast(str, cypher), params.model_dump()

    @abstractmethod
    def materialize(self, raw: Any) -> D:
        """Pure mapping of one graph record dict to the declared Output type."""


class CypherWriteQuery(WriteQuery[P, R], Generic[P, R]):
    """Abstract base for typed Cypher write queries.

    Supports the same declarative (``cypher_template`` ClassVar) and imperative
    (override ``build()``) styles as ``CypherReadQuery``.

    ``build()`` returns ``(cypher, params)``. ``interpret_result()`` maps the
    driver's write result into the declared result type ``R``.

    ``backend`` is fixed to ``CYPHER`` here.
    """

    backend = Backend.CYPHER
    cypher_template: ClassVar[str]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        _validate_declarative_cypher(cls)

    def build(self, params: P) -> CypherQuery:
        """Default declarative build: ``(cls.cypher_template, params.model_dump())``."""
        cypher = getattr(type(self), "cypher_template", None)
        if cypher is None:
            raise NotImplementedError(
                f"{type(self).__name__} sets no 'cypher_template' and does not "
                "override build()"
            )
        return cast(str, cypher), params.model_dump()

    @abstractmethod
    def interpret_result(self, raw: Any) -> R:
        """Pure mapping of the driver's write result into the result type."""
