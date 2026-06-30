"""Author, build, catalogue, validate, and generate Cypher queries.

One module for the whole Cypher query capability, so consumers never
reach into ``orthograph.query.*`` or ``orthograph.cypher.*``:

* **author** — :func:`simple_query` builds a :class:`CypherQuery`; the typed
  bases (:class:`TypedCypherReadQueryModel` / :class:`TypedCypherWriteQueryModel`)
  are re-exported for subclassing.
* **build** — :func:`new_catalogue` returns an empty :class:`QueryCatalogue`.
* **catalogue** — :func:`load_catalogue` loads YAML specs and returns an
  **assembled** :class:`QueryCatalogue` (every spec registered), not a bare list
  (the ergonomics fix over the deprecated ``model.load_query_catalogue``).
* **generate** — :func:`generate_crud` synthesises typed get/merge/create/delete
  queries for every node type that declares a UID.
* **validate** — six public verbs organised on a 2×2 matrix: phase × input grade.

  Universal rule: a ``check_*`` verb runs syntax only and never takes a
  :class:`~orthograph.graph_definition.graph_definition.GraphDefinition`.  A
  ``validate*`` verb runs syntax + semantics and always requires one.  Holds in
  both object mode (whole query) and pieces mode (raw cypher + field sets).

  +----------------+-------------------------------+-----------------------------------+
  | Phase          | Object mode                   | Pieces mode                       |
  +================+===============================+===================================+
  | Syntax only    | :func:`check_syntax`          | :func:`check_cypher_spec`         |
  +----------------+-------------------------------+-----------------------------------+
  | Syntax + sem.  | :func:`validate`              | :func:`validate_cypher_spec`      |
  +----------------+-------------------------------+-----------------------------------+

  :func:`validate_catalogue` and :func:`validate_catalogue_against_profile` are
  catalogue-level counterparts to :func:`validate`.

These delegate only — no query logic lives here.

Examples
--------
Build a catalogue from a YAML string, then validate it against a definition:

>>> from orthograph.queries import load_catalogue, validate_catalogue
>>> from orthograph.definition import GraphDefinition, NodeModel
>>> class Person(NodeModel):
...     __label__ = "Person"
...     __uid_field__ = "name"
...     name: str
>>> definition = GraphDefinition(
...     name="Social", node_types=[Person], relationship_types=[]
... )
>>> catalogue = load_catalogue('''
... - query_id: all_persons
...   cypher_template: "MATCH (p:Person) RETURN p"
... ''')
>>> catalogue.names()
['all_persons']
>>> validate_catalogue(catalogue, definition).is_valid
True
"""

from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel

import orthograph.cypher.validation as _cypher_validation
from orthograph.comparison.rules import Rule
from orthograph.cypher.base_models import (
    TypedCypherReadQueryModel,
    TypedCypherWriteQueryModel,
)
from orthograph.cypher.bindings import NoIdentifiers, NoParams, extract_cypher_params
from orthograph.cypher.exceptions import (
    CypherCatalogueLoadError,
    CypherQueryDefinitionError,
    CypherQueryError,
)
from orthograph.cypher.generator import CypherGenerator
from orthograph.cypher.parser import (
    CypherParserStrategy,
    _validate_cypher,
    parse_cypher,
)
from orthograph.cypher.query import CypherQuery
from orthograph.cypher.validation import check_cypher_spec, validate_cypher_spec
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
    "TypedCypherReadQueryModel",
    "TypedCypherWriteQueryModel",
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
    "check_syntax",
    "validate",
    "validate_catalogue",
    "validate_catalogue_against_profile",
    "check_cypher_spec",
    "validate_cypher_spec",
]


