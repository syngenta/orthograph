"""Static validation of a :class:`QueryCatalogue` against a :class:`GraphDefinition`.

Declarative Cypher queries (``cypher_template`` set) are validated against the
model.  Imperative or non-Cypher queries are reported as ``QUERY_UNVERIFIABLE``
(INFO) with the reason — never silently skipped or counted as passing.
"""

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel

from orthograph.comparison.engine import compare_profile_to_definition
from orthograph.comparison.rules import Rule
from orthograph.cypher.bindings import (
    NoIdentifiers,
    _check_model_alignment,
    extract_cypher_identifiers,
    extract_cypher_params,
)
from orthograph.cypher.parser import (
    ReturnColumn,
    ReturnKind,
    extract_return_columns,
    parse_cypher,
    validate_cypher,
)
from orthograph.cypher.query import CypherQuery
from orthograph.diagnostics.classification import EntityType, Severity
from orthograph.diagnostics.result import ValidationIssue, ValidationResult
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.models import NodeModel, RelationshipModel
from orthograph.graph_profile.models import GraphProfile
from orthograph.query.base_models import Backend, ReadQuery, WriteQuery
from orthograph.query.catalogue import QueryCatalogue


def _unverifiable(name: str, reason: str) -> ValidationIssue:
    return ValidationIssue(
        code="QUERY_UNVERIFIABLE",
        severity=Severity.INFO,
        entity_type=EntityType.QUERY,
        entity_id=name,
        message=f"Query '{name}' could not be statically validated: {reason}",
    )


def _is_projection_output(output_model: type[BaseModel]) -> bool:
    """True when every field of *output_model* is itself a Node/Rel model.

    Such an Output is a *projection*: its fields are filled from whole-node /
    whole-rel RETURN columns, so the variable-name↔field-name gap is the
    legitimate ``materialize`` seam and must not be reported as a mismatch.
    """
    field_types = [
        f.annotation
        for f in output_model.model_fields.values()
        if f.annotation is not None
    ]
    return bool(field_types) and all(
        isinstance(ft, type) and issubclass(ft, (NodeModel, RelationshipModel))
        for ft in field_types
    )


def _label_mismatch_issue(
    col: ReturnColumn, expected_label: str, query_name: str
) -> ValidationIssue:
    return ValidationIssue(
        code="QUERY_RETURN_OUTPUT_LABEL_MISMATCH",
        severity=Severity.ERROR,
        entity_type=EntityType.QUERY,
        entity_id=query_name,
        message=(
            f"Query '{query_name}': RETURN projects "
            f"'{col.name}' (label '{col.label}') but "
            f"Output expects label '{expected_label}'"
        ),
    )


def _no_whole_column_issue(
    query_name: str, *, is_node_model: bool, expected_label: str | None
) -> ValidationIssue:
    model_kind = "NodeModel" if is_node_model else "RelationshipModel"
    column_kind = "node" if is_node_model else "relationship"
    return ValidationIssue(
        code="QUERY_RETURN_OUTPUT_MISMATCH",
        severity=Severity.ERROR,
        entity_type=EntityType.QUERY,
        entity_id=query_name,
        message=(
            f"Query '{query_name}': Output is a {model_kind} "
            f"('{expected_label}') but RETURN contains no matching "
            f"whole-{column_kind} column"
        ),
    )


def _check_whole_entity_alignment(
    return_cols: list[ReturnColumn],
    query_name: str,
    *,
    is_node_model: bool,
    expected_label: str | None,
) -> list[ValidationIssue]:
    """Align a NodeModel / RelationshipModel Output against the RETURN columns.

    Valid when exactly one matching whole-node / whole-rel column carries the
    expected label.  A single column with the wrong label is a
    ``QUERY_RETURN_OUTPUT_LABEL_MISMATCH`` ERROR; columns present but none of the
    matching kind is a ``QUERY_RETURN_OUTPUT_MISMATCH`` ERROR.
    """
    expected_kind = ReturnKind.WHOLE_NODE if is_node_model else ReturnKind.WHOLE_REL
    whole_cols = [c for c in return_cols if c.kind == expected_kind]

    if len(whole_cols) == 1:
        col = whole_cols[0]
        if expected_label and col.label and col.label != expected_label:
            return [_label_mismatch_issue(col, expected_label, query_name)]
        return []

    if len(whole_cols) == 0 and return_cols:
        # Columns present but none whole-node/whole-rel for a Node/Rel Output —
        # e.g. a scalar-only return against a NodeModel.  Emit one ERROR rather
        # than staying silent.
        return [
            _no_whole_column_issue(
                query_name,
                is_node_model=is_node_model,
                expected_label=expected_label,
            )
        ]

    # More than one matching column → valid (unchanged policy).
    return []


