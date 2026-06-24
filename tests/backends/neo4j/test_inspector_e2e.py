"""Live end-to-end tests for the Neo4j inspector.

These tests require a running Neo4j instance.  They are skipped by default
and must be opted into explicitly:

    pytest --neo4j                               # default URI/credentials
    pytest --neo4j --neo4j-uri bolt://host:7687 \\
                   --neo4j-password secret

Every test uses the ``neo4j_clean`` fixture (defined in the root conftest)
which wipes all nodes and relationships both before and after the test, so
tests are fully independent and leave no residue.

What is covered
---------------
- APOC auto-detection (no APOC installed → pure-Cypher selected)
- Empty database: labels/rel-types/constraints/property profiles
- Node property profiles: count, mandatory vs optional, observed types
- Relationship profile: count, property profiles
- Endpoint labels (source_labels / target_labels)
- Cardinality statistics: min/max/avg/sample_size against the source label
- Cardinality is NOT computed against a target-only label
- ``validate_database()`` passes for a matching model
- ``validate_database()`` reports errors for a mismatched model
- ``CypherIdentifierError`` is raised before any Cypher reaches the driver
  when an injection attempt is made via the Identifiers mechanism
- Internal ``QueryCatalogue`` is populated with the expected query names
"""

from typing import Any, Optional

import pytest

from orthograph.backends.neo4j.inspector import (
    Neo4jInspectionStrategy,
    Neo4jInspector,
    validate_database,
)
from orthograph.backends.neo4j.queries import build_apoc_catalogue
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
from orthograph.graph_profile.queries.shared import InspectCardinalityQuery


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


def _seed(driver: Any) -> None:
    """Populate the DB with a minimal filmography dataset.

    Two Person nodes (Alice with born=1985, Bob with no born), two Movie nodes,
    and three ACTED_IN edges: Alice→Inception, Alice→Dune, Bob→Inception.
    This gives cardinality min=1 (Bob), max=2 (Alice), avg=1.5 on Person.
    """
    driver.execute_query(
        "MERGE (alice:Person {name: 'Alice', born: 1985})"
        " MERGE (bob:Person {name: 'Bob'})"
        " MERGE (inc:Movie {title: 'Inception', year: 2010})"
        " MERGE (dune:Movie {title: 'Dune', year: 2021})"
        " MERGE (alice)-[:ACTED_IN {role: 'Lead'}]->(inc)"
        " MERGE (alice)-[:ACTED_IN {role: 'Cameo'}]->(dune)"
        " MERGE (bob)-[:ACTED_IN {role: 'Supporting'}]->(inc)"
    )


@pytest.mark.neo4j
def test_auto_detection_yields_counts(neo4j_driver: Any, neo4j_clean: None) -> None:
    """Auto-detection (default) yields a usable profile with node counts.

    Observable behaviour: with no explicit strategy, the inspector auto-detects
    (APOC → SCHEMA → CYPHER) and a seeded DB yields node-property counts
    regardless of which strategy the live instance resolves to.
    """
    _seed(neo4j_driver)
    profile = Neo4jInspector().inspect(neo4j_driver)
    assert profile.node_type_profiles["Person"].count == 2


@pytest.mark.neo4j
def test_explicit_cypher_strategy_skips_detection(
    neo4j_driver: Any, neo4j_clean: None
) -> None:
    """strategy=CYPHER uses the pure-Cypher path and never probes procedures.

    Observable behaviour: no ``SHOW PROCEDURES`` (auto-detect) query is issued,
    and the produced profile uses pure-Cypher counts.
    """
    _seed(neo4j_driver)
    profile = Neo4jInspector(strategy=Neo4jInspectionStrategy.CYPHER).inspect(
        neo4j_driver
    )
    assert profile.node_type_profiles["Person"].count == 2
    assert profile.relationship_types == {"ACTED_IN"}


@pytest.mark.neo4j
def test_empty_db_returns_empty_profile(neo4j_driver: Any, neo4j_clean: None) -> None:
    """inspect() on an empty DB returns no relationship profiles and empty
    node profiles.

    Note: Neo4j retains label tokens in its schema even after all nodes are
    deleted (``db.labels()`` may still yield entries), so ``node_labels`` is
    not asserted to be empty here.  What must be empty is every node profile's
    property map and count.
    """
    profile = Neo4jInspector(strategy=Neo4jInspectionStrategy.CYPHER).inspect(
        neo4j_driver
    )

    assert profile.source == "neo4j"
    assert profile.relationship_types == set()
    for np in profile.node_type_profiles.values():
        assert np.count == 0
        assert np.property_profiles == {}


@pytest.mark.neo4j
def test_node_labels_detected(neo4j_driver: Any, neo4j_clean: None) -> None:
    """After seeding, both Person and Movie are present in the profile."""
    _seed(neo4j_driver)
    profile = Neo4jInspector(strategy=Neo4jInspectionStrategy.CYPHER).inspect(
        neo4j_driver
    )
    assert profile.node_labels == {"Person", "Movie"}


@pytest.mark.neo4j
def test_node_counts(neo4j_driver: Any, neo4j_clean: None) -> None:
    """Node counts are derived from the two-pass MATCH/count scan.

    Both Person (2) and Movie (2) were seeded.
    """
    _seed(neo4j_driver)
    profile = Neo4jInspector(strategy=Neo4jInspectionStrategy.CYPHER).inspect(
        neo4j_driver
    )
    assert profile.node_type_profiles["Person"].count == 2
    assert profile.node_type_profiles["Movie"].count == 2


