"""Static validation of Cypher queries and query catalogues against a graph model.

Dispatch table
--------------
:func:`_extract_query_spec` accepts any query object and routes to one of two
branch extractors:

    kind                    | extractor                    | guards
    ------------------------|------------------------------|--------------------
    CypherQuery             | _extract_cypher_query_spec   | none
    ReadQueryModel /        | _extract_typed_query_spec    | non-Cypher backend,
    WriteQueryModel         |                              | imperative (no
                            |                              | template), identifier
                            |                              | injection

Each extractor returns either a 4-tuple ``(cypher, params_fields,
identifier_fields, output_model)`` ready for :func:`validate_cypher_spec`, or a
:class:`ValidationResult` already populated with ``QUERY_UNVERIFIABLE`` when a
guard fires.

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
    CypherParserStrategy,
    ReturnColumn,
    ReturnKind,
    _validate_cypher,
    extract_return_columns,
    parse_cypher,
)
from orthograph.cypher.query import CypherQuery
from orthograph.diagnostics.classification import EntityType, Severity
from orthograph.diagnostics.result import ValidationIssue, ValidationResult
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.models import NodeModel, RelationshipModel
from orthograph.graph_profile.models import GraphProfile
from orthograph.query.base_models import Backend, ReadQueryModel, WriteQueryModel
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


def _unverifiable_result(query_name: str, reason: str) -> ValidationResult:
    """Return a ValidationResult with a single QUERY_UNVERIFIABLE issue."""
    result = ValidationResult()
    result.add(_unverifiable(query_name, reason=reason))
    return result


def _inner_model_fields(query_type: type, attr: str) -> set[str]:
    """Return the field names of an inner Pydantic model, or an empty set."""
    cls = getattr(query_type, attr, None)
    if isinstance(cls, type) and issubclass(cls, BaseModel):
        return set(cls.model_fields)
    return set()


def _extract_cypher_query_spec(
    query: CypherQuery,
) -> tuple[str, set[str], set[str], type[BaseModel] | None]:
    """Extract the spec 4-tuple from a CypherQuery. No guards needed."""
    params_fields = set(query.params_schema.model_fields)
    identifier_fields = set((query.identifiers_schema or NoIdentifiers).model_fields)
    return (query.cypher_template, params_fields, identifier_fields, None)


def _extract_typed_query_spec(
    query_name: str,
    query: "ReadQueryModel[Any, Any] | WriteQueryModel[Any, Any]",
) -> "tuple[str, set[str], set[str], type[BaseModel] | None] | ValidationResult":
    """Extract the spec 4-tuple from a typed (ReadQueryModel / WriteQueryModel).

    Returns a ValidationResult sentinel when any guard fires:
      1. Non-Cypher backend.
      2. Imperative query (no cypher_template).
      3. Identifier injection (<<...>> placeholders).
    """
    if query.backend != Backend.CYPHER:
        return _unverifiable_result(
            query_name,
            f"backend is {query.backend.value}; "
            f"this validator only checks Cypher queries",
        )

    template: str | None = getattr(type(query), "cypher_template", None)
    if template is None:
        return _unverifiable_result(
            query_name,
            "query is imperative "
            "(no 'cypher_template'); its Cypher is only known at build() time",
        )

    if injection_issues := _check_identifier_injection(template, query_name):
        result = ValidationResult()
        for issue in injection_issues:
            result.add(issue)
        result.add(
            _unverifiable(
                query_name,
                "query uses identifier injection (<<...>> placeholders); "
                "Cypher template validation is incomplete "
                "without runtime identifier values",
            )
        )
        return result

    query_type = type(query)
    params_fields = _inner_model_fields(query_type, "params_schema")
    identifier_fields = _inner_model_fields(query_type, "identifiers_schema")
    output_cls: type[BaseModel] | None = (
        getattr(query_type, "Output", None)
        if isinstance(query, ReadQueryModel)
        else None
    )
    return (template, params_fields, identifier_fields, output_cls)


def _extract_query_spec(
    query_name: str,
    query: "CypherQuery | ReadQueryModel[Any, Any] | WriteQueryModel[Any, Any]",
) -> "tuple[str, set[str], set[str], type[BaseModel] | None] | ValidationResult":
    """Dispatch to the appropriate spec extractor based on query kind.

    Returns a 4-tuple ``(cypher, params_fields, identifier_fields, output_model)``
    ready for :func:`validate_cypher_spec`, or a :class:`ValidationResult` with
    ``QUERY_UNVERIFIABLE`` when a guard fires.

    Dispatch table:

        CypherQuery → :func:`_extract_cypher_query_spec` (no guards)
        ReadQueryModel / WriteQueryModel → :func:`_extract_typed_query_spec`
        (3 guards)
    """
    if isinstance(query, CypherQuery):
        return _extract_cypher_query_spec(query)
    return _extract_typed_query_spec(query_name, query)


def _cypher_spec_core(
    *,
    cypher: str,
    params_fields: set[str],
    query_name: str,
    identifier_fields: set[str] | None = None,
    graph_definition: GraphDefinition | None = None,
    output_model: type[BaseModel] | None = None,
    parser: CypherParserStrategy | None = None,
) -> ValidationResult:
    """Internal engine: run all validation stages.

    Both :func:`check_cypher_spec` and :func:`validate_cypher_spec` delegate
    here.  ``graph_definition=None`` means syntax-only (stages 1–4 + 6);
    a non-``None`` value also runs stage 5 (domain check).
    """
    result = ValidationResult()

    # --- 1. Syntactic parse ---
    try:
        parse_cypher(cypher, parser)
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
        result.merge(_validate_cypher(cypher, graph_definition, parser))

    # --- 6. RETURN→Output alignment ---
    if output_model is not None:
        return_cols = extract_return_columns(cypher)
        if return_cols is not None:
            for issue in _check_return_output_alignment(
                return_cols, output_model, query_name
            ):
                result.add(issue)

    return result


def check_cypher_spec(
    *,
    cypher: str,
    params_fields: set[str],
    query_name: str,
    identifier_fields: set[str] | None = None,
    output_model: type[BaseModel] | None = None,
    parser: CypherParserStrategy | None = None,
) -> ValidationResult:
    """Validate a Cypher query spec syntactically — no ``GraphDefinition`` required.

    Runs stages 1–4 and 6 of the shared validation pipeline (parse, param
    alignment, identifier alignment, identifier-injection INFO, RETURN→Output
    alignment).  Domain checks (unknown labels / rel-types / properties) are
    skipped because no ``GraphDefinition`` is provided.

    Use :func:`validate_cypher_spec` when you also want semantic validation
    against a graph model.
    """
    return _cypher_spec_core(
        cypher=cypher,
        params_fields=params_fields,
        query_name=query_name,
        identifier_fields=identifier_fields,
        graph_definition=None,
        output_model=output_model,
        parser=parser,
    )


def validate_cypher_spec(
    *,
    cypher: str,
    params_fields: set[str],
    query_name: str,
    identifier_fields: set[str] | None = None,
    graph_definition: GraphDefinition,
    output_model: type[BaseModel] | None = None,
    parser: CypherParserStrategy | None = None,
) -> ValidationResult:
    """Validate a Cypher query spec from primitives (no class or instance required).

    Shared validation core used by both the simple path (``CypherQuery``) and the
    typed path (``validate_query_catalogue``).  Composes only existing helpers:

    * Syntactic parse via ``parse_cypher`` → ``QUERY_PARSE_ERROR`` on failure.
    * ``$param`` ↔ ``params_fields`` and ``<<id>>`` ↔ ``identifier_fields``
      alignment → ``QUERY_PARAM_ALIGNMENT_ERROR`` on mismatch.
    * Semantic / domain check via ``validate_cypher`` (``graph_definition``
      is always passed — use :func:`check_cypher_spec` for syntax-only).
    * RETURN→Output alignment via ``extract_return_columns`` +
      ``_check_return_output_alignment`` when ``output_model is not None``.
    * Identifier-injection INFO via ``_check_identifier_injection``.

    ``graph_definition`` is **required**.  To run syntax-only checks without a
    model, use :func:`check_cypher_spec`.
    """
    return _cypher_spec_core(
        cypher=cypher,
        params_fields=params_fields,
        query_name=query_name,
        identifier_fields=identifier_fields,
        graph_definition=graph_definition,
        output_model=output_model,
        parser=parser,
    )


def _validate_simple_cypher_query(
    query: CypherQuery,
    definition: GraphDefinition | None,
) -> ValidationResult:
    """Run the shared spec validation for a simple :class:`CypherQuery`.

    Delegates to :func:`_extract_query_spec` then :func:`validate_cypher_spec`.
    Simple queries declare no result shape so ``output_model`` is always None.
    """
    spec = _extract_query_spec(query.query_id, query)
    # CypherQuery branch never returns a ValidationResult sentinel.
    assert not isinstance(spec, ValidationResult)
    cypher, params_fields, identifier_fields, output_model = spec
    if definition is None:
        return check_cypher_spec(
            cypher=cypher,
            params_fields=params_fields,
            query_name=query.query_id,
            identifier_fields=identifier_fields,
            output_model=output_model,
        )
    return validate_cypher_spec(
        cypher=cypher,
        params_fields=params_fields,
        query_name=query.query_id,
        identifier_fields=identifier_fields,
        graph_definition=definition,
        output_model=output_model,
    )


def _validate_cypher_query(
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


def _validate_typed_cypher_query(
    query: ReadQueryModel[Any, Any] | WriteQueryModel[Any, Any],
    graph_definition: GraphDefinition,
) -> ValidationResult:
    """Validate a typed (ReadQueryModel / WriteQueryModel) Cypher query against *graph_definition*.

    Guards (all specific to the typed path — CypherQuery never reaches this):

    * Non-Cypher backend → ``QUERY_UNVERIFIABLE`` (INFO).
    * Imperative query (no ``cypher_template``) → ``QUERY_UNVERIFIABLE`` (INFO).
    * Identifier injection → injection INFO + ``QUERY_UNVERIFIABLE`` (static
      validation is incomplete without runtime identifier values; INFO fires
      here rather than inside :func:`validate_cypher_spec` so we bail before
      the deeper checks).

    Otherwise delegates to :func:`_extract_query_spec` then
    :func:`validate_cypher_spec`.
    """  # NOQA E501
    spec = _extract_query_spec(query.query_id, query)
    if isinstance(spec, ValidationResult):
        return spec
    cypher, params_fields, identifier_fields, output_model = spec
    return validate_cypher_spec(
        cypher=cypher,
        params_fields=params_fields,
        query_name=query.query_id,
        identifier_fields=identifier_fields,
        graph_definition=graph_definition,
        output_model=output_model,
    )


def validate_query_catalogue(
    query_catalogue: QueryCatalogue,
    graph_definition: GraphDefinition,
) -> ValidationResult:
    """Validate every query in a query_catalogue against a GraphDefinition (no DB).

    Returns a single merged ``ValidationResult``. Declarative Cypher queries are
    checked against the graph_definition; imperative or non-Cypher queries are
    reported as ``QUERY_UNVERIFIABLE`` (INFO) with the reason.

    For :class:`~orthograph.query.base_models.ReadQueryModel` instances that declare
    both a ``cypher_template`` and an ``Output`` model, the RETURN→Output
    alignment is checked.  Required scalar fields missing from the RETURN clause
    produce an ERROR ``QUERY_RETURN_OUTPUT_MISMATCH``; whole-node returns against
    a matching NodeModel Output produce no noise.  The check is skipped for
    ``RETURN *``, queries with aggregation functions, and all
    :class:`~orthograph.query.base_models.WriteQueryModel` instances (writes expose
    only mutation counters, not projected rows).

    For any declarative Cypher query with ``<<name>>`` identifier injection
    placeholders, a ``QUERY_USES_IDENTIFIER_INJECTION`` INFO issue is emitted.
    """
    result = ValidationResult()
    for query in query_catalogue.queries():
        if isinstance(query, CypherQuery):
            result.merge(_validate_simple_cypher_query(query, graph_definition))
        else:
            result.merge(_validate_typed_cypher_query(query, graph_definition))
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
