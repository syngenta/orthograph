"""Tests for orthograph.graph_profile.queries.shared (vendor-neutral Cypher queries).

Pure tests — no database, no mocks.  Verify build()/materialize() and that
injected identifiers are rejected before any Cypher is produced.  These queries
moved out of the neo4j backend (E25 S1) because their Cypher is vendor-neutral.
"""

import pytest

from orthograph.cypher.bindings import NoParams
from orthograph.cypher.exceptions import CypherIdentifierError
from orthograph.graph_profile.models import CardinalityStats, EndpointLabelsRow
from orthograph.graph_profile.queries.shared import (
    InspectCardinalityQuery,
    InspectEndpointLabelsQuery,
)


def _no_params() -> NoParams:
    return NoParams()


# ---------------------------------------------------------------------------
# InspectCardinalityQuery
# ---------------------------------------------------------------------------


def test_cardinality_build_splices_label_and_rel_type() -> None:
    q = InspectCardinalityQuery(identifiers={"label": "Person", "rel_type": "ACTED_IN"})
    cypher, params = q.build(_no_params())
    assert "`Person`" in cypher
    assert "`ACTED_IN`" in cypher
    assert "min_degree" in cypher
    assert params == {}


def test_cardinality_materialize() -> None:
    q = InspectCardinalityQuery(identifiers={"label": "Person", "rel_type": "ACTED_IN"})
    row = q.materialize(
        {"min_degree": 0, "max_degree": 5, "avg_degree": 2.5, "sample_size": 100}
    )
    assert isinstance(row, CardinalityStats)
    assert row.min_degree == 0
    assert row.max_degree == 5
    assert row.avg_degree == 2.5
    assert row.sample_size == 100


def test_cardinality_injected_label_raises() -> None:
    q = InspectCardinalityQuery(
        identifiers={"label": "Person) DETACH DELETE (n //", "rel_type": "X"}
    )
    with pytest.raises(CypherIdentifierError, match="label"):
        q.build(_no_params())


def test_cardinality_injected_rel_type_raises() -> None:
    q = InspectCardinalityQuery(
        identifiers={"label": "Person", "rel_type": "X} DELETE ALL //"}
    )
    with pytest.raises(CypherIdentifierError, match="relationship type"):
        q.build(_no_params())


# ---------------------------------------------------------------------------
# InspectEndpointLabelsQuery
# ---------------------------------------------------------------------------


def test_endpoint_labels_build_splices_rel_type() -> None:
    q = InspectEndpointLabelsQuery(identifiers={"rel_type": "ACTED_IN"})
    cypher, params = q.build(_no_params())
    assert "`ACTED_IN`" in cypher
    assert "source_labels" in cypher
    assert "target_labels" in cypher
    assert params == {}


def test_endpoint_labels_materialize() -> None:
    q = InspectEndpointLabelsQuery(identifiers={"rel_type": "ACTED_IN"})
    row = q.materialize({"source_labels": ["Person"], "target_labels": ["Movie"]})
    assert isinstance(row, EndpointLabelsRow)
    assert row.source_labels == ["Person"]
    assert row.target_labels == ["Movie"]


def test_endpoint_labels_injected_rel_type_raises() -> None:
    q = InspectEndpointLabelsQuery(identifiers={"rel_type": "X} DETACH DELETE (n //"})
    with pytest.raises(CypherIdentifierError, match="relationship type"):
        q.build(_no_params())