def _check_flat_field_alignment(
    return_cols: list[ReturnColumn],
    output_model: type[BaseModel],
    query_name: str,
) -> list[ValidationIssue]:
    """Align a flat scalar Output against the scalar RETURN columns.

    Each Output field with no matching scalar column is reported: required
    fields as a ``QUERY_RETURN_OUTPUT_MISMATCH`` ERROR, optional fields as the
    same code at INFO.
    """
    scalar_col_names = {c.name for c in return_cols if c.kind == ReturnKind.SCALAR}
    issues: list[ValidationIssue] = []
    for field_name, field_info in sorted(output_model.model_fields.items()):
        if field_name in scalar_col_names:
            continue
        if field_info.is_required():
            issues.append(
                ValidationIssue(
                    code="QUERY_RETURN_OUTPUT_MISMATCH",
                    severity=Severity.ERROR,
                    entity_type=EntityType.QUERY,
                    entity_id=query_name,
                    message=(
                        f"Query '{query_name}': Output field '{field_name}' has no "
                        "matching column in the RETURN clause"
                    ),
                )
            )
        else:
            issues.append(
                ValidationIssue(
                    code="QUERY_RETURN_OUTPUT_MISMATCH",
                    severity=Severity.INFO,
                    entity_type=EntityType.QUERY,
                    entity_id=query_name,
                    message=(
                        f"Query '{query_name}': optional field '{field_name}' "
                        "has no matching RETURN column"
                    ),
                )
            )
    return issues


def _check_return_output_alignment(
    return_cols: list[ReturnColumn],
    output_model: type[BaseModel],
    query_name: str,
) -> list[ValidationIssue]:
    """Tiered RETURN→Output alignment check: classify the Output, then route.

    Three Output shapes, each with its own alignment rule:

    * **whole-entity** (Output is a ``NodeModel`` / ``RelationshipModel``) →
      :func:`_check_whole_entity_alignment` (exactly one matching whole column
      of the right label).
    * **projection** (Output fields are themselves Node/Rel models) → no noise;
      the variable-name↔field-name gap is the legitimate ``materialize`` seam.
    * **flat scalar** (any other ``BaseModel``) → :func:`_check_flat_field_alignment`
      (each Output field must have a matching scalar RETURN column).

    Extra RETURN columns not in ``Output`` are never reported (unchanged policy).
    Returns an empty list when the alignment is considered valid.
    """
    if issubclass(output_model, NodeModel) or issubclass(
        output_model, RelationshipModel
    ):
        is_node_model = issubclass(output_model, NodeModel)
        return _check_whole_entity_alignment(
            return_cols,
            query_name,
            is_node_model=is_node_model,
            expected_label=getattr(output_model, "__label__", None),
        )

    if _is_projection_output(output_model):
        return []

    return _check_flat_field_alignment(return_cols, output_model, query_name)


def _check_identifier_injection(
    cypher_template: str, query_name: str
) -> list[ValidationIssue]:
    """Check if a query uses identifier injection (<<...>> placeholders).

    Emits one ``QUERY_USES_IDENTIFIER_INJECTION`` INFO issue if the query
    contains at least one ``<<name>>`` placeholder.

    Returns an empty list if no identifier injection is detected.
    """
    identifiers = extract_cypher_identifiers(cypher_template)
    if identifiers:
        return [
            ValidationIssue(
                code="QUERY_USES_IDENTIFIER_INJECTION",
                severity=Severity.INFO,
                entity_type=EntityType.QUERY,
                entity_id=query_name,
                message=(
                    f"Query '{query_name}' uses identifier injection "
                    f"(<<...>> placeholders). Ensure Identifiers model is "
                    f"declared and all slots are filled at construction time."
                ),
            )
        ]
    return []


