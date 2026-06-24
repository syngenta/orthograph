"""Live end-to-end tests for the Memgraph inspector.

These tests require a running Memgraph instance.  They are skipped by default
and must be opted into explicitly:

    pytest --memgraph
    pytest --memgraph --memgraph-uri bolt://host:7688 --memgraph-password secret

Every test uses the ``memgraph_clean`` fixture (defined in the root conftest)
which wipes all nodes and relationships both before and after the test.

What is covered
---------------
- Empty database: no profiles returned
- Node property profiles: truthful instance count, completeness semantics
- Relationship profile: properties, truthful instance count
- Endpoint labels (source_labels / target_labels)
- Cardinality statistics computed from confirmed source labels
- ``validate_database()`` passes for a matching model
- ``CypherIdentifierError`` raised on injection attempt
- Internal ``QueryCatalogue`` populated with expected query names

Count / completeness semantics (E46.3)
--------------------------------------
- ``NodeTypeProfile.count`` / ``RelationshipTypeProfile.count`` are truthful,
  sourced from a property-independent ``count()`` (no longer a 0 parity gap).
- ``PropertyProfile.total_count`` is that same true entity total.
- The schema ``mandatory`` boolean is **not** used as a present==total proxy:
  presence requirements are carried by ``constraint_required`` (real DB
  constraints).  Without a value scan there is no observed completeness signal
  (``present_count == total_count`` ⇒ completeness 1.0); the opt-in value scan
  (``value_counts_top_n``) supplies the truthful non-null ``present_count``.
"""

from typing import Any, Optional

import pytest

from orthograph.backends.memgraph.inspector import (
    MemgraphInspector,
    validate_database,
)
from orthograph.backends.memgraph.queries import (
    MemgraphCardinalityQuery,
)
from orthograph.cypher.bindings import NoParams
from orthograph.cypher.exceptions import CypherIdentifierError
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.models import (
    CardinalitySpec,
    ConditionalCardinality,
    ConditionalRule,
    NodeModel,
    PropMatch,
    RelationshipModel,
)
from orthograph.graph_profile.models import PartitionKey


# ---------------------------------------------------------------------------
# Shared domain model
# ---------------------------------------------------------------------------


class Person(NodeModel):
    __label__ = "Person"
    __uid_field__ = "name"
    name: str
    born: Optional[int] = None


class Movie(NodeModel):
    __label__ = "Movie"
    __uid_field__ = "title"
    title: str
    year: int


class ActedIn(RelationshipModel):
    __label__ = "ACTED_IN"
    __source_label__ = "Person"
    __target_label__ = "Movie"
    role: str