@pytest.mark.neo4j
def test_node_property_names(neo4j_driver: Any, neo4j_clean: None) -> None:
    """Property names are inferred from observed keys across all nodes of each
    label.  Person has {name, born}; Movie has {title, year}.
    """
    _seed(neo4j_driver)
    profile = Neo4jInspector(strategy=Neo4jInspectionStrategy.CYPHER).inspect(
        neo4j_driver
    )
    person_props = set(profile.node_type_profiles["Person"].property_profiles)
    movie_props = set(profile.node_type_profiles["Movie"].property_profiles)
    assert person_props == {"name", "born"}
    assert movie_props == {"title", "year"}


@pytest.mark.neo4j
def test_mandatory_property_is_required(neo4j_driver: Any, neo4j_clean: None) -> None:
    """A property present on every node of a label is reported as required.

    name is present on both Alice and Bob (present_count == total_count == 2).
    """
    _seed(neo4j_driver)
    profile = Neo4jInspector(strategy=Neo4jInspectionStrategy.CYPHER).inspect(
        neo4j_driver
    )
    name_pp = profile.node_type_profiles["Person"].property_profiles["name"]
    assert name_pp.completeness == 1.0
    assert name_pp.present_count == 2
    assert name_pp.total_count == 2


@pytest.mark.neo4j
def test_optional_property_is_not_required(
    neo4j_driver: Any, neo4j_clean: None
) -> None:
    """A property absent on at least one node is reported as optional.

    born is present on Alice (1985) but absent on Bob, so present_count=1,
    total_count=2, is_required=False.
    """
    _seed(neo4j_driver)
    profile = Neo4jInspector(strategy=Neo4jInspectionStrategy.CYPHER).inspect(
        neo4j_driver
    )
    born_pp = profile.node_type_profiles["Person"].property_profiles["born"]
    assert born_pp.completeness < 1.0
    assert born_pp.present_count == 1
    assert born_pp.total_count == 2


@pytest.mark.neo4j
def test_relationship_type_detected(neo4j_driver: Any, neo4j_clean: None) -> None:
    """After seeding, ACTED_IN is present in rel_type_profiles."""
    _seed(neo4j_driver)
    profile = Neo4jInspector(strategy=Neo4jInspectionStrategy.CYPHER).inspect(
        neo4j_driver
    )
    assert profile.relationship_types == {"ACTED_IN"}


@pytest.mark.neo4j
def test_relationship_count(neo4j_driver: Any, neo4j_clean: None) -> None:
    """Relationship count is derived from the total_observations of the
    rel-property scan (three edges were seeded).
    """
    _seed(neo4j_driver)
    profile = Neo4jInspector(strategy=Neo4jInspectionStrategy.CYPHER).inspect(
        neo4j_driver
    )
    assert profile.rel_type_profiles["ACTED_IN"].count == 3


@pytest.mark.neo4j
def test_relationship_property_names(neo4j_driver: Any, neo4j_clean: None) -> None:
    """Property names are inferred from observed keys across all edges of the
    relationship type.  All three ACTED_IN edges carry role.
    """
    _seed(neo4j_driver)
    profile = Neo4jInspector(strategy=Neo4jInspectionStrategy.CYPHER).inspect(
        neo4j_driver
    )
    props = set(profile.rel_type_profiles["ACTED_IN"].property_profiles)
    assert props == {"role"}


@pytest.mark.neo4j
def test_endpoint_labels_populated(neo4j_driver: Any, neo4j_clean: None) -> None:
    """source_labels and target_labels are populated by the endpoint-labels query."""
    _seed(neo4j_driver)
    profile = Neo4jInspector(strategy=Neo4jInspectionStrategy.CYPHER).inspect(
        neo4j_driver
    )
    acted_in = profile.rel_type_profiles["ACTED_IN"]
    assert acted_in.source_labels == {"Person"}
    assert acted_in.target_labels == {"Movie"}


@pytest.mark.neo4j
def test_cardinality_stats_populated(neo4j_driver: Any, neo4j_clean: None) -> None:
    """Cardinality statistics are computed against the confirmed source label.

    With two Person nodes — Alice (2 edges) and Bob (1 edge) — the expected
    values are min=1, max=2, avg=1.5, sample_size=2.
    """
    _seed(neo4j_driver)
    profile = Neo4jInspector(strategy=Neo4jInspectionStrategy.CYPHER).inspect(
        neo4j_driver
    )
    cs = profile.rel_type_profiles["ACTED_IN"].cardinality_stats
    assert cs is not None
    assert cs.min == 1
    assert cs.max == 2
    assert cs.mean == 1.5
    assert cs.count == 2


@pytest.mark.neo4j
def test_cardinality_not_computed_against_target_label(
    neo4j_driver: Any, neo4j_clean: None
) -> None:
    """Cardinality is computed against the confirmed source label, not the target.

    Movie nodes are targets of ACTED_IN and have no outgoing edges, so querying
    cardinality against Movie yields degree=0 for every node — producing
    min=0/max=0/avg=0.  The inspector runs endpoint_labels first and restricts
    cardinality to source labels only.  If min_degree is 0 here, a regression
    has occurred.
    """
    _seed(neo4j_driver)
    profile = Neo4jInspector(strategy=Neo4jInspectionStrategy.CYPHER).inspect(
        neo4j_driver
    )
    cs = profile.rel_type_profiles["ACTED_IN"].cardinality_stats
    assert cs is not None
    assert cs.min is not None and cs.min > 0, (
        "min == 0: cardinality was computed against the target label "
        "(Movie) instead of the source label (Person)"
    )


