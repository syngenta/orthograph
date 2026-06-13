"""Orthograph -- Pydantic-native graph data model definition and validation.

Like Pandera for DataFrames, but for graph data structures.
"""

import importlib.metadata


try:
    __version__ = importlib.metadata.version(__package__ or __name__)
except importlib.metadata.PackageNotFoundError:
    __version__ = "unknown version"
