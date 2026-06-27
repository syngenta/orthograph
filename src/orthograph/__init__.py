"""Orthograph — Pydantic-native graph contract and governance layer for Python.

Seven capability modules are importable directly from this package:

* :mod:`orthograph.definition`  — author/load/save/validate the declared contract
* :mod:`orthograph.profile`     — inspect a backend into a :class:`~orthograph.graph_profile.models.GraphProfile`
* :mod:`orthograph.compare`     — three comparisons (profile↔definition, profile↔profile, definition↔definition)
* :mod:`orthograph.queries`     — author/catalogue/validate/generate Cypher queries
* :mod:`orthograph.execution`   — run typed read/write queries against a backend
* :mod:`orthograph.discovery`   — discover available backends and their capabilities
* :mod:`orthograph.rendering`   — render definitions, profiles, and results as text or diagrams

Two supported import styles::

    # 1. attribute access on the root (preferred for notebooks / interactive work)
    import orthograph
    orthograph.definition.NodeModel
    orthograph.profile.inspect_neo4j(driver)

    # 2. direct import from the capability module (preferred in library code)
    from orthograph.definition import NodeModel, GraphDefinition
    from orthograph.profile import inspect_neo4j
    from orthograph.compare import profile_to_definition

Example::

    import orthograph

    class Person(orthograph.definition.NodeModel):
        __label__ = "Person"
        name: str

    definition = orthograph.definition.GraphDefinition(
        name="Social", node_types=[Person], relationship_types=[]
    )
    profile = orthograph.profile.inspect_neo4j(driver)
    result  = orthograph.compare.profile_to_definition(profile, definition)
    print(orthograph.rendering.render_result(result))
    print(orthograph.discovery.available())
"""  # NOQA E501

import importlib.metadata

from orthograph import (  # noqa: F401  (re-exported as public surface)
    compare,
    definition,
    discovery,
    execution,
    profile,
    queries,
    rendering,
)


__all__ = [
    "definition",
    "profile",
    "compare",
    "queries",
    "execution",
    "discovery",
    "rendering",
]


try:
    __version__ = importlib.metadata.version(__package__ or __name__)
except importlib.metadata.PackageNotFoundError:
    __version__ = "unknown version"
