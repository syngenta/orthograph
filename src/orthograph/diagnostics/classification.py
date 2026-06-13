"""Classification enumerations for orthograph diagnostics."""

from enum import Enum


class EntityType(Enum):
    """Discriminator for graph entities."""

    NODE = "node"
    RELATIONSHIP = "relationship"
    QUERY = "query"


class Severity(Enum):
    """Severity level for validation issues."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
