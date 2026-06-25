"""Tests for orthograph.comparison.engine -- compare_profile_to_definition()."""

from orthograph.comparison.engine import (
    compare_profile_to_definition,
    db_type_to_python,
)
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_profile.models import (
    CardinalityStats,
    GraphProfile,
    NodeTypeProfile,
    PropertyProfile,
    RelationshipTypeProfile,
)


# --- Helper to build complete matching profiles ---


def _complete_profile(graph_definition: GraphDefinition) -> GraphProfile:
    """Build a GraphProfile that perfectly matches a model."""
    node_profiles: dict[str, NodeTypeProfile] = {}
    for nt in graph_definition.node_types:
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
    for rt in graph_definition.relationship_types:
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
        rel_profiles[rt.rel_key()] = RelationshipTypeProfile(
            rel_type=rt.__label__,
            count=200,
            source_label=rt.__source_label__,
            target_label=rt.__target_label__,
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


def test_compare_perfect_match(filmography_model: GraphDefinition):
    profile = _complete_profile(filmography_model)
    result = compare_profile_to_definition(profile, filmography_model)
    assert result.is_valid, [str(e) for e in result.errors]


# --- Node label checks ---


def test_compare_missing_node_label(
    filmography_model: GraphDefinition,
):
    profile = _complete_profile(filmography_model)
    # Remove City from profile
    profiles = dict(profile.node_type_profiles)
    del profiles["City"]
    profile = profile.model_copy(update={"node_type_profiles": profiles})
    result = compare_profile_to_definition(profile, filmography_model)
    assert not result.is_valid
    missing = [e for e in result.errors if e.code == "MISSING_NODE_LABEL"]
    assert len(missing) == 1
    assert missing[0].entity_id == "City"
    # No spurious cross-type error for the same address
    spurious = [
        i
        for i in result.issues
        if i.entity_id == "City" and i.code != "MISSING_NODE_LABEL"
    ]
    assert spurious == [], f"Spurious issues at 'City': {spurious}"


def test_compare_unexpected_node_label(
    filmography_model: GraphDefinition,
):
    profile = _complete_profile(filmography_model)
    profiles = dict(profile.node_type_profiles)
    profiles["Animal"] = NodeTypeProfile(label="Animal", count=5)
    profile = profile.model_copy(update={"node_type_profiles": profiles})
    result = compare_profile_to_definition(profile, filmography_model)
    assert result.is_valid  # warnings don't invalidate
    warnings = [w for w in result.warnings if w.code == "UNEXPECTED_NODE_LABEL"]
    assert len(warnings) == 1
    assert warnings[0].entity_id == "Animal"
    # No spurious cross-type warning for the same address
    spurious = [
        i
        for i in result.issues
        if i.entity_id == "Animal" and i.code != "UNEXPECTED_NODE_LABEL"
    ]
    assert spurious == [], f"Spurious issues at 'Animal': {spurious}"


# --- Relationship type checks ---


def test_compare_missing_rel_type(
    filmography_model: GraphDefinition,
):
    profile = _complete_profile(filmography_model)
    profiles = dict(profile.rel_type_profiles)
    del profiles["Person:ACTED_IN:Movie"]
    profile = profile.model_copy(update={"rel_type_profiles": profiles})
    result = compare_profile_to_definition(profile, filmography_model)
    assert not result.is_valid
    missing = [e for e in result.errors if e.code == "MISSING_REL_TYPE"]
    assert len(missing) == 1
    assert missing[0].entity_id == "Person:ACTED_IN:Movie"
    spurious = [
        i
        for i in result.issues
        if i.entity_id == "Person:ACTED_IN:Movie" and i.code != "MISSING_REL_TYPE"
    ]
    assert spurious == [], f"Spurious issues at 'Person:ACTED_IN:Movie': {spurious}"


def test_compare_unexpected_rel_type(
    filmography_model: GraphDefinition,
):
    profile = _complete_profile(filmography_model)
    profiles = dict(profile.rel_type_profiles)
    profiles["Person:FRIEND_OF:Person"] = RelationshipTypeProfile(
        rel_type="FRIEND_OF",
        count=10,
        source_label="Person",
        target_label="Person",
    )
    profile = profile.model_copy(update={"rel_type_profiles": profiles})
    result = compare_profile_to_definition(profile, filmography_model)
    assert result.is_valid
    warnings = [w for w in result.warnings if w.code == "UNEXPECTED_REL_TYPE"]
    assert len(warnings) == 1
    assert warnings[0].entity_id == "Person:FRIEND_OF:Person"
    spurious = [
        i
        for i in result.issues
        if i.entity_id == "Person:FRIEND_OF:Person" and i.code != "UNEXPECTED_REL_TYPE"
    ]
    assert spurious == [], f"Spurious issues at 'Person:FRIEND_OF:Person': {spurious}"


# --- Property checks ---


def test_compare_missing_required_property(
    filmography_model: GraphDefinition,
):
    profile = _complete_profile(filmography_model)
    profiles = dict(profile.node_type_profiles)
    person = profiles["Person"]
    person_props = dict(person.property_profiles)
    del person_props["age"]
    profiles["Person"] = person.model_copy(update={"property_profiles": person_props})
    profile = profile.model_copy(update={"node_type_profiles": profiles})
    result = compare_profile_to_definition(profile, filmography_model)
    assert not result.is_valid
    missing = [e for e in result.errors if e.code == "MISSING_PROPERTY"]
    assert len(missing) == 1
    assert missing[0].entity_id == "Person.age"


def test_compare_property_type_mismatch(
    filmography_model: GraphDefinition,
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
    result = compare_profile_to_definition(profile, filmography_model)
    assert not result.is_valid
    mismatches = [e for e in result.errors if e.code == "PROPERTY_TYPE_MISMATCH"]
    assert len(mismatches) == 1
    assert mismatches[0].entity_id == "Person.age"


def test_compare_property_incomplete(
    filmography_model: GraphDefinition,
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
    result = compare_profile_to_definition(profile, filmography_model)
    assert result.is_valid  # warning, not error
    incomplete = [w for w in result.warnings if w.code == "PROPERTY_INCOMPLETE"]
    assert len(incomplete) == 1
    assert incomplete[0].entity_id == "Person.name"


def test_compare_unexpected_property(
    filmography_model: GraphDefinition,
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
    result = compare_profile_to_definition(profile, filmography_model)
    assert result.is_valid
    unexpected = [i for i in result.issues if i.code == "UNEXPECTED_PROPERTY"]
    assert len(unexpected) == 1
    assert unexpected[0].entity_id == "Person.phone"


# --- Endpoint checks ---


def test_compare_endpoint_mismatch_reclassifies(
    filmography_model: GraphDefinition,
):
    """A wrong endpoint is a different identity (address), so it
    reclassifies to MISSING_REL_TYPE + UNEXPECTED_REL_TYPE."""
    profile = _complete_profile(filmography_model)
    profiles = dict(profile.rel_type_profiles)
    acted_in = profiles.pop("Person:ACTED_IN:Movie")
    # Re-home the observed ACTED_IN onto a wrong source (City) → new identity.
    profiles["City:ACTED_IN:Movie"] = acted_in.model_copy(
        update={"source_label": "City"}
    )
    profile = profile.model_copy(update={"rel_type_profiles": profiles})
    result = compare_profile_to_definition(profile, filmography_model)
    assert not result.is_valid
    codes = {e.code for e in result.issues}
    assert "INVALID_ENDPOINT" not in codes
    assert "MISSING_REL_TYPE" in codes  # declared Person:ACTED_IN:Movie not observed
    assert "UNEXPECTED_REL_TYPE" in {w.code for w in result.warnings}


# --- Cardinality checks ---


def test_compare_cardinality_violation(
    filmography_model: GraphDefinition,
):
    profile = _complete_profile(filmography_model)
    profiles = dict(profile.rel_type_profiles)
    lives_in = profiles["Person:LIVES_IN:City"]
    profiles["Person:LIVES_IN:City"] = lives_in.model_copy(
        update={
            "cardinality_stats": CardinalityStats(
                count=100,
                min=0,  # violates "1..1" (min=1)
                max=3,
                mean=1.5,
            )
        }
    )
    profile = profile.model_copy(update={"rel_type_profiles": profiles})
    result = compare_profile_to_definition(profile, filmography_model)
    assert not result.is_valid
    violations = [e for e in result.errors if e.code == "CARDINALITY_VIOLATION"]
    assert len(violations) == 1


def test_compare_no_cardinality_stats_skipped(
    filmography_model: GraphDefinition,
):
    """When cardinality stats are None, no cardinality check is performed."""
    profile = _complete_profile(filmography_model)
    # _complete_profile already has cardinality_stats=None
    result = compare_profile_to_definition(profile, filmography_model)
    assert not any(e.code == "CARDINALITY_VIOLATION" for e in result.issues)


# --- Undirected relationship endpoint validation tests ---


def test_compare_undirected_cross_type_forward_valid():
    """Undirected cross-type: forward source/target is valid."""
    from orthograph.graph_definition.models import NodeModel, RelationshipModel

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
        __source_label__ = "UPerson"
        __target_label__ = "UCompany"
        __directed__ = False

    graph_definition = GraphDefinition(
        name="Cross",
        node_types=[UPerson, UCompany],
        relationship_types=[UCollaborates],
    )
    profile = _complete_profile(graph_definition)
    result = compare_profile_to_definition(profile, graph_definition)
    assert result.is_valid, [str(e) for e in result.errors]


def test_compare_undirected_cross_type_reverse_valid():
    """Undirected cross-type: reversed source/target should also be valid."""
    from orthograph.graph_definition.models import NodeModel, RelationshipModel

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
        __source_label__ = "RPerson"
        __target_label__ = "RCompany"
        __directed__ = False

    graph_definition = GraphDefinition(
        name="Cross",
        node_types=[RPerson, RCompany],
        relationship_types=[RCollaborates],
    )

    # Build profile with reversed endpoints
    rel_profiles = {
        "RCompany:R_COLLABORATES:RPerson": RelationshipTypeProfile(
            rel_type="R_COLLABORATES",
            count=200,
            source_label="RCompany",  # reversed
            target_label="RPerson",  # reversed
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
    result = compare_profile_to_definition(profile, graph_definition)
    # Should not have INVALID_ENDPOINT errors
    assert not any(e.code == "INVALID_ENDPOINT" for e in result.errors)


def test_compare_directed_cross_type_reverse_rejected():
    """Directed: reversed source/target is rejected (as a presence mismatch)."""
    from orthograph.graph_definition.models import NodeModel, RelationshipModel

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
        __source_label__ = "DPerson"
        __target_label__ = "DMovie"
        __directed__ = True

    graph_definition = GraphDefinition(
        name="Dir",
        node_types=[DPerson, DMovie],
        relationship_types=[DActedIn],
    )

    rel_profiles = {
        "DMovie:D_ACTED_IN:DPerson": RelationshipTypeProfile(
            rel_type="D_ACTED_IN",
            count=200,
            source_label="DMovie",  # wrong
            target_label="DPerson",  # wrong
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
    result = compare_profile_to_definition(profile, graph_definition)
    # Reversed endpoints are a different identity, so the
    # declared shape is MISSING and the observed (reversed) shape is UNEXPECTED.
    # INVALID_ENDPOINT no longer exists.
    codes = {i.code for i in result.issues}
    assert "INVALID_ENDPOINT" not in codes
    assert "MISSING_REL_TYPE" in codes
    assert "UNEXPECTED_REL_TYPE" in codes


# ---------------------------------------------------------------------------
# Regression: Bug 1 — satisfaction rules must not fire on the wrong pass
#
# Before the fix, the union walker ran ALL rules against every address in
# every pass.  MissingNodeLabelRule (no extra.prop_name + right is None)
# would also fire at a rel-type address, and MissingRelTypeRule would also
# fire at a node-label address, doubling false-positive counts.
# ---------------------------------------------------------------------------


def test_missing_node_label_does_not_emit_missing_rel_type(
    filmography_model: GraphDefinition,
):
    """A missing node label must produce exactly one MISSING_NODE_LABEL,
    zero MISSING_REL_TYPE for the same entity id."""
    profile = _complete_profile(filmography_model)
    profiles = dict(profile.node_type_profiles)
    del profiles["City"]
    profile = profile.model_copy(update={"node_type_profiles": profiles})
    result = compare_profile_to_definition(profile, filmography_model)

    # The missing entity is a node, not a rel — no MISSING_REL_TYPE at "City"
    spurious = [
        i
        for i in result.issues
        if i.code == "MISSING_REL_TYPE" and i.entity_id == "City"
    ]
    assert spurious == [], (
        f"MISSING_REL_TYPE emitted at node-label address 'City': {spurious}"
    )

    # Exactly one MISSING_NODE_LABEL at "City"
    node_errors = [i for i in result.errors if i.code == "MISSING_NODE_LABEL"]
    assert len(node_errors) == 1
    assert node_errors[0].entity_id == "City"


def test_missing_rel_type_does_not_emit_missing_node_label(
    filmography_model: GraphDefinition,
):
    """A missing rel type must produce exactly one MISSING_REL_TYPE,
    zero MISSING_NODE_LABEL for the same entity id."""
    profile = _complete_profile(filmography_model)
    profiles = dict(profile.rel_type_profiles)
    del profiles["Person:ACTED_IN:Movie"]
    profile = profile.model_copy(update={"rel_type_profiles": profiles})
    result = compare_profile_to_definition(profile, filmography_model)

    spurious = [
        i
        for i in result.issues
        if i.code == "MISSING_NODE_LABEL" and i.entity_id == "Person:ACTED_IN:Movie"
    ]
    assert spurious == [], (
        "MISSING_NODE_LABEL emitted at rel-type address "
        f"'Person:ACTED_IN:Movie': {spurious}"
    )

    rel_errors = [i for i in result.errors if i.code == "MISSING_REL_TYPE"]
    assert len(rel_errors) == 1
    assert rel_errors[0].entity_id == "Person:ACTED_IN:Movie"


def test_unexpected_node_label_does_not_emit_unexpected_rel_type(
    filmography_model: GraphDefinition,
):
    """An unexpected node label must emit UNEXPECTED_NODE_LABEL, not
    UNEXPECTED_REL_TYPE at the same address."""
    profile = _complete_profile(filmography_model)
    profiles = dict(profile.node_type_profiles)
    profiles["Animal"] = NodeTypeProfile(label="Animal", count=3)
    profile = profile.model_copy(update={"node_type_profiles": profiles})
    result = compare_profile_to_definition(profile, filmography_model)

    spurious = [
        i
        for i in result.issues
        if i.code == "UNEXPECTED_REL_TYPE" and i.entity_id == "Animal"
    ]
    assert spurious == [], (
        f"UNEXPECTED_REL_TYPE emitted at node address 'Animal': {spurious}"
    )

    node_warnings = [i for i in result.warnings if i.code == "UNEXPECTED_NODE_LABEL"]
    assert any(w.entity_id == "Animal" for w in node_warnings)


def test_unexpected_rel_type_does_not_emit_unexpected_node_label(
    filmography_model: GraphDefinition,
):
    """An unexpected rel type must emit UNEXPECTED_REL_TYPE, not
    UNEXPECTED_NODE_LABEL at the same address."""
    profile = _complete_profile(filmography_model)
    profiles = dict(profile.rel_type_profiles)
    profiles["Person:FRIEND_OF:Person"] = RelationshipTypeProfile(
        rel_type="FRIEND_OF", count=10, source_label="Person", target_label="Person"
    )
    profile = profile.model_copy(update={"rel_type_profiles": profiles})
    result = compare_profile_to_definition(profile, filmography_model)

    spurious = [
        i
        for i in result.issues
        if i.code == "UNEXPECTED_NODE_LABEL"
        and i.entity_id == "Person:FRIEND_OF:Person"
    ]
    assert spurious == [], (
        "UNEXPECTED_NODE_LABEL emitted at rel address "
        f"'Person:FRIEND_OF:Person': {spurious}"
    )

    rel_warnings = [i for i in result.warnings if i.code == "UNEXPECTED_REL_TYPE"]
    assert any(w.entity_id == "Person:FRIEND_OF:Person" for w in rel_warnings)


# ---------------------------------------------------------------------------
# Regression: Bug 2 — UNEXPECTED_PROPERTY must NOT fire for properties
# belonging to unexpected (profile-only) node/rel-type labels.
#
# When an unexpected node label appears in the profile, its properties are
# walked in pass-3.  MissingPropertyRule/UnexpectedPropertyRule must not
# fire for those properties — doing so creates spurious noise.
# ---------------------------------------------------------------------------


def test_unexpected_node_label_properties_do_not_emit_unexpected_property(
    filmography_model: GraphDefinition,
):
    """Properties of an unexpected node label must not generate
    UNEXPECTED_PROPERTY issues."""
    profile = _complete_profile(filmography_model)
    profiles = dict(profile.node_type_profiles)
    profiles["Animal"] = NodeTypeProfile(
        label="Animal",
        count=3,
        property_profiles={
            "species": PropertyProfile(
                name="species",
                present_count=3,
                total_count=3,
                observed_types=["String"],
            )
        },
    )
    profile = profile.model_copy(update={"node_type_profiles": profiles})
    result = compare_profile_to_definition(profile, filmography_model)

    spurious = [
        i
        for i in result.issues
        if i.code == "UNEXPECTED_PROPERTY" and i.entity_id.startswith("Animal.")
    ]
    assert spurious == [], (
        f"UNEXPECTED_PROPERTY emitted for unexpected node 'Animal': {spurious}"
    )


def test_unexpected_rel_type_properties_do_not_emit_unexpected_property(
    filmography_model: GraphDefinition,
):
    """Properties of an unexpected relationship type must not generate
    UNEXPECTED_PROPERTY issues."""
    profile = _complete_profile(filmography_model)
    profiles = dict(profile.rel_type_profiles)
    profiles["Person:FRIEND_OF:Person"] = RelationshipTypeProfile(
        rel_type="FRIEND_OF",
        count=5,
        source_label="Person",
        target_label="Person",
        property_profiles={
            "since": PropertyProfile(
                name="since",
                present_count=5,
                total_count=5,
                observed_types=["Long"],
            )
        },
    )
    profile = profile.model_copy(update={"rel_type_profiles": profiles})
    result = compare_profile_to_definition(profile, filmography_model)

    spurious = [
        i
        for i in result.issues
        if i.code == "UNEXPECTED_PROPERTY"
        and i.entity_id.startswith("Person:FRIEND_OF:Person.")
    ]
    assert spurious == [], (
        "UNEXPECTED_PROPERTY emitted for unexpected rel "
        f"'Person:FRIEND_OF:Person': {spurious}"
    )
