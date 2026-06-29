"""Query base classes for the GQLAlchemy builder dialect.

``build()`` returns a GQLAlchemy builder object (not a ``(cypher, dict)`` tuple).
``identifiers_schema`` field values are validated via ``validated_label`` before
being passed to ``node(labels=...)`` or ``.to(relationship_type=...)``.
``params_schema`` values go into ``.where(...)`` bindings.
``materialize()`` is abstract for reads; ``interpret_result()`` is abstract for writes.
"""

from abc import abstractmethod
from typing import Any, ClassVar, Generic

from pydantic import BaseModel

from orthograph.cypher.bindings import NoIdentifiers, identifier_kind
from orthograph.cypher.identifiers import validate_identifier
from orthograph.query.base_models import (
    Backend,
    D,
    P,
    R,
    ReadQueryModel,
    WriteQueryModel,
)


def validated_label(value: str, *, field_name: str = "label") -> str:
    """Validate and return a safe Cypher identifier.

    ``field_name`` selects the identifier kind: names containing ``rel_type``
    are treated as relationship types, all others as node labels.
    """
    return validate_identifier(value, kind=identifier_kind(field_name))


class GqlAlchemyReadQueryModel(ReadQueryModel[P, D], Generic[P, D]):
    """Read query base for the GQLAlchemy builder dialect."""

    backend = Backend.GQLALCHEMY
    identifiers_schema: ClassVar[type[BaseModel]] = NoIdentifiers

    def __init__(self, identifiers: BaseModel | dict[str, Any] | None = None) -> None:
        identifiers = {} if identifiers is None else identifiers
        self._identifiers = type(self).identifiers_schema.model_validate(identifiers)

    @abstractmethod
    def build(self, params: P) -> Any:
        """Author-implemented: construct and return a GQLAlchemy builder object."""

    @abstractmethod
    def materialize(self, raw: Any) -> D:
        """Pure per-record mapping from a raw GQLAlchemy result row to Output."""


class GqlAlchemyWriteQueryModel(WriteQueryModel[P, R], Generic[P, R]):
    """Write query base for the GQLAlchemy builder dialect."""

    backend = Backend.GQLALCHEMY
    identifiers_schema: ClassVar[type[BaseModel]] = NoIdentifiers

    def __init__(self, identifiers: BaseModel | dict[str, Any] | None = None) -> None:
        identifiers = {} if identifiers is None else identifiers
        self._identifiers = type(self).identifiers_schema.model_validate(identifiers)

    @abstractmethod
    def build(self, params: P) -> Any:
        """Author-implemented: construct and return a GQLAlchemy builder object."""

    @abstractmethod
    def interpret_result(self, raw: Any) -> R:
        """Pure mapping of the driver's write result into the result type."""
