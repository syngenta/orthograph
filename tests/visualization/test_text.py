"""Tests for orthograph.visualization.text."""

from datetime import datetime
from typing import Optional

import pytest

from orthograph.core.errors import ValidationIssue, ValidationResult
from orthograph.core.graph_data_model import GraphDataModel
from orthograph.core.node_model import NodeModel
from orthograph.core.relationship_model import RelationshipModel
from orthograph.core.types import Cardinality, EntityType, Severity
from orthograph.extensions.models import (
    CardinalityStats,
    GraphProfile,
    NodeTypeProfile,
    PropertyProfile,
    RelationshipTypeProfile,
)
from orthograph.visualization.text import model_to_text, profile_to_text, result_to_text


# --- Model definitions ---


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


class ActedIn(RelationshipModel):
    __label__ = "ACTED_IN"
    __source_type__ = Person
    __target_type__ = Movie
    __source_cardinality__ = Cardinality.ZERO_OR_MORE
    __target_cardinality__ = Cardinality.ONE_OR_MORE
    role: str


class LivesIn(RelationshipModel):
    __label__ = "LIVES_IN"
    __source_type__ = Person
    __target_type__ = Movie
    __source_cardinality__ = Cardinality.ONE
    __directed__ = False


# --- Fixtures ---


@pytest.fixture()
def model() -> GraphDataModel:
    return GraphDataModel(
        name="Film",
        version="1.0",
        node_types=[Person, Movie],
        relationship_types=[ActedIn],
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
            "ACTED_IN": RelationshipTypeProfile(
                rel_type="ACTED_IN",
                count=12,
                source_labels={"Person"},
                target_labels={"Movie"},
                cardinality_stats=CardinalityStats(
                    min_degree=1, max_degree=4, avg_degree=2.4, sample_size=5
                ),
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


def test_model_to_text_header(model: GraphDataModel):
    text = model_to_text(model)
    assert "Model: Film" in text
    assert "Version: 1.0" in text


def test_model_to_text_node_types(model: GraphDataModel):
    text = model_to_text(model)
    assert "Node Types" in text
    assert "Person" in text
    assert "Movie" in text


def test_model_to_text_properties(model: GraphDataModel):
    text = model_to_text(model)
    assert "name: str (required) [UID]" in text
    assert "age: int (required)" in text
    assert "email: str (optional)" in text


def test_model_to_text_uid_marked(model: GraphDataModel):
    text = model_to_text(model)
    assert "[UID]" in text


def test_model_to_text_relationship_types(model: GraphDataModel):
    text = model_to_text(model)
    assert "Relationship Types" in text
    assert "ACTED_IN" in text
    assert "Person" in text
    assert "Movie" in text


def test_model_to_text_cardinality(model: GraphDataModel):
    text = model_to_text(model)
    assert "0..*" in text
    assert "1..*" in text


def test_model_to_text_relationship_direction():
    m = GraphDataModel(
        name="Test",
        node_types=[Person, Movie],
        relationship_types=[LivesIn],
    )
    text = model_to_text(m)
    assert "---" in text


def test_model_to_text_no_version():
    m = GraphDataModel(
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


def test_profile_to_text_mandatory_partial(sample_profile: GraphProfile):
    text = profile_to_text(sample_profile)
    assert "[mandatory]" in text  # name is 100% complete
    assert "[partial]" in text  # age is 80% complete


def test_profile_to_text_observed_types(sample_profile: GraphProfile):
    text = profile_to_text(sample_profile)
    assert "types=[str]" in text
    assert "types=[int]" in text


def test_profile_to_text_relationship_types(sample_profile: GraphProfile):
    text = profile_to_text(sample_profile)
    assert "ACTED_IN (12 instances)" in text


def test_profile_to_text_relationship_endpoints(sample_profile: GraphProfile):
    text = profile_to_text(sample_profile)
    assert "sources:" in text
    assert "targets:" in text


def test_profile_to_text_cardinality_stats(sample_profile: GraphProfile):
    text = profile_to_text(sample_profile)
    assert "min=1" in text
    assert "max=4" in text
    assert "avg=2.4" in text


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
