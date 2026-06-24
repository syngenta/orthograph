"""Tests for orthograph.backends.memgraph.inspector."""

from typing import Any
from unittest.mock import MagicMock

import pytest

from orthograph.backends.memgraph.inspector import MemgraphInspector, validate_database
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
from tests.backends.conftest import (
    mock_execute_query,
    ordered_side_effect_with_counts,
)
from tests.fixtures.conftest import ActedIn, Movie, Person


# --- Fixtures ---


class Reading(NodeModel):
    """A node whose ``value`` is declared required (no default)."""

    __label__ = "Reading"
    __uid_field__ = "value"
    value: int


@pytest.fixture()
def graph_definition() -> GraphDefinition:
    return GraphDefinition(
        name="Film",
        node_types=[Person, Movie],
        relationship_types=[ActedIn],
    )


# --- inspect produces profile ---


def test_memgraph_inspect_produces_profile() -> None:
    driver = MagicMock()

    responses = [
        # constraints (read before profiles so they can be cross-referenced):
        # UNIQUE on Person.name (no presence guarantee) and EXISTS on
        # Person.age (guarantees presence).
        mock_execute_query(
            [
                {
                    "constraint type": "UNIQUE",
                    "entity type": "NODE",
                    "label": "Person",
                    "properties": ["name"],
                },
                {
                    "constraint type": "EXISTS",
                    "entity type": "NODE",
                    "label": "Person",
                    "properties": ["age"],
                },
            ],
        ),
        # node_properties
        mock_execute_query(
            [
                {
                    "nodeType": ":`Person`",
                    "nodeLabels": ["Person"],
                    "mandatory": True,
                    "propertyName": "name",
                    "propertyTypes": ["String"],
                },
                {
                    "nodeType": ":`Person`",
                    "nodeLabels": ["Person"],
                    "mandatory": True,
                    "propertyName": "age",
                    "propertyTypes": ["Int"],
                },
                {
                    "nodeType": ":`Movie`",
                    "nodeLabels": ["Movie"],
                    "mandatory": True,
                    "propertyName": "title",
                    "propertyTypes": ["String"],
                },
            ],
        ),
        # rel_properties
        mock_execute_query(
            [
                {
                    "relType": ":`ACTED_IN`",
                    "mandatory": True,
                    "propertyName": "role",
                    "propertyTypes": ["String"],
                },
            ],
        ),
        # endpoint_labels for ACTED_IN (queried before cardinality)
        mock_execute_query(
            [{"source_labels": ["Person"], "target_labels": ["Movie"]}],
        ),
        # cardinality for ACTED_IN against Person
        mock_execute_query(
            [
                {
                    "min_degree": 1,
                    "max_degree": 3,
                    "avg_degree": 2.0,
                    "sample_size": 10,
                },
            ],
        ),
    ]

    driver.execute_query.side_effect = ordered_side_effect_with_counts(responses)

    inspector = MemgraphInspector()
    profile = inspector.inspect(driver)

    assert profile.source == "memgraph"
    assert profile.node_labels == {"Person", "Movie"}
    assert profile.relationship_types == {"ACTED_IN"}

    # Check node profiles
    person = profile.node_type_profiles["Person"]
    assert "name" in person.property_profiles
    assert "age" in person.property_profiles
    assert person.property_profiles["name"].observed_types == ["String"]
    # UNIQUE does not guarantee presence; EXISTS does.
    assert person.property_profiles["name"].constraint_required is False
    assert person.property_profiles["age"].constraint_required is True

    movie = profile.node_type_profiles["Movie"]
    assert "title" in movie.property_profiles
    # No covering constraint on Movie.title → inspected, none found.
    assert movie.property_profiles["title"].constraint_required is False

    # Check rel profile
    acted_in = profile.rel_type_profiles["ACTED_IN"]
    assert "role" in acted_in.property_profiles
    assert acted_in.property_profiles["role"].constraint_required is False

    # source/target labels populated
    assert acted_in.source_labels == {"Person"}
    assert acted_in.target_labels == {"Movie"}
    assert acted_in.cardinality_stats is not None
    assert acted_in.cardinality_stats.count == 10

    # Constraints
    assert len(profile.constraints) == 2
    assert {c.constraint_type for c in profile.constraints} == {"UNIQUE", "EXISTS"}


# --- value_distribution ---


def test_memgraph_value_distribution_is_none() -> None:
    """Memgraph inspector: value_distribution=None when the scan is disabled."""
    driver = MagicMock()
    responses = [
        # constraints
        mock_execute_query([], []),
        # node_properties
        mock_execute_query(
            [
                {
                    "nodeType": ":`Person`",
                    "nodeLabels": ["Person"],
                    "mandatory": True,
                    "propertyName": "name",
                    "propertyTypes": ["String"],
                },
            ],
        ),
        # rel_properties
        mock_execute_query([], []),
    ]

    driver.execute_query.side_effect = ordered_side_effect_with_counts(responses)

    profile = MemgraphInspector().inspect(driver)
    name = profile.node_type_profiles["Person"].property_profiles["name"]
    assert name.value_distribution is None
    assert name.observed_type_counts == {}


# --- observed_type_counts (E46.3, value scan) ---


