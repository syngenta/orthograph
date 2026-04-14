"""Tests for orthograph.extensions.validation -- validate_profile()."""

from orthograph.core.graph_data_model import GraphDataModel
from orthograph.extensions.models import (
    CardinalityStats,
    GraphProfile,
    NodeTypeProfile,
    PropertyProfile,
    RelationshipTypeProfile,
)
from orthograph.extensions.validation import db_type_to_python, validate_profile


# --- Helper to build complete matching profiles ---


def _complete_profile(model: GraphDataModel) -> GraphProfile:
    """Build a GraphProfile that perfectly matches a model."""
    node_profiles: dict[str, NodeTypeProfile] = {}
    for nt in model.node_types:
        specs = nt.get_property_specs()
        props = {
            name: PropertyProfile(
                name=name,
                present_count=100,
                total_count=100,
                observed_types=[info.python_type.__name__],
            )
            for name, info in specs.items()
        }
        node_profiles[nt.__label__] = NodeTypeProfile(
            label=nt.__label__, count=100, property_profiles=props
        )

    rel_profiles: dict[str, RelationshipTypeProfile] = {}
    for rt in model.relationship_types:
        specs = rt.get_property_specs()
        props = {
            name: PropertyProfile(
                name=name,
                present_count=200,
                total_count=200,
                observed_types=[info.python_type.__name__],
            )
            for name, info in specs.items()
        }
        rel_profiles[rt.__label__] = RelationshipTypeProfile(
            rel_type=rt.__label__,
            count=200,
            source_labels={rt.__source_type__.__label__},
            target_labels={rt.__target_type__.__label__},
            property_profiles=props,
        )

    return GraphProfile(
        source="test",
        node_type_profiles=node_profiles,
        rel_type_profiles=rel_profiles,
    )


# --- db_type_to_python ---


def test_db_type_to_python_known():
    assert db_type_to_python("String") is str
    assert db_type_to_python("str") is str
    assert db_type_to_python("Long") is int
    assert db_type_to_python("int") is int
    assert db_type_to_python("Double") is float
    assert db_type_to_python("Boolean") is bool


def test_db_type_to_python_unknown():
    assert db_type_to_python("Point3D") is None
    assert db_type_to_python("Duration") is None


# --- Perfect match ---


def test_validate_profile_perfect_match(filmography_model: GraphDataModel):
    profile = _complete_profile(filmography_model)
    result = validate_profile(profile, filmography_model)
    assert result.is_valid, [str(e) for e in result.errors]


# --- Node label checks ---


def test_validate_profile_missing_node_label(
    filmography_model: GraphDataModel,
):
    profile = _complete_profile(filmography_model)
    # Remove City from profile
    profiles = dict(profile.node_type_profiles)
    del profiles["City"]
    profile = profile.model_copy(update={"node_type_profiles": profiles})
    result = validate_profile(profile, filmography_model)
    assert not result.is_valid
    assert any(e.code == "MISSING_NODE_LABEL" for e in result.errors)


def test_validate_profile_unexpected_node_label(
    filmography_model: GraphDataModel,
):
    profile = _complete_profile(filmography_model)
    profiles = dict(profile.node_type_profiles)
    profiles["Animal"] = NodeTypeProfile(label="Animal", count=5)
    profile = profile.model_copy(update={"node_type_profiles": profiles})
    result = validate_profile(profile, filmography_model)
    assert result.is_valid  # warnings don't invalidate
    assert any(e.code == "UNEXPECTED_NODE_LABEL" for e in result.warnings)


# --- Relationship type checks ---


def test_validate_profile_missing_rel_type(
    filmography_model: GraphDataModel,
):
    profile = _complete_profile(filmography_model)
    profiles = dict(profile.rel_type_profiles)
    del profiles["ACTED_IN"]
    profile = profile.model_copy(update={"rel_type_profiles": profiles})
    result = validate_profile(profile, filmography_model)
    assert not result.is_valid
    assert any(e.code == "MISSING_REL_TYPE" for e in result.errors)


def test_validate_profile_unexpected_rel_type(
    filmography_model: GraphDataModel,
):
    profile = _complete_profile(filmography_model)
    profiles = dict(profile.rel_type_profiles)
    profiles["FRIEND_OF"] = RelationshipTypeProfile(rel_type="FRIEND_OF", count=10)
    profile = profile.model_copy(update={"rel_type_profiles": profiles})
    result = validate_profile(profile, filmography_model)
    assert result.is_valid
    assert any(e.code == "UNEXPECTED_REL_TYPE" for e in result.warnings)


# --- Property checks ---


