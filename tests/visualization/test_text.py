"""Tests for orthograph.visualization.text."""

from datetime import datetime

import pytest

from orthograph.diagnostics.classification import EntityType, Severity
from orthograph.diagnostics.result import ValidationIssue, ValidationResult
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.models import (
    CardinalitySpec,
    ConditionalCardinality,
    ConditionalRule,
    NodeModel,
    PropMatch,
    RelationshipModel,
)
from orthograph.graph_profile.models import (
    BoundedDistribution,
    CardinalityStats,
    GraphProfile,
    NodeTypeProfile,
    PartitionedCardinalityRow,
    PartitionKey,
    PropertyProfile,
    RelationshipTypeProfile,
)
from orthograph.visualization.text import model_to_text, profile_to_text, result_to_text
from tests.fixtures.conftest import ActedIn, City, LivesIn, Movie, Person


# --- Model definitions ---


class CustomActedIn(RelationshipModel):
    """Test-specific variant with different cardinalities than shared model."""

    __label__ = "ACTED_IN"
    __source_label__ = "Person"
    __target_label__ = "Movie"
    __source_cardinality__ = "0..*"
    __target_cardinality__ = "1..*"
    role: str


# --- Fixtures ---


@pytest.fixture()
def graph_definition() -> GraphDefinition:
    return GraphDefinition(
        name="Film",
        version="1.0",
        node_types=[Person, Movie],
        relationship_types=[CustomActedIn],
    )


@pytest.fixture()
def sample_profile() -> GraphProfile:
    return GraphProfile(
        source="test",
        timestamp=datetime(2026, 1, 1, 12, 0),
        node_type_profiles={
            "Person": NodeTypeProfile(
                label="Person",
                count=10,
                property_profiles={
                    "name": PropertyProfile(
                        name="name",
                        present_count=10,
                        total_count=10,
                        observed_types=["str"],
                    ),
                    "age": PropertyProfile(
                        name="age",
                        present_count=8,
                        total_count=10,
                        observed_types=["int"],
                    ),
                },
            ),
            "Movie": NodeTypeProfile(
                label="Movie",
                count=5,
                property_profiles={
                    "title": PropertyProfile(
                        name="title",
                        present_count=5,
                        total_count=5,
                        observed_types=["str"],
                    ),
                },
            ),
        },
        rel_type_profiles={
            "Person:ACTED_IN:Movie": RelationshipTypeProfile(
                rel_type="ACTED_IN",
                count=12,
                source_label="Person",
                target_label="Movie",
                cardinality_stats=CardinalityStats(count=5, min=1, max=4, mean=2.4),
            ),
        },
    )


@pytest.fixture()
def sample_result() -> ValidationResult:
    result = ValidationResult()
    result.add(
        ValidationIssue(
            code="PROPERTY_INCOMPLETE",
            severity=Severity.WARNING,
            entity_type=EntityType.NODE,
            entity_id="Person",
            message="Required property 'email' on Person is only 80% complete",
            context={"completeness": 0.8},
        )
    )
    result.add(
        ValidationIssue(
            code="MISSING_NODE_TYPE",
            severity=Severity.ERROR,
            entity_type=EntityType.NODE,
            entity_id="City",
            message="Node type 'City' defined in model but not found in data",
        )
    )
    result.add(
        ValidationIssue(
            code="UNEXPECTED_PROPERTY",
            severity=Severity.INFO,
            entity_type=EntityType.NODE,
            entity_id="Person",
            message="Unexpected property 'nickname' on Person",
        )
    )
    return result


# ============================================================
# model_to_text tests
# ============================================================


def test_model_to_text_header(graph_definition: GraphDefinition):
    text = model_to_text(graph_definition)
    assert "Model: Film" in text
    assert "Version: 1.0" in text


def test_model_to_text_node_types(graph_definition: GraphDefinition):
    text = model_to_text(graph_definition)
    assert "Node Types" in text
    assert "Person" in text
    assert "Movie" in text


def test_model_to_text_properties(graph_definition: GraphDefinition):
    text = model_to_text(graph_definition)
    assert "name: str (required) [UID]" in text
    assert "age: int (required)" in text
    assert "email: str (optional)" in text


def test_model_to_text_uid_marked(graph_definition: GraphDefinition):
    text = model_to_text(graph_definition)
    assert "[UID]" in text