def _value_scan_driver(
    node_property_rows: list[dict[str, Any]],
    type_count_rows: list[dict[str, Any]],
    histogram_rows: list[dict[str, Any]],
    rel_property_rows: list[dict[str, Any]] | None = None,
    entity_count: int = 1000,
) -> MagicMock:
    """A driver that dispatches the value-scan queries on their Cypher text.

    The ordered schema/constraint/cardinality reads return canned rows; the
    per-property ``valueType`` (type counts) and ``toStringOrNull`` (histogram)
    scans are matched on the Cypher so the test does not depend on call order.
    ``entity_count`` is the property-independent ``count()`` total (the honest
    ``completeness`` / ``total_count`` denominator — E46.3).
    """
    driver = MagicMock()
    ordered = iter(
        [
            mock_execute_query([], []),  # constraints
            mock_execute_query(node_property_rows),  # node_properties
            mock_execute_query(rel_property_rows or [], []),  # rel_properties
        ]
    )

    def side_effect(*args: Any, **kwargs: Any) -> Any:
        cypher = args[0] if args else kwargs.get("query", "")
        if "count(n) AS count" in cypher or "count(r) AS count" in cypher:
            # Property-independent entity count (E46.3): the honest completeness
            # denominator.  Defaults high so total_count >= present_count for
            # tests that do not exercise completeness.
            return mock_execute_query([{"count": entity_count}], ["count"])
        if "valueType(" in cypher:
            return mock_execute_query(type_count_rows)
        if "toStringOrNull(" in cypher:
            return mock_execute_query(histogram_rows)
        result = next(ordered, None)
        if result is not None:
            return result
        # endpoint-labels / cardinality / partitioned queries issued during rel
        # enrichment — not under test here, answer with empty rows.
        return mock_execute_query([], [])

    driver.execute_query.side_effect = side_effect
    return driver


def test_memgraph_observed_type_counts_populated_from_scan() -> None:
    """With value_counts_top_n set, the scan populates observed_type_counts."""
    driver = _value_scan_driver(
        node_property_rows=[
            {
                "nodeType": ":`Reading`",
                "nodeLabels": ["Reading"],
                "mandatory": True,
                "propertyName": "value",
                "propertyTypes": ["Int", "Float"],
            },
        ],
        type_count_rows=[
            {"type_name": "INTEGER", "type_count": 95},
            {"type_name": "FLOAT", "type_count": 5},
        ],
        histogram_rows=[{"value": "1", "value_count": 50}],
    )

    profile = MemgraphInspector(value_counts_top_n=10).inspect(driver)
    value = profile.node_type_profiles["Reading"].property_profiles["value"]

    assert value.observed_type_counts == {"Int": 95, "Float": 5}


def test_memgraph_observed_type_counts_subset_of_observed_types() -> None:
    """ADR-035 §3: set(observed_type_counts) ⊆ set(observed_types)."""
    driver = _value_scan_driver(
        node_property_rows=[
            {
                "nodeType": ":`Reading`",
                "nodeLabels": ["Reading"],
                "mandatory": True,
                "propertyName": "value",
                "propertyTypes": ["Int", "Float"],
            },
        ],
        type_count_rows=[
            {"type_name": "INTEGER", "type_count": 95},
            {"type_name": "FLOAT", "type_count": 5},
        ],
        histogram_rows=[{"value": "1", "value_count": 50}],
    )

    profile = MemgraphInspector(value_counts_top_n=10).inspect(driver)
    value = profile.node_type_profiles["Reading"].property_profiles["value"]

    assert set(value.observed_type_counts) <= set(value.observed_types)


def test_memgraph_value_scan_reconciliation_invariant() -> None:
    """ADR-035 §2: sum(type counts) == value_distribution.count == present_count."""
    driver = _value_scan_driver(
        node_property_rows=[
            {
                "nodeType": ":`Reading`",
                "nodeLabels": ["Reading"],
                "mandatory": True,
                "propertyName": "value",
                "propertyTypes": ["Int"],
            },
        ],
        type_count_rows=[{"type_name": "INTEGER", "type_count": 100}],
        histogram_rows=[
            {"value": "1", "value_count": 60},
            {"value": "2", "value_count": 40},
        ],
    )

    profile = MemgraphInspector(value_counts_top_n=10).inspect(driver)
    value = profile.node_type_profiles["Reading"].property_profiles["value"]

    total = sum(value.observed_type_counts.values())
    assert value.value_distribution is not None
    assert total == value.value_distribution.count == value.present_count == 100


def test_memgraph_value_scan_histogram_truncates_against_type_total() -> None:
    """A scalar histogram short of the type total folds the remainder into other_count.

    List-typed values are dropped by toStringOrNull (scalar-only histogram), so
    the histogram total can be below the authoritative present_count; the
    inspector reconciles via other_count, type counts stay exact.
    """
    driver = _value_scan_driver(
        node_property_rows=[
            {
                "nodeType": ":`Reading`",
                "nodeLabels": ["Reading"],
                "mandatory": True,
                "propertyName": "value",
                "propertyTypes": ["Int", "List[Any]"],
            },
        ],
        # 100 non-null values total (90 ints + 10 lists).
        type_count_rows=[
            {"type_name": "INTEGER", "type_count": 90},
            {"type_name": "LIST", "type_count": 10},
        ],
        # Only the scalar (int) values are histogrammed → sums to 90.
        histogram_rows=[
            {"value": "1", "value_count": 50},
            {"value": "2", "value_count": 40},
        ],
    )

    profile = MemgraphInspector(value_counts_top_n=10).inspect(driver)
    value = profile.node_type_profiles["Reading"].property_profiles["value"]

    assert value.observed_type_counts == {"Int": 90, "List[Any]": 10}
    dist = value.value_distribution
    assert dist is not None
    assert dist.count == 100
    assert dist.sample_complete is False
    assert dist.other_count == 10  # 100 - 90 scalar values histogrammed


