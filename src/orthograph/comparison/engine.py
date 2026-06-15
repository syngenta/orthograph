"""Comparison engine — walks two :class:`GraphView` operands and applies rules.

Three public comparison functions are available:

- :func:`compare_profile_to_definition` — checks whether a profile satisfies
  a declared graph definition (renamed from the former ``compare``).
- :func:`compare_profiles` — symmetric diff between two
  :class:`~orthograph.graph_profile.models.GraphProfile` objects.
- :func:`compare_definitions` — symmetric diff between two
  :class:`~orthograph.graph_definition.graph_definition.GraphDefinition`
  objects.

All three delegate to the private :func:`_compare_views` walker which iterates
the union address space and applies the supplied rule set.
"""

from collections.abc import Sequence

from orthograph.comparison.diff_rules import diff_rules
from orthograph.comparison.rules import Rule, RuleContext, standard_rules
from orthograph.comparison.views import DefinitionView, GraphView, ProfileView
from orthograph.diagnostics.classification import EntityType
from orthograph.diagnostics.result import ValidationResult
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_profile.models import GraphProfile


# --- DB type to Python type mapping ---

_DB_TYPE_MAP: dict[str, type] = {
    "String": str,
    "str": str,
    "Long": int,
    "Integer": int,
    "Int": int,
    "int": int,
    "Double": float,
    "Float": float,
    "float": float,
    "Boolean": bool,
    "Bool": bool,
    "bool": bool,
    "StringArray": list,
    "LongArray": list,
    "DoubleArray": list,
    "List": list,
    "list": list,
}


def db_type_to_python(db_type: str) -> type | None:
    """Map a database type string to a Python type."""
    return _DB_TYPE_MAP.get(db_type)


# ---------------------------------------------------------------------------
# Private walker
# ---------------------------------------------------------------------------


def _compare_views(
    left_graph: GraphView,
    right_graph: GraphView,
    rules: Sequence[Rule],
) -> ValidationResult:
    """Walk the union address space of two views and apply every rule.

    This is the single five-pass loop shared by all three public comparison
    functions.  Rules are self-selecting: each rule inspects ``context.left``
    / ``context.right`` and ``context.extra``, and returns early when the
    address is not its concern.
    """
    result = ValidationResult()

    def _apply(ctx: RuleContext) -> None:
        for rule in rules:
            for issue in rule(ctx):
                result.add(issue)

    # ------------------------------------------------------------------
    # 1. Node-label addresses
    # ------------------------------------------------------------------
    left_labels = left_graph.node_labels()
    right_labels = right_graph.node_labels()

    for label in left_labels | right_labels:
        _apply(
            RuleContext(
                left_graph=left_graph,
                right_graph=right_graph,
                address=label,
                left=left_graph.node_at(label),
                right=right_graph.node_at(label),
                extra={"address_type": "node_label"},
            )
        )

    # ------------------------------------------------------------------
    # 2. Relationship-type addresses
    # ------------------------------------------------------------------
    left_rel_types = left_graph.relationship_types()
    right_rel_types = right_graph.relationship_types()

    for rt in left_rel_types | right_rel_types:
        _apply(
            RuleContext(
                left_graph=left_graph,
                right_graph=right_graph,
                address=rt,
                left=left_graph.relationship_at(rt),
                right=right_graph.relationship_at(rt),
                extra={"address_type": "rel_type"},
            )
        )

    # ------------------------------------------------------------------
    # 3. Property addresses — node types
    # Walk only labels present on *both* sides (intersection).
    # Properties of one-sided labels are already covered by the
    # presence rules above; walking them here would generate spurious
    # UNEXPECTED_PROPERTY / MISSING_PROPERTY issues for the parent label.
    # ------------------------------------------------------------------
    for label in left_labels & right_labels:
        left_props = left_graph.node_properties(label)
        right_props = right_graph.node_properties(label)
        for prop_name in set(left_props) | set(right_props):
            _apply(
                RuleContext(
                    left_graph=left_graph,
                    right_graph=right_graph,
                    address=f"{label}.{prop_name}",
                    left=left_props.get(prop_name),
                    right=right_props.get(prop_name),
                    extra={
                        "label": label,
                        "prop_name": prop_name,
                        "entity_type": EntityType.NODE,
                    },
                )
            )

    # ------------------------------------------------------------------
    # 4. Property addresses — relationship types
    # Same intersection semantics as pass-3.
    # ------------------------------------------------------------------
    for rt in left_rel_types & right_rel_types:
        left_props = left_graph.relationship_properties(rt)
        right_props = right_graph.relationship_properties(rt)
        for prop_name in set(left_props) | set(right_props):
            _apply(
                RuleContext(
                    left_graph=left_graph,
                    right_graph=right_graph,
                    address=f"{rt}.{prop_name}",
                    left=left_props.get(prop_name),
                    right=right_props.get(prop_name),
                    extra={
                        "label": rt,
                        "prop_name": prop_name,
                        "entity_type": EntityType.RELATIONSHIP,
                    },
                )
            )

    return result


# ---------------------------------------------------------------------------
# Public comparison functions
# ---------------------------------------------------------------------------


def compare_profile_to_definition(
    profile: GraphProfile,
    graph_definition: GraphDefinition,
    rules: Sequence[Rule] | None = None,
) -> ValidationResult:
    """Check whether *profile* satisfies the constraints in *graph_definition*.

    This is a direct rename of the former ``compare`` function; behaviour and
    emitted codes/severities are identical.

    Parameters
    ----------
    rules:
        Rule set to apply.  Defaults to
        :func:`~orthograph.comparison.rules.standard_rules`.
        Pass a custom list to extend or replace the standard behaviour.

    Implementation note
    -------------------
    The public parameter order is ``(profile, graph_definition)`` but the
    internal :func:`_compare_views` call passes them *reversed*:
    ``left = DefinitionView(graph_definition)``,
    ``right = ProfileView(profile)``.

    This intentional inversion aligns with the rule semantics in
    ``rules.py``, where ``left`` is always the *declared* (definition) side
    and ``right`` is the *observed* (profile) side.  Rules use
    ``context.left`` to read declared constraints and ``context.right`` to
    read observed data — the public argument order is just a convenience for
    callers who think in terms of "does my profile satisfy this definition?".
    """
    active = rules if rules is not None else standard_rules()
    return _compare_views(
        DefinitionView(graph_definition), ProfileView(profile), active
    )


def compare_profiles(
    left: GraphProfile,
    right: GraphProfile,
    rules: Sequence[Rule] | None = None,
) -> ValidationResult:
    """Symmetric diff between two :class:`GraphProfile` objects.

    Emits ``INFO`` issues for addresses present on one side only or where a
    measurable attribute (type, endpoints, cardinality) differs.  Uses
    :func:`~orthograph.comparison.diff_rules.diff_rules` by default.
    """
    active = rules if rules is not None else diff_rules()
    return _compare_views(ProfileView(left), ProfileView(right), active)


def compare_definitions(
    left: GraphDefinition,
    right: GraphDefinition,
    rules: Sequence[Rule] | None = None,
) -> ValidationResult:
    """Symmetric diff between two :class:`GraphDefinition` objects.

    Emits ``INFO`` issues for addresses present on one side only or where a
    measurable attribute (type, endpoints, cardinality) differs.  Uses
    :func:`~orthograph.comparison.diff_rules.diff_rules` by default.
    """
    active = rules if rules is not None else diff_rules()
    return _compare_views(DefinitionView(left), DefinitionView(right), active)