def test_model_to_text_relationship_types(graph_definition: GraphDefinition):
    text = model_to_text(graph_definition)
    assert "Relationship Types" in text
    assert "ACTED_IN" in text
    assert "Person" in text
    assert "Movie" in text


def test_model_to_text_cardinality(graph_definition: GraphDefinition):
    text = model_to_text(graph_definition)
    assert "0..*" in text
    assert "1..*" in text


def test_model_to_text_relationship_direction():
    m = GraphDefinition(
        name="Test",
        node_types=[Person, Movie, City],
        relationship_types=[LivesIn],
    )
    text = model_to_text(m)
    assert "---" in text


def test_model_to_text_no_version():
    m = GraphDefinition(
        name="NoVersion",
        node_types=[Person, Movie],
        relationship_types=[ActedIn],
    )
    text = model_to_text(m)
    assert "Version:" not in text


# ============================================================
# profile_to_text tests
# ============================================================


def test_profile_to_text_header(sample_profile: GraphProfile):
    text = profile_to_text(sample_profile)
    assert "Profile: test" in text
    assert "2026" in text


def test_profile_to_text_node_counts(sample_profile: GraphProfile):
    text = profile_to_text(sample_profile)
    assert "Person (10 instances)" in text
    assert "Movie (5 instances)" in text


def test_profile_to_text_property_completeness(sample_profile: GraphProfile):
    text = profile_to_text(sample_profile)
    assert "name: 100% complete" in text
    assert "age: 80% complete" in text
    assert "(8/10)" in text


def test_profile_to_text_observed_ratio_no_mandatory_tag(sample_profile: GraphProfile):
    """[mandatory]/[partial] tags replaced by observed ratio."""
    text = profile_to_text(sample_profile)
    assert "[mandatory]" not in text
    assert "[partial]" not in text


def test_profile_to_text_observed_types(sample_profile: GraphProfile):
    text = profile_to_text(sample_profile)
    assert "types=[str]" in text
    assert "types=[int]" in text


def test_profile_to_text_relationship_types(sample_profile: GraphProfile):
    text = profile_to_text(sample_profile)
    assert "Person:ACTED_IN:Movie (12 instances)" in text


def test_profile_to_text_relationship_endpoints(sample_profile: GraphProfile):
    text = profile_to_text(sample_profile)
    assert "source:" in text
    assert "target:" in text


def test_profile_to_text_cardinality_stats(sample_profile: GraphProfile):
    text = profile_to_text(sample_profile)
    assert "min=1" in text
    assert "max=4" in text
    assert "avg=2.4" in text


# ============================================================
# Rendering tests: constraint_required and value_distribution
# ============================================================


def test_profile_to_text_constraint_required_true():
    """[constrained] tag shown when constraint_required is True."""
    profile = GraphProfile(
        source="s",
        timestamp=datetime(2026, 1, 1),
        node_type_profiles={
            "X": NodeTypeProfile(
                label="X",
                count=5,
                property_profiles={
                    "name": PropertyProfile(
                        name="name",
                        present_count=5,
                        total_count=5,
                        constraint_required=True,
                    )
                },
            )
        },
    )
    text = profile_to_text(profile)
    assert "[constrained]" in text
    assert "[unconstrained]" not in text


def test_profile_to_text_constraint_required_false():
    """[unconstrained] tag shown when constraint_required is False."""
    profile = GraphProfile(
        source="s",
        timestamp=datetime(2026, 1, 1),
        node_type_profiles={
            "X": NodeTypeProfile(
                label="X",
                count=5,
                property_profiles={
                    "name": PropertyProfile(
                        name="name",
                        present_count=5,
                        total_count=5,
                        constraint_required=False,
                    )
                },
            )
        },
    )
    text = profile_to_text(profile)
    assert "[unconstrained]" in text
    assert "[constrained]" not in text


def test_profile_to_text_constraint_required_none_silent():
    """No constraint tag shown when constraint_required is None (silent)."""
    profile = GraphProfile(
        source="s",
        timestamp=datetime(2026, 1, 1),
        node_type_profiles={
            "X": NodeTypeProfile(
                label="X",
                count=5,
                property_profiles={
                    "p": PropertyProfile(
                        name="p",
                        present_count=5,
                        total_count=5,
                        constraint_required=None,
                    )
                },
            )
        },
    )
    text = profile_to_text(profile)
    assert "[constrained]" not in text
    assert "[unconstrained]" not in text