def test_memgraph_value_scan_on_relationships() -> None:
    """Relationship properties carry type counts from the scan too."""
    driver = _value_scan_driver(
        node_property_rows=[],
        type_count_rows=[{"type_name": "STRING", "type_count": 3}],
        histogram_rows=[{"value": "Lead", "value_count": 1}],
        rel_property_rows=[
            {
                "relType": ":`ACTED_IN`",
                "mandatory": True,
                "propertyName": "role",
                "propertyTypes": ["String"],
            },
        ],
    )

    profile = MemgraphInspector(value_counts_top_n=10).inspect(driver)
    role = profile.rel_type_profiles["ACTED_IN"].property_profiles["role"]

    assert role.observed_type_counts == {"String": 3}


def test_memgraph_value_scan_disabled_yields_empty_counts() -> None:
    """Without value_counts_top_n, observed_type_counts == {} (byte-for-byte today)."""
    driver = _value_scan_driver(
        node_property_rows=[
            {
                "nodeType": ":`Reading`",
                "nodeLabels": ["Reading"],
                "mandatory": True,
                "propertyName": "value",
                "propertyTypes": ["Int"],
            },
        ],
        type_count_rows=[{"type_name": "INTEGER", "type_count": 100}],
        histogram_rows=[{"value": "1", "value_count": 100}],
    )

    profile = MemgraphInspector().inspect(driver)  # no value_counts_top_n
    value = profile.node_type_profiles["Reading"].property_profiles["value"]

    assert value.observed_type_counts == {}
    assert value.value_distribution is None


def test_memgraph_value_scan_parity_with_networkx() -> None:
    """Same logical graph → equivalent observed_type_counts across backends.

    Parity is on semantics: NetworkX names types by Python (``int``), Memgraph by
    its schema vocabulary (``Int``).  The per-type split (the counts) must match.
    """
    import networkx as nx

    from orthograph.backends.networkx.inspector import NetworkxInspector

    g: nx.MultiDiGraph[str] = nx.MultiDiGraph()
    g.add_node("a", __label__="Reading", value=1)
    g.add_node("b", __label__="Reading", value=2)
    g.add_node("c", __label__="Reading", value=3)
    g.add_node("d", __label__="Reading", value=4.5)

    nx_profile = NetworkxInspector(value_counts_top_n=10).inspect(g)
    nx_counts = (
        nx_profile.node_type_profiles["Reading"]
        .property_profiles["value"]
        .observed_type_counts
    )
    assert nx_counts == {"int": 3, "float": 1}

    driver = _value_scan_driver(
        node_property_rows=[
            {
                "nodeType": ":`Reading`",
                "nodeLabels": ["Reading"],
                "mandatory": True,
                "propertyName": "value",
                "propertyTypes": ["Int", "Float"],
            },
        ],
        type_count_rows=[
            {"type_name": "INTEGER", "type_count": 3},
            {"type_name": "FLOAT", "type_count": 1},
        ],
        histogram_rows=[
            {"value": "1", "value_count": 1},
            {"value": "2", "value_count": 1},
            {"value": "3", "value_count": 1},
            {"value": "4.5", "value_count": 1},
        ],
    )
    mg_profile = MemgraphInspector(value_counts_top_n=10).inspect(driver)
    mg_counts = (
        mg_profile.node_type_profiles["Reading"]
        .property_profiles["value"]
        .observed_type_counts
    )

    # Same per-type split (sorted by count); backend-specific names map 1:1.
    assert sorted(mg_counts.values(), reverse=True) == sorted(
        nx_counts.values(), reverse=True
    )
    assert mg_counts == {"Int": 3, "Float": 1}


# --- completeness regression (E46.3 review issue 1) ---


def test_memgraph_value_scan_does_not_fabricate_completeness() -> None:
    """total_count is the true entity count, not derived from present_count.

    Regression for the bug where ``total_count = max(1, present_count)`` forced
    ``completeness == 1.0`` for every present property.  Here 80 of 100 entities
    carry the value, so completeness must be 0.8 — never 1.0.
    """
    driver = _value_scan_driver(
        node_property_rows=[
            {
                "nodeType": ":`Reading`",
                "nodeLabels": ["Reading"],
                "mandatory": False,
                "propertyName": "value",
                "propertyTypes": ["Int"],
            },
        ],
        type_count_rows=[{"type_name": "INTEGER", "type_count": 80}],
        histogram_rows=[{"value": "1", "value_count": 80}],
        entity_count=100,  # 100 Reading nodes, only 80 carry `value`
    )

    profile = MemgraphInspector(value_counts_top_n=10).inspect(driver)
    value = profile.node_type_profiles["Reading"].property_profiles["value"]

    assert value.present_count == 80
    assert value.total_count == 100
    assert value.completeness == 0.8
    # The label instance count is the truthful entity total (no longer 0).
    assert profile.node_type_profiles["Reading"].count == 100


