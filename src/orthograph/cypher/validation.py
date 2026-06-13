"""Static validation of a :class:`QueryCatalogue` against a :class:`GraphDefinition`.

Declarative Cypher queries (``cypher_template`` set) are validated against the
model.  Imperative or non-Cypher queries are reported as ``QUERY_UNVERIFIABLE``
(INFO) with the reason — never silently skipped or counted as passing.
"""

from collections.abc import Sequence

from orthograph.comparison.engine import compare
from orthograph.comparison.rules import Rule
from orthograph.cypher.parser import validate_cypher
from orthograph.diagnostics.classification import EntityType, Severity
from orthograph.diagnostics.result import ValidationIssue, ValidationResult
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_profile.models import GraphProfile
from orthograph.query.base_models import Backend
from orthograph.query.catalogue import QueryCatalogue


def _unverifiable(name: str, reason: str) -> ValidationIssue:
    return ValidationIssue(
        code="QUERY_UNVERIFIABLE",
        severity=Severity.INFO,
        entity_type=EntityType.QUERY,
        entity_id=name,
        message=f"Query '{name}' could not be statically validated: {reason}",
    )


def validate_query_catalogue(
    query_catalogue: QueryCatalogue,
    graph_definition: GraphDefinition,
) -> ValidationResult:
    """Validate every query in a query_catalogue against a GraphDefinition (no DB).

    Returns a single merged ``ValidationResult``. Declarative Cypher queries are
    checked against the graph_definition; imperative or non-Cypher queries are
    reported as ``QUERY_UNVERIFIABLE`` (INFO) with the reason.
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

        result.merge(validate_cypher(template, graph_definition))

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
    result.merge(compare(profile, graph_definition, rules=rules))
    return result