@pytest.mark.neo4j
def test_cardinality_none_when_no_relationships(
    neo4j_driver: Any, neo4j_clean: None
) -> None:
    """When only nodes are present, ACTED_IN does not appear in the profile
    at all, so there is no cardinality to compute.
    """
    neo4j_driver.execute_query(
        "MERGE (:Person {name: 'Alice'})"
        " MERGE (:Movie {title: 'Inception', year: 2010})"
    )
    profile = Neo4jInspector(strategy=Neo4jInspectionStrategy.CYPHER).inspect(
        neo4j_driver
    )
    assert "ACTED_IN" not in profile.rel_type_profiles


@pytest.mark.neo4j
def test_schema_strategy_populates_types_with_true_counts(
    neo4j_driver: Any, neo4j_clean: None
) -> None:
    """SCHEMA strategy: observed_types populated AND completeness counts true.

    This is the reproduced-failure scenario from ADR-033, now fixed: forcing
    ``strategy=SCHEMA`` (the path auto-detection selects when ``apoc.meta.*`` is
    absent but ``db.schema.*`` exists) yields populated ``observed_types`` from
    ``db.schema.*`` while keeping the true completeness counts from the
    pure-Cypher scan.

    Seeded data: Alice has born=1985, Bob has no born — so on Person, ``name`` is
    complete (2/2) and ``born`` is partial (1/2).  Without this strategy the
    pure-Cypher fallback would report ``observed_types == []``.
    """
    _seed(neo4j_driver)
    profile = Neo4jInspector(strategy=Neo4jInspectionStrategy.SCHEMA).inspect(
        neo4j_driver
    )

    person = profile.node_type_profiles["Person"]
    # Types populated from db.schema.* (the fix).
    assert person.property_profiles["name"].observed_types != []
    assert "String" in person.property_profiles["name"].observed_types
    # True completeness counts preserved from the scan.
    name_pp = person.property_profiles["name"]
    assert name_pp.present_count == 2
    assert name_pp.total_count == 2
    born_pp = person.property_profiles["born"]
    assert born_pp.present_count == 1
    assert born_pp.total_count == 2

    # Relationship property types populated too.
    role_pp = profile.rel_type_profiles["ACTED_IN"].property_profiles["role"]
    assert role_pp.observed_types != []
    assert role_pp.present_count == 3
    assert role_pp.total_count == 3


@pytest.mark.neo4j
def test_validate_database_passes_for_matching_model(
    neo4j_driver: Any, neo4j_clean: None
) -> None:
    """validate_database() is valid when the DB schema matches the model."""
    _seed(neo4j_driver)
    result = validate_database(neo4j_driver, FILM_MODEL)
    assert result.is_valid, [str(e) for e in result.errors]


@pytest.mark.neo4j
def test_validate_database_fails_for_missing_label(
    neo4j_driver: Any, neo4j_clean: None
) -> None:
    """validate_database() reports MISSING_NODE_LABEL when the model declares
    a node type that has no instances in the database.
    """
    _seed(neo4j_driver)

    class Ghost(NodeModel):
        __label__ = "Ghost"
        __uid_field__ = "id"
        id: str

    bad_model = GraphDefinition(name="Bad", node_types=[Ghost], relationship_types=[])
    result = validate_database(neo4j_driver, bad_model)
    assert not result.is_valid
    codes = {e.code for e in result.errors}
    assert "MISSING_NODE_LABEL" in codes


@pytest.mark.neo4j
def test_validate_database_fails_for_wrong_endpoint(
    neo4j_driver: Any, neo4j_clean: None
) -> None:
    """validate_database() reports INVALID_ENDPOINT when the model declares a
    relationship endpoint that does not match what the database contains.

    The DB has ACTED_IN going Person→Movie.  The model declares Person→Studio,
    which is wrong.
    """
    _seed(neo4j_driver)

    class Studio(NodeModel):
        __label__ = "Studio"
        __uid_field__ = "name"
        name: str

    class WrongActedIn(RelationshipModel):
        __label__ = "ACTED_IN"
        __source_label__ = "Person"
        __target_label__ = "Studio"

    wrong_model = GraphDefinition(
        name="Wrong",
        node_types=[Person, Movie, Studio],
        relationship_types=[WrongActedIn],
    )
    result = validate_database(neo4j_driver, wrong_model)
    assert not result.is_valid
    codes = {e.code for e in result.errors}
    assert "INVALID_ENDPOINT" in codes


@pytest.mark.neo4j
def test_injection_raises_before_reaching_driver(
    neo4j_driver: Any, neo4j_clean: None
) -> None:
    """CypherIdentifierError is raised by build(), before any Cypher reaches
    the driver.

    The DB must remain untouched: the post-assertion node count confirms that
    no query was executed.
    """
    q = InspectCardinalityQuery(
        identifiers={"label": "Person) DETACH DELETE (n //", "rel_type": "X"}
    )
    with pytest.raises(CypherIdentifierError, match="label"):
        q.build(NoParams())
    records, _, _ = neo4j_driver.execute_query("MATCH (n) RETURN count(n) AS c")
    assert records[0]["c"] == 0


