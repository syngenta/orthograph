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
    extract_cypher_identifiers,
)
from orthograph.cypher.parser import (
    ReturnColumn,
    ReturnKind,
    extract_return_columns,
    validate_cypher,
)
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

        result.merge(validate_cypher(template, graph_definition))

        # RETURN → Output column alignment check — read queries only.
        # WriteQuery also carries an optional Output ClassVar, but writes expose
        # only mutation counters (not rows), so the alignment check does not
        # apply to them.
        if isinstance(query, ReadQuery):
            output_cls: type[BaseModel] | None = getattr(type(query), "Output", None)
            if output_cls is not None:
                return_cols = extract_return_columns(template)
                if return_cols is not None:
                    for issue in _check_return_output_alignment(
                        return_cols, output_cls, query.name
                    ):
                        result.add(issue)

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
