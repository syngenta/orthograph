"""Public model API — in-memory operations on a :class:`GraphDefinition`.

Load a model from YAML, save it, validate in-memory graph data against it,
and validate Cypher queries or a query catalogue against it.
No database connection is required.

Model classes (``NodeModel``, ``RelationshipModel``, ``GraphDefinition``) are
not re-exported here; import them from ``orthograph.graph_definition``.
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import orthograph.cypher.validation as _cypher_validation
from orthograph.comparison.rules import Rule
from orthograph.cypher.parser import validate_cypher
from orthograph.diagnostics.result import ValidationResult
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.models import NodeModel, RelationshipModel
from orthograph.graph_definition.validation import GraphValidator
from orthograph.graph_profile.models import GraphProfile
from orthograph.io.yaml import load_yaml_file, load_yaml_string, save_yaml_file
from orthograph.query.catalogue import QueryCatalogue


def load(source: str | Path) -> GraphDefinition:
    """Load a :class:`GraphDefinition` from YAML.

    A :class:`pathlib.Path` is read as a file; a :class:`str` is parsed as
    YAML content.  To load from a file path held in a string: ``load(Path(p))``.
    """
    if isinstance(source, Path):
        return load_yaml_file(path=source)
    return load_yaml_string(content=source)


def save(graph_definition: GraphDefinition, path: str | Path) -> None:
    """Save ``graph_definition`` to a YAML file at ``path``."""
    save_yaml_file(graph_definition=graph_definition, path=Path(path))


def validate(
    graph_definition: GraphDefinition,
    nodes: Sequence[dict[str, Any] | NodeModel],
    relationships: Sequence[dict[str, Any] | RelationshipModel] | None = None,
) -> ValidationResult:
    """Validate in-memory graph data against ``graph_definition``.

    Check ``.is_valid`` or iterate ``.issues`` on the returned
    :class:`~orthograph.diagnostics.result.ValidationResult`.
    """
    return GraphValidator(graph_definition).validate(
        nodes=nodes, relationships=relationships
    )


def validate_query(query: str, graph_definition: GraphDefinition) -> ValidationResult:
    """Validate a single Cypher query string against ``graph_definition``
    (static, no DB).

    Checks every label, relationship type, property access, and endpoint
    against the declared schema.  Unknown names surface as
    ``QUERY_UNKNOWN_NODE_LABEL``, ``QUERY_UNKNOWN_REL_TYPE``,
    ``QUERY_UNKNOWN_PROPERTY``, or ``QUERY_INVALID_ENDPOINT`` errors.
    """
    return validate_cypher(query=query, graph_definition=graph_definition)


def validate_query_catalogue(
    query_catalogue: QueryCatalogue,
    graph_definition: GraphDefinition,
) -> ValidationResult:
    """Validate every query in ``query_catalogue`` against ``graph_definition``
    (static, no DB).

    Queries without a ``cypher_template`` cannot be statically inspected and
    are reported as ``QUERY_UNVERIFIABLE`` (INFO), never silently skipped.
    Returns a single merged :class:`~orthograph.diagnostics.result.ValidationResult`.
    """
    return _cypher_validation.validate_query_catalogue(
        query_catalogue=query_catalogue, graph_definition=graph_definition
    )


def validate_query_catalogue_against_profile(
    query_catalogue: QueryCatalogue,
    profile: GraphProfile,
    graph_definition: GraphDefinition,
    rules: Sequence[Rule] | None = None,
) -> ValidationResult:
    """Validate a query catalogue and a live database profile against
    ``graph_definition``.

    Runs two passes and merges results: static catalogue validation and
    profile-vs-model comparison.  ``profile`` must be obtained separately via
    :func:`orthograph.api.database.inspect`; this function never opens a
    connection.

    ``rules`` overrides the default rule set for the profile comparison pass.
    """
    return _cypher_validation.validate_query_catalogue_against_profile(
        query_catalogue=query_catalogue,
        profile=profile,
        graph_definition=graph_definition,
        rules=rules,
    )
