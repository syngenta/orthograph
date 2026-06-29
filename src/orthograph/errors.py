"""Public error surface for Orthograph.

Thin re-export shim (mirrors the capability-module pattern, ADR-041). The real
hierarchy lives in :mod:`orthograph.diagnostics.errors`; concrete errors live
in their owning subpackages. Catch :class:`OrthographError` to isolate every
error this library raises.
"""

from orthograph.cypher.exceptions import (
    CypherCatalogueLoadError,
    CypherError,
    CypherIdentifierError,
    CypherModelValidationError,
    CypherQueryDefinitionError,
    CypherQueryError,
    CypherSyntaxError,
    CypherUnknownLabelError,
    CypherUnknownPropertyError,
)
from orthograph.dependencies import MissingDependencyError
from orthograph.diagnostics.errors import (
    OrthographBackendError,
    OrthographError,
    OrthographUsageError,
    OrthographValidationError,
)
from orthograph.diagnostics.result import GraphValidationError
from orthograph.graph_definition.exceptions import (
    AmbiguousCardinalityError,
    CardinalityParseError,
    MissingClassVarError,
    MissingUidFieldError,
    ModelDefinitionError,
)


__all__ = [
    # root + mid-tier
    "OrthographError",
    "OrthographUsageError",
    "OrthographValidationError",
    "OrthographBackendError",
    # validation
    "GraphValidationError",
    # cypher
    "CypherError",
    "CypherQueryDefinitionError",
    "CypherSyntaxError",
    "CypherIdentifierError",
    "CypherUnknownLabelError",
    "CypherUnknownPropertyError",
    "CypherModelValidationError",
    "CypherQueryError",
    "CypherCatalogueLoadError",
    # model definition
    "ModelDefinitionError",
    "MissingClassVarError",
    "MissingUidFieldError",
    "AmbiguousCardinalityError",
    "CardinalityParseError",
    # backend / dependency
    "MissingDependencyError",
]