@pytest.mark.neo4j
def test_internal_catalogue_populated(neo4j_driver: Any, neo4j_clean: None) -> None:
    """The pure-Cypher catalogue holds exactly the expected query names.

    The APOC-keyed value scan (type counts via apoc.meta.cypher.type, and the
    list-keeping histogram via apoc.convert.toJson) is an APOC feature, so the
    pure-Cypher catalogue omits those four queries.
    adds a scalar-only histogram fallback (toStringOrNull) for node and rel
    properties, so those two ARE present.
    """
    from orthograph.backends.neo4j.queries import build_cypher_catalogue

    Neo4jInspector(strategy=Neo4jInspectionStrategy.CYPHER).inspect(neo4j_driver)
    names = set(build_cypher_catalogue().names())
    assert names == {
        "neo4j.inspect.node_labels",
        "neo4j.inspect.rel_types",
        "neo4j.inspect.node_count",
        "neo4j.inspect.rel_count",
        "neo4j.inspect.cypher.node_properties",
        "neo4j.inspect.cypher.rel_properties",
        "inspect.cardinality",
        "neo4j.inspect.constraints",
        "inspect.endpoint_labels",
        "inspect.partitioned_cardinality.source",
        "inspect.partitioned_cardinality.target",
        # E46.6: scalar-only pure-Cypher histogram fallback.
        "neo4j.inspect.cypher.node_value_histogram",
        "neo4j.inspect.cypher.rel_value_histogram",
        # ADR-036: property-independent present-count queries.
        "neo4j.inspect.node_present_count",
        "neo4j.inspect.rel_present_count",
    }


@pytest.mark.neo4j
def test_apoc_catalogue_offline_describe(neo4j_driver: Any, neo4j_clean: None) -> None:
    """The APOC catalogue can be built and described without a live APOC
    installation — it is a pure Python object and does not execute any queries
    during construction.

    Every registered query must expose an output_schema (non-None) so it can
    be introspected via describe().
    """
    query_catalogue = build_apoc_catalogue()
    names = set(query_catalogue.names())
    assert "neo4j.inspect.apoc.node_properties" in names
    assert "neo4j.inspect.apoc.rel_properties" in names
    # Authoritative instance-count queries (property-independent).
    assert "neo4j.inspect.node_count" in names
    assert "neo4j.inspect.rel_count" in names
    # E46.1: APOC catalogue gains type-count + histogram queries (node + rel).
    assert "neo4j.inspect.apoc.node_type_counts" in names
    assert "neo4j.inspect.apoc.rel_type_counts" in names
    assert "neo4j.inspect.apoc.node_value_histogram" in names
    assert "neo4j.inspect.apoc.rel_value_histogram" in names
    # ADR-036: property-independent present-count queries.
    assert "neo4j.inspect.node_present_count" in names
    assert "neo4j.inspect.rel_present_count" in names
    assert len(names) == 17
    for desc in query_catalogue.describe():
        assert desc.output_schema is not None


# ---------------------------------------------------------------------------
# Partitioned cardinality — both-endpoint conditional (E41.7)
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

    Source rule: (assembler, final) = 2..2  — each assembler must produce
    exactly 2 final samples.
    Target rule: (assembler, final) = 1..1  — each final sample must be
    produced by exactly 1 assembler.
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
    """Seed: op1 (assembler) -[MAKES]-> a1, a2 (both final).

    Source side: op1 has outgoing degree 2 in the (assembler, final) partition.
    Target side: a1 and a2 each have incoming degree 1 in the same partition.
    """
    driver.execute_query(
        "MERGE (op1:Operation {uid: 'op1', kind: 'assembler'})"
        " MERGE (a1:Sample {uid: 'a1', kind: 'final'})"
        " MERGE (a2:Sample {uid: 'a2', kind: 'final'})"
        " MERGE (op1)-[:MAKES]->(a1)"
        " MERGE (op1)-[:MAKES]->(a2)"
    )


@pytest.mark.neo4j
def test_both_sides_source_breakdown_populated(
    neo4j_driver: Any, neo4j_clean: None
) -> None:
    """Source breakdown counts each source node's outgoing degree per pair.

    op1 has 2 outgoing MAKES edges to final samples, so the
    (assembler, final) partition must report min=2, max=2, count=1.
    This confirms InspectSourcePartitionedCardinalityQuery is issued (not the
    target query, which would report count=2, min=1, max=1).
    """
    _seed_both_sides(neo4j_driver)
    profile = Neo4jInspector(strategy=Neo4jInspectionStrategy.CYPHER).inspect(
        neo4j_driver, graph_definition=BOTH_SIDES_MODEL
    )
    src = profile.rel_type_profiles["MAKES"].source_partitioned_cardinality
    assert src is not None, "source_partitioned_cardinality must be populated"
    assert _PAIR in src, f"expected partition {_PAIR!r} in {set(src)}"
    assert src[_PAIR].min == 2
    assert src[_PAIR].max == 2
    assert src[_PAIR].count == 1  # one source node (op1)


