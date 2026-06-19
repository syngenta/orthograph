"""End-to-end tests for ``compare_profiles`` and ``compare_definitions`` (E27.T4).

Tests the two new symmetric comparison entry points through the full engine
stack, using the ``filmography_model`` fixture from ``conftest.py`` and
handbuilt profiles.

Coverage per spec:
- Identical operands → zero issues, ``is_valid`` is True.
- Label/type/property present only on one side → matching ``*_ONLY_IN_*`` INFO.
- Changed property type / endpoints / cardinality → matching ``*_CHANGED`` INFO.
- Diff results never contain ``Severity.ERROR`` (``is_valid`` stays True).
"""

from typing import Optional

from orthograph.comparison.engine import compare_definitions, compare_profiles
from orthograph.diagnostics.classification import Severity
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.models import (
    NodeModel,
    RelationshipModel,
)
from orthograph.graph_profile.models import (
    CardinalityStats,
    GraphProfile,
    NodeTypeProfile,
    PropertyProfile,
    RelationshipTypeProfile,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _profile(*labels: str, **rel_types: RelationshipTypeProfile) -> GraphProfile:
    """Quick factory — keyword args become rel_type_profiles."""
    node_profiles = {lbl: NodeTypeProfile(label=lbl, count=1) for lbl in labels}
    rel_profiles = {k: v for k, v in rel_types.items()}
    return GraphProfile(
        source="test",
        node_type_profiles=node_profiles,
        rel_type_profiles=rel_profiles,
    )


def _issue_codes(result) -> set[str]:
    return {i.code for i in result.issues}


# ---------------------------------------------------------------------------
# compare_profiles — identical operands
# ---------------------------------------------------------------------------


def test_compare_profiles_identical_empty_profiles():
    p = GraphProfile(source="empty")
    result = compare_profiles(p, p)
    assert result.issues == []
    assert result.is_valid is True


def test_compare_profiles_identical_nonempty_profiles():
    p = _profile("Person", "Movie")
    result = compare_profiles(p, p)
    assert result.issues == []
    assert result.is_valid is True


# ---------------------------------------------------------------------------
# compare_profiles — label differences
# ---------------------------------------------------------------------------


def test_compare_profiles_node_label_only_in_left():
    left = _profile("Person", "Movie")
    right = _profile("Movie")
    result = compare_profiles(left, right)
    codes = _issue_codes(result)
    assert "NODE_LABEL_ONLY_IN_LEFT" in codes
    assert "NODE_LABEL_ONLY_IN_RIGHT" not in codes
    assert result.is_valid is True  # INFO only


def test_compare_profiles_node_label_only_in_right():
    left = _profile("Movie")
    right = _profile("Person", "Movie")
    result = compare_profiles(left, right)
    codes = _issue_codes(result)
    assert "NODE_LABEL_ONLY_IN_RIGHT" in codes


def test_compare_profiles_rel_type_only_in_left():
    rtp = RelationshipTypeProfile(rel_type="ACTED_IN", count=5)
    left = GraphProfile(
        source="left",
        rel_type_profiles={"ACTED_IN": rtp},
    )
    right = GraphProfile(source="right")
    result = compare_profiles(left, right)
    codes = _issue_codes(result)
    assert "REL_TYPE_ONLY_IN_LEFT" in codes
    assert result.is_valid is True


def test_compare_profiles_rel_type_only_in_right():
    rtp = RelationshipTypeProfile(rel_type="ACTED_IN", count=5)
    left = GraphProfile(source="left")
    right = GraphProfile(
        source="right",
        rel_type_profiles={"ACTED_IN": rtp},
    )
    result = compare_profiles(left, right)
    assert "REL_TYPE_ONLY_IN_RIGHT" in _issue_codes(result)


# ---------------------------------------------------------------------------
# compare_profiles — property differences
# ---------------------------------------------------------------------------


def test_compare_profiles_property_only_in_left():
    pp = PropertyProfile(name="email", present_count=5, total_count=5)
    left = GraphProfile(
        source="left",
        node_type_profiles={
            "Person": NodeTypeProfile(
                label="Person",
                count=5,
                property_profiles={"email": pp},
            )
        },
    )
    right = GraphProfile(
        source="right",
        node_type_profiles={"Person": NodeTypeProfile(label="Person", count=5)},
    )
    result = compare_profiles(left, right)
    assert "PROPERTY_ONLY_IN_LEFT" in _issue_codes(result)
    assert result.is_valid is True


def test_compare_profiles_property_only_in_right():
    pp = PropertyProfile(name="email", present_count=5, total_count=5)
    left = GraphProfile(
        source="left",
        node_type_profiles={"Person": NodeTypeProfile(label="Person", count=5)},
    )
    right = GraphProfile(
        source="right",
        node_type_profiles={
            "Person": NodeTypeProfile(
                label="Person",
                count=5,
                property_profiles={"email": pp},
            )
        },
    )
    result = compare_profiles(left, right)
    assert "PROPERTY_ONLY_IN_RIGHT" in _issue_codes(result)


# ---------------------------------------------------------------------------
# compare_profiles — changed attributes
# ---------------------------------------------------------------------------


def test_compare_profiles_property_type_changed():
    pp_str = PropertyProfile(
        name="score", present_count=5, total_count=5, observed_types=["String"]
    )
    pp_int = PropertyProfile(
        name="score", present_count=5, total_count=5, observed_types=["Long"]
    )
    left = GraphProfile(
        source="left",
        node_type_profiles={
            "Player": NodeTypeProfile(
                label="Player",
                count=5,
                property_profiles={"score": pp_str},
            )
        },
    )
    right = GraphProfile(
        source="right",
        node_type_profiles={
            "Player": NodeTypeProfile(
                label="Player",
                count=5,
                property_profiles={"score": pp_int},
            )
        },
    )
    result = compare_profiles(left, right)
    assert "PROPERTY_TYPE_CHANGED" in _issue_codes(result)
    assert result.is_valid is True


def test_compare_profiles_endpoints_changed():
    rtp_left = RelationshipTypeProfile(
        rel_type="ACTED_IN",
        count=5,
        source_labels={"Person"},
        target_labels={"Movie"},
    )
    rtp_right = RelationshipTypeProfile(
        rel_type="ACTED_IN",
        count=5,
        source_labels={"Director"},
        target_labels={"Movie"},
    )
    left = GraphProfile(source="left", rel_type_profiles={"ACTED_IN": rtp_left})
    right = GraphProfile(source="right", rel_type_profiles={"ACTED_IN": rtp_right})
    result = compare_profiles(left, right)
    assert "ENDPOINTS_CHANGED" in _issue_codes(result)
    assert result.is_valid is True


def test_compare_profiles_cardinality_changed():
    stats_1 = CardinalityStats(
        min_degree=1, max_degree=3, avg_degree=2.0, sample_size=5
    )
    stats_2 = CardinalityStats(
        min_degree=2, max_degree=6, avg_degree=4.0, sample_size=5
    )
    rtp_left = RelationshipTypeProfile(
        rel_type="ACTED_IN", count=5, cardinality_stats=stats_1
    )
    rtp_right = RelationshipTypeProfile(
        rel_type="ACTED_IN", count=5, cardinality_stats=stats_2
    )
    left = GraphProfile(source="left", rel_type_profiles={"ACTED_IN": rtp_left})
    right = GraphProfile(source="right", rel_type_profiles={"ACTED_IN": rtp_right})
    result = compare_profiles(left, right)
    assert "CARDINALITY_CHANGED" in _issue_codes(result)
    assert result.is_valid is True


# ---------------------------------------------------------------------------
# compare_profiles — never ERROR
# ---------------------------------------------------------------------------


def test_compare_profiles_no_error_severity():
    """Diff results must never contain Severity.ERROR."""
    left = _profile("Person", "Movie", "City")
    right = _profile("Movie", "Actor")
    result = compare_profiles(left, right)
    for issue in result.issues:
        assert issue.severity != Severity.ERROR, (
            f"compare_profiles emitted ERROR: {issue}"
        )
    assert result.is_valid is True


# ---------------------------------------------------------------------------
# compare_definitions — identical operands
# ---------------------------------------------------------------------------


class _PersonDef(NodeModel):
    __label__ = "Person"
    name: str
    age: Optional[int] = None


class _MovieDef(NodeModel):
    __label__ = "Movie"
    title: str


class _CityDef(NodeModel):
    __label__ = "City"
    name: str


class _DirectorDefNode(NodeModel):
    __label__ = "Director"
    name: str


class _FilmDefNode(NodeModel):
    __label__ = "Film"
    title: str


class _ActedInDef(RelationshipModel):
    __label__ = "ACTED_IN"
    __source_label__ = "Person"
    __target_label__ = "Movie"
    role: str


class _DirectedDef(RelationshipModel):
    __label__ = "DIRECTED"
    __source_label__ = "Person"
    __target_label__ = "Movie"


# Full: Person, Movie + ACTED_IN, DIRECTED
_GD_FULL = GraphDefinition(
    name="full",
    node_types=[_PersonDef, _MovieDef],
    relationship_types=[_ActedInDef, _DirectedDef],
)

# With City node — extra node label vs _GD_FULL
_GD_WITH_CITY = GraphDefinition(
    name="with_city",
    node_types=[_PersonDef, _MovieDef, _CityDef],
    relationship_types=[_ActedInDef, _DirectedDef],
)

# Small: Person, Movie + only ACTED_IN  (DIRECTED is left-only vs _GD_FULL)
_GD_SMALL = GraphDefinition(
    name="small",
    node_types=[_PersonDef, _MovieDef],
    relationship_types=[_ActedInDef],
)


def test_compare_definitions_identical():
    result = compare_definitions(_GD_FULL, _GD_FULL)
    assert result.issues == []
    assert result.is_valid is True


def test_compare_definitions_empty():
    gd = GraphDefinition(name="empty", node_types=[], relationship_types=[])
    result = compare_definitions(gd, gd)
    assert result.issues == []
    assert result.is_valid is True


# ---------------------------------------------------------------------------
# compare_definitions — label/type differences
# ---------------------------------------------------------------------------


def test_compare_definitions_node_label_only_in_left():
    # _GD_WITH_CITY has City; _GD_FULL does not
    result = compare_definitions(_GD_WITH_CITY, _GD_FULL)
    codes = _issue_codes(result)
    assert "NODE_LABEL_ONLY_IN_LEFT" in codes
    assert result.is_valid is True


def test_compare_definitions_rel_type_only_in_left():
    result = compare_definitions(_GD_FULL, _GD_SMALL)
    codes = _issue_codes(result)
    assert "REL_TYPE_ONLY_IN_LEFT" in codes


def test_compare_definitions_node_label_only_in_right():
    # _GD_FULL has City (via _GD_WITH_CITY orientation)
    result = compare_definitions(_GD_FULL, _GD_WITH_CITY)
    codes = _issue_codes(result)
    assert "NODE_LABEL_ONLY_IN_RIGHT" in codes


# ---------------------------------------------------------------------------
# compare_definitions — property differences
# ---------------------------------------------------------------------------


class _PersonWithEmail(NodeModel):
    __label__ = "Person"
    name: str
    email: str  # extra property vs _PersonDef


_GD_WITH_EMAIL = GraphDefinition(
    name="with_email",
    node_types=[_PersonWithEmail, _MovieDef],
    relationship_types=[],
)

_GD_WITHOUT_EMAIL = GraphDefinition(
    name="without_email",
    node_types=[_PersonDef, _MovieDef],
    relationship_types=[],
)


def test_compare_definitions_property_only_in_left():
    result = compare_definitions(_GD_WITH_EMAIL, _GD_WITHOUT_EMAIL)
    assert "PROPERTY_ONLY_IN_LEFT" in _issue_codes(result)
    assert result.is_valid is True


def test_compare_definitions_property_only_in_right():
    result = compare_definitions(_GD_WITHOUT_EMAIL, _GD_WITH_EMAIL)
    assert "PROPERTY_ONLY_IN_RIGHT" in _issue_codes(result)


# ---------------------------------------------------------------------------
# compare_definitions — changed property type
# ---------------------------------------------------------------------------


class _PersonIntName(NodeModel):
    __label__ = "Person"
    name: int  # changed type vs _PersonDef (str)


_GD_INT_NAME = GraphDefinition(
    name="int_name",
    node_types=[_PersonIntName],
    relationship_types=[],
)

_GD_STR_NAME = GraphDefinition(
    name="str_name",
    node_types=[_PersonDef],
    relationship_types=[],
)


def test_compare_definitions_property_type_changed():
    result = compare_definitions(_GD_INT_NAME, _GD_STR_NAME)
    assert "PROPERTY_TYPE_CHANGED" in _issue_codes(result)
    assert result.is_valid is True


# ---------------------------------------------------------------------------
# compare_definitions — endpoints / cardinality changed
# ---------------------------------------------------------------------------


class _ActedInAltEndpoints(RelationshipModel):
    __label__ = "ACTED_IN"
    __source_label__ = "Director"
    __target_label__ = "Film"


_GD_ALT_ENDPOINTS = GraphDefinition(
    name="alt",
    node_types=[_DirectorDefNode, _FilmDefNode],
    relationship_types=[_ActedInAltEndpoints],
)

_GD_ORIG_ENDPOINTS = GraphDefinition(
    name="orig",
    node_types=[_PersonDef, _MovieDef],
    relationship_types=[_ActedInDef],
)


def test_compare_definitions_endpoints_changed():
    result = compare_definitions(_GD_ORIG_ENDPOINTS, _GD_ALT_ENDPOINTS)
    assert "ENDPOINTS_CHANGED" in _issue_codes(result)
    assert result.is_valid is True


class _LivesInStrict(RelationshipModel):
    __label__ = "LIVES_IN"
    __source_label__ = "Person"
    __target_label__ = "City"
    __source_cardinality__ = "1..1"


class _LivesInLoose(RelationshipModel):
    __label__ = "LIVES_IN"
    __source_label__ = "Person"
    __target_label__ = "City"
    __source_cardinality__ = "0..*"


_GD_STRICT = GraphDefinition(
    name="strict",
    node_types=[_PersonDef, _CityDef],
    relationship_types=[_LivesInStrict],
)

_GD_LOOSE = GraphDefinition(
    name="loose",
    node_types=[_PersonDef, _CityDef],
    relationship_types=[_LivesInLoose],
)


def test_compare_definitions_cardinality_changed():
    result = compare_definitions(_GD_STRICT, _GD_LOOSE)
    assert "CARDINALITY_CHANGED" in _issue_codes(result)
    assert result.is_valid is True


# ---------------------------------------------------------------------------
# compare_definitions — never ERROR
# ---------------------------------------------------------------------------


def test_compare_definitions_no_error_severity():
    """compare_definitions never emits ERROR regardless of which diff codes fire."""
    # label diff
    _assert_no_error(compare_definitions(_GD_FULL, _GD_SMALL))
    # node-label diff (City present only in left)
    _assert_no_error(compare_definitions(_GD_WITH_CITY, _GD_FULL))
    # property diff
    _assert_no_error(compare_definitions(_GD_WITH_EMAIL, _GD_WITHOUT_EMAIL))
    # property type changed
    _assert_no_error(compare_definitions(_GD_INT_NAME, _GD_STR_NAME))
    # endpoints changed
    _assert_no_error(compare_definitions(_GD_ORIG_ENDPOINTS, _GD_ALT_ENDPOINTS))
    # cardinality changed
    _assert_no_error(compare_definitions(_GD_STRICT, _GD_LOOSE))


def test_compare_profiles_no_error_severity_extended():
    """compare_profiles never emits ERROR for any diff code."""
    from orthograph.graph_profile.models import NodeTypeProfile, RelationshipTypeProfile

    # Node-label diff
    p1 = GraphProfile(
        source="a",
        node_type_profiles={"Person": NodeTypeProfile(label="Person", count=5)},
    )
    p2 = GraphProfile(
        source="b",
        node_type_profiles={"Movie": NodeTypeProfile(label="Movie", count=3)},
    )
    _assert_no_error(compare_profiles(p1, p2))

    # Rel-type diff
    r1 = GraphProfile(
        source="c",
        rel_type_profiles={
            "ACTED_IN": RelationshipTypeProfile(
                rel_type="ACTED_IN",
                count=5,
                source_labels={"Person"},
                target_labels={"Movie"},
            )
        },
    )
    r2 = GraphProfile(
        source="d",
        rel_type_profiles={
            "DIRECTED": RelationshipTypeProfile(
                rel_type="DIRECTED",
                count=2,
                source_labels={"Director"},
                target_labels={"Film"},
            )
        },
    )
    _assert_no_error(compare_profiles(r1, r2))


def _assert_no_error(result) -> None:
    for issue in result.issues:
        assert issue.severity != Severity.ERROR, (
            f"Diff comparison emitted ERROR: {issue}"
        )
    assert result.is_valid is True


# ---------------------------------------------------------------------------
# filmography_model fixture tests (uses conftest.py fixture)
# ---------------------------------------------------------------------------


def test_compare_profiles_filmography_identical(filmography_model: GraphDefinition):
    """Identical profiles from filmography model produce zero diff issues."""
    # Build a profile consistent with the filmography model
    from orthograph.graph_profile.models import NodeTypeProfile, RelationshipTypeProfile

    profile = GraphProfile(
        source="film_test",
        node_type_profiles={
            "Person": NodeTypeProfile(label="Person", count=10),
            "Movie": NodeTypeProfile(label="Movie", count=5),
            "City": NodeTypeProfile(label="City", count=3),
        },
        rel_type_profiles={
            "ACTED_IN": RelationshipTypeProfile(rel_type="ACTED_IN", count=20),
            "LIVES_IN": RelationshipTypeProfile(rel_type="LIVES_IN", count=10),
            "DIRECTED": RelationshipTypeProfile(rel_type="DIRECTED", count=5),
        },
    )
    result = compare_profiles(profile, profile)
    assert result.issues == []
    assert result.is_valid is True


def test_compare_definitions_filmography_identical(filmography_model: GraphDefinition):
    """Same GraphDefinition compared against itself emits zero issues."""
    result = compare_definitions(filmography_model, filmography_model)
    assert result.issues == []
    assert result.is_valid is True
