"""Tests for orthograph.compare (E55.5).

The comparison facade: three verbs, one per shipped comparison, each delegating
to the engine. ``profile_to_definition`` checks satisfaction; ``profiles`` and
``definitions`` produce symmetric INFO diffs (US 31 / US 30).
"""

from orthograph.compare import (
    Rule,
    definitions,
    profile_to_definition,
    profiles,
)
from orthograph.diagnostics.classification import Severity
from orthograph.diagnostics.result import ValidationResult
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.models import NodeModel, RelationshipModel
from orthograph.graph_profile.models import (
    GraphProfile,
    NodeTypeProfile,
)


# ---------------------------------------------------------------------------
# Operands
# ---------------------------------------------------------------------------


class _Person(NodeModel):
    __label__ = "Person"
    name: str


class _Movie(NodeModel):
    __label__ = "Movie"
    title: str


class _ActedIn(RelationshipModel):
    __label__ = "ACTED_IN"
    __source_label__ = "Person"
    __target_label__ = "Movie"


_DEFINITION = GraphDefinition(
    name="film",
    node_types=[_Person, _Movie],
    relationship_types=[_ActedIn],
)


def _profile(*labels: str) -> GraphProfile:
    return GraphProfile(
        source="test",
        node_type_profiles={lbl: NodeTypeProfile(label=lbl, count=1) for lbl in labels},
    )


def _codes(result: ValidationResult) -> set[str]:
    return {i.code for i in result.issues}


# ---------------------------------------------------------------------------
# profile_to_definition
# ---------------------------------------------------------------------------


def test_profile_to_definition_flags_drift() -> None:
    """A profile missing a declared label drifts from the definition."""
    profile = _profile("Person")  # Movie declared but not observed
    result = profile_to_definition(profile, _DEFINITION)
    assert "MISSING_NODE_LABEL" in _codes(result)


def test_profile_to_definition_passes_matching_pair() -> None:
    profile = _profile("Person", "Movie")
    result = profile_to_definition(profile, _DEFINITION)
    assert "MISSING_NODE_LABEL" not in _codes(result)


# ---------------------------------------------------------------------------
# profiles (US 31)
# ---------------------------------------------------------------------------


def test_profiles_info_only_diff() -> None:
    left = _profile("Person", "Movie")
    right = _profile("Movie")
    result = profiles(left, right)
    assert "NODE_LABEL_ONLY_IN_LEFT" in _codes(result)
    assert result.is_valid is True  # INFO only
    assert all(i.severity != Severity.ERROR for i in result.issues)


# ---------------------------------------------------------------------------
# definitions (US 30)
# ---------------------------------------------------------------------------


class _PersonWithEmail(NodeModel):
    __label__ = "Person"
    name: str
    email: str


_DEF_WITH_EMAIL = GraphDefinition(
    name="with_email",
    node_types=[_PersonWithEmail, _Movie],
    relationship_types=[_ActedIn],
)


def test_definitions_info_only_diff() -> None:
    result = definitions(_DEF_WITH_EMAIL, _DEFINITION)
    assert "PROPERTY_ONLY_IN_LEFT" in _codes(result)
    assert result.is_valid is True
    assert all(i.severity != Severity.ERROR for i in result.issues)


# ---------------------------------------------------------------------------
# rules= override honoured per verb
# ---------------------------------------------------------------------------


def test_rules_override_honoured() -> None:
    """An empty custom rule set suppresses all issues for every verb."""
    empty: list[Rule] = []

    drift = _profile("Person")
    assert profile_to_definition(drift, _DEFINITION, rules=empty).issues == []

    left, right = _profile("Person", "Movie"), _profile("Movie")
    assert profiles(left, right, rules=empty).issues == []

    assert definitions(_DEF_WITH_EMAIL, _DEFINITION, rules=empty).issues == []
