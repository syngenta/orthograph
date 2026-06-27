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
