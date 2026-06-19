"""NodeModel and RelationshipModel base classes for defining graph types."""

import inspect
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, ClassVar, cast, get_type_hints

from pydantic import BaseModel, model_validator

from orthograph.graph_definition.exceptions import (
    AmbiguousCardinalityError,
    CardinalityParseError,
    MissingClassVarError,
)
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

    @model_validator(mode="before")
    @classmethod
    def _coerce_notation(cls, value: Any) -> Any:
        """Coerce a UML-notation string into field data; pass other inputs through.

        This is the single seam (ADR-031) through which notation strings reach
        ``CardinalitySpec`` — raw construction, YAML parsing, and the
        ``CardinalitySpec``-typed fields of the conditional models. Dicts and
        instances are returned untouched so the normal field pipeline (and the
        ``mode="after"`` ``_validate_bounds``) runs unchanged.
        """
        if isinstance(value, str):
            parsed = cls.parse(value)
            return {"min": parsed.min, "max": parsed.max}
        return value

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

    def resolve_for_pair(
        self, self_props: Mapping[str, object], other_props: Mapping[str, object]
    ) -> "CardinalitySpec":
        """Constant cardinality ignores endpoint properties."""
        return self

    @classmethod
    def parse(cls, text: str) -> "CardinalitySpec":
        """Parse strict UML ``min..max`` notation into a ``CardinalitySpec``.

        ``min`` is a non-negative int; ``max`` is ``None`` for the unbounded
        symbol ``*`` else a non-negative int. Syntactic failures raise
        :exc:`CardinalityParseError`; semantic failures (e.g. ``5..2``,
        negatives) come from ``_validate_bounds`` during construction.
        """
        parts = text.split("..")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise CardinalityParseError(text)
        min_part, max_part = parts
        try:
            min_value = int(min_part)
        except ValueError:
            raise CardinalityParseError(text) from None
        if max_part == "*":
            max_value: int | None = None
        else:
            try:
                max_value = int(max_part)
            except ValueError:
                raise CardinalityParseError(text) from None
        return cls(min=min_value, max=max_value)

    @property
    def notation(self) -> str:
        """Emit UML ``min..max`` notation (inverse of :meth:`parse`)."""
        return f"{self.min}..{'*' if self.max is None else self.max}"

    def __repr__(self) -> str:
        return f"CardinalitySpec({self.notation})"


def _coerce_cardinality(
    value: "str | CardinalitySpec | ConditionalCardinality",
) -> "CardinalitySpec | ConditionalCardinality":
    """Coerce a notation string to :class:`CardinalitySpec`; pass other values through.

    Used by :meth:`RelationshipModel.__init_subclass__` to coerce ClassVar
    cardinality values, where Pydantic's ``mode="before"`` validator does not run.
    ``CardinalitySpec`` and ``ConditionalCardinality`` instances are returned as-is.
    """
    if isinstance(value, str):
        return CardinalitySpec.parse(value)
    return value


# ---------------------------------------------------------------------------
# Conditional cardinality models
# ---------------------------------------------------------------------------


class PropMatch(BaseModel):
    """A conjunction of property-equality predicates for one relationship endpoint.

    An empty ``conditions`` map matches any node (wildcard).
    """

    model_config = {"frozen": True}

    conditions: Mapping[str, object] = {}

    def __init__(
        self, conditions: Mapping[str, object] | None = None, /, **data: object
    ) -> None:
        """Accept a positional mapping as well as the keyword form.

        Pydantic models are keyword-only by construction, but the agreed
        authoring style for cardinality rules is ``PropMatch({"kind": "split"})``
        — a positional dict that removes the repeated ``conditions=`` noise at
        every rule's two endpoints.  The leading parameter is declared
        positional-only (``/``) so both call shapes reach the same field:

            PropMatch({"kind": "split"})          # agreed form
            PropMatch(conditions={"kind": "split"})  # keyword form — still valid
            PropMatch()                            # wildcard — unchanged

        Delegating immediately to ``super().__init__`` means Pydantic's
        validation pipeline, the frozen contract, and the ``_freeze_conditions``
        post-validator (MappingProxyType wrapping) all run exactly as before.
        This override is the only viable seam: there is no Pydantic config switch
        that enables positional construction, so ``__init__`` is both the correct
        and the minimal place to add it.
        """
        if conditions is not None:
            data["conditions"] = conditions
        super().__init__(**data)

    @model_validator(mode="after")
    def _freeze_conditions(self) -> "PropMatch":
        """Replace conditions with a read-only proxy so the frozen contract holds.

        Pydantic's ``frozen=True`` blocks attribute reassignment but not mutation
        of the underlying dict; wrapping in a ``MappingProxyType`` makes the map
        genuinely immutable so equality and specificity cannot drift.
        """
        object.__setattr__(self, "conditions", MappingProxyType(dict(self.conditions)))
        return self

    def matches(self, props: Mapping[str, object]) -> bool:
        """Return True when every condition key/value pair is satisfied by *props*.

        A condition is satisfied only when *props* contains the key and its value
        is equal; an absent key never matches (even against a ``None`` condition).
        """
        return all(k in props and props[k] == v for k, v in self.conditions.items())

    @property
    def specificity(self) -> int:
        """Number of conditions (higher = more specific)."""
        return len(self.conditions)

    @property
    def is_wildcard(self) -> bool:
        """True when there are no conditions (matches everything)."""
        return not self.conditions


