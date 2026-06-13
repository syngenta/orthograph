"""NodeModel and RelationshipModel base classes for defining graph types."""

import typing
from typing import Any, ClassVar, get_type_hints

from pydantic import BaseModel, model_validator

from orthograph.graph_definition.exceptions import MissingClassVarError
from orthograph.graph_definition.property_spec import TypeInfo, resolve_type_info


# ---------------------------------------------------------------------------
# NodeModel
# ---------------------------------------------------------------------------


class NodeModel(BaseModel):
    """Base class for graph node type definitions.

    Subclasses must set __label__. Properties are defined as typed fields.
    """

    __label__: ClassVar[str]
    __uid_field__: ClassVar[str | None] = None
    __optional__: ClassVar[bool] = True

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Skip validation for intermediate abstract classes
        if cls.__name__ == "NodeModel":
            return
        # Ensure __label__ is defined (not inherited from NodeModel defaults)
        if "__label__" not in cls.__dict__ and not any(
            "__label__" in base.__dict__
            for base in cls.__mro__[1:]
            if base is not NodeModel
        ):
            raise MissingClassVarError(
                f"{cls.__name__} must define __label__ class variable"
            )

    @classmethod
    def get_property_specs(cls) -> dict[str, TypeInfo]:
        hints = get_type_hints(cls)
        result: dict[str, TypeInfo] = {}
        for name, annotation in hints.items():
            if name.startswith("_"):
                continue
            result[name] = resolve_type_info(annotation)
        return result

    @classmethod
    def get_required_property_names(cls) -> set[str]:
        specs = cls.get_property_specs()
        return {name for name, info in specs.items() if info.is_required}

    @classmethod
    def get_all_property_names(cls) -> set[str]:
        return set(cls.get_property_specs().keys())


# ---------------------------------------------------------------------------
# Cardinality
# ---------------------------------------------------------------------------


class CardinalitySpec(BaseModel):
    """Defines min/max bounds for relationship cardinality."""

    model_config = {"frozen": True}

    min: int
    max: int | None = None

    @model_validator(mode="after")
    def _validate_bounds(self) -> "CardinalitySpec":
        if self.min < 0:
            raise ValueError(f"min must be >= 0, got {self.min}")
        if self.max is not None and self.max < self.min:
            raise ValueError(f"max ({self.max}) must be >= min ({self.min}) or None")
        return self

    def contains(self, count: int) -> bool:
        """Check if a count falls within the cardinality bounds."""
        if count < self.min:
            return False
        if self.max is not None and count > self.max:
            return False
        return True

    def __repr__(self) -> str:
        max_str = "N" if self.max is None else str(self.max)
        return f"CardinalitySpec({self.min}..{max_str})"


class Cardinality:
    """Named :class:`CardinalitySpec` constants for relationship constraints.

    Cardinality constrains how many instances of a relationship type each
    individual node may have.  It does NOT control whether the relationship
    type must appear anywhere in the data — that is ``__optional__`` on the
    :class:`RelationshipModel`.

    ``ZERO_OR_MORE`` means each node may have zero or more instances.
    Zero is valid; the node simply does not participate.  This is semantically
    distinct from ``ONE_OR_MORE``, which requires at least one instance.
    """

    ZERO_OR_ONE: typing.ClassVar[CardinalitySpec] = CardinalitySpec(min=0, max=1)
    """0..1 — optional, at most one."""

    ONE: typing.ClassVar[CardinalitySpec] = CardinalitySpec(min=1, max=1)
    """1..1 — exactly one."""

    ZERO_OR_MORE: typing.ClassVar[CardinalitySpec] = CardinalitySpec(min=0, max=None)
    """0..* — optional, unbounded (permissive default)."""

    ONE_OR_MORE: typing.ClassVar[CardinalitySpec] = CardinalitySpec(min=1, max=None)
    """1..* — mandatory, unbounded."""


# ---------------------------------------------------------------------------
# RelationshipModel
# ---------------------------------------------------------------------------


class RelationshipModel(BaseModel):
    """Base class for graph relationship type definitions.

    Subclasses must set ``__label__``, ``__source_label__``, and
    ``__target_label__``.  The source/target labels are string node labels
    matching the ``__label__`` of the corresponding :class:`NodeModel` subclass.
    Properties are defined as typed fields.
    """

    __label__: ClassVar[str]
    __source_label__: ClassVar[str]
    __target_label__: ClassVar[str]
    __directed__: ClassVar[bool] = True
    __optional__: ClassVar[bool] = True
    __source_cardinality__: ClassVar[CardinalitySpec] = Cardinality.ZERO_OR_MORE
    """Source-side cardinality (how many outgoing instances each source node may have).
    Default: ``ZERO_OR_MORE`` (no constraint enforced).
    """

    __target_cardinality__: ClassVar[CardinalitySpec] = Cardinality.ZERO_OR_MORE
    """Target-side cardinality (how many incoming instances each target node may have).
    Default: ``ZERO_OR_MORE`` (no constraint enforced).
    """

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if cls.__name__ == "RelationshipModel":
            return

        _check_classvar(cls, "__label__", str)
        _check_classvar(cls, "__source_label__", str)
        _check_classvar(cls, "__target_label__", str)

    @classmethod
    def get_property_specs(cls) -> dict[str, TypeInfo]:
        hints = get_type_hints(cls)
        result: dict[str, TypeInfo] = {}
        for name, annotation in hints.items():
            if name.startswith("_"):
                continue
            result[name] = resolve_type_info(annotation)
        return result

    @classmethod
    def get_required_property_names(cls) -> set[str]:
        specs = cls.get_property_specs()
        return {name for name, info in specs.items() if info.is_required}

    @classmethod
    def get_all_property_names(cls) -> set[str]:
        return set(cls.get_property_specs().keys())


def _check_classvar(cls: type, name: str, expected_type: type) -> None:
    if name not in cls.__dict__ and not any(
        name in base.__dict__
        for base in cls.__mro__[1:]
        if base is not RelationshipModel
    ):
        raise MissingClassVarError(f"{cls.__name__} must define {name} class variable")
