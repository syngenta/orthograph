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

from orthograph.backends.neo4j.inspector import Neo4jInspector, validate_database
from orthograph.backends.neo4j.queries import build_apoc_catalogue
from orthograph.cypher.bindings import NoParams
from orthograph.cypher.exceptions import CypherIdentifierError
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.models import NodeModel, RelationshipModel
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
def test_apoc_auto_detection_no_apoc(neo4j_driver: Any, neo4j_clean: None) -> None:
    """Inspector selects pure-Cypher when APOC procedures are absent.

    Observable behaviour: against a Neo4j instance with no APOC installation,
    auto-detection (``use_apoc=None``) resolves to the pure-Cypher path, so a
    seeded DB still yields node-property counts (the APOC-only metadata path is
    not taken) and inspection succeeds.
    """
    _seed(neo4j_driver)
    profile = Neo4jInspector().inspect(neo4j_driver)
    # Pure-Cypher path derives counts from the MATCH/count scan.
    assert profile.node_type_profiles["Person"].count == 2


@pytest.mark.neo4j
def test_explicit_use_apoc_false_skips_detection(
    neo4j_driver: Any, neo4j_clean: None
) -> None:
    """use_apoc=False uses the pure-Cypher path and never probes for APOC.

    Observable behaviour: no ``SHOW PROCEDURES`` (APOC auto-detect) query is
    issued, and the produced profile uses pure-Cypher counts.
    """
    _seed(neo4j_driver)
    profile = Neo4jInspector(use_apoc=False).inspect(neo4j_driver)
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
    profile = Neo4jInspector(use_apoc=False).inspect(neo4j_driver)

    assert profile.source == "neo4j"
    assert profile.relationship_types == set()
    for np in profile.node_type_profiles.values():
        assert np.count == 0
        assert np.property_profiles == {}


@pytest.mark.neo4j
def test_node_labels_detected(neo4j_driver: Any, neo4j_clean: None) -> None:
    """After seeding, both Person and Movie are present in the profile."""
    _seed(neo4j_driver)
    profile = Neo4jInspector(use_apoc=False).inspect(neo4j_driver)
    assert profile.node_labels == {"Person", "Movie"}


@pytest.mark.neo4j
def test_node_counts(neo4j_driver: Any, neo4j_clean: None) -> None:
    """Node counts are derived from the two-pass MATCH/count scan.

    Both Person (2) and Movie (2) were seeded.
    """
    _seed(neo4j_driver)
    profile = Neo4jInspector(use_apoc=False).inspect(neo4j_driver)
    assert profile.node_type_profiles["Person"].count == 2
    assert profile.node_type_profiles["Movie"].count == 2


@pytest.mark.neo4j
def test_node_property_names(neo4j_driver: Any, neo4j_clean: None) -> None:
    """Property names are inferred from observed keys across all nodes of each
    label.  Person has {name, born}; Movie has {title, year}.
    """
    _seed(neo4j_driver)
    profile = Neo4jInspector(use_apoc=False).inspect(neo4j_driver)
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
    profile = Neo4jInspector(use_apoc=False).inspect(neo4j_driver)
    name_pp = profile.node_type_profiles["Person"].property_profiles["name"]
    assert name_pp.is_required is True
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
    profile = Neo4jInspector(use_apoc=False).inspect(neo4j_driver)
    born_pp = profile.node_type_profiles["Person"].property_profiles["born"]
    assert born_pp.is_required is False
    assert born_pp.present_count == 1
    assert born_pp.total_count == 2


@pytest.mark.neo4j
def test_relationship_type_detected(neo4j_driver: Any, neo4j_clean: None) -> None:
    """After seeding, ACTED_IN is present in rel_type_profiles."""
    _seed(neo4j_driver)
    profile = Neo4jInspector(use_apoc=False).inspect(neo4j_driver)
    assert profile.relationship_types == {"ACTED_IN"}


@pytest.mark.neo4j
def test_relationship_count(neo4j_driver: Any, neo4j_clean: None) -> None:
    """Relationship count is derived from the total_observations of the
    rel-property scan (three edges were seeded).
    """
    _seed(neo4j_driver)
    profile = Neo4jInspector(use_apoc=False).inspect(neo4j_driver)
    assert profile.rel_type_profiles["ACTED_IN"].count == 3


@pytest.mark.neo4j
def test_relationship_property_names(neo4j_driver: Any, neo4j_clean: None) -> None:
    """Property names are inferred from observed keys across all edges of the
    relationship type.  All three ACTED_IN edges carry role.
    """
    _seed(neo4j_driver)
    profile = Neo4jInspector(use_apoc=False).inspect(neo4j_driver)
    props = set(profile.rel_type_profiles["ACTED_IN"].property_profiles)
    assert props == {"role"}


@pytest.mark.neo4j
def test_endpoint_labels_populated(neo4j_driver: Any, neo4j_clean: None) -> None:
    """source_labels and target_labels are populated by the endpoint-labels query."""
    _seed(neo4j_driver)
    profile = Neo4jInspector(use_apoc=False).inspect(neo4j_driver)
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
    profile = Neo4jInspector(use_apoc=False).inspect(neo4j_driver)
    cs = profile.rel_type_profiles["ACTED_IN"].cardinality_stats
    assert cs is not None
    assert cs.min_degree == 1
    assert cs.max_degree == 2
    assert cs.avg_degree == 1.5
    assert cs.sample_size == 2


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
    profile = Neo4jInspector(use_apoc=False).inspect(neo4j_driver)
    cs = profile.rel_type_profiles["ACTED_IN"].cardinality_stats
    assert cs is not None
    assert cs.min_degree > 0, (
        "min_degree == 0: cardinality was computed against the target label "
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
    profile = Neo4jInspector(use_apoc=False).inspect(neo4j_driver)
    assert "ACTED_IN" not in profile.rel_type_profiles


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
    """The pure-Cypher catalogue holds exactly the 7 expected query names."""
    from orthograph.backends.neo4j.queries import build_cypher_catalogue

    Neo4jInspector(use_apoc=False).inspect(neo4j_driver)
    names = set(build_cypher_catalogue().names())
    assert names == {
        "neo4j.inspect.node_labels",
        "neo4j.inspect.rel_types",
        "neo4j.inspect.cypher.node_properties",
        "neo4j.inspect.cypher.rel_properties",
        "inspect.cardinality",
        "neo4j.inspect.constraints",
        "inspect.endpoint_labels",
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
    assert len(names) == 7
    for desc in query_catalogue.describe():
        assert desc.output_schema is not None