FILM_MODEL = GraphDefinition(
    name="Film",
    node_types=[Person, Movie],
    relationship_types=[ActedIn],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed(driver: Any) -> None:
    """Insert two Person nodes, two Movie nodes, and three ACTED_IN edges."""
    driver.execute_query(
        "MERGE (alice:Person {name: 'Alice', born: 1985})"
        " MERGE (bob:Person {name: 'Bob'})"
        " MERGE (inc:Movie {title: 'Inception', year: 2010})"
        " MERGE (dune:Movie {title: 'Dune', year: 2021})"
        " MERGE (alice)-[:ACTED_IN {role: 'Lead'}]->(inc)"
        " MERGE (alice)-[:ACTED_IN {role: 'Cameo'}]->(dune)"
        " MERGE (bob)-[:ACTED_IN {role: 'Supporting'}]->(inc)"
    )


# ---------------------------------------------------------------------------
# Empty database
# ---------------------------------------------------------------------------


@pytest.mark.memgraph
def test_empty_db_returns_empty_profile(
    memgraph_driver: Any, memgraph_clean: None
) -> None:
    """inspect() on an empty DB returns no node or rel profiles."""
    profile = MemgraphInspector().inspect(memgraph_driver)
    assert profile.source == "memgraph"
    assert profile.node_labels == set()
    assert profile.relationship_types == set()


# ---------------------------------------------------------------------------
# Seeded: node profiles
# ---------------------------------------------------------------------------


@pytest.mark.memgraph
def test_node_labels_detected(memgraph_driver: Any, memgraph_clean: None) -> None:
    _seed(memgraph_driver)
    profile = MemgraphInspector().inspect(memgraph_driver)
    assert profile.node_labels == {"Person", "Movie"}


@pytest.mark.memgraph
def test_node_count_is_truthful(memgraph_driver: Any, memgraph_clean: None) -> None:
    """Instance count comes from a property-independent count() (E46.3).

    The seed creates 2 Person nodes and 2 Movie nodes; the count must reflect
    that, not the old ``0`` parity-gap placeholder.
    """
    _seed(memgraph_driver)
    profile = MemgraphInspector().inspect(memgraph_driver)
    assert profile.node_type_profiles["Person"].count == 2
    assert profile.node_type_profiles["Movie"].count == 2


@pytest.mark.memgraph
def test_node_property_names(memgraph_driver: Any, memgraph_clean: None) -> None:
    _seed(memgraph_driver)
    profile = MemgraphInspector().inspect(memgraph_driver)
    person_props = set(profile.node_type_profiles["Person"].property_profiles)
    movie_props = set(profile.node_type_profiles["Movie"].property_profiles)
    assert person_props == {"name", "born"}
    assert movie_props == {"title", "year"}


@pytest.mark.memgraph
def test_no_scan_completeness_is_unsignalled(
    memgraph_driver: Any, memgraph_clean: None
) -> None:
    """Without a value scan, completeness carries no incompleteness signal.

    The schema ``mandatory`` flag is no longer used as a present==total proxy
    (presence requirements are carried by ``constraint_required``).  So without
    a scan, every property reports ``completeness == 1.0`` — even ``born``,
    which is absent on Bob — because there is no *observed* completeness datum.
    """
    _seed(memgraph_driver)
    profile = MemgraphInspector().inspect(memgraph_driver)
    person_props = profile.node_type_profiles["Person"].property_profiles
    assert person_props["name"].completeness == 1.0
    assert person_props["born"].completeness == 1.0


@pytest.mark.memgraph
def test_value_scan_reports_truthful_completeness(
    memgraph_driver: Any, memgraph_clean: None
) -> None:
    """With a value scan, completeness reflects the real non-null occurrences.

    ``born`` is present on Alice but absent on Bob, so among 2 Person nodes its
    completeness is 0.5 — the value scan, not the dropped ``mandatory``
    heuristic, supplies the truthful figure.
    """
    _seed(memgraph_driver)
    profile = MemgraphInspector(value_counts_top_n=10).inspect(memgraph_driver)
    person_props = profile.node_type_profiles["Person"].property_profiles
    name_pp = person_props["name"]
    born_pp = person_props["born"]
    # name is present on every Person.
    assert name_pp.present_count == 2
    assert name_pp.total_count == 2
    assert name_pp.completeness == 1.0
    # born is present on Alice only.
    assert born_pp.present_count == 1
    assert born_pp.total_count == 2
    assert born_pp.completeness == 0.5


# ---------------------------------------------------------------------------
# Seeded: relationship profiles
# ---------------------------------------------------------------------------


@pytest.mark.memgraph
def test_relationship_type_detected(memgraph_driver: Any, memgraph_clean: None) -> None:
    _seed(memgraph_driver)
    profile = MemgraphInspector().inspect(memgraph_driver)
    assert profile.relationship_types == {"Person:ACTED_IN:Movie"}


@pytest.mark.memgraph
def test_relationship_property_names(
    memgraph_driver: Any, memgraph_clean: None
) -> None:
    _seed(memgraph_driver)
    profile = MemgraphInspector().inspect(memgraph_driver)
    props = set(profile.rel_type_profiles["Person:ACTED_IN:Movie"].property_profiles)
    assert props == {"role"}


# ---------------------------------------------------------------------------
# Endpoint labels
# ---------------------------------------------------------------------------


@pytest.mark.memgraph
def test_endpoint_labels_populated(memgraph_driver: Any, memgraph_clean: None) -> None:
    _seed(memgraph_driver)
    profile = MemgraphInspector().inspect(memgraph_driver)
    acted_in = profile.rel_type_profiles["Person:ACTED_IN:Movie"]
    assert acted_in.source_label == "Person"
    assert acted_in.target_label == "Movie"


# ---------------------------------------------------------------------------
# Cardinality
# ---------------------------------------------------------------------------


@pytest.mark.memgraph
def test_cardinality_stats_populated(
    memgraph_driver: Any, memgraph_clean: None
) -> None:
    _seed(memgraph_driver)
    profile = MemgraphInspector().inspect(memgraph_driver)
    cs = profile.rel_type_profiles["Person:ACTED_IN:Movie"].cardinality_stats
    assert cs is not None
    assert cs.min == 1
    assert cs.max == 2
    assert cs.mean == 1.5
    assert cs.count == 2


@pytest.mark.memgraph
def test_cardinality_not_computed_against_target_label(
    memgraph_driver: Any, memgraph_clean: None
) -> None:
    """Regression: cardinality must not be computed against Movie (target)."""
    _seed(memgraph_driver)
    profile = MemgraphInspector().inspect(memgraph_driver)
    cs = profile.rel_type_profiles["Person:ACTED_IN:Movie"].cardinality_stats
    assert cs is not None
    assert cs.min is not None and cs.min > 0, (
        "min == 0: cardinality was computed against the target label"
    )


# ---------------------------------------------------------------------------
# validate_database
# ---------------------------------------------------------------------------


@pytest.mark.memgraph
def test_validate_database_passes_for_matching_model(
    memgraph_driver: Any, memgraph_clean: None
) -> None:
    _seed(memgraph_driver)
    result = validate_database(memgraph_driver, FILM_MODEL)
    assert result.is_valid, [str(e) for e in result.errors]


@pytest.mark.memgraph
def test_validate_database_fails_for_missing_label(
    memgraph_driver: Any, memgraph_clean: None
) -> None:
    _seed(memgraph_driver)

    class Ghost(NodeModel):
        __label__ = "Ghost"
        __uid_field__ = "id"
        id: str

    bad_model = GraphDefinition(name="Bad", node_types=[Ghost], relationship_types=[])
    result = validate_database(memgraph_driver, bad_model)
    assert not result.is_valid
    codes = {e.code for e in result.errors}
    assert "MISSING_NODE_LABEL" in codes


# ---------------------------------------------------------------------------
# Identifier injection guard
# ---------------------------------------------------------------------------


@pytest.mark.memgraph
def test_injection_raises_before_reaching_driver(
    memgraph_driver: Any, memgraph_clean: None
) -> None:
    q = MemgraphCardinalityQuery(
        identifiers={"label": "Person) DETACH DELETE (n //", "rel_type": "X"}
    )
    with pytest.raises(CypherIdentifierError, match="label"):
        q.build(NoParams())


# ---------------------------------------------------------------------------
# Internal catalogue
# ---------------------------------------------------------------------------


@pytest.mark.memgraph
def test_internal_catalogue_populated(
    memgraph_driver: Any, memgraph_clean: None
) -> None:
    """The Memgraph catalogue holds exactly the expected query names."""
    from orthograph.backends.memgraph.queries import build_memgraph_catalogue

    MemgraphInspector().inspect(memgraph_driver)
    names = set(build_memgraph_catalogue().names())
    assert names == {
        "memgraph.inspect.node_properties",
        "memgraph.inspect.rel_properties",
        "memgraph.inspect.constraints",
        "memgraph.inspect.cardinality",
        "memgraph.inspect.endpoint_labels",
        "memgraph.inspect.partitioned_cardinality.source",
        "memgraph.inspect.partitioned_cardinality.target",
        "memgraph.inspect.node_type_counts",
        "memgraph.inspect.rel_type_counts",
        "memgraph.inspect.node_value_histogram",
        "memgraph.inspect.rel_value_histogram",
    }


# ---------------------------------------------------------------------------
# Value scan — observed_type_counts + value_distribution (E46.3, ADR-035)
# ---------------------------------------------------------------------------


@pytest.mark.memgraph
def test_value_scan_mixed_type_property_split(
    memgraph_driver: Any, memgraph_clean: None
) -> None:
    """A mixed-type property reports the exact per-type split (valueType, exact)."""
    memgraph_driver.execute_query(
        "CREATE (:Reading {value: 1})"
        " CREATE (:Reading {value: 2})"
        " CREATE (:Reading {value: 3})"
        " CREATE (:Reading {value: 4.5})"
    )
    profile = MemgraphInspector(value_counts_top_n=10).inspect(memgraph_driver)
    value = profile.node_type_profiles["Reading"].property_profiles["value"]

    assert value.observed_type_counts == {"Int": 3, "Float": 1}
    assert set(value.observed_type_counts) <= set(value.observed_types)


@pytest.mark.memgraph
def test_value_scan_reconciliation_invariant(
    memgraph_driver: Any, memgraph_clean: None
) -> None:
    """sum(type counts) == value_distribution.count == present_count (ADR-035 §2)."""
    memgraph_driver.execute_query(
        "CREATE (:Reading {value: 1})"
        " CREATE (:Reading {value: 1})"
        " CREATE (:Reading {value: 2})"
    )
    profile = MemgraphInspector(value_counts_top_n=10).inspect(memgraph_driver)
    value = profile.node_type_profiles["Reading"].property_profiles["value"]

    total = sum(value.observed_type_counts.values())
    assert value.value_distribution is not None
    assert total == value.value_distribution.count == value.present_count == 3


@pytest.mark.memgraph
def test_value_scan_list_property_dropped_from_histogram_no_crash(
    memgraph_driver: Any, memgraph_clean: None
) -> None:
    """A list-typed property: type counts exact; toStringOrNull drops it (no crash)."""
    memgraph_driver.execute_query("CREATE (:Tag {labels: ['a', 'b']})")
    profile = MemgraphInspector(value_counts_top_n=10).inspect(memgraph_driver)
    labels = profile.node_type_profiles["Tag"].property_profiles["labels"]

    # Type counts classify the list exactly; the scalar histogram dropped it,
    # so its whole population folds into other_count (or value_distribution is
    # None when nothing scalar was histogrammed).
    assert labels.observed_type_counts == {"List[Any]": 1}
    if labels.value_distribution is not None:
        assert labels.value_distribution.histogram in ({}, None)


@pytest.mark.memgraph
def test_value_scan_disabled_yields_empty_counts(
    memgraph_driver: Any, memgraph_clean: None
) -> None:
    """Without value_counts_top_n the scan is skipped (counts {} / dist None)."""
    memgraph_driver.execute_query("CREATE (:Reading {value: 1})")
    profile = MemgraphInspector().inspect(memgraph_driver)
    value = profile.node_type_profiles["Reading"].property_profiles["value"]

    assert value.observed_type_counts == {}
    assert value.value_distribution is None


# ---------------------------------------------------------------------------
# Partitioned cardinality -- both-endpoint conditional (E41.7)
# ---------------------------------------------------------------------------


class Operation(NodeModel):
    """Source node for the both-sides conditional scenario."""

    __label__ = "Operation"
    __uid_field__ = "uid"
    uid: str
    kind: str


class Sample(NodeModel):
    """Target node for the both-sides conditional scenario."""

    __label__ = "Sample"
    __uid_field__ = "uid"
    uid: str
    kind: str


class Makes(RelationshipModel):
    """Conditional on BOTH endpoints (E41.7 live-DB scenario).

    Source rule: (assembler, final) = 2..2.
    Target rule: (assembler, final) = 1..1.
    """

    __label__ = "MAKES"
    __source_label__ = "Operation"
    __target_label__ = "Sample"
    __source_cardinality__ = ConditionalCardinality(
        rules=(
            ConditionalRule(
                source=PropMatch({"kind": "assembler"}),
                target=PropMatch({"kind": "final"}),
                spec=CardinalitySpec(min=2, max=2),
            ),
        ),
        default="0..*",
    )
    __target_cardinality__ = ConditionalCardinality(
        rules=(
            ConditionalRule(
                source=PropMatch({"kind": "assembler"}),
                target=PropMatch({"kind": "final"}),
                spec=CardinalitySpec(min=1, max=1),
            ),
        ),
        default="0..*",
    )


BOTH_SIDES_MODEL = GraphDefinition(
    name="BothSides",
    node_types=[Operation, Sample],
    relationship_types=[Makes],
)

_PAIR = str(PartitionKey(source_value="assembler", target_value="final"))


def _seed_both_sides(driver: Any) -> None:
    """Seed: op1 (assembler) -[MAKES]-> a1, a2 (both final)."""
    driver.execute_query(
        "MERGE (op1:Operation {uid: 'op1', kind: 'assembler'})"
        " MERGE (a1:Sample {uid: 'a1', kind: 'final'})"
        " MERGE (a2:Sample {uid: 'a2', kind: 'final'})"
        " MERGE (op1)-[:MAKES]->(a1)"
        " MERGE (op1)-[:MAKES]->(a2)"
    )


@pytest.mark.memgraph
def test_both_sides_source_breakdown_populated(
    memgraph_driver: Any, memgraph_clean: None
) -> None:
    """Source breakdown counts each source node's outgoing degree per pair.

    op1 has 2 outgoing MAKES edges, so the (assembler, final) partition must
    report min=2, max=2, count=1.
    """
    _seed_both_sides(memgraph_driver)
    profile = MemgraphInspector().inspect(
        memgraph_driver, graph_definition=BOTH_SIDES_MODEL
    )
    src = profile.rel_type_profiles[
        "Operation:MAKES:Sample"
    ].source_partitioned_cardinality
    assert src is not None, "source_partitioned_cardinality must be populated"
    assert _PAIR in src, f"expected partition {_PAIR!r} in {set(src)}"
    assert src[_PAIR].min == 2
    assert src[_PAIR].max == 2
    assert src[_PAIR].count == 1


@pytest.mark.memgraph
def test_both_sides_target_breakdown_populated(
    memgraph_driver: Any, memgraph_clean: None
) -> None:
    """Target breakdown counts each target node's incoming degree per pair.

    a1 and a2 each have 1 incoming MAKES edge, so the (assembler, final)
    partition must report min=1, max=1, count=2.
    """
    _seed_both_sides(memgraph_driver)
    profile = MemgraphInspector().inspect(
        memgraph_driver, graph_definition=BOTH_SIDES_MODEL
    )
    tgt = profile.rel_type_profiles[
        "Operation:MAKES:Sample"
    ].target_partitioned_cardinality
    assert tgt is not None, "target_partitioned_cardinality must be populated"
    assert _PAIR in tgt, f"expected partition {_PAIR!r} in {set(tgt)}"
    assert tgt[_PAIR].min == 1
    assert tgt[_PAIR].max == 1
    assert tgt[_PAIR].count == 2


@pytest.mark.memgraph
def test_both_sides_source_and_target_are_distinct(
    memgraph_driver: Any, memgraph_clean: None
) -> None:
    """The two breakdowns carry different degree values (E41.7 regression guard).

    If both sides issued the source query, both would show count=1, min=2 and
    the min assertion on the target side would fail.
    """
    _seed_both_sides(memgraph_driver)
    profile = MemgraphInspector().inspect(
        memgraph_driver, graph_definition=BOTH_SIDES_MODEL
    )
    rtp = profile.rel_type_profiles["Operation:MAKES:Sample"]
    assert rtp.source_partitioned_cardinality is not None
    assert rtp.target_partitioned_cardinality is not None
    assert rtp.source_partitioned_cardinality[_PAIR].min != (
        rtp.target_partitioned_cardinality[_PAIR].min
    ), "source and target breakdowns are identical -- likely both used the source query"


@pytest.mark.memgraph
def test_both_sides_compare_passes_when_in_bounds(
    memgraph_driver: Any, memgraph_clean: None
) -> None:
    """validate_database passes when both sides satisfy their per-pair rules."""
    _seed_both_sides(memgraph_driver)
    result = validate_database(memgraph_driver, BOTH_SIDES_MODEL)
    violations = [i for i in result.issues if i.code == "CARDINALITY_VIOLATION"]
    assert violations == [], [str(v) for v in violations]
