"""Tests for orthograph.graph_definition.graph_definition -- GraphDefinition."""

from typing import Optional

import pytest

from orthograph.diagnostics.result import GraphValidationError
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.models import (
    Cardinality,
    NodeModel,
    RelationshipModel,
)


# --- Shared node/relationship fixtures ---


class Person(NodeModel):
    __label__ = "Person"
    __uid_field__ = "name"

    name: str
    age: int
    email: Optional[str] = None


class Movie(NodeModel):
    __label__ = "Movie"
    __uid_field__ = "title"

    title: str
    year: int


class City(NodeModel):
    __label__ = "City"

    name: str


class ActedIn(RelationshipModel):
    __label__ = "ACTED_IN"
    __source_label__ = "Person"
    __target_label__ = "Movie"
    __source_cardinality__ = Cardinality.ZERO_OR_MORE
    __target_cardinality__ = Cardinality.ZERO_OR_MORE

    role: str


class Directed(RelationshipModel):
    __label__ = "DIRECTED"
    __source_label__ = "Person"
    __target_label__ = "Movie"


class LivesIn(RelationshipModel):
    __label__ = "LIVES_IN"
    __source_label__ = "Person"
    __target_label__ = "City"
    __source_cardinality__ = Cardinality.ONE
    __target_cardinality__ = Cardinality.ZERO_OR_MORE


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


class Company(NodeModel):
    __label__ = "Company"
    __uid_field__ = "name"
    name: str


class FriendOf(RelationshipModel):
    __label__ = "FRIEND_OF"
    __source_label__ = "Person"
    __target_label__ = "Person"
    __directed__ = False


class Collaborates(RelationshipModel):
    __label__ = "COLLABORATES"
    __source_label__ = "Person"
    __target_label__ = "Company"
    __directed__ = False


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
