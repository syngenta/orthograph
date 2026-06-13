"""Tests for orthograph.diagnostics -- validation value-objects and errors."""

import pytest

from orthograph.diagnostics.classification import EntityType, Severity
from orthograph.diagnostics.result import (
    GraphValidationError,
    ValidationIssue,
    ValidationResult,
)


# --- ValidationIssue tests ---


def test_validation_issue_create_error():
    issue = ValidationIssue(
        code="UNKNOWN_LABEL",
        severity=Severity.ERROR,
        entity_type=EntityType.NODE,
        entity_id="node_123",
        message="Unknown node label: Foo",
    )
    assert issue.code == "UNKNOWN_LABEL"
    assert issue.severity == Severity.ERROR
    assert issue.entity_type == EntityType.NODE
    assert issue.entity_id == "node_123"
    assert issue.message == "Unknown node label: Foo"
    assert issue.context == {}


def test_validation_issue_create_with_context():
    issue = ValidationIssue(
        code="CARDINALITY_VIOLATION",
        severity=Severity.ERROR,
        entity_type=EntityType.NODE,
        entity_id="person_1",
        message="Expected 1..1 LIVES_IN, found 0",
        context={"expected_min": 1, "expected_max": 1, "actual": 0},
    )
    assert issue.context["expected_min"] == 1
    assert issue.context["actual"] == 0


def test_validation_issue_create_warning():
    issue = ValidationIssue(
        code="ISOLATED_NODE",
        severity=Severity.WARNING,
        entity_type=EntityType.NODE,
        entity_id="orphan_1",
        message="Node has no relationships",
    )
    assert issue.severity == Severity.WARNING


def test_validation_issue_str_representation():
    issue = ValidationIssue(
        code="MISSING_PROPERTY",
        severity=Severity.ERROR,
        entity_type=EntityType.NODE,
        entity_id="n1",
        message="Missing required property: name",
    )
    s = str(issue)
    assert "MISSING_PROPERTY" in s
    assert "ERROR" in s.upper() or "error" in s


# --- ValidationResult tests ---


def test_validation_result_empty_is_valid():
    result = ValidationResult()
    assert result.is_valid
    assert len(result.issues) == 0


def test_validation_result_add_error_makes_invalid():
    result = ValidationResult()
    result.add(
        ValidationIssue(
            code="TEST",
            severity=Severity.ERROR,
            entity_type=EntityType.NODE,
            entity_id="n1",
            message="test error",
        )
    )
    assert not result.is_valid
    assert len(result.issues) == 1


def test_validation_result_warnings_dont_invalidate():
    result = ValidationResult()
    result.add(
        ValidationIssue(
            code="TEST",
            severity=Severity.WARNING,
            entity_type=EntityType.NODE,
            entity_id="n1",
            message="test warning",
        )
    )
    assert result.is_valid
    assert len(result.issues) == 1


def test_validation_result_errors_property():
    result = ValidationResult()
    result.add(
        ValidationIssue(
            code="ERR",
            severity=Severity.ERROR,
            entity_type=EntityType.NODE,
            entity_id="n1",
            message="error",
        )
    )
    result.add(
        ValidationIssue(
            code="WARN",
            severity=Severity.WARNING,
            entity_type=EntityType.NODE,
            entity_id="n2",
            message="warning",
        )
    )
    assert len(result.errors) == 1
    assert len(result.warnings) == 1
    assert result.errors[0].code == "ERR"
    assert result.warnings[0].code == "WARN"


def test_validation_result_merge():
    r1 = ValidationResult()
    r1.add(
        ValidationIssue(
            code="A",
            severity=Severity.ERROR,
            entity_type=EntityType.NODE,
            entity_id="n1",
            message="a",
        )
    )
    r2 = ValidationResult()
    r2.add(
        ValidationIssue(
            code="B",
            severity=Severity.ERROR,
            entity_type=EntityType.RELATIONSHIP,
            entity_id="r1",
            message="b",
        )
    )
    r1.merge(r2)
    assert len(r1.issues) == 2
    assert not r1.is_valid


def test_validation_result_raise_on_errors():
    result = ValidationResult()
    result.add(
        ValidationIssue(
            code="X",
            severity=Severity.ERROR,
            entity_type=EntityType.NODE,
            entity_id="n1",
            message="fail",
        )
    )
    with pytest.raises(GraphValidationError):
        result.raise_on_errors()


def test_validation_result_raise_on_errors_no_errors():
    result = ValidationResult()
    result.raise_on_errors()  # Should not raise
