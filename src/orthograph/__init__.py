"""Orthograph -- Pydantic-native graph data model definition and validation.

Like Pandera for DataFrames, but for graph data structures.
"""

import importlib.metadata

from orthograph.core.exceptions import (
    GraphValidationError,
    MissingClassVarError,
    MissingUidFieldError,
    ModelDefinitionError,
    ValidationIssue,
    ValidationResult,
)
from orthograph.core.graph_data_model import GraphDataModel
from orthograph.core.node_model import NodeModel
from orthograph.core.relationship_model import RelationshipModel
from orthograph.core.types import (
    Cardinality,
    CardinalitySpec,
    EntityType,
    Severity,
    TypeInfo,
)
from orthograph.core.validator import GraphValidator


try:
    __version__ = importlib.metadata.version(__package__ or __name__)
except importlib.metadata.PackageNotFoundError:
    __version__ = "unknown version"

__all__ = [
    # Core models
    "NodeModel",
    "RelationshipModel",
    "GraphDataModel",
    "GraphValidator",
    # Types
    "Cardinality",
    "CardinalitySpec",
    "EntityType",
    "Severity",
    "TypeInfo",
    # Errors
    "ValidationResult",
    "ValidationIssue",
    "GraphValidationError",
    "ModelDefinitionError",
    "MissingClassVarError",
    "MissingUidFieldError",
    # Version
    "__version__",
]
