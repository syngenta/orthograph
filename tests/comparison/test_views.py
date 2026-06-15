"""Tests for GraphView Protocol, DefinitionView, and ProfileView (E27.T1)."""

from typing import Optional

from orthograph.comparison.views import DefinitionView, GraphView, ProfileView
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.models import NodeModel, RelationshipModel
from orthograph.graph_definition.property_spec import TypeInfo
from orthograph.graph_profile.models import (
    GraphProfile,
    NodeTypeProfile,
    PropertyProfile,
    RelationshipTypeProfile,
)


class _Person(NodeModel):
    __label__ = "Person"
    name: str
    age: Optional[int] = None


class _Movie(NodeModel):
    __label__ = "Movie"
    title: str


class _ActedIn(RelationshipModel):
    __label__ = "ACTED_IN"
    __source_label__ = "Person"
    __target_label__ = "Movie"
    role: str


_GRAPH_DEF = GraphDefinition(
    name="test",
    node_types=[_Person, _Movie],
    relationship_types=[_ActedIn],
)

_NAME_PROFILE = PropertyProfile(
    name="name", present_count=3, total_count=3, observed_types=["String"]
)
_AGE_PROFILE = PropertyProfile(
    name="age", present_count=2, total_count=3, observed_types=["Long"]
)
_ROLE_PROFILE = PropertyProfile(
    name="role", present_count=5, total_count=5, observed_types=["String"]
)

_GRAPH_PROFILE = GraphProfile(
    source="test",
    node_type_profiles={
        "Person": NodeTypeProfile(
            label="Person",
            count=3,
            property_profiles={"name": _NAME_PROFILE, "age": _AGE_PROFILE},
        ),
        "Movie": NodeTypeProfile(label="Movie", count=2),
    },
    rel_type_profiles={
        "ACTED_IN": RelationshipTypeProfile(
            rel_type="ACTED_IN",
            count=5,
            source_labels={"Person"},
            target_labels={"Movie"},
            property_profiles={"role": _ROLE_PROFILE},
        ),
    },
)


def test_definition_view_satisfies_graph_view_protocol():
    """DefinitionView satisfies the runtime-checkable GraphView Protocol."""
    view = DefinitionView(_GRAPH_DEF)
    assert isinstance(view, GraphView)


def test_profile_view_satisfies_graph_view_protocol():
    """ProfileView satisfies the runtime-checkable GraphView Protocol."""
    view = ProfileView(_GRAPH_PROFILE)
    assert isinstance(view, GraphView)


def test_object_missing_methods_does_not_satisfy_graph_view():
    """An object implementing only node_labels does not satisfy GraphView."""

    class _Incomplete:
        def node_labels(self) -> set[str]:
            return set()

    assert not isinstance(_Incomplete(), GraphView)


def test_definition_view_node_labels():
    """node_labels() returns the set of declared node labels."""
    view = DefinitionView(_GRAPH_DEF)
    assert view.node_labels() == {"Person", "Movie"}


def test_definition_view_relationship_types():
    """relationship_types() returns the set of declared relationship labels."""
    view = DefinitionView(_GRAPH_DEF)
    assert view.relationship_types() == {"ACTED_IN"}


def test_definition_view_node_at_returns_model_class():
    """node_at() returns the NodeModel subclass for a known label."""
    view = DefinitionView(_GRAPH_DEF)
    assert view.node_at("Person") is _Person
    assert view.node_at("Movie") is _Movie


def test_definition_view_node_at_absent_returns_none():
    """node_at() returns None for a label not in the definition."""
    view = DefinitionView(_GRAPH_DEF)
    assert view.node_at("Ghost") is None


def test_definition_view_relationship_at_returns_model_class():
    """relationship_at() returns the RelationshipModel subclass for a known type."""
    view = DefinitionView(_GRAPH_DEF)
    assert view.relationship_at("ACTED_IN") is _ActedIn


def test_definition_view_relationship_at_absent_returns_none():
    """relationship_at() returns None for a type not in the definition."""
    view = DefinitionView(_GRAPH_DEF)
    assert view.relationship_at("DIRECTED") is None


def test_definition_view_node_properties_returns_type_info_dict():
    """node_properties() returns a dict of TypeInfo keyed by property name."""
    view = DefinitionView(_GRAPH_DEF)
    props = view.node_properties("Person")
    assert set(props.keys()) == {"name", "age"}
    assert isinstance(props["name"], TypeInfo)
    assert props["name"].python_type is str
    assert props["name"].is_required is True
    assert isinstance(props["age"], TypeInfo)
    assert props["age"].python_type is int
    assert props["age"].is_required is False


def test_definition_view_node_properties_absent_label_returns_empty():
    """node_properties() returns {} for a label not in the definition."""
    view = DefinitionView(_GRAPH_DEF)
    assert view.node_properties("Ghost") == {}


