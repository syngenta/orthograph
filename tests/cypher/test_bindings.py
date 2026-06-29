"""Tests for cypher.bindings — the parser-free parameter/identifier core.

These lock two things:
  * the pure parameter/identifier helpers behave correctly, and
  * the module carries no parser/graphglot dependency, so other Cypher-emitting
    backends can reuse it without pulling in graphglot.
"""

import ast

import pytest
from pydantic import BaseModel

from orthograph.cypher.bindings import (
    NoIdentifiers,
    NoParams,
    check_placeholder_alignment,
    extract_cypher_identifiers,
    extract_cypher_params,
    identifier_kind,
    render_with_identifiers,
    substitute_identifier_placeholders,
)
from orthograph.cypher.exceptions import (
    CypherIdentifierError,
    CypherQueryDefinitionError,
)


def test_empty_models_have_no_fields() -> None:
    assert NoParams.model_fields == {}
    assert NoIdentifiers.model_fields == {}


def test_extract_params_and_identifiers_are_independent() -> None:
    cypher = "MATCH (n:`<<label>>` {released: $released}) RETURN n"
    assert extract_cypher_params(cypher) == {"released"}
    assert extract_cypher_identifiers(cypher) == {"label"}


def test_extract_cypher_params_empty_when_no_params() -> None:
    assert extract_cypher_params("MATCH (m:Movie) RETURN m") == set()


def test_extract_cypher_identifiers_ignores_value_placeholders() -> None:
    assert extract_cypher_identifiers("MATCH (m {released: $released}) RETURN m") == (
        set()
    )


def test_extract_params_matches_ascii_grammar_not_unicode() -> None:
    """The $name pattern is the ASCII identifier grammar, not \\w: it stops at a
    Unicode word char (which \\w under re.UNICODE would have consumed) rather
    than capturing it, and it never starts a name on a digit.
    """
    # Under \\w the whole "caf\u00e9" would be captured; the ASCII grammar stops
    # at the accented char, capturing only the ASCII prefix.
    assert extract_cypher_params("RETURN $caf\u00e9") == {"caf"}
    # ASCII identifiers (including a trailing digit) match in full.
    assert extract_cypher_params("RETURN $name1") == {"name1"}
    # A name cannot start with a digit; the leading digit is not captured.
    assert extract_cypher_params("RETURN $1name") == set()


def test_extract_identifiers_matches_ascii_grammar_not_unicode() -> None:
    """Mirror of the $param check for the <<name>> identifier placeholder."""
    # "<<caf\u00e9>>": the accented char breaks the name, so the trailing ">>"
    # is missing for the captured prefix and the placeholder does not match.
    assert extract_cypher_identifiers("MATCH (n:`<<caf\u00e9>>`) RETURN n") == set()
    assert extract_cypher_identifiers("MATCH (n:`<<label1>>`) RETURN n") == {"label1"}
    assert extract_cypher_identifiers("MATCH (n:`<<1label>>`) RETURN n") == set()


def test_substitute_identifier_placeholders_swaps_all() -> None:
    cypher = "MATCH (n:`<<label>>`)-[r:`<<rel_type>>`]->(m) RETURN n"
    assert substitute_identifier_placeholders(cypher, "X") == (
        "MATCH (n:`X`)-[r:`X`]->(m) RETURN n"
    )


def test_substitute_identifier_placeholders_noop_without_placeholders() -> None:
    cypher = "MATCH (m:Movie {released: $released}) RETURN m"
    assert substitute_identifier_placeholders(cypher, "X") == cypher


def test_extract_cypher_identifiers_dedupes_repeated_name() -> None:
    """A placeholder used twice is reported once (set semantics)."""
    cypher = "MATCH (n:`<<label>>`) WHERE n.x = 1 RETURN n // also `<<label>>`"
    assert extract_cypher_identifiers(cypher) == {"label"}


def test_identifier_kind_rule() -> None:
    assert identifier_kind("label") == "label"
    assert identifier_kind("source_label") == "label"
    assert identifier_kind("rel_type") == "relationship type"
    assert identifier_kind("edge_rel_type") == "relationship type"


def test_render_with_identifiers_no_op_when_empty() -> None:
    cypher = "MATCH (m:Movie {released: $released}) RETURN m"
    assert render_with_identifiers(cypher, NoIdentifiers()) == cypher


def test_render_with_identifiers_validates_and_splices() -> None:
    class Ids(BaseModel):
        label: str

    out = render_with_identifiers("MATCH (n:`<<label>>`) RETURN n", Ids(label="Person"))
    assert out == "MATCH (n:`Person`) RETURN n"


def test_render_with_identifiers_rejects_injection() -> None:
    class Ids(BaseModel):
        label: str

    with pytest.raises(CypherIdentifierError, match="label"):
        render_with_identifiers(
            "MATCH (n:`<<label>>`) RETURN n", Ids(label="x) DETACH DELETE (n //")
        )