class ConditionalRule(BaseModel):
    """A single rule binding a (source, target) predicate pair to a cardinality spec."""

    model_config = {"frozen": True}

    source: PropMatch
    target: PropMatch
    spec: CardinalitySpec


def _matching_rules(
    rules: tuple["ConditionalRule", ...],
    self_props: Mapping[str, object],
    other_props: Mapping[str, object],
) -> list["ConditionalRule"]:
    """Return rules whose source and target predicates both match the given props."""
    return [
        r
        for r in rules
        if r.source.matches(self_props) and r.target.matches(other_props)
    ]


def _highest_specificity(
    matches: list["ConditionalRule"],
) -> list["ConditionalRule"]:
    """Return the subset of *matches* that share the maximum combined specificity.

    Precondition: *matches* must be non-empty.
    """
    assert matches, "_highest_specificity requires at least one match"
    max_score = max(r.source.specificity + r.target.specificity for r in matches)
    return [
        r for r in matches if r.source.specificity + r.target.specificity == max_score
    ]


class ConditionalCardinality(BaseModel):
    """Cardinality that varies by endpoint property values.

    Resolution uses most-specific-wins: the rule whose combined
    ``source.specificity + target.specificity`` is highest wins.
    A required ``default`` applies when no rule matches.
    """

    model_config = {"frozen": True}

    rules: tuple[ConditionalRule, ...]
    default: CardinalitySpec

    def resolve_for_pair(
        self,
        self_props: Mapping[str, object],
        other_props: Mapping[str, object],
    ) -> CardinalitySpec:
        """Return the cardinality spec for the given endpoint property pair.

        Raises :exc:`AmbiguousCardinalityError` when two rules of equal
        top specificity both match (defence-in-depth; prevented at definition
        time by E40.4 checks).
        """
        matched = _matching_rules(self.rules, self_props, other_props)
        if not matched:
            return self.default
        winners = _highest_specificity(matched)
        if len(winners) > 1:
            predicates = [(w.source.conditions, w.target.conditions) for w in winners]
            raise AmbiguousCardinalityError(
                f"Multiple rules of equal specificity match {dict(self_props)!r} / "
                f"{dict(other_props)!r}: {predicates}"
            )
        return winners[0].spec

    def __str__(self) -> str:
        """Return a compact string representation of the conditional cardinality.

        Format: `{(source_cond,target_cond):spec; ...; default:default_spec}`.
        """

        def format_spec(spec: CardinalitySpec) -> str:
            """Format a CardinalitySpec as a compact string."""
            max_str = "*" if spec.max is None else str(spec.max)
            return f"{spec.min}..{max_str}"

        rule_parts: list[str] = []
        for rule in self.rules:
            source_vals = (
                dict(rule.source.conditions) if rule.source.conditions else "*"
            )
            target_vals = (
                dict(rule.target.conditions) if rule.target.conditions else "*"
            )
            spec_str = format_spec(rule.spec)
            rule_parts.append(f"({source_vals},{target_vals}):{spec_str}")

        default_str = format_spec(self.default)
        all_parts = rule_parts + [f"default:{default_str}"]
        return "{" + "; ".join(all_parts) + "}"

    def __repr__(self) -> str:
        """Return the string representation (same as __str__)."""
        return self.__str__()


