"""NodeModel and RelationshipModel base classes for defining graph types."""

import inspect
import typing
from typing import Any, ClassVar, cast, get_type_hints

from pydantic import BaseModel, model_validator

from orthograph.graph_definition.exceptions import MissingClassVarError
from orthograph.graph_definition.property_spec import TypeInfo, resolve_type_info


# ---------------------------------------------------------------------------
# Module-private helpers
# ---------------------------------------------------------------------------


def _assert_classvar_defined(cls: type, name: str, base: type) -> None:
    """Raise :exc:`MissingClassVarError` if class variable *name* is missing from *cls*.

    The variable is considered defined when it appears in ``cls.__dict__``
    directly, or in any intermediate base up to (but not including) *base*.
    This allows concrete intermediate subclasses to supply the variable so
    their own children inherit it without re-declaring it.
    """
    if name in cls.__dict__:
        return
    if any(name in b.__dict__ for b in cls.__mro__[1:] if b is not base):
        return
    raise MissingClassVarError(f"{cls.__name__} must define {name} class variable")


def _resolve_uid_field_to_validate(cls: "type[NodeModel]") -> str | None:
    """Return the uid-field name that should be validated for *cls*, or ``None``.

    There are three cases:

    1. **Explicitly declared on this class** — ``__uid_field__`` is in
       ``cls.__dict__``.  The value is used directly (``None`` means the
       subclass intentionally clears an inherited UID, so we skip validation).

    2. **Inherited UID with re-annotated field** — the subclass does *not*
       redeclare ``__uid_field__`` but re-annotates the property the parent
       designated as the UID.  Without this check a child could silently
       weaken a required UID field to ``str | None`` and bypass the guard.

    3. **Everything else** — no uid field applies to this class, return ``None``.
    """
    if "__uid_field__" in cls.__dict__:
        # Case 1: explicitly set on this class (may be None to clear an inherited UID).
        return cast("str | None", cls.__dict__["__uid_field__"])

    # Case 2: not declared here — check for the inheritance-gap scenario.
    inherited = cls.__uid_field__
    # Use inspect.get_annotations so that:
    #   • Only the class's *own* annotations are returned (not inherited ones).
    #   • Deferred annotations (PEP 649/749, default in Python 3.14+) and
    #     stringified annotations (from __future__ import annotations) are
    #     evaluated to their runtime values via eval_str=True, so the key
    #     lookup below works on the real field name rather than an empty dict
    #     produced by cls.__dict__.get("__annotations__", {}) in Python 3.14
    #     where __annotations__ may not be populated until explicitly accessed.
    child_annotations = inspect.get_annotations(cls, eval_str=True)
    if inherited is not None and inherited in child_annotations:
        return inherited

    # Case 3: nothing to validate.
    return None


def _validate_uid_field(cls: "type[NodeModel]", uid_field: str) -> None:
    """Raise :exc:`MissingClassVarError` if *uid_field* is not a valid UID property.

    A valid UID field must:

    * be declared as a property on the model (no typos), and
    * be **required** (non-nullable) — a UID that can be ``None`` is
      meaningless as a unique identifier.
    """
    declared = cls.get_property_specs()

    if uid_field not in declared:
        raise MissingClassVarError(
            f"{cls.__name__}.__uid_field__ = {uid_field!r} is not a declared "
            f"property. Declared properties: {sorted(declared)}"
        )

    if not declared[uid_field].is_required:
        raise MissingClassVarError(
            f"{cls.__name__}.__uid_field__ = {uid_field!r} is declared as an "
            f"optional (nullable) property. "
            f"A UID field must be required (non-None). "
            f"Change the annotation from `{uid_field}: <type> | None` to "
            f"`{uid_field}: <type>`."
        )


