"""Serialization formats for graph-definition I/O.

Single source of truth for the on-disk formats the facade can read/write.
Today only YAML is supported; JSON is planned and will be added here so the
``format`` argument of ``api.definition.load_from_file`` /
``save_to_file`` gains it without changing call sites.
"""

from enum import Enum


class DefinitionFormat(str, Enum):
    """A graph-definition serialization format.

    Members map to the canonical lowercase token (``DefinitionFormat.YAML ==
    "yaml"``). Extend here (e.g. ``JSON = "json"``) to add a format.
    """

    YAML = "yaml"


__all__ = ["DefinitionFormat"]
