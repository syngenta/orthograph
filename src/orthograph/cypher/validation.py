"""Static validation of a :class:`QueryCatalogue` against a :class:`GraphDefinition`.

Declarative Cypher queries (``cypher_template`` set) are validated against the
model.  Imperative or non-Cypher queries are reported as ``QUERY_UNVERIFIABLE``
(INFO) with the reason — never silently skipped or counted as passing.
"""

from collections.abc import Sequence

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
from orthograph.query.base_models import Backend, ReadQuery
from orthograph.query.catalogue import QueryCatalogue


# Dummy identifier used when validating templates with <<name>> placeholders.
# This matches the placeholder used in base_models.py at definition time.
_PARSE_PLACEHOLDER = "__IDENT__"


def _unverifiable(name: str, reason: str) -> ValidationIssue:
    return ValidationIssue(
        code="QUERY_UNVERIFIABLE",
        severity=Severity.INFO,
        entity_type=EntityType.QUERY,
        entity_id=name,
        message=f"Query '{name}' could not be statically validated: {reason}",
    )


def _check_return_output_alignment(
    return_cols: list[ReturnColumn],
    output_model: type[BaseModel],
    query_name: str,
) -> list[ValidationIssue]:
    """Tiered RETURN→Output alignment check.

    Branches on both the *Output* kind and the classified RETURN columns:

    * **Output is a NodeModel** and there is exactly one matching
      ``WHOLE_NODE`` column of the same label → **valid, no issue**.
      If the label does not match → **ERROR** ``QUERY_RETURN_OUTPUT_LABEL_MISMATCH``.
    * **Output is a RelationshipModel** and there is exactly one matching
      ``WHOLE_REL`` column of the same label → **valid, no issue**.
      If the label does not match → **ERROR** ``QUERY_RETURN_OUTPUT_LABEL_MISMATCH``.
    * **Output is a flat BaseModel** (not a Node/Rel model) and RETURN is scalar
      columns → each **required** field missing from the scalar projections is an
      **ERROR** ``QUERY_RETURN_OUTPUT_MISMATCH``; optional fields missing are INFO.
    * **Output is a projection BaseModel** (fields are themselves Node/Rel models)
      and RETURN has whole-node/whole-rel columns → no mismatch noise (the
      variable-name↔field-name gap is the legitimate ``materialize`` seam).

    Extra RETURN columns not in ``Output`` are never reported (unchanged policy).

    Returns an empty list when the alignment is considered valid.
    """
    issues: list[ValidationIssue] = []

    # --- Branch 1 & 2: Output is a NodeModel or RelationshipModel ---
    is_node_model = issubclass(output_model, NodeModel)
    is_rel_model = (not is_node_model) and issubclass(output_model, RelationshipModel)

    if is_node_model or is_rel_model:
        expected_kind = ReturnKind.WHOLE_NODE if is_node_model else ReturnKind.WHOLE_REL
        expected_label: str | None = getattr(output_model, "__label__", None)

        # Find all whole-node / whole-rel columns.
        whole_cols = [c for c in return_cols if c.kind == expected_kind]

        if len(whole_cols) == 1:
            col = whole_cols[0]
            if expected_label and col.label and col.label != expected_label:
                # Wrong label: mismatch.
                issues.append(
                    ValidationIssue(
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
                )
        elif len(whole_cols) == 0 and return_cols:
            # There are columns but none are whole-node/whole-rel for a
            # NodeModel/RelationshipModel Output — could be a scalar-only return
            # against a NodeModel.  Emit a single ERROR so the developer gets
            # actionable feedback rather than silence.
            issues.append(
                ValidationIssue(
                    code="QUERY_RETURN_OUTPUT_MISMATCH",
                    severity=Severity.ERROR,
                    entity_type=EntityType.QUERY,
                    entity_id=query_name,
                    message=(
                        f"Query '{query_name}': Output is a "
                        f"{'NodeModel' if is_node_model else 'RelationshipModel'} "
                        f"('{expected_label}') but RETURN contains no matching "
                        f"whole-{'node' if is_node_model else 'relationship'} column"
                    ),
                )
            )
        # len(whole_cols) > 1 or len(whole_cols) == 1 with matching label → valid.
        return issues

    # --- Branch 3 & 4: flat BaseModel ---
    # First determine whether this looks like a projection Output (fields are
    # themselves Node/Rel models).  If so, the variable-name↔field-name gap is
    # expected → no noise.
    field_types = [
        f.annotation
        for f in output_model.model_fields.values()
        if f.annotation is not None
    ]
    is_projection_output = bool(field_types) and all(
        isinstance(ft, type) and issubclass(ft, (NodeModel, RelationshipModel))
        for ft in field_types
    )

    if is_projection_output:
        # Branch 4: projection of whole-node/whole-rel columns → no noise.
        return issues

    # Branch 3: scalar flat BaseModel — check required fields against scalar
    # column names.
    scalar_col_names = {c.name for c in return_cols if c.kind == ReturnKind.SCALAR}
    for field_name, field_info in sorted(output_model.model_fields.items()):
        if field_name not in scalar_col_names:
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


def validate_query(
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
        # --- Simple CypherQuery branch (YAML / direct-instantiation path) ---
        # Resolved first so the remainder of the loop is narrowed to
        # ReadQuery | WriteQuery, where .name is guaranteed to exist.
        if isinstance(query, CypherQuery):
            params_fields: set[str] = set(query.params_schema.model_fields)
            identifier_fields_simple: set[str] = set(
                (query.identifiers_schema or NoIdentifiers).model_fields
            )
            result.merge(
                validate_cypher_spec(
                    cypher=query.cypher_template,
                    params_fields=params_fields,
                    query_name=query.query_id,
                    identifier_fields=identifier_fields_simple,
                    graph_definition=graph_definition,
                    output_model=None,
                )
            )
            continue

        if query.backend != Backend.CYPHER:
            result.add(
                _unverifiable(
                    query.name,
                    f"backend is {query.backend.value}; this validator only "
                    "checks Cypher queries",
                )
            )
            continue

        template = getattr(type(query), "cypher_template", None)
        if template is None:
            result.add(
                _unverifiable(
                    query.name,
                    "query is imperative (no 'cypher_template'); its Cypher is "
                    "only known at build() time",
                )
            )
            continue

        # T10: Check for identifier injection BEFORE validating Cypher.
        # Queries with identifier injection are reported as QUERY_UNVERIFIABLE
        # (INFO) because the identifiers will be substituted at runtime,
        # making static validation incomplete.
        has_identifier_injection = bool(extract_cypher_identifiers(template))
        for issue in _check_identifier_injection(template, query.name):
            result.add(issue)

        if has_identifier_injection:
            result.add(
                _unverifiable(
                    query.name,
                    "query uses identifier injection (<<...>> placeholders); "
                    "Cypher template validation is incomplete without runtime "
                    "identifier values",
                )
            )
            continue

        params_cls = getattr(type(query), "Params", None)
        params_fields_typed: set[str] = (
            set(params_cls.model_fields)
            if isinstance(params_cls, type) and issubclass(params_cls, BaseModel)
            else set()
        )
        identifiers_cls = getattr(type(query), "Identifiers", None)
        identifier_fields: set[str] = (
            set(identifiers_cls.model_fields)
            if isinstance(identifiers_cls, type)
            and issubclass(identifiers_cls, BaseModel)
            else set()
        )
        output_cls: type[BaseModel] | None = (
            getattr(type(query), "Output", None)
            if isinstance(query, ReadQuery)
            else None
        )
        result.merge(
            validate_cypher_spec(
                cypher=template,
                params_fields=params_fields_typed,
                query_name=query.name,
                identifier_fields=identifier_fields,
                graph_definition=graph_definition,
                output_model=output_cls,
            )
        )

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
