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

Two declared parameter groups
------------------------------

A typed Cypher query declares **two** parameter groups, both Pydantic models:

  * ``Params`` — values. Each field maps 1:1 to a ``$value`` placeholder and is
    substituted *by the driver*.
  * ``Identifiers`` — labels / relationship types. Cypher cannot parameterise
    identifiers, so each ``Identifiers`` field maps 1:1 to a distinct,
    collision-proof ``<<name>>`` placeholder which is *validated and spliced
    into the query text* by ``build()`` via ``validate_identifier`` (the
    safe-identifier grammar). ``$value`` and ``<<name>>`` never collide — they
    use independent patterns and independent models.

``Identifiers`` is **opt-in with an empty default** (``NoIdentifiers``). A
query that declares no ``Identifiers`` and uses no ``<<placeholder>>`` is
byte-for-byte a plain value-only query — no boilerplate, no behaviour change.

For symmetry, ``NoParams`` is the canonical empty *value* model: a query that
takes no ``$value`` parameters declares ``Params = NoParams`` rather than
hand-rolling an empty ``BaseModel``. ``Params`` is always declared (it is the
generic type parameter ``P``), whereas ``Identifiers`` may be omitted — the
only honest difference between the two groups.

**Call shape (identifiers bound at construction).** ``Identifiers`` values are
passed to the query *constructor* and validated/stored on the instance;
``build(self, params)`` keeps its single-argument signature and the generic
``Executor.read/write`` seam in ``orthograph.catalogue.typed`` is unchanged
(``CypherExecutor`` is not touched). The alternative — threading an
``identifiers`` argument through ``build()`` and the executor — was rejected to
keep that seam stable::

    class NodesByLabel(CypherReadQuery[NoParams, NodeRow]):
        class Identifiers(BaseModel):
            label: str
        Params = NoParams
        Output = NodeRow
        name = "nodes_by_label"
        cypher_template = "MATCH (n:`<<label>>`) RETURN n"
        def materialize(self, raw): ...

    query = NodesByLabel(identifiers={"label": "Person"})
    cypher, params = query.build(NoParams())
    # -> ("MATCH (n:`Person`) RETURN n", {})

**Kind resolution.** Each ``Identifiers`` field is validated with a ``kind``
derived from its name: a field named ``rel_type`` or ending in ``_rel_type`` is
a ``"relationship type"``; every other field is a ``"label"``.

Lives alongside ``generator.py`` and ``parser.py`` — it does not replace them.

