"""Tests for orthograph.graph_definition.graph_definition -- GraphDefinition."""

from typing import ClassVar

import pytest

from orthograph.diagnostics.result import GraphValidationError
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.models import (
    CardinalitySpec,
    ConditionalCardinality,
    ConditionalRule,
    NodeModel,
    PropMatch,
    RelationshipModel,
)
from tests.graph_definition.conftest import (  # noqa: F401 — fixtures auto-used by pytest
    ActedIn,
    City,
    Collaborates,
    Company,
    Directed,
    FriendOf,
    LivesIn,
    Movie,
    Person,
)


# --- GraphDefinition creation tests ---


def test_graph_data_model_create_simple():
    graph_definition = GraphDefinition(
        name="Filmography",
        node_types=[Person, Movie],
        relationship_types=[ActedIn, Directed],
    )
    assert graph_definition.name == "Filmography"
    assert len(graph_definition.node_types) == 2
    assert len(graph_definition.relationship_types) == 2


def test_graph_data_model_create_with_version():
    graph_definition = GraphDefinition(
        name="Test",
        version="1.0.0",
        node_types=[Person],
        relationship_types=[],
    )
    assert graph_definition.version == "1.0.0"


def test_graph_data_model_create_empty():
    graph_definition = GraphDefinition(
        name="Empty",
        node_types=[],
        relationship_types=[],
    )
    assert graph_definition.name == "Empty"
    assert len(graph_definition.node_types) == 0


def test_graph_data_model_node_types_accessible_by_label():
    graph_definition = GraphDefinition(
        name="Test",
        node_types=[Person, Movie],
        relationship_types=[],
    )
    assert graph_definition.get_node_type("Person") is Person
    assert graph_definition.get_node_type("Movie") is Movie
    assert graph_definition.get_node_type("NonExistent") is None


def test_graph_data_model_relationship_types_accessible_by_label():
    graph_definition = GraphDefinition(
        name="Test",
        node_types=[Person, Movie],
        relationship_types=[ActedIn, Directed],
    )
    assert graph_definition.get_relationship_type("ACTED_IN") is ActedIn
    assert graph_definition.get_relationship_type("DIRECTED") is Directed
    assert graph_definition.get_relationship_type("FAKE") is None


def test_graph_data_model_node_labels():
    graph_definition = GraphDefinition(
        name="Test",
        node_types=[Person, Movie, City],
        relationship_types=[],
    )
    assert graph_definition.node_labels == {"Person", "Movie", "City"}


def test_graph_data_model_relationship_labels():
    graph_definition = GraphDefinition(
        name="Test",
        node_types=[Person, Movie],
        relationship_types=[ActedIn, Directed],
    )
    assert graph_definition.relationship_labels == {"ACTED_IN", "DIRECTED"}


# --- GraphDefinition structural validation tests ---


def test_graph_data_model_valid_passes():
    graph_definition = GraphDefinition(
        name="Valid",
        node_types=[Person, Movie],
        relationship_types=[ActedIn, Directed],
    )
    result = graph_definition.validate_structure()
    assert result.is_valid


def test_graph_data_model_duplicate_node_labels_rejected():
    class PersonDup(NodeModel):
        __label__ = "Person"
        name: str

    with pytest.raises(GraphValidationError, match="Duplicate node label"):
        GraphDefinition(
            name="Bad",
            node_types=[Person, PersonDup],
            relationship_types=[],
        )


def test_graph_data_model_duplicate_relationship_labels_rejected():
    class ActedInDup(RelationshipModel):
        __label__ = "ACTED_IN"
        __source_label__ = "Person"
        __target_label__ = "Movie"

    with pytest.raises(GraphValidationError, match="Duplicate relationship label"):
        GraphDefinition(
            name="Bad",
            node_types=[Person, Movie],
            relationship_types=[ActedIn, ActedInDup],
        )


def test_graph_data_model_undefined_source_node_type_rejected():
    # ActedIn references Person, but we only include Movie
    with pytest.raises(GraphValidationError, match="Person"):
        GraphDefinition(
            name="Bad",
            node_types=[Movie],
            relationship_types=[ActedIn],
        )


def test_graph_data_model_undefined_target_node_type_rejected():
    # ActedIn references Movie, but we only include Person
    with pytest.raises(GraphValidationError, match="Movie"):
        GraphDefinition(
            name="Bad",
            node_types=[Person],
            relationship_types=[ActedIn],
        )