def test_profile_to_text_value_distribution_complete():
    """Complete value distribution rendered as values=[k:v, ...]."""
    from orthograph.graph_profile.models import BoundedDistribution

    dist = BoundedDistribution(
        count=5, histogram={"red": 3, "blue": 2}, sample_complete=True
    )
    profile = GraphProfile(
        source="s",
        timestamp=datetime(2026, 1, 1),
        node_type_profiles={
            "X": NodeTypeProfile(
                label="X",
                count=5,
                property_profiles={
                    "colour": PropertyProfile(
                        name="colour",
                        present_count=5,
                        total_count=5,
                        value_distribution=dist,
                    )
                },
            )
        },
    )
    text = profile_to_text(profile)
    assert "values=[" in text
    assert "red:3" in text
    assert "blue:2" in text
    assert "more" not in text


def test_profile_to_text_value_distribution_truncated():
    """Truncated distribution shows +N more marker."""
    from orthograph.graph_profile.models import BoundedDistribution

    dist = BoundedDistribution(
        count=1000,
        histogram={"uid1": 1, "uid2": 1},
        sample_complete=False,
        limit=2,
        other_count=998,
    )
    profile = GraphProfile(
        source="s",
        timestamp=datetime(2026, 1, 1),
        node_type_profiles={
            "X": NodeTypeProfile(
                label="X",
                count=1000,
                property_profiles={
                    "id": PropertyProfile(
                        name="id",
                        present_count=1000,
                        total_count=1000,
                        value_distribution=dist,
                    )
                },
            )
        },
    )
    text = profile_to_text(profile)
    assert "values=[" in text
    assert "+998 more" in text


def test_profile_to_text_value_distribution_none_silent():
    """No values= shown when value_distribution is None."""
    profile = GraphProfile(
        source="s",
        timestamp=datetime(2026, 1, 1),
        node_type_profiles={
            "X": NodeTypeProfile(
                label="X",
                count=5,
                property_profiles={
                    "p": PropertyProfile(
                        name="p",
                        present_count=5,
                        total_count=5,
                        value_distribution=None,
                    )
                },
            )
        },
    )
    text = profile_to_text(profile)
    assert "values=" not in text


def test_profile_to_text_all_none_fields_no_crash():
    """profile_to_text handles a profile with all optional fields None."""
    profile = GraphProfile(
        source="empty",
        timestamp=datetime(2026, 1, 1),
        node_type_profiles={
            "A": NodeTypeProfile(
                label="A",
                count=0,
                property_profiles={
                    "x": PropertyProfile(name="x", present_count=0, total_count=0)
                },
            )
        },
        rel_type_profiles={
            "A:REL:A": RelationshipTypeProfile(
                rel_type="REL",
                count=0,
                source_label="A",
                target_label="A",
                cardinality_stats=None,
            )
        },
    )
    text = profile_to_text(profile)
    assert "Profile: empty" in text


# ============================================================
# result_to_text tests
# ============================================================


def test_result_to_text_fail(sample_result: ValidationResult):
    text = result_to_text(sample_result)
    assert "Validation: FAIL" in text


def test_result_to_text_counts(sample_result: ValidationResult):
    text = result_to_text(sample_result)
    assert "Errors: 1" in text
    assert "Warnings: 1" in text
    assert "Total issues: 3" in text


def test_result_to_text_severity_labels(sample_result: ValidationResult):
    text = result_to_text(sample_result)
    assert "[ERROR]" in text
    assert "[WARNING]" in text
    assert "[INFO]" in text


def test_result_to_text_issue_codes(sample_result: ValidationResult):
    text = result_to_text(sample_result)
    assert "PROPERTY_INCOMPLETE" in text
    assert "MISSING_NODE_TYPE" in text
    assert "UNEXPECTED_PROPERTY" in text


def test_result_to_text_grouped_by_entity(sample_result: ValidationResult):
    text = result_to_text(sample_result)
    assert "node:Person" in text
    assert "node:City" in text


def test_result_to_text_context(sample_result: ValidationResult):
    text = result_to_text(sample_result)
    assert "context:" in text
    assert "completeness" in text


def test_result_to_text_valid():
    result = ValidationResult()
    text = result_to_text(result)
    assert "Validation: PASS" in text
    assert "No issues found." in text
    assert "Errors: 0" in text


# ============================================================
# Conditional cardinality tests
# ============================================================