def test_memgraph_value_scan_preserves_property_incomplete_warning() -> None:
    """A required-but-unconstrained property present on a subset still warns.

    End-to-end regression: with the fabricated ``completeness == 1.0`` the
    ``PROPERTY_INCOMPLETE`` WARNING was silently suppressed when the value scan
    ran.  The scan must be enabled (``value_counts_top_n``) to exercise that
    exact path — ``validate_database`` alone runs no scan.
    """
    from orthograph.comparison.engine import compare_profile_to_definition

    gd = GraphDefinition(name="Readings", node_types=[Reading], relationship_types=[])

    driver = _value_scan_driver(
        node_property_rows=[
            {
                "nodeType": ":`Reading`",
                "nodeLabels": ["Reading"],
                # No DB presence constraint (mandatory False) — the declared
                # model requires `value`, but only 80/100 nodes carry it.
                "mandatory": False,
                "propertyName": "value",
                "propertyTypes": ["Int"],
            },
        ],
        type_count_rows=[{"type_name": "INTEGER", "type_count": 80}],
        histogram_rows=[{"value": "1", "value_count": 80}],
        entity_count=100,
    )

    profile = MemgraphInspector(value_counts_top_n=10).inspect(driver)
    result = compare_profile_to_definition(profile, gd)

    incomplete = [w for w in result.warnings if w.code == "PROPERTY_INCOMPLETE"]
    assert len(incomplete) == 1, (
        "PROPERTY_INCOMPLETE must fire for a required property present on only "
        "80/100 entities (regression: fabricated completeness==1.0 suppressed it)."
    )
    assert incomplete[0].entity_id == "Reading.value"


# --- validate_database ---


def test_memgraph_validate_database(graph_definition: GraphDefinition) -> None:
    driver = MagicMock()

    responses = [
        # constraints (read before profiles so they can be cross-referenced)
        mock_execute_query([], []),
        # node_properties
        mock_execute_query(
            [
                {
                    "nodeType": ":`Person`",
                    "nodeLabels": ["Person"],
                    "mandatory": True,
                    "propertyName": "name",
                    "propertyTypes": ["String"],
                },
                {
                    "nodeType": ":`Person`",
                    "nodeLabels": ["Person"],
                    "mandatory": True,
                    "propertyName": "age",
                    "propertyTypes": ["Int"],
                },
                {
                    "nodeType": ":`Person`",
                    "nodeLabels": ["Person"],
                    "mandatory": False,
                    "propertyName": "email",
                    "propertyTypes": ["String"],
                },
                {
                    "nodeType": ":`Movie`",
                    "nodeLabels": ["Movie"],
                    "mandatory": True,
                    "propertyName": "title",
                    "propertyTypes": ["String"],
                },
                {
                    "nodeType": ":`Movie`",
                    "nodeLabels": ["Movie"],
                    "mandatory": True,
                    "propertyName": "year",
                    "propertyTypes": ["Int"],
                },
            ],
        ),
        # rel_properties
        mock_execute_query(
            [
                {
                    "relType": ":`ACTED_IN`",
                    "mandatory": True,
                    "propertyName": "role",
                    "propertyTypes": ["String"],
                },
            ],
        ),
        # endpoint_labels for ACTED_IN (parity query — before cardinality)
        mock_execute_query(
            [{"source_labels": ["Person"], "target_labels": ["Movie"]}],
        ),
        # cardinality for ACTED_IN against Person
        mock_execute_query(
            [
                {
                    "min_degree": 0,
                    "max_degree": 5,
                    "avg_degree": 2.0,
                    "sample_size": 50,
                },
            ],
        ),
    ]

    driver.execute_query.side_effect = ordered_side_effect_with_counts(responses)

    result = validate_database(driver, graph_definition)
    assert result.is_valid, [str(e) for e in result.errors]


# --- partitioned_cardinality ---


def _conditional_operation_sample_definition() -> GraphDefinition:
    """The ADR-029 deciding scenario: HAS_OUTPUT with conditional source side."""

    class Operation(NodeModel):
        __label__ = "Operation"
        __uid_field__ = "uid"
        uid: str
        kind: str

    class Sample(NodeModel):
        __label__ = "Sample"
        __uid_field__ = "uid"
        uid: str
        kind: str

    class HasOutput(RelationshipModel):
        __label__ = "HAS_OUTPUT"
        __source_label__ = "Operation"
        __target_label__ = "Sample"
        __source_cardinality__ = ConditionalCardinality(
            rules=(
                ConditionalRule(
                    source=PropMatch({"kind": "subsampling"}),
                    target=PropMatch({"kind": "subsampling"}),
                    spec=CardinalitySpec(min=1, max=2),
                ),
            ),
            default="0..*",
        )
        __target_cardinality__ = "0..*"

    return GraphDefinition(
        name="OperationSample",
        node_types=[Operation, Sample],
        relationship_types=[HasOutput],
    )


def _partitioned_row(
    sk: str | None,
    tk: str | None,
    min_degree: int,
    max_degree: int,
    avg_degree: float,
    sample_size: int,
) -> dict[str, Any]:
    return {
        "sk": sk,
        "tk": tk,
        "min_degree": min_degree,
        "max_degree": max_degree,
        "avg_degree": avg_degree,
        "sample_size": sample_size,
    }