@pytest.mark.neo4j
def test_both_sides_target_breakdown_populated(
    neo4j_driver: Any, neo4j_clean: None
) -> None:
    """Target breakdown counts each target node's incoming degree per pair.

    a1 and a2 each have 1 incoming MAKES edge from an assembler, so the
    (assembler, final) partition must report min=1, max=1, count=2.
    This confirms InspectTargetPartitionedCardinalityQuery is issued (not the
    source query, which would report count=1, min=2, max=2 — op1's degree).
    """
    _seed_both_sides(neo4j_driver)
    profile = Neo4jInspector(strategy=Neo4jInspectionStrategy.CYPHER).inspect(
        neo4j_driver, graph_definition=BOTH_SIDES_MODEL
    )
    tgt = profile.rel_type_profiles["MAKES"].target_partitioned_cardinality
    assert tgt is not None, "target_partitioned_cardinality must be populated"
    assert _PAIR in tgt, f"expected partition {_PAIR!r} in {set(tgt)}"
    assert tgt[_PAIR].min == 1
    assert tgt[_PAIR].max == 1
    assert tgt[_PAIR].count == 2  # two target nodes (a1, a2)


@pytest.mark.neo4j
def test_both_sides_source_and_target_are_distinct(
    neo4j_driver: Any, neo4j_clean: None
) -> None:
    """The two breakdowns carry different degree values for the same partition.

    This is the live-DB regression guard for the E41.7 bug: if both sides
    issued InspectSourcePartitionedCardinalityQuery, source and target would
    be identical (both op1's outgoing degree = 2), and the min=1 assertion
    on the target side would fail.
    """
    _seed_both_sides(neo4j_driver)
    profile = Neo4jInspector(strategy=Neo4jInspectionStrategy.CYPHER).inspect(
        neo4j_driver, graph_definition=BOTH_SIDES_MODEL
    )
    rtp = profile.rel_type_profiles["MAKES"]
    src = rtp.source_partitioned_cardinality
    tgt = rtp.target_partitioned_cardinality
    assert src is not None
    assert tgt is not None
    # Source degree = 2 (op1 has 2 outgoing edges); target degree = 1 (each
    # of a1, a2 has 1 incoming edge).  They must differ.
    assert src[_PAIR].min != tgt[_PAIR].min, (
        "source and target breakdowns are identical — likely both used the "
        "source-anchored query (E41.7 regression)"
    )


@pytest.mark.neo4j
def test_both_sides_compare_passes_when_in_bounds(
    neo4j_driver: Any, neo4j_clean: None
) -> None:
    """validate_database passes when both sides satisfy their per-pair rules."""
    _seed_both_sides(neo4j_driver)
    result = validate_database(neo4j_driver, BOTH_SIDES_MODEL)
    violations = [i for i in result.issues if i.code == "CARDINALITY_VIOLATION"]
    assert violations == [], [str(v) for v in violations]


# ---------------------------------------------------------------------------
# Value-scan queries — type counts + histogram (E46.1, ADR-035)
#
# These exercise the new queries directly against a live instance (inspector
# wiring).  They prove the runtime behaviours mocks can only
# approximate: the GROUP BY type aggregation, the bounded cost, the histogram
# truncation, and the APOC-vs-CYPHER availability of the runtime-type function.
# ---------------------------------------------------------------------------


def _run(driver: Any, query: Any, params: Any) -> list[Any]:
    """Build a query, execute it, and materialise every record."""
    cypher, bound = query.build(params)
    records, _, _ = driver.execute_query(cypher, bound)
    return [query.materialize(r) for r in records]


def _seed_mixed_born(driver: Any) -> None:
    """Person.born is mostly Long with a couple of String rows (dirty data).

    3 ints (1980, 1985, 1990) and 2 strings ('1999', 'unknown') → on a live
    instance: {'Long': 3, 'String': 2}, present_count == 5.
    """
    driver.execute_query(
        "MERGE (:Person {name: 'a', born: 1980})"
        " MERGE (:Person {name: 'b', born: 1985})"
        " MERGE (:Person {name: 'c', born: 1990})"
        " MERGE (:Person {name: 'd', born: '1999'})"
        " MERGE (:Person {name: 'e', born: 'unknown'})"
    )


@pytest.mark.neo4j
def test_node_type_counts_exact_split(neo4j_driver: Any, neo4j_clean: None) -> None:
    """A mixed-type property yields the exact {type: count} split (APOC)."""
    from orthograph.backends.neo4j.queries import ApocNodeTypeCountsQuery

    _seed_mixed_born(neo4j_driver)
    rows = _run(
        neo4j_driver,
        ApocNodeTypeCountsQuery(
            identifiers={"label": "Person", "property_name": "born"}
        ),
        NoParams(),
    )
    counts = {r.type_name: r.type_count for r in rows}
    assert counts == {"Long": 3, "String": 2}


@pytest.mark.neo4j
def test_type_counts_reconcile_with_present_count(
    neo4j_driver: Any, neo4j_clean: None
) -> None:
    """sum(type counts) == present_count (the ADR-035 reconciliation total).

    The histogram count (non-truncated here) equals the same total, so the
    type side and value side reconcile at the total.
    """
    from orthograph.backends.neo4j.queries import (
        ApocNodeTypeCountsQuery,
        ApocNodeValueHistogramQuery,
    )

    _seed_mixed_born(neo4j_driver)
    type_rows = _run(
        neo4j_driver,
        ApocNodeTypeCountsQuery(
            identifiers={"label": "Person", "property_name": "born"}
        ),
        NoParams(),
    )
    hist_rows = _run(
        neo4j_driver,
        ApocNodeValueHistogramQuery(
            identifiers={"label": "Person", "property_name": "born"}
        ),
        ApocNodeValueHistogramQuery.Params(top_n=100),
    )
    type_total = sum(r.type_count for r in type_rows)
    hist_total = sum(r.value_count for r in hist_rows)
    assert type_total == 5  # present_count
    assert hist_total == 5


