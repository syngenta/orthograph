"""Tests for cypher.exceptions — the Cypher extension's exception hierarchy."""

from orthograph.cypher.exceptions import (
    CypherError,
    CypherQueryDefinitionError,
    CypherSyntaxError,
)


def test_cypher_error_is_plain_exception_not_typeerror() -> None:
    assert issubclass(CypherError, Exception)
    assert not issubclass(CypherError, TypeError)


def test_all_cypher_exceptions_derive_from_cypher_error() -> None:
    assert issubclass(CypherQueryDefinitionError, CypherError)
    assert issubclass(CypherSyntaxError, CypherError)


def test_specific_exceptions_are_catchable_as_the_base() -> None:
    for exc in (CypherQueryDefinitionError("boom"), CypherSyntaxError("boom")):
        try:
            raise exc
        except CypherError as caught:
            assert str(caught) == "boom"