def test_validate_profile_missing_required_property(
    filmography_model: GraphDataModel,
):
    profile = _complete_profile(filmography_model)
    profiles = dict(profile.node_type_profiles)
    person = profiles["Person"]
    person_props = dict(person.property_profiles)
    del person_props["age"]
    profiles["Person"] = person.model_copy(update={"property_profiles": person_props})
    profile = profile.model_copy(update={"node_type_profiles": profiles})
    result = validate_profile(profile, filmography_model)
    assert not result.is_valid
    assert any(e.code == "MISSING_PROPERTY" for e in result.errors)


def test_validate_profile_property_type_mismatch(
    filmography_model: GraphDataModel,
):
    profile = _complete_profile(filmography_model)
    profiles = dict(profile.node_type_profiles)
    person = profiles["Person"]
    person_props = dict(person.property_profiles)
    person_props["age"] = PropertyProfile(
        name="age",
        present_count=100,
        total_count=100,
        observed_types=["String"],  # should be int
    )
    profiles["Person"] = person.model_copy(update={"property_profiles": person_props})
    profile = profile.model_copy(update={"node_type_profiles": profiles})
    result = validate_profile(profile, filmography_model)
    assert not result.is_valid
    assert any(e.code == "PROPERTY_TYPE_MISMATCH" for e in result.errors)


def test_validate_profile_property_incomplete(
    filmography_model: GraphDataModel,
):
    profile = _complete_profile(filmography_model)
    profiles = dict(profile.node_type_profiles)
    person = profiles["Person"]
    person_props = dict(person.property_profiles)
    person_props["name"] = PropertyProfile(
        name="name",
        present_count=80,
        total_count=100,
        observed_types=["str"],
    )
    profiles["Person"] = person.model_copy(update={"property_profiles": person_props})
    profile = profile.model_copy(update={"node_type_profiles": profiles})
    result = validate_profile(profile, filmography_model)
    assert result.is_valid  # warning, not error
    assert any(e.code == "PROPERTY_INCOMPLETE" for e in result.warnings)


def test_validate_profile_unexpected_property(
    filmography_model: GraphDataModel,
):
    profile = _complete_profile(filmography_model)
    profiles = dict(profile.node_type_profiles)
    person = profiles["Person"]
    person_props = dict(person.property_profiles)
    person_props["phone"] = PropertyProfile(
        name="phone",
        present_count=30,
        total_count=100,
    )
    profiles["Person"] = person.model_copy(update={"property_profiles": person_props})
    profile = profile.model_copy(update={"node_type_profiles": profiles})
    result = validate_profile(profile, filmography_model)
    assert result.is_valid
    assert any(e.code == "UNEXPECTED_PROPERTY" for e in result.issues)


# --- Endpoint checks ---


def test_validate_profile_invalid_endpoint(
    filmography_model: GraphDataModel,
):
    profile = _complete_profile(filmography_model)
    profiles = dict(profile.rel_type_profiles)
    acted_in = profiles["ACTED_IN"]
    profiles["ACTED_IN"] = acted_in.model_copy(
        update={"source_labels": {"City"}}  # wrong source
    )
    profile = profile.model_copy(update={"rel_type_profiles": profiles})
    result = validate_profile(profile, filmography_model)
    assert not result.is_valid
    assert any(e.code == "INVALID_ENDPOINT" for e in result.errors)


# --- Cardinality checks ---


def test_validate_profile_cardinality_violation(
    filmography_model: GraphDataModel,
):
    profile = _complete_profile(filmography_model)
    profiles = dict(profile.rel_type_profiles)
    lives_in = profiles["LIVES_IN"]
    profiles["LIVES_IN"] = lives_in.model_copy(
        update={
            "cardinality_stats": CardinalityStats(
                min_degree=0,  # violates Cardinality.ONE (min=1)
                max_degree=3,
                avg_degree=1.5,
                sample_size=100,
            )
        }
    )
    profile = profile.model_copy(update={"rel_type_profiles": profiles})
    result = validate_profile(profile, filmography_model)
    assert not result.is_valid
    assert any(e.code == "CARDINALITY_VIOLATION" for e in result.errors)


def test_validate_profile_no_cardinality_stats_skipped(
    filmography_model: GraphDataModel,
):
    """When cardinality stats are None, no cardinality check is performed."""
    profile = _complete_profile(filmography_model)
    # _complete_profile already has cardinality_stats=None
    result = validate_profile(profile, filmography_model)
    assert not any(e.code == "CARDINALITY_VIOLATION" for e in result.issues)


# --- Undirected relationship endpoint validation tests ---