def test_definition_view_relationship_properties_returns_type_info_dict():
    """relationship_properties() returns a dict of TypeInfo keyed by property name."""
    view = DefinitionView(_GRAPH_DEF)
    props = view.relationship_properties("ACTED_IN")
    assert set(props.keys()) == {"role"}
    assert isinstance(props["role"], TypeInfo)
    assert props["role"].python_type is str


def test_definition_view_relationship_properties_absent_type_returns_empty():
    """relationship_properties() returns {} for a type not in the definition."""
    view = DefinitionView(_GRAPH_DEF)
    assert view.relationship_properties("DIRECTED") == {}


def test_profile_view_node_labels():
    """node_labels() returns the set of observed node labels."""
    view = ProfileView(_GRAPH_PROFILE)
    assert view.node_labels() == {"Person", "Movie"}


def test_profile_view_relationship_types():
    """relationship_types() returns the set of observed relationship types."""
    view = ProfileView(_GRAPH_PROFILE)
    assert view.relationship_types() == {"ACTED_IN"}


def test_profile_view_node_at_returns_node_type_profile():
    """node_at() returns the NodeTypeProfile for a known label."""
    view = ProfileView(_GRAPH_PROFILE)
    assert view.node_at("Person") is _GRAPH_PROFILE.node_type_profiles["Person"]


def test_profile_view_node_at_absent_returns_none():
    """node_at() returns None for a label not in the profile."""
    view = ProfileView(_GRAPH_PROFILE)
    assert view.node_at("Ghost") is None


def test_profile_view_relationship_at_returns_rel_type_profile():
    """relationship_at() returns the RelationshipTypeProfile for a known type."""
    view = ProfileView(_GRAPH_PROFILE)
    assert (
        view.relationship_at("ACTED_IN") is _GRAPH_PROFILE.rel_type_profiles["ACTED_IN"]
    )


def test_profile_view_relationship_at_absent_returns_none():
    """relationship_at() returns None for a type not in the profile."""
    view = ProfileView(_GRAPH_PROFILE)
    assert view.relationship_at("DIRECTED") is None


def test_profile_view_node_properties_returns_property_profile_dict():
    """node_properties() returns the property_profiles dict for a known label."""
    view = ProfileView(_GRAPH_PROFILE)
    props = view.node_properties("Person")
    assert set(props.keys()) == {"name", "age"}
    assert props["name"] is _NAME_PROFILE
    assert props["age"] is _AGE_PROFILE


def test_profile_view_node_properties_absent_label_returns_empty():
    """node_properties() returns {} for a label not in the profile."""
    view = ProfileView(_GRAPH_PROFILE)
    assert view.node_properties("Ghost") == {}


def test_profile_view_node_properties_label_with_no_props_returns_empty():
    """node_properties() returns {} for a label whose profile has no properties."""
    view = ProfileView(_GRAPH_PROFILE)
    assert view.node_properties("Movie") == {}


def test_profile_view_relationship_properties_returns_property_profile_dict():
    """relationship_properties() returns the property_profiles dict for a known type."""
    view = ProfileView(_GRAPH_PROFILE)
    props = view.relationship_properties("ACTED_IN")
    assert set(props.keys()) == {"role"}
    assert props["role"] is _ROLE_PROFILE


def test_profile_view_relationship_properties_absent_type_returns_empty():
    """relationship_properties() returns {} for a type not in the profile."""
    view = ProfileView(_GRAPH_PROFILE)
    assert view.relationship_properties("DIRECTED") == {}


def test_views_module_imports_no_backend():
    """views.py imports no backend (neo4j/memgraph/networkx/gqlalchemy) modules."""
    import subprocess
    import sys

    code = (
        "import sys, orthograph.comparison.views; "
        "b = ('neo4j', 'memgraph', 'networkx', 'gqlalchemy'); "
        "found = [m for m in sys.modules if any(x in m for x in b)]; "
        "print(found)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "[]", (
        f"Backend modules were imported by views.py: {result.stdout.strip()}"
    )


def test_definition_view_filmography_node_labels(filmography_model: GraphDefinition):
    """node_labels() returns all three node labels from the filmography model."""
    view = DefinitionView(filmography_model)
    assert view.node_labels() == {"Person", "Movie", "City"}


def test_definition_view_filmography_relationship_types(
    filmography_model: GraphDefinition,
):
    """relationship_types() returns all three rel types from the filmography model."""
    view = DefinitionView(filmography_model)
    assert view.relationship_types() == {"ACTED_IN", "LIVES_IN", "DIRECTED"}


def test_definition_view_filmography_node_properties_person(
    filmography_model: GraphDefinition,
):
    """node_properties() returns correct TypeInfo for the filmography Person type."""
    view = DefinitionView(filmography_model)
    props = view.node_properties("Person")
    assert "name" in props
    assert "age" in props
    assert "email" in props
    assert props["name"].is_required is True
    assert props["email"].is_required is False