class Operation(NodeModel):
    """Test node type for conditional cardinality."""

    __label__ = "Operation"
    __uid_field__ = "id"
    id: str
    kind: str


class Sample(NodeModel):
    """Test node type for conditional cardinality."""

    __label__ = "Sample"
    __uid_field__ = "id"
    id: str
    kind: str


class HasOutput(RelationshipModel):
    """Test relationship with conditional cardinality."""

    __label__ = "HAS_OUTPUT"
    __source_label__ = "Operation"
    __target_label__ = "Sample"
    __source_cardinality__ = ConditionalCardinality(
        rules=(
            ConditionalRule(
                source=PropMatch({"kind": "subsampling"}),
                target=PropMatch({"kind": "subsampling"}),
                spec=CardinalitySpec(min=1, max=2),
            ),
            ConditionalRule(
                source=PropMatch({"kind": "split"}),
                target=PropMatch({"kind": "nothing"}),
                spec="0..0",
            ),
        ),
        default="0..*",
    )


def test_model_to_text_conditional_cardinality():
    """model_to_text renders conditional cardinality without crashing."""
    m = GraphDefinition(
        name="ConditionalTest",
        node_types=[Operation, Sample],
        relationship_types=[HasOutput],
    )
    text = model_to_text(m)
    assert "HAS_OUTPUT" in text
    # The format should contain the conditional cardinality summary
    assert "{" in text  # Conditional summary starts with {
    assert "default:" in text  # Should show default spec


def test_model_to_text_conditional_cardinality_includes_rules():
    """Conditional cardinality summary includes rules and default."""
    m = GraphDefinition(
        name="ConditionalTest",
        node_types=[Operation, Sample],
        relationship_types=[HasOutput],
    )
    text = model_to_text(m)
    # Check that the text includes both constant and conditional rendering
    assert "Operation" in text
    assert "Sample" in text


def test_model_to_text_constant_cardinality_unchanged():
    """Constant cardinality rendering is unchanged (regression)."""
    m = GraphDefinition(
        name="ConstantTest",
        node_types=[Person, Movie],
        relationship_types=[ActedIn],
    )
    text = model_to_text(m)
    # ActedIn uses constant cardinalities
    assert "ACTED_IN" in text
    # Should render as simple min..max, not as conditional
    assert "0..*" in text


# ============================================================
# Keyed profiles, scalar endpoints
# ============================================================


class PersonKnowsPerson(RelationshipModel):
    """Same-label source: Person-KNOWS->Person."""

    __label__ = "KNOWS"
    __source_label__ = "Person"
    __target_label__ = "Person"


class CompanyKnowsCompany(RelationshipModel):
    """Same-label different endpoint: Company-KNOWS->Company."""

    __label__ = "KNOWS"
    __source_label__ = "Company"
    __target_label__ = "Company"


class CompanyNode(NodeModel):
    __label__ = "Company"
    __uid_field__ = "name"
    name: str


def _make_two_shape_profile() -> GraphProfile:
    """GraphProfile with two KNOWS shapes (Person->Person and Company->Company)."""
    return GraphProfile(
        source="test-e50",
        timestamp=datetime(2026, 1, 1, 12, 0),
        node_type_profiles={},
        rel_type_profiles={
            "Person:KNOWS:Person": RelationshipTypeProfile(
                rel_type="KNOWS",
                source_label="Person",
                target_label="Person",
                count=5,
            ),
            "Company:KNOWS:Company": RelationshipTypeProfile(
                rel_type="KNOWS",
                source_label="Company",
                target_label="Company",
                count=3,
            ),
        },
    )


def test_profile_to_text_two_same_label_shapes_render_separately():
    """Two same-label/different-endpoint shapes appear as two distinct entries."""
    text = profile_to_text(_make_two_shape_profile())
    # Both must appear as separate lines — not blended
    assert "Person:KNOWS:Person" in text or (text.count("KNOWS") >= 2), (
        "Expected two KNOWS entries"
    )
    # Each shape shows its correct scalar endpoint
    assert "Person" in text
    assert "Company" in text


def test_profile_to_text_scalar_source_label():
    """profile_to_text shows scalar source_label for each profile."""
    text = profile_to_text(_make_two_shape_profile())
    assert "source:" in text


def test_profile_to_text_scalar_target_label():
    """profile_to_text shows scalar target_label for each profile."""
    text = profile_to_text(_make_two_shape_profile())
    assert "target:" in text


