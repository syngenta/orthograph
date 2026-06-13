"""Tests for orthograph.graph_definition.exceptions -- model-definition exceptions.

Validation value-object tests (ValidationIssue, ValidationResult,
GraphValidationError) live in tests/diagnostics/test_result.py.
"""

from orthograph.graph_definition.exceptions import (
    MissingClassVarError,
    MissingUidFieldError,
    ModelDefinitionError,
)


def test_model_definition_error_is_exception():
    err = ModelDefinitionError("bad model")
    assert isinstance(err, Exception)


def test_model_definition_error_is_not_type_error():
    err = ModelDefinitionError("bad model")
    assert not isinstance(err, TypeError)


def test_missing_class_var_error_is_model_definition_error():
    err = MissingClassVarError("missing __label__")
    assert isinstance(err, ModelDefinitionError)
    assert isinstance(err, Exception)


def test_missing_uid_field_error_is_model_definition_error():
    err = MissingUidFieldError("no uid field")
    assert isinstance(err, ModelDefinitionError)
    assert isinstance(err, Exception)


def test_model_definition_error_message():
    err = ModelDefinitionError("MyNode is missing __label__")
    assert "MyNode" in str(err)
