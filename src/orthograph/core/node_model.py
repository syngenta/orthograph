"""NodeModel base class for defining graph node types."""

from typing import Any, ClassVar, get_type_hints

from pydantic import BaseModel

from orthograph.core.types import TypeInfo, resolve_type_info


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
            raise TypeError(f"{cls.__name__} must define __label__ class variable")

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