def validate_cypher_spec(
    *,
    cypher: str,
    params_fields: set[str],
    query_name: str,
    identifier_fields: set[str] | None = None,
    graph_definition: GraphDefinition | None = None,
    output_model: type[BaseModel] | None = None,
) -> ValidationResult:
    """Validate a Cypher query spec from primitives (no class or instance required).

    Shared validation core used by both the simple path (``CypherQuery``) and the
    typed path (``validate_query_catalogue``).  Composes only existing helpers:

    * Syntactic parse via ``parse_cypher`` → ``QUERY_PARSE_ERROR`` on failure.
    * ``$param`` ↔ ``params_fields`` and ``<<id>>`` ↔ ``identifier_fields``
      alignment → ``QUERY_PARAM_ALIGNMENT_ERROR`` on mismatch.
    * Semantic / domain check via ``validate_cypher`` when
      ``graph_definition is not None``.
    * RETURN→Output alignment via ``extract_return_columns`` +
      ``_check_return_output_alignment`` when ``output_model is not None``.
    * Identifier-injection INFO via ``_check_identifier_injection``.
    """
    result = ValidationResult()

    # --- 1. Syntactic parse ---
    try:
        parse_cypher(cypher)
    except Exception as exc:
        result.add(
            ValidationIssue(
                code="QUERY_PARSE_ERROR",
                severity=Severity.ERROR,
                entity_type=EntityType.QUERY,
                entity_id=query_name,
                message=f"Query '{query_name}' could not be parsed: {exc}",
            )
        )
        return result

    # --- 2. $param alignment ---
    used_params = extract_cypher_params(cypher)
    for problem in _check_model_alignment(
        declared=params_fields,
        used=used_params,
        fmt_placeholder=lambda n: f"${n}",
        template_label="parameter(s)",
        model_name=query_name,
    ):
        result.add(
            ValidationIssue(
                code="QUERY_PARAM_ALIGNMENT_ERROR",
                severity=Severity.ERROR,
                entity_type=EntityType.QUERY,
                entity_id=query_name,
                message=f"Query '{query_name}': {problem}",
            )
        )

    # --- 3. <<id>> alignment ---
    used_ids = extract_cypher_identifiers(cypher)
    for problem in _check_model_alignment(
        declared=identifier_fields or set(),
        used=used_ids,
        fmt_placeholder=lambda n: f"<<{n}>>",
        template_label="identifier placeholder(s)",
        model_name=query_name,
    ):
        result.add(
            ValidationIssue(
                code="QUERY_PARAM_ALIGNMENT_ERROR",
                severity=Severity.ERROR,
                entity_type=EntityType.QUERY,
                entity_id=query_name,
                message=f"Query '{query_name}': {problem}",
            )
        )

    # --- 4. Identifier-injection INFO ---
    for issue in _check_identifier_injection(cypher, query_name):
        result.add(issue)

    # --- 5. Semantic / domain check ---
    if graph_definition is not None:
        result.merge(validate_cypher(cypher, graph_definition))

    # --- 6. RETURN→Output alignment ---
    if output_model is not None:
        return_cols = extract_return_columns(cypher)
        if return_cols is not None:
            for issue in _check_return_output_alignment(
                return_cols, output_model, query_name
            ):
                result.add(issue)

    return result


def _validate_simple_cypher_query(
    query: CypherQuery,
    definition: GraphDefinition | None,
) -> ValidationResult:
    """Run the shared spec validation for a simple :class:`CypherQuery`.

    Extracts the ``$param`` and ``<<identifier>>`` field names declared on the
    query and delegates to :func:`validate_cypher_spec` with no ``Output`` model
    (simple queries declare no result shape).  This is the single source of the
    simple-query validation idiom used by both :func:`validate_cypher_query` and the
    ``CypherQuery`` branch of :func:`validate_query_catalogue`.
    """
    params_fields: set[str] = set(query.params_schema.model_fields)
    identifier_fields: set[str] = set(
        (query.identifiers_schema or NoIdentifiers).model_fields
    )
    return validate_cypher_spec(
        cypher=query.cypher_template,
        params_fields=params_fields,
        query_name=query.query_id,
        identifier_fields=identifier_fields,
        graph_definition=definition,
        output_model=None,
    )


def validate_cypher_query(
    query: CypherQuery,
    definition: GraphDefinition | None,
) -> ValidationResult:
    """Validate a :class:`~orthograph.cypher.query.CypherQuery` against *definition*.

    Runs the same syntactic + semantic checks as the typed path via the shared
    :func:`validate_cypher_spec` core:

    * ``$param`` ↔ declared arg alignment → ``QUERY_PARAM_ALIGNMENT_ERROR``
    * Cypher dialect parse (syntax) → ``QUERY_PARSE_ERROR``
    * Unknown node labels   → ``QUERY_UNKNOWN_NODE_LABEL`` (ERROR)
    * Unknown rel types     → ``QUERY_UNKNOWN_REL_TYPE`` (ERROR)
    * Unknown properties    → ``QUERY_UNKNOWN_PROPERTY`` (ERROR)
    * Invalid endpoints     → ``QUERY_INVALID_ENDPOINT`` (ERROR)

    Parameters
    ----------
    query:
        The :class:`~orthograph.cypher.query.CypherQuery` to validate.
    definition:
        A :class:`~orthograph.graph_definition.graph_definition.GraphDefinition`
        to validate the query against.  Pass ``None`` to perform a syntactic-only
        check (param alignment + parse); domain validation is skipped.
    """
    return _validate_simple_cypher_query(query, definition)