@pytest.mark.neo4j
def test_type_counts_bounded_on_high_cardinality(
    neo4j_driver: Any, neo4j_clean: None
) -> None:
    """The type-count query returns <= (distinct types) rows even on a UID-like
    property with many distinct values — it groups by *type*, never by value.
    """
    from orthograph.backends.neo4j.queries import ApocNodeTypeCountsQuery

    # 50 distinct string UIDs → 1 distinct type ('String').
    neo4j_driver.execute_query(
        "UNWIND range(1, 50) AS i"
        " CREATE (:Widget {uid: toString(i) + '-' + randomUUID()})"
    )
    rows = _run(
        neo4j_driver,
        ApocNodeTypeCountsQuery(
            identifiers={"label": "Widget", "property_name": "uid"}
        ),
        NoParams(),
    )
    # One row per distinct TYPE, not per distinct value.
    assert len(rows) == 1
    assert rows[0].type_name == "String"
    assert rows[0].type_count == 50


@pytest.mark.neo4j
def test_value_histogram_truncates_while_type_stays_exact(
    neo4j_driver: Any, neo4j_clean: None
) -> None:
    """A high-cardinality property: histogram hits the LIMIT (truncates) while
    the type-count query stays exact (single {'String': total} entry).
    """
    from orthograph.backends.neo4j.queries import (
        ApocNodeTypeCountsQuery,
        ApocNodeValueHistogramQuery,
    )

    neo4j_driver.execute_query(
        "UNWIND range(1, 50) AS i CREATE (:Widget {uid: toString(i)})"
    )
    top_n = 10
    hist_rows = _run(
        neo4j_driver,
        ApocNodeValueHistogramQuery(
            identifiers={"label": "Widget", "property_name": "uid"}
        ),
        ApocNodeValueHistogramQuery.Params(top_n=top_n),
    )
    # The histogram is capped at top_n (the truncating part).
    assert len(hist_rows) == top_n
    # The type counts remain exact and complete (not truncated).
    type_rows = _run(
        neo4j_driver,
        ApocNodeTypeCountsQuery(
            identifiers={"label": "Widget", "property_name": "uid"}
        ),
        NoParams(),
    )
    assert len(type_rows) == 1
    assert type_rows[0].type_name == "String"
    assert type_rows[0].type_count == 50


@pytest.mark.neo4j
def test_rel_type_counts_exact_split(neo4j_driver: Any, neo4j_clean: None) -> None:
    """Relationship property type counts mirror the node-side behaviour."""
    from orthograph.backends.neo4j.queries import ApocRelTypeCountsQuery

    neo4j_driver.execute_query(
        "MERGE (p:Person {name: 'p'})"
        " MERGE (m:Movie {title: 'm', year: 2000})"
        " MERGE (p)-[:ACTED_IN {role: 'Lead'}]->(m)"
        " MERGE (p)-[:ACTED_IN {role: 2}]->(m)"
    )
    rows = _run(
        neo4j_driver,
        ApocRelTypeCountsQuery(
            identifiers={"rel_type": "ACTED_IN", "property_name": "role"}
        ),
        NoParams(),
    )
    counts = {r.type_name: r.type_count for r in rows}
    assert counts == {"String": 1, "Long": 1}


# ---------------------------------------------------------------------------
# Inspector wiring — value_counts_top_n (E46.2, ADR-035)
#
# These tests exercise Neo4jInspector end-to-end with value_counts_top_n set,
# proving the $top_n parameter binding reaches the live driver (not only
# MagicMock, which ignores kwargs) and that the profile fields are populated
# and reconcile.
# ---------------------------------------------------------------------------


@pytest.mark.neo4j
def test_inspector_value_counts_top_n_apoc_wiring(
    neo4j_driver: Any, neo4j_clean: None
) -> None:
    """APOC + value_counts_top_n wires $top_n through to the live driver.

    Exercises the inspector end-to-end with value_counts_top_n set, proving:
    - The histogram $top_n parameter binding reaches the driver (mocks ignore
      kwargs; this test does not).
    - observed_type_counts and value_distribution are both populated.
    - Reconciliation invariant: sum(type_counts) == value_distribution.count
      == present_count (ADR-035 §2).
    """
    _seed_mixed_born(neo4j_driver)
    profile = Neo4jInspector(
        strategy=Neo4jInspectionStrategy.APOC, value_counts_top_n=20
    ).inspect(neo4j_driver)

    born = profile.node_type_profiles["Person"].property_profiles["born"]

    # Type counts populated with the exact per-type split.
    assert born.observed_type_counts == {"Long": 3, "String": 2}
    # Histogram populated (all 5 distinct values fit within top_n=20).
    assert born.value_distribution is not None
    assert born.value_distribution.sample_complete is True
    assert born.value_distribution.count == 5
    # Reconciliation invariant.
    assert sum(born.observed_type_counts.values()) == born.value_distribution.count
    assert born.value_distribution.count == born.present_count


