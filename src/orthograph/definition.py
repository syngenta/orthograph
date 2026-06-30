"""Author, persist, and validate a graph definition.

The declared side of Orthograph: build a :class:`GraphDefinition` from the
authoring primitives, load/save it as YAML, and run the two distinct
validations:

* :func:`validate_definition` — internal **structural** consistency of the
  contract itself (duplicate/undefined/isolated types, cardinality rules).
* :func:`validate_data` — in-memory graph **records** against that contract.

These two never overlap: ``validate_definition`` asks "is this contract
coherent?"; ``validate_data`` asks "do these nodes/relationships obey it?".

The authoring primitives (``NodeModel``, ``RelationshipModel``,
``GraphDefinition``, the cardinality models) are re-exported here so consumers
need not reach into ``orthograph.graph_definition.*``.

Examples
--------
Build a contract from Python classes and round-trip it through YAML:

>>> from orthograph.definition import (
...     GraphDefinition, NodeModel, RelationshipModel,
...     validate_definition, validate_data, load_yaml_string,
... )
>>> class Person(NodeModel):
...     __label__ = "Person"
...     __uid_field__ = "name"
...     name: str
>>> class Movie(NodeModel):
...     __label__ = "Movie"
...     __uid_field__ = "title"
...     title: str
...     year: int
>>> class ActedIn(RelationshipModel):
...     __label__ = "ACTED_IN"
...     __source_label__ = "Person"
...     __target_label__ = "Movie"
...     role: str
>>> definition = GraphDefinition(
...     name="Filmography",
...     node_types=[Person, Movie],
...     relationship_types=[ActedIn],
... )
>>> validate_definition(definition).is_valid
True

Load the same contract from YAML:

>>> yaml_src = '''
... name: Filmography
... node_types:
...   Person:
...     uid_field: name
...     properties:
...       name:
...         type: str
...         required: true
...   Movie:
...     uid_field: title
...     properties:
...       title:
...         type: str
...         required: true
...       year:
...         type: int
...         required: true
... relationship_types:
...   - label: ACTED_IN
...     source: Person
...     target: Movie
...     properties:
...       role:
...         type: str
...         required: true
... '''
>>> loaded = load_yaml_string(yaml_src)
>>> loaded.name
'Filmography'
>>> [n.__label__ for n in loaded.node_types]
['Person', 'Movie']
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from orthograph.diagnostics.result import GraphValidationError, ValidationResult
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.models import (
    CardinalitySpec,
    ConditionalCardinality,
    ConditionalRule,
    NodeModel,
    PropMatch,
    RelationshipModel,
)
from orthograph.graph_definition.validation import GraphValidator
from orthograph.io.formats import DefinitionFormat
from orthograph.io.yaml import load_yaml_file, load_yaml_string, save_yaml_file


def load_from_file(
    path: str | Path,
    format: DefinitionFormat = DefinitionFormat.YAML,
) -> GraphDefinition:
    """Load a :class:`GraphDefinition` from a file.

    Operand: a serialized definition file. ``format`` selects the on-disk
    encoding (only :attr:`DefinitionFormat.YAML` today; JSON planned).

    Raises
    ------
    FileNotFoundError
        When ``path`` does not exist.
    """
    if format is DefinitionFormat.YAML:
        return load_yaml_file(path=Path(path))
    else:
        raise ValueError(f"Unsupported definition format: {format}")


def save_to_file(
    definition: GraphDefinition,
    path: str | Path,
    format: DefinitionFormat = DefinitionFormat.YAML,
) -> None:
    """Save ``definition`` to a file.

    Operand: a :class:`GraphDefinition`. ``format`` selects the on-disk
    encoding (only :attr:`DefinitionFormat.YAML` today; JSON planned).
    """
    if format is DefinitionFormat.YAML:
        save_yaml_file(graph_definition=definition, path=Path(path))
        return
    raise ValueError(f"Unsupported definition format: {format}")


def validate_definition(definition: GraphDefinition) -> ValidationResult:
    """Validate the **structural consistency** of ``definition`` itself.

    Operand: the definition (the contract). Checks duplicate keys, undefined
    node references, isolated nodes, and cardinality rules — no data required.
    Check ``.is_valid`` or iterate ``.issues`` on the returned
    :class:`~orthograph.diagnostics.result.ValidationResult`.

    Examples
    --------
    A well-formed definition (connected graph) is structurally valid:

    >>> from orthograph.definition import (
    ...     GraphDefinition, NodeModel, RelationshipModel, validate_definition,
    ... )
    >>> class Person(NodeModel):
    ...     __label__ = "Person"
    ...     __uid_field__ = "name"
    ...     name: str
    >>> class Movie(NodeModel):
    ...     __label__ = "Movie"
    ...     __uid_field__ = "title"
    ...     title: str
    >>> class ActedIn(RelationshipModel):
    ...     __label__ = "ACTED_IN"
    ...     __source_label__ = "Person"
    ...     __target_label__ = "Movie"
    >>> definition = GraphDefinition(
    ...     name="Filmography",
    ...     node_types=[Person, Movie],
    ...     relationship_types=[ActedIn],
    ... )
    >>> validate_definition(definition).is_valid
    True

    An isolated node (no relationship connects it) generates a warning but
    does not make the definition structurally invalid:

    >>> alone = GraphDefinition(
    ...     name="Isolated",
    ...     node_types=[Person],
    ...     relationship_types=[],
    ... )
    >>> result = validate_definition(alone)
    >>> result.is_valid
    True
    >>> result.issues[0].code
    'ISOLATED_NODE'
    """
    return definition.validate_structure()


def validate_data(
    definition: GraphDefinition,
    nodes: Sequence[dict[str, Any] | NodeModel],
    relationships: Sequence[dict[str, Any] | RelationshipModel] | None = None,
) -> ValidationResult:
    """Validate in-memory graph **records** against ``definition``.

    Operand: the ``nodes``/``relationships`` data. Checks labels, properties,
    referential integrity, and cardinality of the supplied records against the
    contract. Check ``.is_valid`` or iterate ``.issues`` on the returned
    :class:`~orthograph.diagnostics.result.ValidationResult`.

    Examples
    --------
    Define a two-node, one-relationship graph and validate a matching record set:

    >>> from typing import Optional
    >>> from orthograph.definition import (
    ...     GraphDefinition, NodeModel, RelationshipModel, validate_data,
    ... )
    >>> class Person(NodeModel):
    ...     __label__ = "Person"
    ...     __uid_field__ = "name"
    ...     name: str
    ...     born: Optional[int] = None
    >>> class Movie(NodeModel):
    ...     __label__ = "Movie"
    ...     __uid_field__ = "title"
    ...     title: str
    ...     year: int
    >>> class ActedIn(RelationshipModel):
    ...     __label__ = "ACTED_IN"
    ...     __source_label__ = "Person"
    ...     __target_label__ = "Movie"
    ...     role: str
    >>> definition = GraphDefinition(
    ...     name="Filmography",
    ...     node_types=[Person, Movie],
    ...     relationship_types=[ActedIn],
    ... )
    >>> nodes = [
    ...     {"__label__": "Person", "name": "Alice", "born": 1985},
    ...     {"__label__": "Movie",  "title": "Inception", "year": 2010},
    ... ]
    >>> relationships = [
    ...     {"__label__": "ACTED_IN", "__source_uid__": "Alice",
    ...      "__target_uid__": "Inception", "role": "Lead"},
    ... ]
    >>> result = validate_data(definition, nodes, relationships)
    >>> result.is_valid
    True

    A node missing a required field fails validation:

    >>> bad = [{"__label__": "Movie", "title": "Dune"}]  # missing 'year'
    >>> result2 = validate_data(definition, bad)
    >>> result2.is_valid
    False
    >>> result2.issues[0].code
    'PROPERTY_VALIDATION_ERROR'

    A node with an unknown label is also rejected:

    >>> unknown = [{"__label__": "Director", "name": "Nolan"}]
    >>> validate_data(definition, unknown).is_valid
    False
    """
    return GraphValidator(definition).validate(nodes=nodes, relationships=relationships)


__all__ = [
    # authoring primitives
    "NodeModel",
    "RelationshipModel",
    "GraphDefinition",
    "CardinalitySpec",
    "ConditionalCardinality",
    "ConditionalRule",
    "PropMatch",
    # I/O
    "DefinitionFormat",
    "load_from_file",
    "save_to_file",
    "load_yaml_string",
    # validation
    "validate_definition",
    "validate_data",
    # exceptions
    "GraphValidationError",
]