class _PropertySpecMixin:
    """Shared property-introspection methods for node and relationship models.

    Both :class:`NodeModel` and :class:`RelationshipModel` expose the same
    three classmethods for querying declared properties.  This mixin provides
    a single implementation.

    Not part of the public API — use :class:`NodeModel` or
    :class:`RelationshipModel` directly.
    """

    @classmethod
    def get_property_specs(cls) -> dict[str, TypeInfo]:
        """Return resolved type information for every declared property.

        Private fields (names starting with ``_``) are excluded.  The returned
        mapping is keyed by property name; each value is a :class:`TypeInfo`
        with ``python_type`` and ``is_required``.
        """
        hints = get_type_hints(cls)
        return {
            name: resolve_type_info(annotation)
            for name, annotation in hints.items()
            if not name.startswith("_")
        }

    @classmethod
    def get_required_property_names(cls) -> set[str]:
        """Return the names of all non-nullable (required) properties."""
        return {
            name for name, info in cls.get_property_specs().items() if info.is_required
        }

    @classmethod
    def get_all_property_names(cls) -> set[str]:
        """Return the names of all declared properties (required and optional)."""
        return set(cls.get_property_specs().keys())


class NodeModel(_PropertySpecMixin, BaseModel):
    """Base class for graph node type definitions.

    Declare a node type by subclassing ``NodeModel`` and setting the required
    class variables.  All typed instance fields become graph properties.

    **Required class variables**

    ``__label__`` : ``str``
        The Neo4j node label this model represents (e.g. ``"Person"``).

    **Optional class variables**

    ``__uid_field__`` : ``str | None`` (default ``None``)
        Name of the property that uniquely identifies a node instance.
        When set, the targeted field must be declared as a **required**
        (non-nullable) property.  Set to ``None`` on a child to clear an
        inherited UID.

    ``__optional__`` : ``bool`` (default ``True``)
        When ``False`` the graph validator treats the absence of *any* node
        of this type as a schema violation.

    **Example**::

        class Person(NodeModel):
            __label__ = "Person"
            __uid_field__ = "email"

            email: str
            name: str
            age: int | None = None
    """

    __label__: ClassVar[str]
    __uid_field__: ClassVar[str | None] = None
    __optional__: ClassVar[bool] = True

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Validate class-variable contracts at subclass definition time.

        Runs two checks for every concrete subclass (the base ``NodeModel``
        itself is skipped):

        1. ``__label__`` must be defined — either directly or through a
           concrete intermediate base.
        2. ``__uid_field__``, when applicable, must point to a declared,
           non-nullable property.  See :func:`_resolve_uid_field_to_validate`
           for the three resolution cases.
        """
        super().__init_subclass__(**kwargs)
        if cls.__name__ == "NodeModel":
            return

        _assert_classvar_defined(cls, "__label__", base=NodeModel)

        uid_field = _resolve_uid_field_to_validate(cls)
        if uid_field is not None:
            _validate_uid_field(cls, uid_field)


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


class RelationshipModel(_PropertySpecMixin, BaseModel):
    """Base class for graph relationship type definitions.

    Declare a relationship type by subclassing ``RelationshipModel`` and
    setting the required class variables.  All typed instance fields become
    graph properties.

    **Required class variables**

    ``__label__`` : ``str``
        The Neo4j relationship type label (e.g. ``"ACTED_IN"``).

    ``__source_label__`` : ``str``
        The ``__label__`` of the :class:`NodeModel` at the tail of the arrow.

    ``__target_label__`` : ``str``
        The ``__label__`` of the :class:`NodeModel` at the head of the arrow.

    **Optional class variables**

    ``__directed__`` : ``bool`` (default ``True``)
        ``False`` for undirected relationships.

    ``__optional__`` : ``bool`` (default ``True``)
        When ``False`` the validator requires at least one instance of this
        relationship type in the graph.

    ``__source_cardinality__`` : :class:`CardinalitySpec` (default ``ZERO_OR_MORE``)
        How many outgoing instances each source node may have.

    ``__target_cardinality__`` : :class:`CardinalitySpec` (default ``ZERO_OR_MORE``)
        How many incoming instances each target node may have.

    **Example**::

        class ActedIn(RelationshipModel):
            __label__ = "ACTED_IN"
            __source_label__ = "Person"
            __target_label__ = "Movie"

            role: str
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
        """Enforce required class variables at subclass definition time."""
        super().__init_subclass__(**kwargs)
        if cls.__name__ == "RelationshipModel":
            return

        for var in ("__label__", "__source_label__", "__target_label__"):
            _assert_classvar_defined(cls, var, base=RelationshipModel)