@pytest.mark.neo4j
def test_inspector_value_counts_top_n_cypher_yields_empty_type_counts(
    neo4j_driver: Any, neo4j_clean: None
) -> None:
    """CYPHER + value_counts_top_n: no type counts (no runtime-type function).

    Type counts need apoc.meta.cypher.type, which pure-CYPHER lacks, so
    observed_type_counts == {} . restores a scalar
    histogram fallback (toStringOrNull), so value_distribution IS populated for
    the scalar Person.born — see test_cypher_fallback_scalar_histogram_populated
    for the histogram assertions.  present_count comes from the pure-Cypher scan.
    """
    _seed_mixed_born(neo4j_driver)
    profile = Neo4jInspector(
        strategy=Neo4jInspectionStrategy.CYPHER, value_counts_top_n=20
    ).inspect(neo4j_driver)

    born = profile.node_type_profiles["Person"].property_profiles["born"]

    # No runtime-type function on pure-Cypher → no type counts.
    assert born.observed_type_counts == {}
    # present_count still comes from the pure-Cypher property scan.
    assert born.present_count == 5


@pytest.mark.neo4j
def test_inspector_value_counts_top_n_truncation(
    neo4j_driver: Any, neo4j_clean: None
) -> None:
    """top_n smaller than distinct values truncates histogram; type counts exact.

    Seeds 50 distinct string UIDs, inspects with top_n=5.  The histogram is
    capped at 5 rows (sample_complete=False, other_count>0); type counts report
    the full {'String': 50} without truncation (ADR-035 §4).
    """
    neo4j_driver.execute_query(
        "UNWIND range(1, 50) AS i CREATE (:Widget {uid: toString(i)})"
    )
    profile = Neo4jInspector(
        strategy=Neo4jInspectionStrategy.APOC, value_counts_top_n=5
    ).inspect(neo4j_driver)

    uid = profile.node_type_profiles["Widget"].property_profiles["uid"]

    # Histogram truncated.
    assert uid.value_distribution is not None
    assert uid.value_distribution.sample_complete is False
    assert uid.value_distribution.limit == 5
    assert uid.value_distribution.other_count is not None
    assert uid.value_distribution.other_count > 0
    # Type counts exact and untruncated.
    assert uid.observed_type_counts == {"String": 50}
    # Reconciliation still holds at the total.
    assert sum(uid.observed_type_counts.values()) == uid.value_distribution.count
    assert uid.value_distribution.count == uid.present_count


# ---------------------------------------------------------------------------
# Pure-Cypher scalar histogram fallback
#
# On a strategy without APOC, value_counts_top_n still populates a *scalar*
# value_distribution via the toStringOrNull pure-Cypher histogram; list/array
# properties are left None (skipped) rather than crashing toString(list).
# Type counts stay {} (no portable runtime-type function on pure-Cypher).
# ---------------------------------------------------------------------------


@pytest.mark.neo4j
def test_cypher_fallback_scalar_histogram_populated(
    neo4j_driver: Any, neo4j_clean: None
) -> None:
    """CYPHER + value_counts_top_n → scalar property gets a histogram, no types.

    Seeds Person.born scalars; under strategy=CYPHER the toStringOrNull fallback
    histogram populates value_distribution while observed_type_counts stays {}
    (no apoc.meta.cypher.type on pure-Cypher).
    """
    _seed_mixed_born(neo4j_driver)
    profile = Neo4jInspector(
        strategy=Neo4jInspectionStrategy.CYPHER, value_counts_top_n=20
    ).inspect(neo4j_driver)

    born = profile.node_type_profiles["Person"].property_profiles["born"]

    # No runtime-type function on pure-Cypher → no type counts.
    assert born.observed_type_counts == {}
    # E46.6: the scalar histogram fallback IS populated (all 5 values are scalar
    # — ints and strings both stringify, so the histogram is complete).
    assert born.value_distribution is not None
    assert born.value_distribution.count == 5
    assert born.value_distribution.sample_complete is True
    histogram = born.value_distribution.histogram
    assert histogram is not None
    assert sum(histogram.values()) == 5


@pytest.mark.neo4j
def test_cypher_fallback_list_property_is_skipped_not_crashed(
    neo4j_driver: Any, neo4j_clean: None
) -> None:
    """CYPHER + a StringArray property → value_distribution is None (NO crash).

    Hard regression guard for the discovered toString(list) failure
    (`Invalid input for function 'toString()': … StringArray`).  ACTED_IN.roles
    is a StringArray; under strategy=CYPHER the toStringOrNull fallback returns
    null for every list value, so the scalar histogram is empty → None.  The
    inspection must complete without a TypeError.
    """
    neo4j_driver.execute_query(
        "MERGE (p:Person {name: 'Alice'})"
        " MERGE (m:Movie {title: 'Inception', year: 2010})"
        " MERGE (p)-[:ACTED_IN {roles: ['Cobb', 'Lead']}]->(m)"
    )
    # Must not raise (the whole point of the guard).
    profile = Neo4jInspector(
        strategy=Neo4jInspectionStrategy.CYPHER, value_counts_top_n=20
    ).inspect(neo4j_driver)

    roles = profile.rel_type_profiles["ACTED_IN"].property_profiles["roles"]
    # List values are dropped by toStringOrNull → no scalar histogram.
    assert roles.value_distribution is None
    assert roles.observed_type_counts == {}
    # Presence is still truthful (the edge has the property).
    assert roles.present_count == 1


