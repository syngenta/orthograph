"""Tests for cypher.exceptions — the Cypher extension's exception hierarchy."""

from orthograph.cypher.exceptions import (
    CypherCatalogueLoadError,
    CypherError,
    CypherQueryDefinitionError,
    CypherQuerySpecError,
    CypherSyntaxError,
)


def test_cypher_error_is_plain_exception_not_typeerror() -> None:
    """CypherError is a plain Exception, not a TypeError."""
    assert issubclass(CypherError, Exception)
    assert not issubclass(CypherError, TypeError)


def test_all_cypher_exceptions_derive_from_cypher_error() -> None:
    """All Cypher exceptions inherit from CypherError."""
    assert issubclass(CypherQueryDefinitionError, CypherError)
    assert issubclass(CypherSyntaxError, CypherError)
    assert issubclass(CypherQuerySpecError, CypherError)
    assert issubclass(CypherCatalogueLoadError, CypherError)


def test_specific_exceptions_are_catchable_as_the_base() -> None:
    """Each specific exception can be caught as CypherError."""
    for exc in (
        CypherQueryDefinitionError("boom"),
        CypherSyntaxError("boom"),
        CypherQuerySpecError("boom"),
        CypherCatalogueLoadError("boom"),
    ):
        try:
            raise exc
        except CypherError as caught:
            assert str(caught) == "boom"


def test_query_spec_error_and_catalogue_load_error_are_independent() -> None:
    """CypherQuerySpecError and CypherCatalogueLoadError
    do not inherit from each other."""
    assert not issubclass(CypherQuerySpecError, CypherCatalogueLoadError)
    assert not issubclass(CypherCatalogueLoadError, CypherQuerySpecError)