def validate_typed_cypher_query(
    query: ReadQuery[Any, Any] | WriteQuery[Any, Any],
    graph_definition: GraphDefinition,
) -> ValidationResult:
    """Validate a typed (ReadQuery / WriteQuery) Cypher query against *graph_definition*.

    Guards (all specific to the typed path — CypherQuery never reaches this):

    * Non-Cypher backend → ``QUERY_UNVERIFIABLE`` (INFO).
    * Imperative query (no ``cypher_template``) → ``QUERY_UNVERIFIABLE`` (INFO).
    * Identifier injection → injection INFO + ``QUERY_UNVERIFIABLE`` (static
      validation is incomplete without runtime identifier values; INFO fires
      here rather than inside :func:`validate_cypher_spec` so we bail before
      the deeper checks).

    Otherwise extracts Params / Identifiers / Output from the query class and
    delegates to :func:`validate_cypher_spec`.
    """  # NOQA E501
    if query.backend != Backend.CYPHER:
        result = ValidationResult()
        result.add(
            _unverifiable(
                query.name,
                reason=f"backend is {query.backend.value}; this validator only "
                "checks Cypher queries",
            )
        )
        return result

    template = getattr(type(query), "cypher_template", None)
    if template is None:
        result = ValidationResult()
        result.add(
            _unverifiable(
                query.name,
                "query is imperative (no 'cypher_template'); its Cypher is "
                "only known at build() time",
            )
        )
        return result

    # T10: emit injection INFO then bail — extract once, no second call inside
    # validate_cypher_spec (we return before reaching it).
    if injection_issues := _check_identifier_injection(template, query.name):
        result = ValidationResult()
        for issue in injection_issues:
            result.add(issue)
        result.add(
            _unverifiable(
                query.name,
                "query uses identifier injection (<<...>> placeholders); "
                "Cypher template validation is incomplete without runtime "
                "identifier values",
            )
        )
        return result

    params_cls = getattr(type(query), "Params", None)
    params_fields: set[str] = (
        set(params_cls.model_fields)
        if isinstance(params_cls, type) and issubclass(params_cls, BaseModel)
        else set()
    )
    identifiers_cls = getattr(type(query), "Identifiers", None)
    identifier_fields: set[str] = (
        set(identifiers_cls.model_fields)
        if isinstance(identifiers_cls, type) and issubclass(identifiers_cls, BaseModel)
        else set()
    )
    output_cls: type[BaseModel] | None = (
        getattr(type(query), "Output", None) if isinstance(query, ReadQuery) else None
    )
    return validate_cypher_spec(
        cypher=template,
        params_fields=params_fields,
        query_name=query.name,
        identifier_fields=identifier_fields,
        graph_definition=graph_definition,
        output_model=output_cls,
    )


def validate_query_catalogue(
    query_catalogue: QueryCatalogue,
    graph_definition: GraphDefinition,
) -> ValidationResult:
    """Validate every query in a query_catalogue against a GraphDefinition (no DB).

    Returns a single merged ``ValidationResult``. Declarative Cypher queries are
    checked against the graph_definition; imperative or non-Cypher queries are
    reported as ``QUERY_UNVERIFIABLE`` (INFO) with the reason.

    For :class:`~orthograph.query.base_models.ReadQuery` instances that declare
    both a ``cypher_template`` and an ``Output`` model, the RETURN→Output
    alignment is checked.  Required scalar fields missing from the RETURN clause
    produce an ERROR ``QUERY_RETURN_OUTPUT_MISMATCH``; whole-node returns against
    a matching NodeModel Output produce no noise.  The check is skipped for
    ``RETURN *``, queries with aggregation functions, and all
    :class:`~orthograph.query.base_models.WriteQuery` instances (writes expose
    only mutation counters, not projected rows).

    For any declarative Cypher query with ``<<name>>`` identifier injection
    placeholders, a ``QUERY_USES_IDENTIFIER_INJECTION`` INFO issue is emitted.
    """
    result = ValidationResult()
    for query in query_catalogue.queries():
        if isinstance(query, CypherQuery):
            result.merge(_validate_simple_cypher_query(query, graph_definition))
        else:
            result.merge(validate_typed_cypher_query(query, graph_definition))
    return result


def validate_query_catalogue_against_profile(
    query_catalogue: QueryCatalogue,
    profile: GraphProfile,
    graph_definition: GraphDefinition,
    rules: Sequence[Rule] | None = None,
) -> ValidationResult:
    """Validate a query catalogue and a database profile against ``graph_definition``.

    Merges two passes: static catalogue validation and profile-vs-model
    comparison.  ``rules`` overrides the default comparison rule set.
    Never opens a database connection.
    """
    result = validate_query_catalogue(query_catalogue, graph_definition)
    result.merge(compare_profile_to_definition(profile, graph_definition, rules=rules))
    return result