def new_catalogue() -> QueryCatalogue:
    """Return a fresh, empty :class:`QueryCatalogue`.

    Operand: nothing — a new registry. Register queries with
    ``register_read`` / ``register_write`` / ``register_cypher_query``.

    Examples
    --------
    >>> from orthograph.queries import new_catalogue
    >>> catalogue = new_catalogue()
    >>> catalogue.names()
    []
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

    Examples
    --------
    Load from a YAML string (typical for inline tests or fixtures):

    >>> from orthograph.queries import load_catalogue
    >>> catalogue = load_catalogue('''
    ... - query_id: all_persons
    ...   cypher_template: "MATCH (p:Person) RETURN p"
    ... - query_id: person_by_name
    ...   cypher_template: "MATCH (p:Person {name: $name}) RETURN p"
    ... ''')
    >>> catalogue.names()
    ['all_persons', 'person_by_name']
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
    it with :func:`check_syntax` or :func:`validate` before use.

    Examples
    --------
    Build a simple parameterised query and check its syntax:

    >>> from pydantic import BaseModel
    >>> from orthograph.queries import simple_query, check_syntax
    >>> class FindPersonParams(BaseModel):
    ...     name: str
    >>> q = simple_query(
    ...     name="find_person_by_name",
    ...     cypher_template="MATCH (p:Person {name: $name}) RETURN p",
    ...     params=FindPersonParams,
    ... )
    >>> check_syntax(q).is_valid
    True
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

    Examples
    --------
    Generate standard CRUD queries for a single node type:

    >>> from orthograph.definition import GraphDefinition, NodeModel
    >>> from orthograph.queries import generate_crud
    >>> class Person(NodeModel):
    ...     __label__ = "Person"
    ...     __uid_field__ = "name"
    ...     name: str
    >>> definition = GraphDefinition(
    ...     name="Social", node_types=[Person], relationship_types=[]
    ... )
    >>> catalogue = generate_crud(definition)
    >>> catalogue.names()
    ['match_person_by_uid', 'merge_person', 'create_person', 'delete_person_by_uid']
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


def check_syntax(
    query: str | CypherQuery,
    *,
    parser: CypherParserStrategy | None = None,
) -> ValidationResult:
    """Check a single query syntactically — no :class:`GraphDefinition` required.

    Operand: one query — a raw Cypher ``str`` or a :class:`CypherQuery`.  Runs
    parse, param alignment, identifier alignment, and RETURN→Output alignment
    (stages 1–4 + 6 of the shared pipeline).  Domain checks are skipped.

    Use :func:`validate` when you also want semantic validation against a graph
    model.

    Examples
    --------
    A well-formed Cypher string passes:

    >>> from orthograph.queries import check_syntax
    >>> check_syntax("MATCH (p:Person) RETURN p").is_valid
    True

    A ``CypherQuery`` with a declared ``params`` model is also checked:

    >>> from pydantic import BaseModel
    >>> from orthograph.queries import simple_query
    >>> class Params(BaseModel):
    ...     name: str
    >>> q = simple_query(
    ...     name="find_person",
    ...     cypher_template="MATCH (p:Person {name: $name}) RETURN p",
    ...     params=Params,
    ... )
    >>> check_syntax(q).is_valid
    True
    """
    if isinstance(query, CypherQuery):
        return _cypher_validation._validate_cypher_query(query, None)
    # Raw str: syntax-only — extract actual params so alignment trivially passes.
    return _cypher_validation.check_cypher_spec(
        cypher=query,
        params_fields=extract_cypher_params(query),
        query_name="<string>",
        parser=parser,
    )


def validate(
    query: str | CypherQuery,
    definition: GraphDefinition,
    *,
    parser: CypherParserStrategy | None = None,
) -> ValidationResult:
    """Validate a single query against ``definition`` (static, no DB).

    Operand: one query — a raw Cypher ``str`` (syntax + semantic checks) or a
    :class:`CypherQuery` (full spec validation including param alignment).
    Check ``.is_valid`` or iterate ``.issues`` on the returned
    :class:`~orthograph.diagnostics.result.ValidationResult`.

    Use :func:`check_syntax` for syntax-only checks without a model.

    Examples
    --------
    A query that references a known label and property passes:

    >>> from orthograph.definition import GraphDefinition, NodeModel
    >>> from orthograph.queries import validate
    >>> class Person(NodeModel):
    ...     __label__ = "Person"
    ...     __uid_field__ = "name"
    ...     name: str
    >>> definition = GraphDefinition(
    ...     name="Social", node_types=[Person], relationship_types=[]
    ... )
    >>> validate("MATCH (p:Person) RETURN p.name", definition).is_valid
    True

    A query that accesses an undeclared property fails with a semantic error:

    >>> result = validate("MATCH (p:Person) RETURN p.email", definition)
    >>> result.is_valid
    False
    >>> result.issues[0].code
    'QUERY_UNKNOWN_PROPERTY'
    """
    if isinstance(query, CypherQuery):
        return _cypher_validation._validate_cypher_query(query, definition)
    return _validate_cypher(query=query, graph_definition=definition, parser=parser)


def validate_catalogue(
    catalogue: QueryCatalogue,
    definition: GraphDefinition,
) -> ValidationResult:
    """Validate every query in ``catalogue`` against ``definition`` (static, no DB).

    Operand: a :class:`QueryCatalogue`. Queries without a ``cypher_template``
    cannot be statically inspected and are reported as ``QUERY_UNVERIFIABLE``
    (INFO), never silently skipped.

    Examples
    --------
    Register a query and validate the whole catalogue against a definition
    (the Quick Start governance example):

    >>> from pydantic import BaseModel
    >>> from orthograph.definition import GraphDefinition, NodeModel
    >>> from orthograph.queries import new_catalogue, simple_query, validate_catalogue
    >>> class Person(NodeModel):
    ...     __label__ = "Person"
    ...     __uid_field__ = "name"
    ...     name: str
    >>> definition = GraphDefinition(
    ...     name="Filmography",
    ...     node_types=[Person],
    ...     relationship_types=[],
    ... )
    >>> class FindPersonParams(BaseModel):
    ...     name: str
    >>> catalogue = new_catalogue()
    >>> _ = catalogue.register_cypher_query(
    ...     simple_query(
    ...         name="find_person_by_name",
    ...         cypher_template="MATCH (p:Person {name: $name}) RETURN p",
    ...         params=FindPersonParams,
    ...     )
    ... )
    >>> validate_catalogue(catalogue, definition).is_valid
    True
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
