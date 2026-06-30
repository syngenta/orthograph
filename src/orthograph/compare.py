"""Every shipped comparison, one verb each.

Three intent-named verbs, each delegating to the comparison engine:

* :func:`profile_to_definition` — does an observed profile satisfy a declared
  definition? (US: validate live graph against the contract)
* :func:`profiles` — symmetric diff between two observed profiles (US 31,
  e.g. staging↔prod).
* :func:`definitions` — symmetric diff between two declared definitions (US 30,
  e.g. version↔version).

These delegate only — no comparison logic lives here. ``Rule`` is re-exported so
consumers can pass a custom ``rules=`` set without reaching into
``orthograph.comparison.*``.

Examples
--------
Compare two definition versions to detect a new required property:

>>> from orthograph.definition import GraphDefinition, NodeModel
>>> from orthograph.compare import definitions
>>> class V1(NodeModel):
...     __label__ = "Person"
...     __uid_field__ = "name"
...     name: str
>>> class V2(NodeModel):
...     __label__ = "Person"
...     __uid_field__ = "name"
...     name: str
...     email: str
>>> v1 = GraphDefinition(name="v1", node_types=[V1], relationship_types=[])
>>> v2 = GraphDefinition(name="v2", node_types=[V2], relationship_types=[])
>>> result = definitions(v1, v2)
>>> result.issues[0].code
'PROPERTY_ONLY_IN_RIGHT'
"""

from collections.abc import Sequence

from orthograph.comparison.engine import (
    compare_definitions,
    compare_profile_to_definition,
    compare_profiles,
)
from orthograph.comparison.rules import Rule
from orthograph.diagnostics.result import ValidationResult
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_profile.models import GraphProfile


__all__ = ["Rule", "profile_to_definition", "profiles", "definitions"]


def profile_to_definition(
    profile: GraphProfile,
    definition: GraphDefinition,
    rules: Sequence[Rule] | None = None,
) -> ValidationResult:
    """Check whether ``profile`` satisfies the constraints in ``definition``.

    Operand: an observed profile against a declared definition. ``rules``
    overrides the default satisfaction rule set.

    Examples
    --------
    Inspect a networkx graph and check it against a declared definition
    (requires the ``networkx`` extra):

    >>> from typing import Optional
    >>> import networkx as nx
    >>> from orthograph.definition import GraphDefinition, NodeModel
    >>> from orthograph.profile import inspect_networkx
    >>> from orthograph.compare import profile_to_definition
    >>> class Person(NodeModel):
    ...     __label__ = "Person"
    ...     __uid_field__ = "name"
    ...     name: str
    ...     born: Optional[int] = None
    >>> definition = GraphDefinition(
    ...     name="Social", node_types=[Person], relationship_types=[]
    ... )
    >>> g = nx.MultiDiGraph()
    >>> _ = g.add_node("alice", __label__="Person", name="Alice", born=1985)
    >>> profile = inspect_networkx(g)
    >>> profile_to_definition(profile, definition).is_valid
    True
    """
    return compare_profile_to_definition(
        profile=profile, definition=definition, rules=rules
    )


def profiles(
    left: GraphProfile,
    right: GraphProfile,
    rules: Sequence[Rule] | None = None,
) -> ValidationResult:
    """Symmetric diff between two observed profiles (US 31).

    Operand: two profiles (e.g. staging↔prod). Emits ``INFO`` issues for
    one-sided or differing addresses. ``rules`` overrides the default diff set.

    Examples
    --------
    Compare two networkx snapshots to detect a new node label (requires
    the ``networkx`` extra):

    >>> import networkx as nx
    >>> from orthograph.profile import inspect_networkx
    >>> from orthograph.compare import profiles
    >>> g1 = nx.MultiDiGraph()
    >>> _ = g1.add_node("alice", __label__="Person", name="Alice")
    >>> g2 = nx.MultiDiGraph()
    >>> _ = g2.add_node("alice", __label__="Person", name="Alice")
    >>> _ = g2.add_node("acme",  __label__="Company", name="ACME")
    >>> result = profiles(inspect_networkx(g1), inspect_networkx(g2))
    >>> result.issues[0].code
    'NODE_LABEL_ONLY_IN_RIGHT'
    """
    return compare_profiles(left=left, right=right, rules=rules)


def definitions(
    left: GraphDefinition,
    right: GraphDefinition,
    rules: Sequence[Rule] | None = None,
) -> ValidationResult:
    """Symmetric diff between two declared definitions (US 30).

    Operand: two definitions (e.g. version↔version). Emits ``INFO`` issues for
    one-sided or differing addresses. ``rules`` overrides the default diff set.

    Examples
    --------
    Detect a new required property added between two definition versions:

    >>> from orthograph.definition import GraphDefinition, NodeModel
    >>> from orthograph.compare import definitions
    >>> class PersonV1(NodeModel):
    ...     __label__ = "Person"
    ...     __uid_field__ = "name"
    ...     name: str
    >>> class PersonV2(NodeModel):
    ...     __label__ = "Person"
    ...     __uid_field__ = "name"
    ...     name: str
    ...     email: str          # new required property
    >>> v1 = GraphDefinition(name="v1", node_types=[PersonV1], relationship_types=[])
    >>> v2 = GraphDefinition(name="v2", node_types=[PersonV2], relationship_types=[])
    >>> result = definitions(v1, v2)
    >>> result.is_valid
    True
    >>> result.issues[0].code
    'PROPERTY_ONLY_IN_RIGHT'
    """
    return compare_definitions(left=left, right=right, rules=rules)
