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
- Node property profiles: count (parity gap: always 0), mandatory heuristic
- Relationship profile: properties, count (parity gap: always 0)
- Endpoint labels (source_labels / target_labels)
- Cardinality statistics computed from confirmed source labels
- ``validate_database()`` passes for a matching model
- ``CypherIdentifierError`` raised on injection attempt
- Internal ``QueryCatalogue`` populated with expected query names

Parity gaps (documented, not tested for non-zero values)
---------------------------------------------------------
- ``NodeTypeProfile.count`` is always 0: Memgraph's
  ``schema.node_type_properties()`` yields no observation counts.
- ``RelationshipTypeProfile.count`` is always 0, same reason.
- ``PropertyProfile.present_count`` / ``.total_count`` use a mandatory
  heuristic (present=int(mandatory), total=1).
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
from orthograph.graph_definition.models import NodeModel, RelationshipModel


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
def test_node_count_is_zero_parity_gap(
    memgraph_driver: Any, memgraph_clean: None
) -> None:
    """Documented parity gap: Memgraph schema procedures yield no counts."""
    _seed(memgraph_driver)
    profile = MemgraphInspector().inspect(memgraph_driver)
    # count is always 0 — this test documents the known gap, not a bug
    assert profile.node_type_profiles["Person"].count == 0
    assert profile.node_type_profiles["Movie"].count == 0


@pytest.mark.memgraph
def test_node_property_names(memgraph_driver: Any, memgraph_clean: None) -> None:
    _seed(memgraph_driver)
    profile = MemgraphInspector().inspect(memgraph_driver)
    person_props = set(profile.node_type_profiles["Person"].property_profiles)
    movie_props = set(profile.node_type_profiles["Movie"].property_profiles)
    assert person_props == {"name", "born"}
    assert movie_props == {"title", "year"}


@pytest.mark.memgraph
def test_mandatory_property_heuristic(
    memgraph_driver: Any, memgraph_clean: None
) -> None:
    """name is required on every Person → heuristic marks it required."""
    _seed(memgraph_driver)
    profile = MemgraphInspector().inspect(memgraph_driver)
    name_pp = profile.node_type_profiles["Person"].property_profiles["name"]
    assert name_pp.is_required is True


@pytest.mark.memgraph
def test_optional_property_heuristic(
    memgraph_driver: Any, memgraph_clean: None
) -> None:
    """born is absent on Bob → heuristic marks it non-required."""
    _seed(memgraph_driver)
    profile = MemgraphInspector().inspect(memgraph_driver)
    born_pp = profile.node_type_profiles["Person"].property_profiles["born"]
    assert born_pp.is_required is False


# ---------------------------------------------------------------------------
# Seeded: relationship profiles
# ---------------------------------------------------------------------------


@pytest.mark.memgraph
def test_relationship_type_detected(memgraph_driver: Any, memgraph_clean: None) -> None:
    _seed(memgraph_driver)
    profile = MemgraphInspector().inspect(memgraph_driver)
    assert profile.relationship_types == {"ACTED_IN"}


@pytest.mark.memgraph
def test_relationship_property_names(
    memgraph_driver: Any, memgraph_clean: None
) -> None:
    _seed(memgraph_driver)
    profile = MemgraphInspector().inspect(memgraph_driver)
    props = set(profile.rel_type_profiles["ACTED_IN"].property_profiles)
    assert props == {"role"}


# ---------------------------------------------------------------------------
# Endpoint labels
# ---------------------------------------------------------------------------


@pytest.mark.memgraph
def test_endpoint_labels_populated(memgraph_driver: Any, memgraph_clean: None) -> None:
    _seed(memgraph_driver)
    profile = MemgraphInspector().inspect(memgraph_driver)
    acted_in = profile.rel_type_profiles["ACTED_IN"]
    assert acted_in.source_labels == {"Person"}
    assert acted_in.target_labels == {"Movie"}


# ---------------------------------------------------------------------------
# Cardinality
# ---------------------------------------------------------------------------


@pytest.mark.memgraph
def test_cardinality_stats_populated(
    memgraph_driver: Any, memgraph_clean: None
) -> None:
    _seed(memgraph_driver)
    profile = MemgraphInspector().inspect(memgraph_driver)
    cs = profile.rel_type_profiles["ACTED_IN"].cardinality_stats
    assert cs is not None
    assert cs.min_degree == 1
    assert cs.max_degree == 2
    assert cs.avg_degree == 1.5
    assert cs.sample_size == 2


@pytest.mark.memgraph
def test_cardinality_not_computed_against_target_label(
    memgraph_driver: Any, memgraph_clean: None
) -> None:
    """Regression: cardinality must not be computed against Movie (target)."""
    _seed(memgraph_driver)
    profile = MemgraphInspector().inspect(memgraph_driver)
    cs = profile.rel_type_profiles["ACTED_IN"].cardinality_stats
    assert cs is not None
    assert cs.min_degree > 0, (
        "min_degree == 0: cardinality was computed against the target label"
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
    """The Memgraph catalogue holds exactly the 5 expected query names."""
    from orthograph.backends.memgraph.queries import build_memgraph_catalogue

    MemgraphInspector().inspect(memgraph_driver)
    names = set(build_memgraph_catalogue().names())
    assert names == {
        "memgraph.inspect.node_properties",
        "memgraph.inspect.rel_properties",
        "memgraph.inspect.constraints",
        "memgraph.inspect.cardinality",
        "memgraph.inspect.endpoint_labels",
    }