def test_graph_data_model_isolated_node_warning():
    graph_definition = GraphDefinition(
        name="WithIsolated",
        node_types=[Person, Movie, City],
        relationship_types=[ActedIn],
    )
    result = graph_definition.validate_structure()
    assert result.is_valid  # warnings don't invalidate
    assert len(result.warnings) == 1
    assert "City" in result.warnings[0].message


def test_graph_data_model_no_isolated_warning_for_optional_nodes():
    class OptCity(NodeModel):
        __label__ = "OptCity"
        __optional__ = True
        name: str

    graph_definition = GraphDefinition(
        name="WithOptional",
        node_types=[Person, Movie, OptCity],
        relationship_types=[ActedIn],
    )
    result = graph_definition.validate_structure()
    assert result.is_valid
    # Optional isolated nodes should still warn
    assert len(result.warnings) == 1


# --- GraphDefinition relationships for node tests ---


def test_graph_data_model_get_outgoing_relationships():
    graph_definition = GraphDefinition(
        name="Test",
        node_types=[Person, Movie, City],
        relationship_types=[ActedIn, Directed, LivesIn],
    )
    outgoing = graph_definition.get_outgoing_relationship_types(Person)
    labels = {r.__label__ for r in outgoing}
    assert labels == {"ACTED_IN", "DIRECTED", "LIVES_IN"}


def test_graph_data_model_get_incoming_relationships():
    graph_definition = GraphDefinition(
        name="Test",
        node_types=[Person, Movie, City],
        relationship_types=[ActedIn, Directed, LivesIn],
    )
    incoming = graph_definition.get_incoming_relationship_types(Movie)
    labels = {r.__label__ for r in incoming}
    assert labels == {"ACTED_IN", "DIRECTED"}


def test_graph_data_model_no_relationships_for_isolated_node():
    graph_definition = GraphDefinition(
        name="Test",
        node_types=[Person, Movie, City],
        relationship_types=[ActedIn],
    )
    outgoing = graph_definition.get_outgoing_relationship_types(City)
    assert len(outgoing) == 0


# --- GraphDefinition enum generation tests ---


def test_graph_data_model_node_label_enum():
    graph_definition = GraphDefinition(
        name="Test",
        node_types=[Person, Movie],
        relationship_types=[],
    )
    enum = graph_definition.get_node_label_enum()
    assert set(enum.__members__.keys()) == {"Person", "Movie"}
    assert enum.Person.value == "Person"


def test_graph_data_model_relationship_label_enum():
    graph_definition = GraphDefinition(
        name="Test",
        node_types=[Person, Movie],
        relationship_types=[ActedIn, Directed],
    )
    enum = graph_definition.get_relationship_label_enum()
    assert set(enum.__members__.keys()) == {"ACTED_IN", "DIRECTED"}
    assert enum.ACTED_IN.value == "ACTED_IN"


# --- Undirected relationship tests ---


def test_undirected_same_type_outgoing_includes_both_directions():
    """Undirected self-referencing rel appears in outgoing for the node type."""
    graph_definition = GraphDefinition(
        name="Social",
        node_types=[Person],
        relationship_types=[FriendOf],
    )
    outgoing = graph_definition.get_outgoing_relationship_types(Person)
    labels = {r.__label__ for r in outgoing}
    assert "FRIEND_OF" in labels


def test_undirected_same_type_incoming_includes_both_directions():
    """Undirected self-referencing rel appears in incoming for the node type."""
    graph_definition = GraphDefinition(
        name="Social",
        node_types=[Person],
        relationship_types=[FriendOf],
    )
    incoming = graph_definition.get_incoming_relationship_types(Person)
    labels = {r.__label__ for r in incoming}
    assert "FRIEND_OF" in labels


def test_undirected_cross_type_outgoing_from_source():
    graph_definition = GraphDefinition(
        name="Cross",
        node_types=[Person, Company],
        relationship_types=[Collaborates],
    )
    outgoing = graph_definition.get_outgoing_relationship_types(Person)
    labels = {r.__label__ for r in outgoing}
    assert "COLLABORATES" in labels


def test_undirected_cross_type_outgoing_from_target():
    """Undirected cross-type: target_type also sees it as outgoing."""
    graph_definition = GraphDefinition(
        name="Cross",
        node_types=[Person, Company],
        relationship_types=[Collaborates],
    )
    outgoing = graph_definition.get_outgoing_relationship_types(Company)
    labels = {r.__label__ for r in outgoing}
    assert "COLLABORATES" in labels


