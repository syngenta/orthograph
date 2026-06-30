"""Inspect a live backend into a vendor-free ``GraphProfile``.

Three per-backend verbs produce the observed side of a graph: read the
backend's current shape into a vendor-free :class:`GraphProfile`.

Per-backend verbs (fully typed, all knobs visible):

* :func:`inspect_networkx` — inspect a :class:`MultiDiGraph` (``networkx``).
* :func:`inspect_neo4j`    — inspect a :class:`BoltDriver` (``neo4j``).
* :func:`inspect_memgraph` — inspect a :class:`BoltDriver` (Memgraph Bolt port).

Connection helper and structural types:

* :func:`check_connection` — validate a borrowed connection is the right shape
  for ``backend``; returns it unchanged.  Constructs and stores nothing
  (Constraint 13 / ADR-028: Orthograph never owns a connection).
* :class:`BoltDriver`   — structural type satisfied by ``neo4j.Driver``.
* :class:`MultiDiGraph` — structural type satisfied by ``networkx.MultiDiGraph``.

Re-exported: ``GraphProfile``, ``Neo4jInspectionStrategy``, ``BoltDriver``,
``MultiDiGraph``.

This module stays thin: every verb delegates to
:func:`orthograph.backends.loader.run_inspection`, which owns the
constructor-vs-call kwarg split and resolves the inspector through the
registry's deferred-import thunks — so ``import orthograph`` loads no DB-vendor
package (ADR-012).

----

**Driver vs factory** — note the asymmetry with :mod:`orthograph.execution`:
``inspect_*`` accept the **driver/graph directly** (neo4j: a :class:`BoltDriver`;
networkx: the :class:`MultiDiGraph` itself).  ``execution.run_*`` accept a
**connection_factory** (a callable returning a session context manager).

**Async inspection** — inspection is synchronous.  Async variants
(``inspect_*_async``) are deliberately absent; async inspection is deferred.
The query-runner async path is separate.

Examples
--------
Inspect a networkx in-memory graph into a vendor-free ``GraphProfile``
(requires the ``networkx`` extra):

>>> import networkx as nx
>>> from orthograph.profile import inspect_networkx
>>> g = nx.MultiDiGraph()
>>> _ = g.add_node("alice", __label__="Person", name="Alice")
>>> _ = g.add_node("inception", __label__="Movie", title="Inception", year=2010)
>>> _ = g.add_edge("alice", "inception", __label__="ACTED_IN", role="Lead")
>>> profile = inspect_networkx(g)
>>> profile.source
'networkx'
>>> sorted(profile.node_labels)
['Movie', 'Person']
>>> "Person:ACTED_IN:Movie" in profile.relationship_types
True
"""

from typing import Any, Protocol, runtime_checkable

from orthograph.backends import loader
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_profile.models import (
    BoundedDistribution,
    CardinalityStats,
    ConstraintInfo,
    GraphProfile,
    NodeTypeProfile,
    PartitionedCardinalityRow,
    PartitionKey,
    PropertyProfile,
    RelationshipTypeProfile,
)


# Re-exported through the sanctioned ``loader`` seam (never imported from the
# concrete ``backends.neo4j`` package directly — that would breach the
# layering rule enforced by test_architecture).
Neo4jInspectionStrategy = loader.Neo4jInspectionStrategy


# ---------------------------------------------------------------------------
# Vendor-free structural connection types
# ---------------------------------------------------------------------------
# Each Protocol captures exactly the interface Orthograph uses from a vendor
# object.  Pure stdlib: a ``neo4j.Driver`` / ``networkx.MultiDiGraph`` satisfies
# it structurally at type-check time and via ``isinstance`` at runtime, with no
# vendor import here.


@runtime_checkable
class BoltDriver(Protocol):
    """Structural type for a neo4j Bolt driver.

    Satisfied by ``neo4j.Driver`` from
    ``neo4j.GraphDatabase.driver(uri, auth=(user, password))``.  Orthograph only
    calls ``execute_query``; no other method is part of the inspection contract.
    """

    def execute_query(self, query_: str, /, **kwargs: Any) -> Any: ...


@runtime_checkable
class MultiDiGraph(Protocol):
    """Structural type for a directed multigraph.

    Satisfied by ``networkx.MultiDiGraph``.  Orthograph reads ``nodes`` and
    ``edges`` during inspection; no other member is part of the contract.
    """

    @property
    def nodes(self) -> Any: ...

    @property
    def edges(self) -> Any: ...


__all__ = [
    "BoltDriver",
    "GraphProfile",
    "NodeTypeProfile",
    "RelationshipTypeProfile",
    "PropertyProfile",
    "CardinalityStats",
    "BoundedDistribution",
    "PartitionKey",
    "PartitionedCardinalityRow",
    "ConstraintInfo",
    "MultiDiGraph",
    "Neo4jInspectionStrategy",
    "check_connection",
    "inspect_memgraph",
    "inspect_neo4j",
    "inspect_networkx",
]


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------


