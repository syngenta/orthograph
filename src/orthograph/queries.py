"""Author, build, catalogue, validate, and generate Cypher queries.

One module for the whole Cypher query capability, so consumers never
reach into ``orthograph.query.*`` or ``orthograph.cypher.*``:

* **author** — :func:`simple_query` builds a :class:`CypherQuery`; the typed
  bases (:class:`CypherReadQuery` / :class:`CypherWriteQuery`) are re-exported
  for subclassing.
* **build** — :func:`new_catalogue` returns an empty :class:`QueryCatalogue`.
* **catalogue** — :func:`load_catalogue` loads YAML specs and returns an
  **assembled** :class:`QueryCatalogue` (every spec registered), not a bare list
  (the ergonomics fix over the deprecated ``model.load_query_catalogue``).
* **generate** — :func:`generate_crud` synthesises typed get/merge/create/delete
  queries for every node type that declares a UID.
* **validate** — :func:`validate_query`, :func:`validate_catalogue`, and
  :func:`validate_catalogue_against_profile` are the three static checks.

These delegate only — no query logic lives here.
"""

from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel

import orthograph.cypher.validation as _cypher_validation
from orthograph.comparison.rules import Rule
from orthograph.cypher.base_models import CypherReadQuery, CypherWriteQuery
from orthograph.cypher.bindings import NoIdentifiers, NoParams
from orthograph.cypher.exceptions import (
    CypherCatalogueLoadError,
    CypherQueryDefinitionError,
    CypherQueryError,
)
from orthograph.cypher.generator import CypherGenerator
from orthograph.cypher.parser import parse_cypher, validate_cypher
from orthograph.cypher.query import CypherQuery
from orthograph.diagnostics.result import ValidationResult
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_profile.models import GraphProfile
from orthograph.io.query_catalogue_yaml import (
    load_query_catalogue_file,
    load_query_catalogue_string,
)
from orthograph.query.catalogue import QueryCatalogue


__all__ = [
    # authoring primitives
    "QueryCatalogue",
    "CypherQuery",
    "CypherReadQuery",
    "CypherWriteQuery",
    "NoParams",
    "NoIdentifiers",
    "CypherQueryError",
    "CypherCatalogueLoadError",
    "CypherQueryDefinitionError",
    "CypherGenerator",
    # build / catalogue
    "new_catalogue",
    "load_catalogue",
    # author
    "simple_query",
    # generate
    "generate_crud",
    # validate
    "parse_cypher",
    "validate_cypher",
    "validate_query",
    "validate_catalogue",
    "validate_catalogue_against_profile",
]


def new_catalogue() -> QueryCatalogue:
    """Return a fresh, empty :class:`QueryCatalogue`.

    Operand: nothing — a new registry. Register queries with
    ``register_read`` / ``register_write`` / ``register_cypher_query``.
    """
    return QueryCatalogue()


def load_catalogue(source: str | Path) -> QueryCatalogue:
    """Load YAML query specs and return an **assembled** :class:`QueryCatalogue`.

    Operand: a YAML catalogue (a :class:`pathlib.Path` is read as a file; a
    :class:`str` is parsed as YAML content). Each spec is registered into a fresh
    catalogue, so the result is ready to validate or execute — unlike the
    deprecated ``model.load_query_catalogue``, which returns a bare list.

    Raises
    ------
    FileNotFoundError
        When ``source`` is a :class:`Path` that does not exist.
    CypherCatalogueLoadError
        When the YAML is malformed, the top-level is not a list, or any entry
        is missing a required field.
    """
    if isinstance(source, Path):
        specs = load_query_catalogue_file(path=source)
    else:
        specs = load_query_catalogue_string(content=source)
    catalogue = QueryCatalogue()
    for spec in specs:
        catalogue.register_cypher_query(spec)
    return catalogue


def simple_query(
    name: str,
    cypher_template: str,
    *,
    params: type[BaseModel] = NoParams,
    identifiers: type[BaseModel] | None = None,
    description: str | None = None,
) -> CypherQuery:
    """Build a :class:`CypherQuery` from a name, template, and typed bindings.

    Operand: a Cypher string. ``params`` declares the ``$value`` parameters
    (default :class:`NoParams`); ``identifiers`` declares the ``<<name>>``
    identifier slots (default none). Returns a catalogue-citizen query — validate
    it with :func:`validate_query` before use.
    """
    return CypherQuery(
        query_id=name,
        cypher_template=cypher_template,
        description=description,
        params_schema=params,
        identifiers_schema=identifiers,
    )


def generate_crud(definition: GraphDefinition) -> QueryCatalogue:
    """Generate typed CRUD queries for every UID-bearing node type in ``definition``.

    Operand: a :class:`GraphDefinition`. For each node type that declares a
    ``__uid_field__``, four typed queries are registered: ``match_<label>_by_uid``,
    ``merge_<label>``, ``create_<label>``, ``delete_<label>_by_uid``. Node types
    without a UID are skipped (a UID is required to address a single node).
    Returns the assembled :class:`QueryCatalogue`.
    """
    generator = CypherGenerator(definition)
    catalogue = QueryCatalogue()
    for node_type in definition.node_types:
        if node_type.__uid_field__ is None:
            continue
        catalogue.register_read(generator.match_by_uid_query(node_type))
        catalogue.register_write(generator.merge_query(node_type))
        catalogue.register_write(generator.create_query(node_type))
        catalogue.register_write(generator.delete_by_uid_query(node_type))
    return catalogue


def validate_query(
    query: str | CypherQuery,
    definition: GraphDefinition,
) -> ValidationResult:
    """Validate a single query against ``definition`` (static, no DB).

    Operand: one query — a raw Cypher ``str`` (checked via ``validate_cypher``)
    or a :class:`CypherQuery` (checked via its full spec validation). Check
    ``.is_valid`` or iterate ``.issues`` on the returned
    :class:`~orthograph.diagnostics.result.ValidationResult`.
    """
    if isinstance(query, CypherQuery):
        return _cypher_validation.validate_query(query, definition)
    return validate_cypher(query=query, graph_definition=definition)


def validate_catalogue(
    catalogue: QueryCatalogue,
    definition: GraphDefinition,
) -> ValidationResult:
    """Validate every query in ``catalogue`` against ``definition`` (static, no DB).

    Operand: a :class:`QueryCatalogue`. Queries without a ``cypher_template``
    cannot be statically inspected and are reported as ``QUERY_UNVERIFIABLE``
    (INFO), never silently skipped.
    """
    return _cypher_validation.validate_query_catalogue(
        query_catalogue=catalogue, graph_definition=definition
    )


def validate_catalogue_against_profile(
    catalogue: QueryCatalogue,
    profile: GraphProfile,
    definition: GraphDefinition,
    rules: Sequence[Rule] | None = None,
) -> ValidationResult:
    """Validate a catalogue and an observed profile against ``definition``.

    Operand: a catalogue plus a :class:`GraphProfile`. Merges two passes: static
    catalogue validation and profile-vs-definition comparison. ``profile`` must
    be obtained separately via the ``orthograph.profile.inspect_*`` verbs;
    this function never opens a connection. ``rules`` overrides the default
    comparison rule set.
    """
    return _cypher_validation.validate_query_catalogue_against_profile(
        query_catalogue=catalogue,
        profile=profile,
        graph_definition=definition,
        rules=rules,
    )