def test_undirected_cross_type_incoming_from_source():
    """Undirected cross-type: source_type also sees it as incoming."""
    graph_definition = GraphDefinition(
        name="Cross",
        node_types=[Person, Company],
        relationship_types=[Collaborates],
    )
    incoming = graph_definition.get_incoming_relationship_types(Person)
    labels = {r.__label__ for r in incoming}
    assert "COLLABORATES" in labels


def test_undirected_cross_type_incoming_from_target():
    graph_definition = GraphDefinition(
        name="Cross",
        node_types=[Person, Company],
        relationship_types=[Collaborates],
    )
    incoming = graph_definition.get_incoming_relationship_types(Company)
    labels = {r.__label__ for r in incoming}
    assert "COLLABORATES" in labels


def test_undirected_same_type_no_duplicates():
    """For self-referencing undirected, should not duplicate entries."""
    graph_definition = GraphDefinition(
        name="Social",
        node_types=[Person],
        relationship_types=[FriendOf],
    )
    outgoing = graph_definition.get_outgoing_relationship_types(Person)
    # source_type == target_type == Person, first branch catches it,
    # second elif won't trigger (since source_type is also Person)
    labels = [r.__label__ for r in outgoing]
    assert labels.count("FRIEND_OF") == 1


def test_directed_not_affected_by_undirected_logic():
    """Directed relationships remain strictly directional."""
    graph_definition = GraphDefinition(
        name="Test",
        node_types=[Person, Movie],
        relationship_types=[ActedIn],
    )
    # Movie should not see ACTED_IN as outgoing (only incoming)
    outgoing_movie = graph_definition.get_outgoing_relationship_types(Movie)
    assert all(r.__label__ != "ACTED_IN" for r in outgoing_movie)
    # Person should not see ACTED_IN as incoming
    incoming_person = graph_definition.get_incoming_relationship_types(Person)
    assert all(r.__label__ != "ACTED_IN" for r in incoming_person)


# --- Immutability tests ---


def test_graph_definition_is_frozen_after_construction():
    """GraphDefinition should be immutable after __init__ completes."""
    graph_definition = GraphDefinition(
        name="Filmography",
        node_types=[Person, Movie],
        relationship_types=[ActedIn],
    )

    # Attempting to modify any attribute should raise AttributeError
    with pytest.raises(AttributeError, match="GraphDefinition is frozen"):
        graph_definition.name = "OtherName"


def test_graph_definition_cannot_modify_version():
    """Modifying version after construction should raise AttributeError."""
    graph_definition = GraphDefinition(
        name="Test",
        version="1.0.0",
        node_types=[Person],
        relationship_types=[],
    )

    with pytest.raises(AttributeError, match="GraphDefinition is frozen"):
        graph_definition.version = "2.0.0"


def test_graph_definition_cannot_modify_node_types():
    """Modifying node_types list after construction should raise AttributeError."""
    graph_definition = GraphDefinition(
        name="Filmography",
        node_types=[Person, Movie],
        relationship_types=[],
    )

    with pytest.raises(AttributeError, match="GraphDefinition is frozen"):
        graph_definition.node_types = []


def test_graph_definition_cannot_modify_relationship_types():
    """Modifying relationship_types after construction should raise AttributeError."""
    graph_definition = GraphDefinition(
        name="Filmography",
        node_types=[Person, Movie],
        relationship_types=[ActedIn],
    )

    with pytest.raises(AttributeError, match="GraphDefinition is frozen"):
        graph_definition.relationship_types = []


def test_graph_definition_cannot_add_private_attributes():
    """Adding new attributes after construction should raise AttributeError."""
    graph_definition = GraphDefinition(
        name="Filmography",
        node_types=[Person],
        relationship_types=[],
    )

    with pytest.raises(AttributeError, match="GraphDefinition is frozen"):
        graph_definition.custom_field = "value"


def test_graph_definition_attributes_accessible_before_freeze():
    """Attributes should be readable even though they are frozen."""
    graph_definition = GraphDefinition(
        name="Filmography",
        version="1.0.0",
        node_types=[Person, Movie],
        relationship_types=[ActedIn, Directed],
    )

    assert graph_definition.name == "Filmography"
    assert graph_definition.version == "1.0.0"
    assert len(graph_definition.node_types) == 2
    assert len(graph_definition.relationship_types) == 2


# ---------------------------------------------------------------------------
# E40.4 — Conditional cardinality definition-time checks
# ---------------------------------------------------------------------------

# Shared node types for cardinality check tests
# Using the movie domain: Director directs Movie(s).
# Both nodes carry a required ``kind`` property used as the cardinality
# discriminator (e.g. director kind: "feature"/"documentary"/"short";
# movie kind: "blockbuster"/"indie"/"none").


