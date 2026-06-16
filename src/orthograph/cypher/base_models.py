"""Abstract base classes for typed Cypher queries.

Two authoring styles:

  * **Declarative (preferred)** — set a ``cypher_template`` ClassVar. The base
    validates it at class-definition time (dialect parse + ``$param`` ↔
    ``Params`` alignment and ``<<name>>`` ↔ ``Identifiers`` alignment).
    ``build()`` is provided automatically.  Subclasses implement only
    ``materialize()``.

    For optional filters, use ``$param IS NULL OR n.prop = $param`` to keep
    the query shape static.

  * **Imperative (escape hatch)** — omit ``cypher_template`` and override
    ``build()``.  Use only when the query shape genuinely changes at runtime
    (different clauses, dynamic ``RETURN`` columns, etc.).  A ``UserWarning``
    is emitted at class-definition time; suppress with
    ``warnings.filterwarnings`` if intentional.

Two parameter groups:

  * ``Params`` — value parameters, mapped 1:1 to ``$name`` placeholders and
    substituted by the driver.
  * ``Identifiers`` — label/relationship-type/property-key values, mapped 1:1
    to ``<<name>>`` placeholders and spliced (after safe-identifier validation)
    by ``build()``.  Defaults to ``NoIdentifiers``; use ``NoParams`` for the
    value side when there are no driver parameters.

Identifier values are bound at construction so ``build(params)`` keeps its
single-argument signature::

    query = NodesByLabel(identifiers={"label": "Person"})
    cypher, params = query.build(NoParams())
    # -> ("MATCH (n:`Person`) RETURN n", {})
"""

import inspect
import warnings
from abc import abstractmethod
from typing import Any, ClassVar, Generic, cast

from graphglot.error import GraphGlotError
from pydantic import BaseModel

from orthograph.cypher.bindings import (
    CypherQuery,
    NoIdentifiers,
    check_placeholder_alignment,
    render_with_identifiers,
    substitute_identifier_placeholders,
)
from orthograph.cypher.exceptions import CypherQueryDefinitionError
from orthograph.cypher.parser import parse_cypher
from orthograph.query.base_models import (
    Backend,
    D,
    P,
    R,
    ReadQuery,
    WriteQuery,
    _auto_populate_classvar,
    _extract_generic_args,
)


# Dummy identifier swapped in for ``<<name>>`` placeholders before the dialect
# parse (``<<name>>`` is not valid Cypher); a legal identifier so the rest of
# the template is still dialect-checked.
_PARSE_PLACEHOLDER = "__IDENT__"


def _validate_declarative_cypher(cls: type) -> None:
    """Validate a query class with a ``cypher_template`` ClassVar at definition time.

    Checks: non-empty string, dialect parse (with ``<<name>>`` substituted),
    and strict 1:1 ``$param`` ↔ ``Params`` / ``<<name>>`` ↔ ``Identifiers``
    alignment.  Raises ``CypherQueryDefinitionError`` listing all problems.
    Emits ``UserWarning`` instead for imperative (no template) classes.
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

    Declarative style — set ``cypher_template``, implement ``materialize()``::

        class MoviesByYear(CypherReadQuery[ReleasedYearParams, Movie]):
            Params = ReleasedYearParams
            Output = Movie
            name = "movies_by_year"
            cypher_template = "MATCH (m:Movie {released: $released}) RETURN m"

            def materialize(self, raw): ...

    Imperative style — omit ``cypher_template``, override ``build()``.

    **Optional class variables:**

    * ``Identifiers`` — a BaseModel class (defaults to ``NoIdentifiers``). When set,
      identifier values (like labels, relationship types, or property names) are
      bound at construction via an ``Identifiers`` model instance. The ``<<name>>``
      placeholders in the ``cypher_template`` are replaced with safe, validated
      identifier values (validated against Cypher syntax rules before substitution)
      by the default ``build()`` method::

          class NodesByLabel(CypherReadQuery[NoParams, Movie]):
              Identifiers = LabelIdentifiers  # declares label: str
              cypher_template = "MATCH (n:`<<label>>`) RETURN n"

              def materialize(self, raw): ...

          query = NodesByLabel(identifiers={"label": "Person"})
          # Renders to: ("MATCH (n:`Person`) RETURN n", {})

    ``backend`` is fixed to ``CYPHER``.
    """

    backend = Backend.CYPHER
    cypher_template: ClassVar[str]
    Identifiers: ClassVar[type[BaseModel]] = NoIdentifiers

    def __init__(self, identifiers: BaseModel | dict[str, Any] | None = None) -> None:
        """Bind and validate ``Identifiers`` values at construction."""
        identifiers = {} if identifiers is None else identifiers
        self._identifiers = type(self).Identifiers.model_validate(identifiers)

    def __init_subclass__(cls, **kwargs: Any) -> None:
        # T6: auto-populate Params/Output from CypherReadQuery[P, D] generic args
        # *before* super().__init_subclass__ runs ReadQuery's contract enforcement.
        if not inspect.isabstract(cls):
            args = _extract_generic_args(cls, CypherReadQuery)
            if args and len(args) >= 2:
                _auto_populate_classvar(cls, "Params", args[0])
                _auto_populate_classvar(cls, "Output", args[1])
        super().__init_subclass__(**kwargs)
        _validate_declarative_cypher(cls)

    def build(self, params: P) -> CypherQuery:
        """Return ``(rendered_cypher, params.model_dump())``.

        Identifier values bound at construction are validated and spliced into
        their ``<<name>>`` slots.  Override this for imperative queries.
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

    Supports the same declarative and imperative styles, and the same
    ``Identifiers``/``<<placeholder>>`` mechanism as :class:`CypherReadQuery`.

    **Optional class variables:**

    * ``Identifiers`` — a BaseModel class (defaults to ``NoIdentifiers``). When set,
      identifier values (like labels, relationship types, or property names) are
      bound at construction. The ``<<name>>`` placeholders in the ``cypher_template``
      are replaced with safe, validated identifier values before execution.

    ``build()`` returns ``(cypher, params)``.  ``backend`` is fixed to ``CYPHER``.
    """

    backend = Backend.CYPHER
    cypher_template: ClassVar[str]
    Identifiers: ClassVar[type[BaseModel]] = NoIdentifiers

    def __init__(self, identifiers: BaseModel | dict[str, Any] | None = None) -> None:
        """Bind and validate ``Identifiers`` values at construction."""
        identifiers = {} if identifiers is None else identifiers
        self._identifiers = type(self).Identifiers.model_validate(identifiers)

    def __init_subclass__(cls, **kwargs: Any) -> None:
        # T6: auto-populate Params from CypherWriteQuery[P, R] generic arg
        # *before* super().__init_subclass__ runs WriteQuery's contract enforcement.
        if not inspect.isabstract(cls):
            args = _extract_generic_args(cls, CypherWriteQuery)
            if args and len(args) >= 1:
                _auto_populate_classvar(cls, "Params", args[0])
        super().__init_subclass__(**kwargs)
        _validate_declarative_cypher(cls)

    def build(self, params: P) -> CypherQuery:
        """Return ``(rendered_cypher, params.model_dump())``.

        Identifier values bound at construction are validated and spliced into
        their ``<<name>>`` slots.
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