def representative_spec(
    cardinality: "CardinalitySpec | ConditionalCardinality",
) -> CardinalitySpec:
    """Return a concrete :class:`CardinalitySpec` for a possibly-conditional value.

    Display, serialization, and structural-diff contexts do not have the
    endpoint property pairs required to resolve a :class:`ConditionalCardinality`
    precisely; for those a representative spec is needed. A plain
    ``CardinalitySpec`` is returned as-is, while a ``ConditionalCardinality``
    yields its ``default`` bound.

    This avoids the ``AttributeError`` that arises from accessing ``.min`` /
    ``.max`` / ``.contains()`` on a ``ConditionalCardinality`` (which has none
    of those attributes). Per-endpoint resolution for the validation path is
    tracked separately (E40.5).
    """
    if isinstance(cardinality, ConditionalCardinality):
        return cardinality.default
    return cardinality


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

    ``__source_cardinality__`` : ``CardinalitySpec | ConditionalCardinality``
        (default ``"0..*"``) Outgoing instances per source node; author as a
        UML notation string or a :class:`CardinalitySpec` /
        :class:`ConditionalCardinality` instance.

    ``__target_cardinality__`` : ``CardinalitySpec | ConditionalCardinality``
        (default ``"0..*"``) Incoming instances per target node; author as a
        UML notation string or a :class:`CardinalitySpec` /
        :class:`ConditionalCardinality` instance.

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
    __source_cardinality__: ClassVar[str | CardinalitySpec | ConditionalCardinality] = (
        CardinalitySpec(min=0, max=None)
    )
    """Source-side cardinality (how many outgoing instances each source node may have).

    Author as a UML notation string (e.g. ``"1..*"``) or a
    :class:`CardinalitySpec` / :class:`ConditionalCardinality` instance.
    String values are coerced to :class:`CardinalitySpec` at subclass definition
    time by :meth:`__init_subclass__`.
    Default: ``CardinalitySpec(min=0, max=None)`` (``"0..*"`` — no constraint enforced).
    """

    __target_cardinality__: ClassVar[str | CardinalitySpec | ConditionalCardinality] = (
        CardinalitySpec(min=0, max=None)
    )
    """Target-side cardinality (how many incoming instances each target node may have).

    Author as a UML notation string (e.g. ``"1..*"``) or a
    :class:`CardinalitySpec` / :class:`ConditionalCardinality` instance.
    String values are coerced to :class:`CardinalitySpec` at subclass definition
    time by :meth:`__init_subclass__`.
    Default: ``CardinalitySpec(min=0, max=None)`` (``"0..*"`` — no constraint enforced).
    """

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Enforce required class variables at subclass definition time."""
        super().__init_subclass__(**kwargs)
        if cls.__name__ == "RelationshipModel":
            return

        for var in ("__label__", "__source_label__", "__target_label__"):
            _assert_classvar_defined(cls, var, base=RelationshipModel)

        for attr in ("__source_cardinality__", "__target_cardinality__"):
            if attr in cls.__dict__:
                coerced = _coerce_cardinality(cls.__dict__[attr])
                setattr(cls, attr, coerced)

    @classmethod
    def source_cardinality(cls) -> "CardinalitySpec | ConditionalCardinality":
        """Return the resolved source-side cardinality.

        The ``__source_cardinality__`` ClassVar is typed to include ``str`` so
        that subclasses may *author* cardinality as UML notation, but
        :meth:`__init_subclass__` coerces every string to a
        :class:`CardinalitySpec` at definition time. After coercion the value is
        never a string, so this accessor is the single seam that narrows the
        authoring union to the resolved invariant. Consumers (visualization,
        serialization, validation, diffing) read through here rather than
        touching the raw ClassVar, so the ``str`` case is narrowed in exactly
        one place instead of at every call site.
        """
        return _coerce_cardinality(cls.__source_cardinality__)

    @classmethod
    def target_cardinality(cls) -> "CardinalitySpec | ConditionalCardinality":
        """Return the resolved target-side cardinality.

        See :meth:`source_cardinality` for why this accessor exists.
        """
        return _coerce_cardinality(cls.__target_cardinality__)