class Director(NodeModel):
    """Scope: Director node with required 'kind' property (style of directing)."""

    __label__ = "Director"
    kind: str


class Film(NodeModel):
    """Scope: Film node with required 'kind' property (production type)."""

    __label__ = "Film"
    kind: str


class FilmOptKind(NodeModel):
    """Scope: Film-like node with optional 'kind' (discriminator tests)."""

    __label__ = "FilmOptKind"
    kind: str | None = None


def _adr029_conditional() -> ConditionalCardinality:
    """Build the ADR-029 deciding-scenario ConditionalCardinality for DIRECTED.

    Rules mirror the cardinality-spec deciding table:
    - (documentary, documentary) → 1..2  (co-directed documentaries)
    - (short, none) → ZERO               (short-format directors skip this film kind)
    - (feature, none) → ZERO             (feature directors skip this film kind)
    """
    return ConditionalCardinality(
        rules=(
            ConditionalRule(
                source=PropMatch({"kind": "documentary"}),
                target=PropMatch({"kind": "documentary"}),
                spec=CardinalitySpec(min=1, max=2),
            ),
            ConditionalRule(
                source=PropMatch({"kind": "short"}),
                target=PropMatch({"kind": "none"}),
                spec="0..0",
            ),
            ConditionalRule(
                source=PropMatch({"kind": "feature"}),
                target=PropMatch({"kind": "none"}),
                spec="0..0",
            ),
        ),
        default="0..*",
    )


def test_conditional_cardinality_valid_schema_constructs_cleanly():
    """Scope: A valid ConditionalCardinality on DIRECTED constructs without errors."""

    class Directed(RelationshipModel):
        __label__ = "DIRECTED"
        __source_label__ = "Director"
        __target_label__ = "Film"
        __source_cardinality__: ClassVar[CardinalitySpec | ConditionalCardinality] = (
            _adr029_conditional()
        )

    # Should not raise
    gd = GraphDefinition(
        name="Filmography",
        node_types=[Director, Film],
        relationship_types=[Directed],
    )
    assert gd is not None


def test_conditional_cardinality_unknown_discriminator_key_rejected():
    """Scope: Unknown discriminator key raises CARDINALITY_UNKNOWN_DISCRIMINATOR."""

    class Directed(RelationshipModel):
        __label__ = "DIRECTED"
        __source_label__ = "Director"
        __target_label__ = "Film"
        __source_cardinality__: ClassVar[CardinalitySpec | ConditionalCardinality] = (
            ConditionalCardinality(
                rules=(
                    ConditionalRule(
                        source=PropMatch({"nonexistent_prop": "short"}),
                        target=PropMatch({"kind": "none"}),
                        spec="0..0",
                    ),
                ),
                default="0..*",
            )
        )

    with pytest.raises(GraphValidationError) as exc_info:
        GraphDefinition(
            name="Bad",
            node_types=[Director, Film],
            relationship_types=[Directed],
        )
    codes = [i.code for i in exc_info.value.issues]
    assert "CARDINALITY_UNKNOWN_DISCRIMINATOR" in codes


def test_conditional_cardinality_optional_discriminator_rejected():
    """Scope: Optional discriminator raises CARDINALITY_DISCRIMINATOR_OPTIONAL."""

    class Directed(RelationshipModel):
        __label__ = "DIRECTED"
        __source_label__ = "Director"
        __target_label__ = "FilmOptKind"
        __target_cardinality__: ClassVar[CardinalitySpec | ConditionalCardinality] = (
            ConditionalCardinality(
                rules=(
                    ConditionalRule(
                        source=PropMatch({"kind": "documentary"}),
                        target=PropMatch({"kind": "documentary"}),
                        spec=CardinalitySpec(min=1, max=2),
                    ),
                ),
                default="0..*",
            )
        )

    with pytest.raises(GraphValidationError) as exc_info:
        GraphDefinition(
            name="Bad",
            node_types=[Director, FilmOptKind],
            relationship_types=[Directed],
        )
    issues = exc_info.value.issues
    codes = [i.code for i in issues]
    assert "CARDINALITY_DISCRIMINATOR_OPTIONAL" in codes
    msgs = " ".join(i.message for i in issues)
    assert "kind" in msgs