def check_connection(backend: str, connection: Any) -> Any:
    """Validate that ``connection`` is the right shape for ``backend``.

    Returns ``connection`` unchanged.  Constructs and stores **nothing** —
    Orthograph never owns a connection (Constraint 13 / ADR-028).

    * ``"neo4j"`` / ``"memgraph"`` → expects a :class:`BoltDriver`.
    * ``"networkx"`` → expects a :class:`MultiDiGraph`.

    Raises
    ------
    TypeError
        If ``connection`` is not the expected shape for ``backend``.
    ValueError
        If ``backend`` is not a known inspectable backend.
    """
    if backend in ("neo4j", "memgraph"):
        if not isinstance(connection, BoltDriver):
            raise TypeError(
                f"backend {backend!r} expects a BoltDriver with an "
                f"'execute_query' method (neo4j.GraphDatabase.driver(...)), "
                f"got {type(connection).__name__!r}."
            )
    elif backend == "networkx":
        if not isinstance(connection, MultiDiGraph):
            raise TypeError(
                f"backend 'networkx' expects a MultiDiGraph with 'nodes' and "
                f"'edges' (networkx.MultiDiGraph), "
                f"got {type(connection).__name__!r}."
            )
    else:
        known = ", ".join(
            n for n in loader.backend_names() if loader.capabilities(n).can_inspect
        )
        raise ValueError(
            f"Unknown inspectable backend {backend!r}. "
            f"Known inspectable backends: {known}."
        )
    return connection


# ---------------------------------------------------------------------------
# Per-backend verbs
# ---------------------------------------------------------------------------


def inspect_networkx(
    graph: MultiDiGraph,
    *,
    value_counts_top_n: int | None = None,
    graph_definition: GraphDefinition | None = None,
) -> GraphProfile:
    """Inspect a ``networkx.MultiDiGraph`` and return a :class:`GraphProfile`.

    ``graph`` is borrowed for the duration of this call and never stored.

    Parameters
    ----------
    graph:
        A :class:`MultiDiGraph` (``networkx.MultiDiGraph``) whose nodes carry
        ``__label__`` attributes.
    value_counts_top_n:
        When set, run an opt-in per-property value scan that populates
        ``observed_type_counts`` and a bounded ``value_distribution`` histogram
        (truncated to at most ``top_n`` distinct values).  ``None`` or ``0``
        skips the scan entirely.
    graph_definition:
        When supplied, relationship types whose declared side is a
        :class:`~orthograph.graph_definition.models.ConditionalCardinality`
        additionally receive per-side partitioned cardinality breakdowns.
        Without a definition the breakdowns are ``None`` (comparison reports
        ``CARDINALITY_UNVERIFIABLE``).

    Examples
    --------
    Inspect a small in-memory graph (requires the ``networkx`` extra):

    >>> import networkx as nx
    >>> from orthograph.profile import inspect_networkx
    >>> g = nx.MultiDiGraph()
    >>> _ = g.add_node("alice", __label__="Person", name="Alice")
    >>> _ = g.add_node("inception", __label__="Movie", title="Inception")
    >>> _ = g.add_edge("alice", "inception", __label__="ACTED_IN", role="Lead")
    >>> profile = inspect_networkx(g)
    >>> profile.source
    'networkx'
    >>> sorted(profile.node_labels)
    ['Movie', 'Person']
    >>> "Person:ACTED_IN:Movie" in profile.relationship_types
    True
    """
    return loader.run_inspection(
        "networkx",
        graph,
        value_counts_top_n=value_counts_top_n,
        graph_definition=graph_definition,
    )


def inspect_neo4j(
    driver: BoltDriver,
    *,
    database: str | None = None,
    strategy: Neo4jInspectionStrategy | None = None,
    value_counts_top_n: int | None = None,
    graph_definition: GraphDefinition | None = None,
) -> GraphProfile:
    """Inspect a Neo4j database and return a :class:`GraphProfile`.

    ``driver`` is borrowed for the duration of this call and never stored
    (Constraint 13 / ADR-028).

    Parameters
    ----------
    driver:
        A :class:`BoltDriver` (``neo4j.Driver``) from
        ``neo4j.GraphDatabase.driver(uri, auth=(user, password))``.
    database:
        Target database name, forwarded as ``database_`` to
        ``driver.execute_query``.  ``None`` uses the server default.
    strategy:
        Force a :class:`Neo4jInspectionStrategy`.  ``None`` (default)
        auto-detects in the order APOC → SCHEMA → CYPHER.  Use
        ``Neo4jInspectionStrategy.CYPHER`` to skip APOC/schema probes on servers
        where those procedures are absent.
    value_counts_top_n:
        When set, run an opt-in per-property value scan that populates
        ``observed_type_counts`` and a bounded ``value_distribution`` histogram.
        Requires APOC for full type counts; degrades to a scalar-only histogram
        when APOC is unavailable.  ``None`` skips.
    graph_definition:
        When supplied, conditional relationship types additionally receive
        per-side partitioned cardinality breakdowns.
    """
    return loader.run_inspection(
        "neo4j",
        driver,
        database=database,
        strategy=strategy,
        value_counts_top_n=value_counts_top_n,
        graph_definition=graph_definition,
    )


def inspect_memgraph(
    driver: BoltDriver,
    *,
    value_counts_top_n: int | None = None,
    graph_definition: GraphDefinition | None = None,
) -> GraphProfile:
    """Inspect a Memgraph database and return a :class:`GraphProfile`.

    ``driver`` is borrowed for the duration of this call and never stored
    (Constraint 13 / ADR-028).

    Parameters
    ----------
    driver:
        A :class:`BoltDriver` (``neo4j.Driver``) connected to the Memgraph Bolt
        port (``neo4j.GraphDatabase.driver(uri, auth=(user, password))``,
        default ``bolt://localhost:7687``).
    value_counts_top_n:
        When set, run an opt-in per-property value scan that populates
        ``observed_type_counts`` (via Memgraph's ``valueType``) and a bounded
        scalar ``value_distribution`` histogram.  ``None`` skips.
    graph_definition:
        When supplied, conditional relationship types additionally receive
        per-side partitioned cardinality breakdowns.
    """
    return loader.run_inspection(
        "memgraph",
        driver,
        value_counts_top_n=value_counts_top_n,
        graph_definition=graph_definition,
    )