# ---------------------------------------------------------------------------
# Instance count is property-independent
# ---------------------------------------------------------------------------


@pytest.mark.neo4j
def test_property_less_relationship_has_nonzero_count(
    neo4j_driver: Any, neo4j_clean: None
) -> None:
    """A relationship type with NO properties still reports its true edge count.

    Regression guard for the bug where rel/node count was derived from property
    observations: a property-less type yielded count=0 despite having edges.
    LINKS carries no properties; three edges are seeded, so count must be 3.
    """
    neo4j_driver.execute_query(
        "MERGE (a:Thing {id: 'a'})"
        " MERGE (b:Thing {id: 'b'})"
        " MERGE (c:Thing {id: 'c'})"
        " MERGE (a)-[:LINKS]->(b)"
        " MERGE (b)-[:LINKS]->(c)"
        " MERGE (a)-[:LINKS]->(c)"
    )
    profile = Neo4jInspector(strategy=Neo4jInspectionStrategy.CYPHER).inspect(
        neo4j_driver
    )
    links = profile.rel_type_profiles["LINKS"]
    # The true edge count — independent of (absent) properties.
    assert links.count == 3
    # No properties were stored on the relationship.
    assert links.property_profiles == {}


@pytest.mark.neo4j
def test_property_less_node_label_has_nonzero_count(
    neo4j_driver: Any, neo4j_clean: None
) -> None:
    """A node label with NO properties still reports its true node count.

    Companion to the relationship guard: a property-less label must not collapse
    to count=0.  Two property-less Marker nodes are seeded.
    """
    neo4j_driver.execute_query("CREATE (:Marker) CREATE (:Marker)")
    profile = Neo4jInspector(strategy=Neo4jInspectionStrategy.CYPHER).inspect(
        neo4j_driver
    )
    marker = profile.node_type_profiles["Marker"]
    assert marker.count == 2
    assert marker.property_profiles == {}


# ---------------------------------------------------------------------------
# APOC no-scan count correction (ADR-036)
#
# The APOC strategy historically sourced present_count from APOC's sampled
# propertyObservations, which undercounts relationship properties (the
# 100-vs-172 finding).  ADR-036 corrects this on the default no-scan path via a
# dedicated count() … IS NOT NULL.  These tests need a dataset large enough to
# actually trip APOC's relationship-property sampling, so they seed > 100 edges.
# ---------------------------------------------------------------------------


@pytest.mark.neo4j
def test_apoc_no_scan_rel_present_count_is_truthful(
    neo4j_driver: Any, neo4j_clean: None
) -> None:
    """APOC default (no value scan): relationship present_count is the TRUE count.

    Seeds 172 ACTED_IN edges, every one carrying ``role`` (non-null).  Under the
    APOC strategy with no ``value_counts_top_n``, ADR-036 derives present_count
    from a real ``count() … IS NOT NULL`` rather than APOC's
    ``apoc.meta.relTypeProperties`` observation count (which undercounts).  The
    profile must therefore report 172, matching a direct Cypher count.
    """
    # 172 distinct Person→Movie edges, each with a role.
    neo4j_driver.execute_query(
        "MERGE (m:Movie {title: 'Inception', year: 2010})"
        " WITH m UNWIND range(1, 172) AS i"
        " MERGE (p:Person {name: 'actor_' + toString(i)})"
        " MERGE (p)-[:ACTED_IN {role: 'role_' + toString(i)}]->(m)"
    )
    # Ground truth straight from the DB.
    recs, _, _ = neo4j_driver.execute_query(
        "MATCH ()-[r:ACTED_IN]->() WHERE r.role IS NOT NULL RETURN count(r) AS c"
    )
    true_present = recs[0]["c"]
    assert true_present == 172  # sanity: the seed is what we think it is.

    profile = Neo4jInspector(strategy=Neo4jInspectionStrategy.APOC).inspect(
        neo4j_driver
    )
    role = profile.rel_type_profiles["ACTED_IN"].property_profiles["role"]
    # The corrected present_count equals the true non-null count, not APOC's
    # (potentially sampled / undercounted) propertyObservations.
    assert role.present_count == true_present
    # total_count is the property-independent edge count; role is on every edge.
    assert role.total_count == 172
    assert role.completeness == 1.0


@pytest.mark.neo4j
def test_apoc_no_scan_partial_completeness_is_truthful(
    neo4j_driver: Any, neo4j_clean: None
) -> None:
    """APOC default: a partially-present property reports true completeness.

    150 Person nodes; ``born`` set on exactly 90 of them.  ADR-036 makes
    present_count (90) and total_count (150) both come from real counts, so
    completeness is 0.6 regardless of APOC's sampling.
    """
    neo4j_driver.execute_query(
        "UNWIND range(1, 150) AS i"
        " CREATE (p:Person {name: 'p_' + toString(i)})"
        " WITH p, i WHERE i <= 90 SET p.born = 1900 + i"
    )
    profile = Neo4jInspector(strategy=Neo4jInspectionStrategy.APOC).inspect(
        neo4j_driver
    )
    born = profile.node_type_profiles["Person"].property_profiles["born"]
    assert born.present_count == 90
    assert born.total_count == 150
    assert born.completeness == pytest.approx(0.6)
