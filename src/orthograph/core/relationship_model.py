"""RelationshipModel base class for defining graph relationship types."""

from typing import Any, ClassVar, get_type_hints

from pydantic import BaseModel

from orthograph.core.exceptions import MissingClassVarError
from orthograph.core.node_model import NodeModel
from orthograph.core.types import (
    Cardinality,
    CardinalitySpec,
    TypeInfo,
    resolve_type_info,
)


class RelationshipModel(BaseModel):
    """Base class for graph relationship type definitions.

    Subclasses must set __label__, __source_type__, and __target_type__.
    Properties are defined as typed fields.
    """

    __label__: ClassVar[str]
    __source_type__: ClassVar[type[NodeModel]]
    __target_type__: ClassVar[type[NodeModel]]
    __directed__: ClassVar[bool] = True
    __optional__: ClassVar[bool] = True
    __source_cardinality__: ClassVar[CardinalitySpec] = Cardinality.ZERO_OR_MORE
    """Default: ZERO_OR_MORE is a permissive default -- no cardinality
    constraint is enforced on the source side.  Override per relationship
    type to express business rules (e.g. ``Cardinality.ONE`` to require
    exactly one outgoing instance per source node).

    This is orthogonal to ``__optional__``: ``__optional__`` controls whether
    the relationship *type* must have at least one instance anywhere in the
    data; cardinality controls how many instances each *individual node* may
    have.  Both axes can be set independently."""

    __target_cardinality__: ClassVar[CardinalitySpec] = Cardinality.ZERO_OR_MORE
    """Default: ZERO_OR_MORE on the target side.  Same semantics as
    ``__source_cardinality__`` but applied to incoming relationship counts
    per target node."""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if cls.__name__ == "RelationshipModel":
            return

        _check_classvar(cls, "__label__", str)
        _check_classvar(cls, "__source_type__", type)
        _check_classvar(cls, "__target_type__", type)

    @classmethod
    def get_property_specs(cls) -> dict[str, TypeInfo]:
        """Return TypeInfo for each declared property field."""
        hints = get_type_hints(cls)
        result: dict[str, TypeInfo] = {}
        for name, annotation in hints.items():
            if name.startswith("_"):
                continue
            result[name] = resolve_type_info(annotation)
        return result

    @classmethod
    def get_required_property_names(cls) -> set[str]:
        """Return names of required (non-optional) properties."""
        specs = cls.get_property_specs()
        return {name for name, info in specs.items() if info.is_required}

    @classmethod
    def get_all_property_names(cls) -> set[str]:
        """Return names of all declared properties."""
        return set(cls.get_property_specs().keys())


def _check_classvar(cls: type, name: str, expected_type: type) -> None:
    """Verify a required ClassVar is defined on the class."""
    if name not in cls.__dict__ and not any(
        name in base.__dict__
        for base in cls.__mro__[1:]
        if base is not RelationshipModel
    ):
        raise MissingClassVarError(f"{cls.__name__} must define {name} class variable")
