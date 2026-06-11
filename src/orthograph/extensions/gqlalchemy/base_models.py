"""GraphORM query bases for the GQLAlchemy backend.

Analogues of ``cypher/base_models.py`` for the GQLAlchemy builder dialect.
Key differences from the Cypher base:

* ``backend`` is fixed to ``Backend.GQLALCHEMY``.
* The ``Identifiers`` / ``Params`` split is realised as builder arguments:
  ``Identifiers`` field values (validated via ``validated_label``) are passed to
  ``node(labels=...)`` / ``.to(relationship_type=...)``; ``Params`` field values
  are passed to ``.where(...)`` bindings.
* ``build()`` returns a **builder object** (legal under ``typed.py``'s
  ``build() -> Any``), NOT a ``(cypher, dict)`` tuple.  Authors implement
  ``build()`` directly and return the raw GQLAlchemy builder; no declarative
  template mechanism is provided.
* ``materialize()`` / ``interpret_result()`` are left abstract; authors implement
  them per query.

``NoIdentifiers`` is imported from the cypher layer deliberately — it is part of
the shared Cypher substrate.  A later architecture sprint may revisit placement.
"""

from abc import abstractmethod
from typing import Any, ClassVar, Generic

from pydantic import BaseModel

from orthograph.catalogue.typed import Backend, D, P, R, ReadQuery, WriteQuery
from orthograph.extensions.cypher.bindings import NoIdentifiers, identifier_kind
from orthograph.extensions.cypher.identifiers import validate_identifier


def validated_label(value: str, *, field_name: str = "label") -> str:
    """Validate an identifier value as a safe Cypher identifier and return it.

    Thin convenience wrapper so query authors get identifier safety without
    re-importing ``validate_identifier``/``identifier_kind``. ``field_name``
    selects the kind (``rel_type``/``*_rel_type`` -> relationship type, else
    label), matching the Cypher backend's rule.
    """
    return validate_identifier(value, kind=identifier_kind(field_name))


class GqlAlchemyReadQuery(ReadQuery[P, D], Generic[P, D]):
    """GraphORM read base for the GQLAlchemy builder dialect.

    ``build()`` returns a GQLAlchemy builder object (not a tuple).  Authors
    validate each ``Identifiers`` field via ``validated_label`` before passing
    the value to ``node(labels=...)`` or ``.to(relationship_type=...)``, and
    pass ``Params`` values into ``.where(...)`` bindings.
    """

    backend = Backend.GQLALCHEMY
    Identifiers: ClassVar[type[BaseModel]] = NoIdentifiers

    def __init__(self, identifiers: BaseModel | dict[str, Any] | None = None) -> None:
        identifiers = {} if identifiers is None else identifiers
        self._identifiers = type(self).Identifiers.model_validate(identifiers)

    @abstractmethod
    def build(self, params: P) -> Any:
        """Author-implemented: construct and return a GQLAlchemy builder object."""

    @abstractmethod
    def materialize(self, raw: Any) -> D:
        """Pure per-record mapping from a raw GQLAlchemy result row to Output."""


class GqlAlchemyWriteQuery(WriteQuery[P, R], Generic[P, R]):
    """GraphORM write base for the GQLAlchemy builder dialect.

    ``build()`` returns a GQLAlchemy builder object (not a tuple).  Authors
    validate each ``Identifiers`` field via ``validated_label`` before passing
    the value to ``node(labels=...)`` or ``.to(relationship_type=...)``, and
    pass ``Params`` values into builder bindings.
    """

    backend = Backend.GQLALCHEMY
    Identifiers: ClassVar[type[BaseModel]] = NoIdentifiers

    def __init__(self, identifiers: BaseModel | dict[str, Any] | None = None) -> None:
        identifiers = {} if identifiers is None else identifiers
        self._identifiers = type(self).Identifiers.model_validate(identifiers)

    @abstractmethod
    def build(self, params: P) -> Any:
        """Author-implemented: construct and return a GQLAlchemy builder object."""

    @abstractmethod
    def interpret_result(self, raw: Any) -> R:
        """Pure mapping of the driver's write result into the result type."""