def test_validate_profile_undirected_cross_type_forward_valid():
    """Undirected cross-type: forward source/target is valid."""
    from orthograph.core.node_model import NodeModel
    from orthograph.core.relationship_model import RelationshipModel

    class UPerson(NodeModel):
        __label__ = "UPerson"
        __uid_field__ = "name"
        name: str

    class UCompany(NodeModel):
        __label__ = "UCompany"
        __uid_field__ = "name"
        name: str

    class UCollaborates(RelationshipModel):
        __label__ = "U_COLLABORATES"
        __source_type__ = UPerson
        __target_type__ = UCompany
        __directed__ = False

    model = GraphDataModel(
        name="Cross",
        node_types=[UPerson, UCompany],
        relationship_types=[UCollaborates],
    )
    profile = _complete_profile(model)
    result = validate_profile(profile, model)
    assert result.is_valid, [str(e) for e in result.errors]


def test_validate_profile_undirected_cross_type_reverse_valid():
    """Undirected cross-type: reversed source/target should also be valid."""
    from orthograph.core.node_model import NodeModel
    from orthograph.core.relationship_model import RelationshipModel

    class RPerson(NodeModel):
        __label__ = "RPerson"
        __uid_field__ = "name"
        name: str

    class RCompany(NodeModel):
        __label__ = "RCompany"
        __uid_field__ = "name"
        name: str

    class RCollaborates(RelationshipModel):
        __label__ = "R_COLLABORATES"
        __source_type__ = RPerson
        __target_type__ = RCompany
        __directed__ = False

    model = GraphDataModel(
        name="Cross",
        node_types=[RPerson, RCompany],
        relationship_types=[RCollaborates],
    )

    # Build profile with reversed endpoints
    rel_profiles = {
        "R_COLLABORATES": RelationshipTypeProfile(
            rel_type="R_COLLABORATES",
            count=200,
            source_labels={"RCompany"},  # reversed
            target_labels={"RPerson"},  # reversed
        ),
    }
    node_profiles = {
        "RPerson": NodeTypeProfile(
            label="RPerson",
            count=100,
            property_profiles={
                "name": PropertyProfile(
                    name="name",
                    present_count=100,
                    total_count=100,
                    observed_types=["str"],
                ),
            },
        ),
        "RCompany": NodeTypeProfile(
            label="RCompany",
            count=100,
            property_profiles={
                "name": PropertyProfile(
                    name="name",
                    present_count=100,
                    total_count=100,
                    observed_types=["str"],
                ),
            },
        ),
    }
    profile = GraphProfile(
        source="test",
        node_type_profiles=node_profiles,
        rel_type_profiles=rel_profiles,
    )
    result = validate_profile(profile, model)
    # Should not have INVALID_ENDPOINT errors
    assert not any(e.code == "INVALID_ENDPOINT" for e in result.errors)


def test_validate_profile_directed_cross_type_reverse_rejected():
    """Directed: reversed source/target is rejected."""
    from orthograph.core.node_model import NodeModel
    from orthograph.core.relationship_model import RelationshipModel

    class DPerson(NodeModel):
        __label__ = "DPerson"
        __uid_field__ = "name"
        name: str

    class DMovie(NodeModel):
        __label__ = "DMovie"
        __uid_field__ = "title"
        title: str

    class DActedIn(RelationshipModel):
        __label__ = "D_ACTED_IN"
        __source_type__ = DPerson
        __target_type__ = DMovie
        __directed__ = True

    model = GraphDataModel(
        name="Dir",
        node_types=[DPerson, DMovie],
        relationship_types=[DActedIn],
    )

    rel_profiles = {
        "D_ACTED_IN": RelationshipTypeProfile(
            rel_type="D_ACTED_IN",
            count=200,
            source_labels={"DMovie"},  # wrong
            target_labels={"DPerson"},  # wrong
        ),
    }
    node_profiles = {
        "DPerson": NodeTypeProfile(
            label="DPerson",
            count=100,
            property_profiles={
                "name": PropertyProfile(
                    name="name",
                    present_count=100,
                    total_count=100,
                    observed_types=["str"],
                ),
            },
        ),
        "DMovie": NodeTypeProfile(
            label="DMovie",
            count=100,
            property_profiles={
                "title": PropertyProfile(
                    name="title",
                    present_count=100,
                    total_count=100,
                    observed_types=["str"],
                ),
            },
        ),
    }
    profile = GraphProfile(
        source="test",
        node_type_profiles=node_profiles,
        rel_type_profiles=rel_profiles,
    )
    result = validate_profile(profile, model)
    assert any(e.code == "INVALID_ENDPOINT" for e in result.errors)
