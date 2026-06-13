"""Tests for cypher.identifiers — safe-identifier validation/escaping (E17 T1).

Pure string rules; no model, no generator, no session.
"""

import pytest

from orthograph.cypher.exceptions import CypherIdentifierError
from orthograph.cypher.identifiers import (
    escape_identifier,
    is_safe_identifier,
    validate_identifier,
)


def test_is_safe_identifier_accepts_plain_identifier() -> None:
    assert is_safe_identifier("Person") is True
    assert is_safe_identifier("rel_type") is True
    assert is_safe_identifier("_x") is True


def test_is_safe_identifier_rejects_unsafe() -> None:
    assert is_safe_identifier("Per son") is False
    assert is_safe_identifier("1Movie") is False
    assert is_safe_identifier("x} ) DETACH DELETE n //") is False
    assert is_safe_identifier("") is False


def test_is_safe_identifier_rejects_trailing_newline() -> None:
    # ``$`` would match just before a final ``\n``; ``\Z`` must not. A trailing
    # newline is the only character a ``$``-anchored grammar would smuggle past
    # this gate, so it is the regression guard for the anchor.
    assert is_safe_identifier("Person\n") is False
    assert is_safe_identifier("\nPerson") is False
    assert is_safe_identifier("Person\nDETACH DELETE n") is False


def test_validate_identifier_returns_safe_name() -> None:
    assert validate_identifier("Person", kind="label") == "Person"


def test_validate_identifier_raises_on_unsafe_mentioning_kind() -> None:
    with pytest.raises(CypherIdentifierError, match="property key"):
        validate_identifier("x`y", kind="property key")


def test_validate_identifier_rejects_injection() -> None:
    with pytest.raises(CypherIdentifierError, match="label"):
        validate_identifier("x) DETACH DELETE (n //", kind="label")


def test_escape_identifier_doubles_internal_backtick() -> None:
    assert escape_identifier("Fo`o") == "`Fo``o`"
    assert escape_identifier("Foo") == "`Foo`"
