"""Static validation of a QueryCatalogue against a GraphDataModel.

``validate_catalogue`` checks every registered query against a model WITHOUT a
database, reusing ``validate_cypher``. It is intentionally Cypher-specific and
lives in the cypher extension (not the backend-free catalogue package): only
declarative Cypher queries carry a statically-inspectable ``cypher_template``.

Each query yields one of:

  * **Declarative Cypher** (``cypher_template`` set) — validated via
    ``validate_cypher``; unknown labels / rel types / properties become ERRORs.
  * **Imperative Cypher** (no template; ``build()`` overridden) — reported as a
    ``QUERY_UNVERIFIABLE`` INFO issue, because the query text is only known at
    ``build()`` time and cannot be inspected statically.
  * **Non-Cypher** (a different ``backend``) — reported as a ``QUERY_UNVERIFIABLE``
    INFO issue, because this Cypher-specific function cannot check it.

Unverifiable reports are INFO (not ERROR): they do not, by themselves, make the
catalogue invalid — they tell the caller *why* a query could not be checked.
"""

from orthograph.catalogue.registry import QueryCatalogue
from orthograph.catalogue.typed import Backend
from orthograph.core.exceptions import ValidationIssue, ValidationResult
from orthograph.core.graph_data_model import GraphDataModel
from orthograph.core.types import EntityType, Severity
from orthograph.extensions.cypher.parser import validate_cypher
from orthograph.extensions.models import GraphProfile
from orthograph.extensions.validation import validate_profile


def _unverifiable(name: str, reason: str) -> ValidationIssue:
    return ValidationIssue(
        code="QUERY_UNVERIFIABLE",
        severity=Severity.INFO,
        entity_type=EntityType.QUERY,
        entity_id=name,
        message=f"Query '{name}' could not be statically validated: {reason}",
    )


def validate_catalogue(
    catalogue: QueryCatalogue,
    model: GraphDataModel,
) -> ValidationResult:
    """Validate every query in a catalogue against a GraphDataModel (no database).

    Returns a single merged ``ValidationResult``. Declarative Cypher queries are
    checked against the model; imperative or non-Cypher queries are reported as
    ``QUERY_UNVERIFIABLE`` (INFO) with the reason.
    """
    result = ValidationResult()

    for query in catalogue.queries():
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

        result.merge(validate_cypher(template, model))

    return result


def validate_catalogue_against_profile(
    catalogue: QueryCatalogue,
    profile: GraphProfile,
    model: GraphDataModel,
) -> ValidationResult:
    """Validate a catalogue's queries AND a database's shape against a model.

    Merges two existing passes into one result:

      * ``validate_catalogue(catalogue, model)`` — the queries vs the model.
      * ``validate_profile(profile, model)``     — the live DB shape vs the model.

    The ``profile`` is produced by a ``GraphInspector`` (the caller owns the
    driver and runs ``inspect()``), so this function never touches a connection.
    """
    result = validate_catalogue(catalogue, model)
    result.merge(validate_profile(profile, model))
    return result