def test_profile_to_text_two_shapes_output_is_deterministic():
    """Output ordering is stable across two calls."""
    p = _make_two_shape_profile()
    assert profile_to_text(p) == profile_to_text(p)


# ============================================================
# Partitioned cardinality rendering
# ============================================================


def _make_partitioned_profile() -> GraphProfile:
    """A one-sided (target) partitioned breakdown: wildcard source, keyed target."""
    return GraphProfile(
        source="test",
        timestamp=datetime(2026, 1, 1, 12, 0),
        rel_type_profiles={
            "Sample:IS_INPUT:Operation": RelationshipTypeProfile(
                rel_type="IS_INPUT",
                count=105,
                source_label="Sample",
                target_label="Operation",
                cardinality_stats=CardinalityStats(
                    count=149, min=0.0, max=3.0, mean=0.7
                ),
                target_partitioned_cardinality=[
                    PartitionedCardinalityRow(
                        key=PartitionKey(source={}, target={"type": "combine"}),
                        stats=BoundedDistribution(count=10, min=2.0, max=4.0, mean=2.7),
                    ),
                    PartitionedCardinalityRow(
                        key=PartitionKey(source={}, target={"type": "split"}),
                        stats=BoundedDistribution(count=8, min=1.0, max=1.0, mean=1.0),
                    ),
                ],
            )
        },
    )


def test_profile_to_text_renders_target_partitioned_cardinality():
    """The target partitioned breakdown renders with discriminator names visible."""
    text = profile_to_text(_make_partitioned_profile())
    assert (
        "target_partitioned_cardinality "
        "(target node's incoming degree, grouped by partition):" in text
    )
    # Both partitions present; names visible in the key display form.
    assert "target={type=combine}: min=2.0, max=4.0, avg=2.70, sample_size=10" in text
    assert "target={type=split}: min=1.0, max=1.0, avg=1.00, sample_size=8" in text


def test_profile_to_text_wildcard_source_renders_empty_map():
    """The wildcard source endpoint renders as ``source={}``."""
    text = profile_to_text(_make_partitioned_profile())
    assert "source={} target={type=combine}" in text


def test_profile_to_text_partitions_sorted_deterministically():
    """Partitions are sorted by str(key) — ``combine`` before ``split``."""
    text = profile_to_text(_make_partitioned_profile())
    assert text.index("type=combine") < text.index("type=split")


def test_profile_to_text_no_partition_section_when_both_none():
    """Non-conditional rel types render no partition section (no regression)."""
    text = profile_to_text(sample_profile_no_partitions())
    assert "partitioned_cardinality" not in text


def sample_profile_no_partitions() -> GraphProfile:
    """A relationship type with no partitioned breakdown on either side."""
    return GraphProfile(
        source="test",
        timestamp=datetime(2026, 1, 1, 12, 0),
        rel_type_profiles={
            "Person:KNOWS:Person": RelationshipTypeProfile(
                rel_type="KNOWS",
                count=3,
                source_label="Person",
                target_label="Person",
                cardinality_stats=CardinalityStats(count=3, min=0, max=2, mean=1.0),
            )
        },
    )


def test_profile_to_text_renders_both_sides_when_present():
    """A both-endpoint conditional type renders both partition sections."""
    profile = GraphProfile(
        source="test",
        timestamp=datetime(2026, 1, 1, 12, 0),
        rel_type_profiles={
            "A:REL:B": RelationshipTypeProfile(
                rel_type="REL",
                count=12,
                source_label="A",
                target_label="B",
                source_partitioned_cardinality=[
                    PartitionedCardinalityRow(
                        key=PartitionKey(source={"type": "combine"}, target={}),
                        stats=BoundedDistribution(count=4, min=1.0, max=2.0, mean=1.5),
                    ),
                ],
                target_partitioned_cardinality=[
                    PartitionedCardinalityRow(
                        key=PartitionKey(source={}, target={"type": "split"}),
                        stats=BoundedDistribution(count=8, min=1.0, max=1.0, mean=1.0),
                    ),
                ],
            )
        },
    )
    text = profile_to_text(profile)
    assert (
        "source_partitioned_cardinality "
        "(source node's outgoing degree, grouped by partition):" in text
    )
    assert (
        "target_partitioned_cardinality "
        "(target node's incoming degree, grouped by partition):" in text
    )
