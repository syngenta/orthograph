"""NetworkX extension for orthograph."""

from orthograph.extensions.networkx.conversion import schema_to_networkx
from orthograph.extensions.networkx.inspector import NetworkxInspector


__all__ = ["NetworkxInspector", "schema_to_networkx"]