def test_render_with_identifiers_splices_multiple_fields() -> None:
    class Ids(BaseModel):
        label: str
        rel_type: str

    out = render_with_identifiers(
        "MATCH (n:`<<label>>`)-[r:`<<rel_type>>`]->(m) RETURN n",
        Ids(label="Person", rel_type="ACTED_IN"),
    )
    assert out == "MATCH (n:`Person`)-[r:`ACTED_IN`]->(m) RETURN n"


def test_render_with_identifiers_unresolved_placeholder_raises() -> None:
    """A <<name>> with no matching field is caught at render time, not left to
    surface as an opaque driver syntax error (regression guard).
    """
    # NoIdentifiers has no fields, so <<label>> can never be substituted.
    with pytest.raises(CypherQueryDefinitionError, match=r"<<label>>"):
        render_with_identifiers("MATCH (n:`<<label>>`) RETURN n", NoIdentifiers())


def test_render_with_identifiers_partial_mismatch_raises() -> None:
    """A model that resolves some placeholders but leaves one unmatched still
    raises, naming the leftover.
    """

    class OnlyLabel(BaseModel):
        label: str

    with pytest.raises(CypherQueryDefinitionError, match=r"<<rel_type>>"):
        render_with_identifiers(
            "MATCH (n:`<<label>>`)-[r:`<<rel_type>>`]->(m) RETURN n",
            OnlyLabel(label="Person"),
        )


def test_render_with_identifiers_extra_field_without_placeholder_is_noop() -> None:
    """An identifiers field with no placeholder in the template does not corrupt
    the output (it simply finds nothing to replace). check_placeholder_alignment
    is what flags this 1:1 at definition time; render itself stays lenient on
    extra fields and strict on leftover placeholders.
    """

    class Ids(BaseModel):
        label: str

    out = render_with_identifiers("MATCH (n:Movie) RETURN n", Ids(label="Person"))
    assert out == "MATCH (n:Movie) RETURN n"


def test_render_with_identifiers_no_op_preserves_value_placeholders() -> None:
    """With empty identifiers, $value placeholders are left untouched (only
    <<name>> is the render's concern).
    """
    cypher = "MATCH (m:Movie {released: $released}) RETURN m"
    assert render_with_identifiers(cypher, NoIdentifiers()) == cypher


def test_check_placeholder_alignment_returns_problems_without_raising() -> None:
    class ParamsModel(BaseModel):
        released: int

    class IdsModel(BaseModel):
        label: str

    class Q:
        params_schema = ParamsModel
        identifiers_schema = IdsModel

    # Both a missing $param field and a missing <<name>> field.
    problems = check_placeholder_alignment(Q, "MATCH (n) RETURN n")
    assert any("released" in p for p in problems)
    assert any("label" in p for p in problems)
    # Pure function: it returns problems, it does not raise.
    assert isinstance(problems, list)


def test_check_placeholder_alignment_clean_query_has_no_problems() -> None:
    class ParamsModel(BaseModel):
        released: int

    class Q:
        params_schema = ParamsModel
        identifiers_schema = NoIdentifiers

    assert (
        check_placeholder_alignment(Q, "MATCH (m:Movie {released: $released}) RETURN m")
        == []
    )


def test_check_placeholder_alignment_flags_unused_identifier_field() -> None:
    """An Identifiers field with no matching <<name>> is flagged (the unused-id
    branch), mirroring the unused-$param check.
    """

    class IdsModel(BaseModel):
        label: str

    class Q:
        params_schema = NoParams
        identifiers_schema = IdsModel

    problems = check_placeholder_alignment(Q, "MATCH (n:Movie) RETURN n")
    assert any("<<label>>" in p and "no matching placeholder" in p for p in problems)


def test_check_placeholder_alignment_flags_undeclared_identifier_placeholder() -> None:
    """A <<name>> with no matching Identifiers field is flagged (the missing-id
    branch).
    """

    class Q:
        params_schema = NoParams
        identifiers_schema = NoIdentifiers

    problems = check_placeholder_alignment(Q, "MATCH (n:`<<label>>`) RETURN n")
    assert any("<<label>>" in p and "not declared" in p for p in problems)


def test_check_placeholder_alignment_ignores_absent_or_non_model_attrs() -> None:
    """If Params/Identifiers are absent or not BaseModel subclasses, the function
    does not crash and simply skips those checks.
    """

    class NoAttrs:
        pass

    class BadTypes:
        params_schema = "not a model"
        identifiers_schema = 123

    assert check_placeholder_alignment(NoAttrs, "MATCH (n) RETURN n") == []
    assert check_placeholder_alignment(BadTypes, "MATCH (n) RETURN n") == []


def test_bindings_imports_no_parser_or_graphglot() -> None:
    """Static guard: the module must not import the parser or graphglot, so a
    sibling Cypher-emitting backend can reuse it without that dependency.
    """
    import orthograph.cypher.bindings as bindings

    src = ast.parse(open(bindings.__file__, encoding="utf-8").read())
    modules = {
        node.module
        for node in ast.walk(src)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    modules |= {
        alias.name
        for node in ast.walk(src)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert not any("graphglot" in m for m in modules)
    assert not any(m.endswith(".parser") for m in modules)
    assert not any(m.endswith(".base_models") for m in modules)