No database driver is imported here: ``build()`` and ``materialize()`` stay
pure. The only I/O seam is ``CypherExecutor`` (see ``query_executor.py``).
"""

import warnings
from abc import abstractmethod
from typing import Any, ClassVar, Generic, cast

from graphglot.error import GraphGlotError
from pydantic import BaseModel

from orthograph.catalogue.typed import Backend, D, P, R, ReadQuery, WriteQuery
from orthograph.extensions.cypher.bindings import (
    CypherQuery,
    NoIdentifiers,
    check_placeholder_alignment,
    render_with_identifiers,
    substitute_identifier_placeholders,
)
from orthograph.extensions.cypher.exceptions import CypherQueryDefinitionError
from orthograph.extensions.cypher.parser import parse_cypher


# Dummy identifier swapped in for ``<<name>>`` placeholders before the dialect
# parse (``<<name>>`` is not valid Cypher); a legal identifier so the rest of
# the template is still dialect-checked.
_PARSE_PLACEHOLDER = "__IDENT__"


def _validate_declarative_cypher(cls: type) -> None:
    """Validate a query class that declares a ``cypher_template`` ClassVar.

    Runs at class-definition time so problems fail fast, before any database is
    touched:

      1. ``cypher_template`` must be a non-empty string.
      2. The Cypher must parse under the dialect (syntax / dialect compliance).
         ``<<name>>`` identifier placeholders are substituted with a safe dummy
         identifier before parsing, so the rest of the template is still
         dialect-checked. (This is the only step that needs the parser.)
      3. Every ``$param`` ↔ a ``Params`` field and every ``<<name>>`` ↔ an
         ``Identifiers`` field, both strict 1:1 (delegated to the parser-free
         ``check_placeholder_alignment`` in ``bindings``).

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

    if not isinstance(cypher, str) or not cypher.strip():
        raise CypherQueryDefinitionError(
            f"{cls.__name__}: cypher_template must be a non-empty string"
        )

    problems: list[str] = []

    parseable = substitute_identifier_placeholders(cypher, _PARSE_PLACEHOLDER)
    try:
        parse_cypher(parseable)
    except (GraphGlotError, ValueError) as exc:
        # graphglot raises GraphGlotError subclasses (ParseError, TokenError,
        # ...) for malformed Cypher; parse_cypher itself raises ValueError on
        # empty input. Anything else (e.g. a programming error in the parser) is
        # a bug here, not "cypher does not parse", so it is left to propagate.
        problems.append(f"cypher does not parse: {exc}")

    problems.extend(check_placeholder_alignment(cls, cypher))

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

    A query may declare an ``Identifiers`` model and reference its fields as
    ``<<name>>`` placeholders; the identifier values are bound at construction
    (``MyQuery(identifiers={"label": "Person"})``) and spliced — after
    ``validate_identifier`` — into the template by ``build()``. ``Identifiers``
    defaults to the empty ``NoIdentifiers``; a query that declares none and
    uses no ``<<placeholder>>`` renders byte-for-byte unchanged.

    ``build()`` returns ``(cypher, params)`` — a Cypher string and the parameter
    dict the driver substitutes. ``materialize()`` maps a single graph record
    dict (keys like ``"m.title"``) to the declared ``Output`` model.

    ``backend`` is fixed to ``CYPHER`` here.
    """

    backend = Backend.CYPHER
    cypher_template: ClassVar[str]
    Identifiers: ClassVar[type[BaseModel]] = NoIdentifiers

    def __init__(self, identifiers: BaseModel | dict[str, Any] | None = None) -> None:
        """Bind and validate this query's ``Identifiers`` values.

        ``identifiers`` accepts an ``Identifiers`` instance, a mapping, or
        ``None`` (the empty default). Per the chosen call shape, the values live
        on the instance; ``build(self, params)`` keeps its single-argument
        signature and the generic ``Executor`` seam is unchanged.
        """
        identifiers = {} if identifiers is None else identifiers
        self._identifiers = type(self).Identifiers.model_validate(identifiers)

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        _validate_declarative_cypher(cls)

    def build(self, params: P) -> CypherQuery:
        """Default declarative build: ``(rendered_cypher, params.model_dump())``.

        Subclasses that set ``cypher_template`` get this for free. Each
        ``Identifiers`` field bound at construction is validated and spliced into
        its ``<<name>>`` slot before the string is returned; with no identifiers
        the string is returned unchanged. Subclasses that build the query
        conditionally override this method (and need not set ``cypher_template``).
        """
        cypher = getattr(type(self), "cypher_template", None)
        if cypher is None:
            raise NotImplementedError(
                f"{type(self).__name__} sets no 'cypher_template' and does not "
                "override build()"
            )
        rendered = render_with_identifiers(cast(str, cypher), self._identifiers)
        return rendered, params.model_dump()

    @abstractmethod
    def materialize(self, raw: Any) -> D:
        """Pure mapping of one graph record dict to the declared Output type."""


class CypherWriteQuery(WriteQuery[P, R], Generic[P, R]):
    """Abstract base for typed Cypher write queries.

    Supports the same declarative (``cypher_template`` ClassVar) and imperative
    (override ``build()``) styles as ``CypherReadQuery``, and the same
    ``Identifiers``/``<<placeholder>>`` mechanism (bound at construction,
    validated and spliced by ``build()``).

    ``build()`` returns ``(cypher, params)``. ``interpret_result()`` maps the
    driver's write result into the declared result type ``R``.

    ``backend`` is fixed to ``CYPHER`` here.
    """

    backend = Backend.CYPHER
    cypher_template: ClassVar[str]
    Identifiers: ClassVar[type[BaseModel]] = NoIdentifiers

    def __init__(self, identifiers: BaseModel | dict[str, Any] | None = None) -> None:
        """Bind and validate this query's ``Identifiers`` values (see
        ``CypherReadQuery.__init__``).
        """
        identifiers = {} if identifiers is None else identifiers
        self._identifiers = type(self).Identifiers.model_validate(identifiers)

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        _validate_declarative_cypher(cls)

    def build(self, params: P) -> CypherQuery:
        """Default declarative build: ``(rendered_cypher, params.model_dump())``.

        Identifier values bound at construction are validated and spliced into
        their ``<<name>>`` slots; with no identifiers the string is unchanged.
        """
        cypher = getattr(type(self), "cypher_template", None)
        if cypher is None:
            raise NotImplementedError(
                f"{type(self).__name__} sets no 'cypher_template' and does not "
                "override build()"
            )
        rendered = render_with_identifiers(cast(str, cypher), self._identifiers)
        return rendered, params.model_dump()

    @abstractmethod
    def interpret_result(self, raw: Any) -> R:
        """Pure mapping of the driver's write result into the result type."""