def test_memgraph_partitioned_cardinality_assembles_expected_partitions() -> None:
    """Given grouped-query rows, MemgraphInspector assembles partitioned_cardinality.

    Parity note: variance is None on DB side (Cypher does not compute it).
    Parity assertions check min/max/count only.
    """
    driver = MagicMock()
    gd = _conditional_operation_sample_definition()

    responses = [
        # constraints
        mock_execute_query([], []),
        # node_properties
        mock_execute_query(
            [
                {
                    "nodeType": ":`Operation`",
                    "nodeLabels": ["Operation"],
                    "mandatory": True,
                    "propertyName": "kind",
                    "propertyTypes": ["String"],
                },
                {
                    "nodeType": ":`Sample`",
                    "nodeLabels": ["Sample"],
                    "mandatory": True,
                    "propertyName": "kind",
                    "propertyTypes": ["String"],
                },
            ]
        ),
        # rel_properties for HAS_OUTPUT (none)
        mock_execute_query(
            [
                {
                    "relType": ":`HAS_OUTPUT`",
                    "mandatory": False,
                    "propertyName": None,
                    "propertyTypes": [],
                }
            ]
        ),
        # endpoint_labels for HAS_OUTPUT
        mock_execute_query(
            [{"source_labels": ["Operation"], "target_labels": ["Sample"]}]
        ),
        # aggregate cardinality for HAS_OUTPUT against Operation
        mock_execute_query(
            [{"min_degree": 1, "max_degree": 3, "avg_degree": 2.0, "sample_size": 1}]
        ),
        # partitioned cardinality for HAS_OUTPUT against Operation
        mock_execute_query(
            [
                _partitioned_row("subsampling", "subsampling", 2, 2, 2.0, 1),
                _partitioned_row("subsampling", "nothing", 1, 1, 1.0, 1),
            ]
        ),
    ]

    driver.execute_query.side_effect = ordered_side_effect_with_counts(responses)

    profile = MemgraphInspector().inspect(driver, graph_definition=gd)
    has_output = profile.rel_type_profiles["HAS_OUTPUT"]

    partitions = has_output.source_partitioned_cardinality
    assert partitions is not None

    sub_sub = str(PartitionKey(source_value="subsampling", target_value="subsampling"))
    sub_nothing = str(PartitionKey(source_value="subsampling", target_value="nothing"))
    assert set(partitions) == {sub_sub, sub_nothing}

    assert partitions[sub_sub].min == 2
    assert partitions[sub_sub].max == 2
    assert partitions[sub_sub].count == 1
    assert partitions[sub_sub].variance is None

    assert partitions[sub_nothing].min == 1
    assert partitions[sub_nothing].max == 1
    assert partitions[sub_nothing].count == 1


def test_memgraph_partitioned_cardinality_zero_degree_rows_suppressed() -> None:
    """Zero-degree rows from OPTIONAL MATCH are suppressed (parity with NetworkX)."""
    driver = MagicMock()
    gd = _conditional_operation_sample_definition()

    responses = [
        mock_execute_query([], []),  # constraints
        mock_execute_query(
            [
                {
                    "nodeType": ":`Operation`",
                    "nodeLabels": ["Operation"],
                    "mandatory": True,
                    "propertyName": "kind",
                    "propertyTypes": ["String"],
                },
                {
                    "nodeType": ":`Sample`",
                    "nodeLabels": ["Sample"],
                    "mandatory": True,
                    "propertyName": "kind",
                    "propertyTypes": ["String"],
                },
            ]
        ),
        mock_execute_query(
            [
                {
                    "relType": ":`HAS_OUTPUT`",
                    "mandatory": False,
                    "propertyName": None,
                    "propertyTypes": [],
                }
            ]
        ),
        mock_execute_query(
            [{"source_labels": ["Operation"], "target_labels": ["Sample"]}]
        ),
        mock_execute_query(
            [{"min_degree": 2, "max_degree": 2, "avg_degree": 2.0, "sample_size": 1}]
        ),
        # Zero-degree null-target row must be suppressed.
        mock_execute_query(
            [
                _partitioned_row("subsampling", "subsampling", 2, 2, 2.0, 1),
                _partitioned_row("subsampling", None, 0, 0, 0.0, 1),
            ]
        ),
    ]

    driver.execute_query.side_effect = ordered_side_effect_with_counts(responses)

    profile = MemgraphInspector().inspect(driver, graph_definition=gd)
    partitions = profile.rel_type_profiles["HAS_OUTPUT"].source_partitioned_cardinality

    assert partitions is not None
    sub_sub = str(PartitionKey(source_value="subsampling", target_value="subsampling"))
    assert set(partitions) == {sub_sub}


def test_memgraph_partitioned_cardinality_constant_type_is_none() -> None:
    """A non-conditional relationship type leaves both partitioned fields None."""
    driver = MagicMock()
    gd = GraphDefinition(
        name="Film",
        node_types=[Person, Movie],
        relationship_types=[ActedIn],
    )

    responses = [
        mock_execute_query([], []),  # constraints
        mock_execute_query(
            [
                {
                    "nodeType": ":`Person`",
                    "nodeLabels": ["Person"],
                    "mandatory": True,
                    "propertyName": "name",
                    "propertyTypes": ["String"],
                },
                {
                    "nodeType": ":`Movie`",
                    "nodeLabels": ["Movie"],
                    "mandatory": True,
                    "propertyName": "title",
                    "propertyTypes": ["String"],
                },
            ]
        ),
        mock_execute_query(
            [
                {
                    "relType": ":`ACTED_IN`",
                    "mandatory": True,
                    "propertyName": "role",
                    "propertyTypes": ["String"],
                }
            ]
        ),
        mock_execute_query([{"source_labels": ["Person"], "target_labels": ["Movie"]}]),
        mock_execute_query(
            [{"min_degree": 1, "max_degree": 2, "avg_degree": 1.5, "sample_size": 10}]
        ),
        # No partitioned cardinality query for non-conditional types.
    ]

    driver.execute_query.side_effect = ordered_side_effect_with_counts(responses)

    profile = MemgraphInspector().inspect(driver, graph_definition=gd)
    acted_in = profile.rel_type_profiles["ACTED_IN"]

    assert acted_in.source_partitioned_cardinality is None
    assert acted_in.target_partitioned_cardinality is None
    assert acted_in.cardinality_stats is not None