def test_conditional_cardinality_duplicate_rule_key_rejected():
    """Scope: Identical (source, target) predicates raise CARDINALITY_DUPLICATE_RULE."""

    # Duplicates are expressible by explicit construction as two ConditionalRule
    # entries sharing identical source/target predicates.
    dup_card = ConditionalCardinality(
        rules=(
            ConditionalRule(
                source=PropMatch({"kind": "short"}),
                target=PropMatch({"kind": "none"}),
                spec="0..0",
            ),
            ConditionalRule(
                source=PropMatch({"kind": "short"}),
                target=PropMatch({"kind": "none"}),
                spec=CardinalitySpec(min=1, max=1),
            ),
        ),
        default="0..*",
    )

    class DirectedDup(RelationshipModel):
        __label__ = "DIRECTED_DUP"
        __source_label__ = "Director"
        __target_label__ = "Film"
        __source_cardinality__: ClassVar[CardinalitySpec | ConditionalCardinality] = (
            dup_card
        )

    with pytest.raises(GraphValidationError) as exc_info:
        GraphDefinition(
            name="Bad",
            node_types=[Director, Film],
            relationship_types=[DirectedDup],
        )
    codes = [i.code for i in exc_info.value.issues]
    assert "CARDINALITY_DUPLICATE_RULE" in codes


def test_conditional_cardinality_ambiguous_overlap_rejected():
    """Scope: Equal-specificity co-matchable rules raise CARDINALITY_AMBIGUOUS_RULES."""
    from orthograph.graph_definition.models import ConditionalRule, PropMatch

    # ("short","*") spec=1 + ("*","none") spec=1 → equal, can co-match
    ambiguous_card = ConditionalCardinality(
        rules=(
            ConditionalRule(
                source=PropMatch({"kind": "short"}),
                target=PropMatch(),
                spec="0..0",
            ),
            ConditionalRule(
                source=PropMatch(),
                target=PropMatch({"kind": "none"}),
                spec=CardinalitySpec(min=1, max=1),
            ),
        ),
        default="0..*",
    )

    class DirectedAmb(RelationshipModel):
        __label__ = "DIRECTED_AMB"
        __source_label__ = "Director"
        __target_label__ = "Film"
        __source_cardinality__: ClassVar[CardinalitySpec | ConditionalCardinality] = (
            ambiguous_card
        )

    with pytest.raises(GraphValidationError) as exc_info:
        GraphDefinition(
            name="Bad",
            node_types=[Director, Film],
            relationship_types=[DirectedAmb],
        )
    codes = [i.code for i in exc_info.value.issues]
    assert "CARDINALITY_AMBIGUOUS_RULES" in codes


def test_conditional_cardinality_narrow_overrides_broad_allowed():
    """Scope: ('short','*') + ('short','none') allowed — narrow-overrides-broad."""
    from orthograph.graph_definition.models import ConditionalRule, PropMatch

    # ("short","*") spec=1, ("short","none") spec=2 → different scores → no ambiguity
    card = ConditionalCardinality(
        rules=(
            ConditionalRule(
                source=PropMatch({"kind": "short"}),
                target=PropMatch(),
                spec="0..0",
            ),
            ConditionalRule(
                source=PropMatch({"kind": "short"}),
                target=PropMatch({"kind": "none"}),
                spec=CardinalitySpec(min=1, max=1),
            ),
        ),
        default="0..*",
    )

    class DirectedNarrow(RelationshipModel):
        __label__ = "DIRECTED_NARROW"
        __source_label__ = "Director"
        __target_label__ = "Film"
        __source_cardinality__: ClassVar[CardinalitySpec | ConditionalCardinality] = (
            card
        )

    # Must NOT raise
    gd = GraphDefinition(
        name="OK",
        node_types=[Director, Film],
        relationship_types=[DirectedNarrow],
    )
    assert gd is not None


def test_conditional_cardinality_catchall_rule_rejected():
    """Scope: A (*, *) catch-all rule raises CARDINALITY_CATCHALL_RULE."""
    from orthograph.graph_definition.models import ConditionalRule, PropMatch

    catchall_card = ConditionalCardinality(
        rules=(
            ConditionalRule(
                source=PropMatch(),
                target=PropMatch(),
                spec="0..0",
            ),
        ),
        default="0..*",
    )

    class DirectedCatchall(RelationshipModel):
        __label__ = "DIRECTED_CATCHALL"
        __source_label__ = "Director"
        __target_label__ = "Film"
        __source_cardinality__: ClassVar[CardinalitySpec | ConditionalCardinality] = (
            catchall_card
        )

    with pytest.raises(GraphValidationError) as exc_info:
        GraphDefinition(
            name="Bad",
            node_types=[Director, Film],
            relationship_types=[DirectedCatchall],
        )
    codes = [i.code for i in exc_info.value.issues]
    assert "CARDINALITY_CATCHALL_RULE" in codes