def test_memgraph_partitioned_cardinality_no_definition_is_none() -> None:
    """Without a GraphDefinition, both partitioned fields stay None (graceful)."""
    driver = MagicMock()

    responses = [
        mock_execute_query([], []),
        mock_execute_query(
            [
                {
                    "nodeType": ":`Person`",
                    "nodeLabels": ["Person"],
                    "mandatory": True,
                    "propertyName": "name",
                    "propertyTypes": ["String"],
                }
            ]
        ),
        mock_execute_query(
            [
                {
                    "relType": ":`ACTED_IN`",
                    "mandatory": True,
                    "propertyName": "role",
                    "propertyTypes": ["String"],
                }
            ]
        ),
        mock_execute_query([{"source_labels": ["Person"], "target_labels": []}]),
        mock_execute_query(
            [{"min_degree": 1, "max_degree": 1, "avg_degree": 1.0, "sample_size": 5}]
        ),
    ]

    driver.execute_query.side_effect = ordered_side_effect_with_counts(responses)

    profile = MemgraphInspector().inspect(driver)
    assert profile.rel_type_profiles["ACTED_IN"].source_partitioned_cardinality is None
    assert profile.rel_type_profiles["ACTED_IN"].target_partitioned_cardinality is None


def test_memgraph_partitioned_cardinality_parity_with_networkx() -> None:
    """Deciding-scenario partitions match the NetworkX reference (min/max/count).

    Parity note: variance excluded from comparison (None from DB, computed by NX).
    """
    import networkx as nx

    from orthograph.backends.networkx.inspector import NetworkxInspector

    gd = _conditional_operation_sample_definition()

    g: nx.MultiDiGraph[str] = nx.MultiDiGraph()
    g.add_node("op1", __label__="Operation", uid="op1", kind="subsampling")
    g.add_node("s1", __label__="Sample", uid="s1", kind="subsampling")
    g.add_node("s2", __label__="Sample", uid="s2", kind="subsampling")
    g.add_node("s3", __label__="Sample", uid="s3", kind="nothing")
    g.add_edge("op1", "s1", __label__="HAS_OUTPUT")
    g.add_edge("op1", "s2", __label__="HAS_OUTPUT")
    g.add_edge("op1", "s3", __label__="HAS_OUTPUT")

    nx_profile = NetworkxInspector().inspect(g, graph_definition=gd)
    nx_partitions = nx_profile.rel_type_profiles[
        "HAS_OUTPUT"
    ].source_partitioned_cardinality
    assert nx_partitions is not None

    driver = MagicMock()
    responses = [
        mock_execute_query([], []),  # constraints
        mock_execute_query(
            [
                {
                    "nodeType": ":`Operation`",
                    "nodeLabels": ["Operation"],
                    "mandatory": True,
                    "propertyName": "kind",
                    "propertyTypes": ["String"],
                },
                {
                    "nodeType": ":`Sample`",
                    "nodeLabels": ["Sample"],
                    "mandatory": True,
                    "propertyName": "kind",
                    "propertyTypes": ["String"],
                },
            ]
        ),
        mock_execute_query(
            [
                {
                    "relType": ":`HAS_OUTPUT`",
                    "mandatory": False,
                    "propertyName": None,
                    "propertyTypes": [],
                }
            ]
        ),
        mock_execute_query(
            [{"source_labels": ["Operation"], "target_labels": ["Sample"]}]
        ),
        mock_execute_query(
            [{"min_degree": 1, "max_degree": 3, "avg_degree": 2.0, "sample_size": 1}]
        ),
        mock_execute_query(
            [
                _partitioned_row("subsampling", "subsampling", 2, 2, 2.0, 1),
                _partitioned_row("subsampling", "nothing", 1, 1, 1.0, 1),
            ]
        ),
    ]

    driver.execute_query.side_effect = ordered_side_effect_with_counts(responses)

    mg_profile = MemgraphInspector().inspect(driver, graph_definition=gd)
    mg_partitions = mg_profile.rel_type_profiles[
        "HAS_OUTPUT"
    ].source_partitioned_cardinality
    assert mg_partitions is not None

    assert set(mg_partitions) == set(nx_partitions)

    for key in nx_partitions:
        nx_p = nx_partitions[key]
        db_p = mg_partitions[key]
        assert db_p.min == nx_p.min, f"min mismatch for {key!r}"
        assert db_p.max == nx_p.max, f"max mismatch for {key!r}"
        assert db_p.count == nx_p.count, f"count mismatch for {key!r}"


# --- Bug regression tests ---


def test_memgraph_validate_database_forwards_graph_definition() -> None:
    """validate_database forwards graph_definition so partitioned_cardinality is set.

    Regression for the bug where validate_database called inspect() without
    graph_definition, silently leaving partitioned_cardinality=None.
    """
    driver = MagicMock()
    gd = _conditional_operation_sample_definition()

    responses = [
        mock_execute_query([], []),  # constraints
        mock_execute_query(
            [
                {
                    "nodeType": ":`Operation`",
                    "nodeLabels": ["Operation"],
                    "mandatory": True,
                    "propertyName": "kind",
                    "propertyTypes": ["String"],
                },
                {
                    "nodeType": ":`Sample`",
                    "nodeLabels": ["Sample"],
                    "mandatory": True,
                    "propertyName": "kind",
                    "propertyTypes": ["String"],
                },
            ]
        ),
        mock_execute_query(
            [
                {
                    "relType": ":`HAS_OUTPUT`",
                    "mandatory": False,
                    "propertyName": None,
                    "propertyTypes": [],
                }
            ]
        ),
        mock_execute_query(
            [{"source_labels": ["Operation"], "target_labels": ["Sample"]}]
        ),
        mock_execute_query(
            [{"min_degree": 1, "max_degree": 3, "avg_degree": 2.0, "sample_size": 1}]
        ),
        mock_execute_query(
            [_partitioned_row("subsampling", "subsampling", 2, 2, 2.0, 1)]
        ),
    ]

    # Property-independent count() queries are served out of band (E46.3); the
    # ordered responses cover the schema/cardinality/partitioned reads.  Track
    # whether the partitioned query was issued instead of asserting on a raw
    # driver-call count (which the count() queries would otherwise inflate).
    ordered = ordered_side_effect_with_counts(responses)
    partitioned_issued = False

    def side_effect(*args: Any, **kwargs: Any) -> Any:
        nonlocal partitioned_issued
        cypher = args[0] if args else kwargs.get("query_", kwargs.get("query", ""))
        if "AS sk" in cypher and "AS tk" in cypher:
            partitioned_issued = True
        return ordered(*args, **kwargs)

    driver.execute_query.side_effect = side_effect

    from orthograph.backends.memgraph.inspector import (
        validate_database as memgraph_validate,
    )

    memgraph_validate(driver, gd)
    # The partitioned query must have been issued (it is the 6th ordered read).
    assert partitioned_issued, (
        "Expected the partitioned cardinality query to be issued. "
        "validate_database likely did not forward graph_definition."
    )


def test_memgraph_unprocessable_first_side_falls_through_to_processable_second() -> (
    None
):
    """Unprocessable first conditional side does not prevent second side from running.

    Regression for the bug where break fired after any ConditionalCardinality,
    even when _extract_discriminators returned None (multi-property discriminator).
    """

    class Producer(NodeModel):
        __label__ = "Producer"
        __uid_field__ = "uid"
        uid: str
        kind: str
        tier: str  # second property — makes source discriminator multi-key

    class Artifact(NodeModel):
        __label__ = "Artifact"
        __uid_field__ = "uid"
        uid: str
        kind: str

    class Produces(RelationshipModel):
        __label__ = "PRODUCES"
        __source_label__ = "Producer"
        __target_label__ = "Artifact"
        # Source side: multi-property → _extract_discriminators → None (unprocessable)
        __source_cardinality__ = ConditionalCardinality(
            rules=(
                ConditionalRule(
                    source=PropMatch({"kind": "heavy", "tier": "1"}),
                    target=PropMatch({"kind": "final"}),
                    spec=CardinalitySpec(min=1, max=3),
                ),
            ),
            default="0..*",
        )
        # Target side: single-property → processable
        __target_cardinality__ = ConditionalCardinality(
            rules=(
                ConditionalRule(
                    source=PropMatch({"kind": "heavy"}),
                    target=PropMatch({"kind": "final"}),
                    spec=CardinalitySpec(min=2, max=2),
                ),
            ),
            default="0..*",
        )

    gd = GraphDefinition(
        name="ProducerArtifact",
        node_types=[Producer, Artifact],
        relationship_types=[Produces],
    )

    driver = MagicMock()
    responses = [
        mock_execute_query([], []),  # constraints
        mock_execute_query(
            [
                {
                    "nodeType": ":`Artifact`",
                    "nodeLabels": ["Artifact"],
                    "mandatory": True,
                    "propertyName": "kind",
                    "propertyTypes": ["String"],
                },
                {
                    "nodeType": ":`Producer`",
                    "nodeLabels": ["Producer"],
                    "mandatory": True,
                    "propertyName": "kind",
                    "propertyTypes": ["String"],
                },
            ]
        ),
        mock_execute_query(
            [
                {
                    "relType": ":`PRODUCES`",
                    "mandatory": False,
                    "propertyName": None,
                    "propertyTypes": [],
                }
            ]
        ),
        mock_execute_query(
            [{"source_labels": ["Producer"], "target_labels": ["Artifact"]}]
        ),
        mock_execute_query(
            [{"min_degree": 2, "max_degree": 2, "avg_degree": 2.0, "sample_size": 1}]
        ),
        # Partitioned query for the target side (must be issued).
        mock_execute_query([_partitioned_row("heavy", "final", 2, 2, 2.0, 1)]),
    ]

    # Count() queries served out of band (E46.3); the target-side partitioned
    # read remains the last ordered response.
    driver.execute_query.side_effect = ordered_side_effect_with_counts(responses)

    profile = MemgraphInspector().inspect(driver, graph_definition=gd)
    produces = profile.rel_type_profiles["PRODUCES"]

    # The processable target side must have produced its breakdown; the
    # unprocessable source side must not have blocked iteration.
    assert produces.target_partitioned_cardinality is not None, (
        "target_partitioned_cardinality must be populated from the "
        "processable target side."
    )
    assert produces.source_partitioned_cardinality is None


def _both_sides_definition() -> GraphDefinition:
    """MAKES conditional on BOTH endpoints.

    Source side (assembler, final) = 2..2; target side (assembler, final) = 1..1.
    """

    class Operation(NodeModel):
        __label__ = "Operation"
        __uid_field__ = "uid"
        uid: str
        kind: str

    class Sample(NodeModel):
        __label__ = "Sample"
        __uid_field__ = "uid"
        uid: str
        kind: str

    class Makes(RelationshipModel):
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

    return GraphDefinition(
        name="BothSides",
        node_types=[Operation, Sample],
        relationship_types=[Makes],
    )


def test_memgraph_partitioned_cardinality_both_sides_parity_with_networkx() -> None:
    """Both-sides conditional: each side's breakdown matches NetworkX.

    The ``side_effect`` dispatches the partitioned queries on the rendered Cypher
    (source anchors on ``count(n)``, target on ``count(m)``), so issuing the wrong
    query for a side would return the wrong degree rows and fail parity — the
    regression guard for the both-sides bug.
    """
    import networkx as nx

    from orthograph.backends.networkx.inspector import NetworkxInspector

    gd = _both_sides_definition()

    g: nx.MultiDiGraph[str] = nx.MultiDiGraph()
    g.add_node("op1", __label__="Operation", uid="op1", kind="assembler")
    g.add_node("a1", __label__="Sample", uid="a1", kind="final")
    g.add_node("a2", __label__="Sample", uid="a2", kind="final")
    g.add_edge("op1", "a1", __label__="MAKES")
    g.add_edge("op1", "a2", __label__="MAKES")

    nx_profile = NetworkxInspector().inspect(g, graph_definition=gd)
    nx_rtp = nx_profile.rel_type_profiles["MAKES"]
    assert nx_rtp.source_partitioned_cardinality is not None
    assert nx_rtp.target_partitioned_cardinality is not None

    driver = MagicMock()
    ordered_responses = [
        mock_execute_query([], []),  # constraints
        mock_execute_query(
            [
                {
                    "nodeType": ":`Operation`",
                    "nodeLabels": ["Operation"],
                    "mandatory": True,
                    "propertyName": "kind",
                    "propertyTypes": ["String"],
                },
                {
                    "nodeType": ":`Sample`",
                    "nodeLabels": ["Sample"],
                    "mandatory": True,
                    "propertyName": "kind",
                    "propertyTypes": ["String"],
                },
            ]
        ),
        mock_execute_query(
            [
                {
                    "relType": ":`MAKES`",
                    "mandatory": False,
                    "propertyName": None,
                    "propertyTypes": [],
                }
            ]
        ),
        mock_execute_query(
            [{"source_labels": ["Operation"], "target_labels": ["Sample"]}]
        ),
        mock_execute_query(
            [{"min_degree": 2, "max_degree": 2, "avg_degree": 2.0, "sample_size": 1}]
        ),  # aggregate (no "AS sk")
    ]
    ordered_iter = iter(ordered_responses)
    issued_partitioned: list[str] = []

    def side_effect(*args: Any, **kwargs: Any) -> Any:
        cypher = args[0] if args else kwargs.get("query", "")
        if "count(n) AS count" in cypher or "count(r) AS count" in cypher:
            # Property-independent entity count (E46.3) — served out of band.
            return mock_execute_query([{"count": 2}], ["count"])
        if not ("AS sk" in cypher and "AS tk" in cypher):
            return next(ordered_iter)
        if "count(n)" in cypher:
            issued_partitioned.append("source")
            return mock_execute_query(
                [_partitioned_row("assembler", "final", 2, 2, 2.0, 1)]
            )
        if "count(m)" in cypher:
            issued_partitioned.append("target")
            return mock_execute_query(
                [_partitioned_row("assembler", "final", 1, 1, 1.0, 2)]
            )
        raise AssertionError(f"Unrecognised partitioned query Cypher: {cypher!r}")

    driver.execute_query.side_effect = side_effect

    mg_profile = MemgraphInspector().inspect(driver, graph_definition=gd)
    mg_rtp = mg_profile.rel_type_profiles["MAKES"]

    assert issued_partitioned == ["source", "target"], (
        "Each conditional side must issue its own anchored query; "
        f"got {issued_partitioned}."
    )

    for side in ("source", "target"):
        nx_part = getattr(nx_rtp, f"{side}_partitioned_cardinality")
        db_part = getattr(mg_rtp, f"{side}_partitioned_cardinality")
        assert db_part is not None, f"{side} breakdown missing on DB side"
        assert set(db_part) == set(nx_part), f"{side} keys differ"
        for key in nx_part:
            assert db_part[key].min == nx_part[key].min, f"{side} min mismatch {key!r}"
            assert db_part[key].max == nx_part[key].max, f"{side} max mismatch {key!r}"
            assert db_part[key].count == nx_part[key].count, (
                f"{side} count mismatch {key!r}"
            )
