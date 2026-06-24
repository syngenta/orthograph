"""Tests for orthograph.backends.neo4j.inspector."""

from typing import Any
from unittest.mock import MagicMock

import pytest

from orthograph.backends.neo4j.inspector import (
    Neo4jInspectionStrategy,
    Neo4jInspector,
    validate_database,
)
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
from tests.backends.conftest import mock_execute_query
from tests.fixtures.conftest import ActedIn, Movie, Person


# --- Fixtures ---


@pytest.fixture()
def graph_definition() -> GraphDefinition:
    return GraphDefinition(
        name="Film",
        node_types=[Person, Movie],
        relationship_types=[ActedIn],
    )


# --- Strategy auto-detection ---


def test_neo4j_detect_strategy_apoc() -> None:
    """_detect_strategy returns APOC when apoc.meta procedures are present."""
    driver = MagicMock()
    driver.execute_query.return_value = mock_execute_query(
        [{"cnt": 5}],
        ["cnt"],
    )
    inspector = Neo4jInspector()
    assert inspector._detect_strategy(driver) is Neo4jInspectionStrategy.APOC


def test_neo4j_detect_strategy_schema() -> None:
    """_detect_strategy → SCHEMA when apoc.meta absent but db.schema present."""
    driver = MagicMock()

    call_count = 0
    responses = [
        # apoc.meta probe → absent
        mock_execute_query([{"cnt": 0}], ["cnt"]),
        # db.schema.nodeTypeProperties probe → present
        mock_execute_query([{"cnt": 1}], ["cnt"]),
    ]

    def side_effect(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        cypher = args[0] if args else kwargs.get("query_", kwargs.get("query", ""))
        # Dedicated instance-count queries are served out of band so existing
        # strict-ordered response lists stay valid (E46.x count fix).
        if "count(n) AS count" in cypher or "count(r) AS count" in cypher:
            return mock_execute_query([{"count": 0}], ["count"])
        # Property present-count queries (ADR-036) are likewise served out of
        # band so the APOC no-scan correction does not shift response indices.
        if "AS present_count" in cypher:
            return mock_execute_query([{"present_count": 0}], ["present_count"])
        result = responses[call_count]
        call_count += 1
        return result

    driver.execute_query.side_effect = side_effect
    inspector = Neo4jInspector()
    assert inspector._detect_strategy(driver) is Neo4jInspectionStrategy.SCHEMA


def test_neo4j_detect_strategy_cypher() -> None:
    """_detect_strategy returns CYPHER when neither apoc.meta nor db.schema present."""
    driver = MagicMock()

    call_count = 0
    responses = [
        # apoc.meta probe → absent
        mock_execute_query([{"cnt": 0}], ["cnt"]),
        # db.schema.nodeTypeProperties probe → absent
        mock_execute_query([{"cnt": 0}], ["cnt"]),
    ]

    def side_effect(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        cypher = args[0] if args else kwargs.get("query_", kwargs.get("query", ""))
        # Dedicated instance-count queries are served out of band so existing
        # strict-ordered response lists stay valid .
        if "count(n) AS count" in cypher or "count(r) AS count" in cypher:
            return mock_execute_query([{"count": 0}], ["count"])
        # Property present-count queries (ADR-036) are likewise served out of
        # band so the APOC no-scan correction does not shift response indices.
        if "AS present_count" in cypher:
            return mock_execute_query([{"present_count": 0}], ["present_count"])
        result = responses[call_count]
        call_count += 1
        return result

    driver.execute_query.side_effect = side_effect
    inspector = Neo4jInspector()
    assert inspector._detect_strategy(driver) is Neo4jInspectionStrategy.CYPHER


def test_neo4j_explicit_strategy_skips_detection() -> None:
    """An explicit strategy skips the SHOW PROCEDURES detection calls."""
    driver = MagicMock()
    driver.execute_query.return_value = mock_execute_query([], [])
    inspector = Neo4jInspector(strategy=Neo4jInspectionStrategy.CYPHER)
    inspector.inspect(driver)
    for call in driver.execute_query.call_args_list:
        assert "SHOW PROCEDURES" not in str(call)


# --- use_apoc deprecation shim ---


def test_use_apoc_true_emits_deprecation_and_maps_to_apoc() -> None:
    """use_apoc=True emits DeprecationWarning and behaves as strategy=APOC."""
    driver = MagicMock()
    driver.execute_query.return_value = mock_execute_query([], [])
    with pytest.warns(DeprecationWarning):
        inspector = Neo4jInspector(use_apoc=True)
    inspector.inspect(driver)
    # APOC path skips the SHOW PROCEDURES auto-detect probe.
    for call in driver.execute_query.call_args_list:
        assert "SHOW PROCEDURES" not in str(call)


def test_use_apoc_false_emits_deprecation_and_maps_to_cypher() -> None:
    """use_apoc=False emits DeprecationWarning and behaves as strategy=CYPHER."""
    driver = MagicMock()
    driver.execute_query.return_value = mock_execute_query([], [])
    with pytest.warns(DeprecationWarning):
        inspector = Neo4jInspector(use_apoc=False)
    inspector.inspect(driver)
    for call in driver.execute_query.call_args_list:
        assert "SHOW PROCEDURES" not in str(call)


def test_use_apoc_none_emits_deprecation_and_maps_to_auto() -> None:
    """use_apoc=None (explicitly passed) emits DeprecationWarning and auto-detects."""
    driver = MagicMock()
    driver.execute_query.return_value = mock_execute_query([{"cnt": 5}], ["cnt"])
    with pytest.warns(DeprecationWarning):
        Neo4jInspector(use_apoc=None)


def test_no_args_does_not_warn() -> None:
    """Constructing with no args (default auto) must not emit a warning."""
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        Neo4jInspector()  # must not raise


# --- SCHEMA strategy merge (counts from scan + types from db.schema) ---


def _schema_strategy_responses() -> list[Any]:
    """Ordered driver responses for a SCHEMA-strategy inspect() run.

    One node label (Person) with two scanned properties (name: complete,
    email: partial) and one rel type (ACTED_IN) with one property (role).
    db.schema reports types for name/email/role; it also reports a property
    (nickname) NOT seen by the scan, which must be ignored (the scan is the
    source of truth for which properties exist + their counts).
    """
    return [
        # _detect_strategy: apoc.meta absent
        mock_execute_query([{"cnt": 0}], ["cnt"]),
        # _detect_strategy: db.schema present
        mock_execute_query([{"cnt": 1}], ["cnt"]),
        # node_labels
        mock_execute_query([{"label": "Person"}], ["label"]),
        # rel_types
        mock_execute_query([{"relationshipType": "ACTED_IN"}], ["relationshipType"]),
        # bulk db.schema node types
        mock_execute_query(
            [
                {
                    "nodeType": ":`Person`",
                    "nodeLabels": ["Person"],
                    "propertyName": "name",
                    "propertyTypes": ["String"],
                    "mandatory": True,
                },
                {
                    "nodeType": ":`Person`",
                    "nodeLabels": ["Person"],
                    "propertyName": "email",
                    "propertyTypes": ["String"],
                    "mandatory": False,
                },
            ],
        ),
        # bulk db.schema rel types
        mock_execute_query(
            [
                {
                    "relType": ":`ACTED_IN`",
                    "propertyName": "role",
                    "propertyTypes": ["String"],
                    "mandatory": False,
                },
            ],
        ),
        # constraints (read before profiles so they can be cross-referenced)
        mock_execute_query([], []),
        # CypherNodePropertiesQuery for Person (true counts, types=[])
        mock_execute_query(
            [
                {
                    "propertyName": "name",
                    "propertyTypes": [],
                    "mandatory": True,
                    "propertyObservations": 10,
                    "totalObservations": 10,
                },
                {
                    "propertyName": "email",
                    "propertyTypes": [],
                    "mandatory": False,
                    "propertyObservations": 4,
                    "totalObservations": 10,
                },
            ],
        ),
        # CypherRelPropertiesQuery for ACTED_IN (true counts, types=[])
        mock_execute_query(
            [
                {
                    "propertyName": "role",
                    "propertyTypes": [],
                    "mandatory": True,
                    "propertyObservations": 7,
                    "totalObservations": 7,
                },
            ],
        ),
        # endpoint_labels for ACTED_IN
        mock_execute_query(
            [{"source_labels": ["Person"], "target_labels": ["Movie"]}],
        ),
        # cardinality for ACTED_IN against Person
        mock_execute_query(
            [
                {
                    "min_degree": 1,
                    "max_degree": 2,
                    "avg_degree": 1.5,
                    "sample_size": 10,
                },
            ],
        ),
    ]


def test_schema_strategy_merges_counts_and_types() -> None:
    """SCHEMA: counts come from the scan, observed_types from db.schema.*."""
    driver = MagicMock()
    call_count = 0
    responses = _schema_strategy_responses()

    def side_effect(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        cypher = args[0] if args else kwargs.get("query_", kwargs.get("query", ""))
        # Dedicated instance-count queries are served out of band so existing
        # strict-ordered response lists stay valid .
        if "count(n) AS count" in cypher or "count(r) AS count" in cypher:
            return mock_execute_query([{"count": 0}], ["count"])
        # Property present-count queries  are likewise served out of
        # band so the APOC no-scan correction does not shift response indices.
        if "AS present_count" in cypher:
            return mock_execute_query([{"present_count": 0}], ["present_count"])
        result = responses[call_count]
        call_count += 1
        return result

    driver.execute_query.side_effect = side_effect

    profile = Neo4jInspector().inspect(driver)

    person = profile.node_type_profiles["Person"]
    # Counts come from the pure-Cypher scan (true completeness).
    name = person.property_profiles["name"]
    assert name.present_count == 10
    assert name.total_count == 10
    # Types come from db.schema.*.
    assert name.observed_types == ["String"]

    email = person.property_profiles["email"]
    assert email.present_count == 4
    assert email.total_count == 10
    assert email.observed_types == ["String"]

    # Rel: counts from scan, types from db.schema.
    acted_in = profile.rel_type_profiles["ACTED_IN"]
    role = acted_in.property_profiles["role"]
    assert role.present_count == 7
    assert role.total_count == 7
    assert role.observed_types == ["String"]


def test_schema_strategy_scan_only_property_keeps_empty_types() -> None:
    """A property seen by the scan but not by db.schema keeps observed_types=[]."""
    driver = MagicMock()
    call_count = 0
    responses = _schema_strategy_responses()
    # Drop the db.schema 'email' type row: only 'name' has a db.schema type now.
    responses[4] = mock_execute_query(
        [
            {
                "nodeType": ":`Person`",
                "nodeLabels": ["Person"],
                "propertyName": "name",
                "propertyTypes": ["String"],
                "mandatory": True,
            },
        ],
    )

    def side_effect(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        cypher = args[0] if args else kwargs.get("query_", kwargs.get("query", ""))
        # Dedicated instance-count queries are served out of band so existing
        # strict-ordered response lists stay valid (E46.x count fix).
        if "count(n) AS count" in cypher or "count(r) AS count" in cypher:
            return mock_execute_query([{"count": 0}], ["count"])
        # Property present-count queries  are likewise served out of
        # band so the APOC no-scan correction does not shift response indices.
        if "AS present_count" in cypher:
            return mock_execute_query([{"present_count": 0}], ["present_count"])
        result = responses[call_count]
        call_count += 1
        return result

    driver.execute_query.side_effect = side_effect

    profile = Neo4jInspector().inspect(driver)
    person = profile.node_type_profiles["Person"]
    # name still gets its type; email (scan-only) keeps [].
    assert person.property_profiles["name"].observed_types == ["String"]
    assert person.property_profiles["email"].observed_types == []
    # Counts unaffected for both.
    assert person.property_profiles["email"].present_count == 4
    assert person.property_profiles["email"].total_count == 10


def test_apoc_strategy_regression_lock() -> None:
    """APOC strategy: types from APOC; counts corrected via real count() (ADR-036).

    apoc.meta present → APOC selected; no db.schema query is issued.  Types come
    from APOC, but ``present_count`` now comes from the dedicated
    ``count() … IS NOT NULL`` query (superseding APOC's sampled
    ``propertyObservations``), and ``total_count`` from the instance count.
    On a quiescent DB the corrected count equals APOC's reported value (100).
    """
    driver = MagicMock()
    call_count = 0
    responses = [
        # _detect_strategy: apoc.meta present → APOC (no db.schema probe)
        mock_execute_query([{"cnt": 3}], ["cnt"]),
        # node_labels
        mock_execute_query([{"label": "Person"}], ["label"]),
        # rel_types
        mock_execute_query([], []),
        # constraints (read before profiles so they can be cross-referenced)
        mock_execute_query([], []),
        # apoc node_properties for Person
        mock_execute_query(
            [
                {
                    "propertyName": "name",
                    "propertyTypes": ["String"],
                    "mandatory": True,
                    "propertyObservations": 100,
                    "totalObservations": 100,
                },
            ],
        ),
    ]

    def side_effect(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        cypher = args[0] if args else kwargs.get("query_", kwargs.get("query", ""))
        # ADR-036: total_count from the instance count, present_count from the
        # real count() … IS NOT NULL.  Quiescent DB → corrected count == 100.
        if "count(n) AS count" in cypher or "count(r) AS count" in cypher:
            return mock_execute_query([{"count": 100}], ["count"])
        if "AS present_count" in cypher:
            return mock_execute_query([{"present_count": 100}], ["present_count"])
        result = responses[call_count]
        call_count += 1
        return result

    driver.execute_query.side_effect = side_effect

    profile = Neo4jInspector().inspect(driver)
    name = profile.node_type_profiles["Person"].property_profiles["name"]
    assert name.present_count == 100
    assert name.total_count == 100
    assert name.observed_types == ["String"]
    # No db.schema query was issued on the APOC path.
    for call in driver.execute_query.call_args_list:
        assert "db.schema" not in str(call)


# --- ADR-036: APOC no-scan count correction ---


def _apoc_count_correction_driver(
    *,
    node_props: list[dict[str, Any]],
    rel_props: list[dict[str, Any]],
    node_total: int,
    rel_total: int,
    node_present: dict[str, int],
    rel_present: dict[str, int],
) -> MagicMock:
    """Build an APOC-strategy driver dispatching on rendered Cypher (ADR-036).

    Property *metadata* (types, APOC's sampled observations) comes from the
    ordered ``apoc.meta.*`` responses; the instance counts and per-property
    present-counts are dispatched by their distinctive Cypher so the test can
    return a *true* count that differs from APOC's reported observation count.
    """
    driver = MagicMock()
    ordered = [
        mock_execute_query([{"cnt": 3}], ["cnt"]),  # apoc.meta present → APOC
        mock_execute_query([{"label": "Person"}], ["label"]),
        mock_execute_query([{"relationshipType": "ACTED_IN"}], ["relationshipType"]),
        mock_execute_query([], []),  # constraints
        mock_execute_query(node_props),  # apoc node_properties (Person)
        mock_execute_query(rel_props),  # apoc rel_properties (ACTED_IN)
        mock_execute_query([{"source_labels": ["Person"], "target_labels": ["Movie"]}]),
        mock_execute_query(
            [{"min_degree": 1, "max_degree": 2, "avg_degree": 1.5, "sample_size": 3}]
        ),
    ]
    ordered_iter = iter(ordered)

    def side_effect(*args: Any, **kwargs: Any) -> Any:
        cypher = args[0] if args else kwargs.get("query_", kwargs.get("query", ""))
        if "count(n) AS count" in cypher:
            return mock_execute_query([{"count": node_total}], ["count"])
        if "count(r) AS count" in cypher:
            return mock_execute_query([{"count": rel_total}], ["count"])
        if "count(n) AS present_count" in cypher:
            # Dispatch by property key embedded in the rendered Cypher.
            prop = next(p for p in node_present if f"n.`{p}`" in cypher)
            return mock_execute_query(
                [{"present_count": node_present[prop]}], ["present_count"]
            )
        if "count(r) AS present_count" in cypher:
            prop = next(p for p in rel_present if f"r.`{p}`" in cypher)
            return mock_execute_query(
                [{"present_count": rel_present[prop]}], ["present_count"]
            )
        return next(ordered_iter)

    driver.execute_query.side_effect = side_effect
    return driver


def test_apoc_no_scan_corrects_rel_present_count_undercount() -> None:
    """APOC no-scan: the relationship present_count comes from a real count().

    Reproduces the E46.2 finding: APOC reports propertyObservations=100 for
    ACTED_IN.role while the true non-null count is 172.  ADR-036 sources
    present_count from a dedicated count() … IS NOT NULL, so the profile reports
    172, and total_count from the instance count (172 edges).
    """
    driver = _apoc_count_correction_driver(
        node_props=[
            {
                "propertyName": "name",
                "propertyTypes": ["String"],
                "mandatory": True,
                "propertyObservations": 10,
                "totalObservations": 10,
            }
        ],
        rel_props=[
            {
                "propertyName": "role",
                "propertyTypes": ["String"],
                "mandatory": True,
                "propertyObservations": 100,  # APOC undercount
                "totalObservations": 100,
            }
        ],
        node_total=10,
        rel_total=172,
        node_present={"name": 10},
        rel_present={"role": 172},  # the true non-null count
    )

    profile = Neo4jInspector().inspect(driver)
    role = profile.rel_type_profiles["ACTED_IN"].property_profiles["role"]
    # present_count is the TRUE count, not APOC's undercounted 100.
    assert role.present_count == 172
    # total_count is the property-independent instance count (edge count).
    assert role.total_count == 172
    assert role.completeness == 1.0
    # observed_types still come from APOC.
    assert role.observed_types == ["String"]


def test_apoc_no_scan_corrects_node_counts() -> None:
    """APOC no-scan: node present_count / total_count come from real counts.

    Person has 50 nodes; `email` is present on 30 (partial).  APOC reported a
    different (sampled) observation count, but the profile must reflect the true
    30/50 from the dedicated count queries.
    """
    driver = _apoc_count_correction_driver(
        node_props=[
            {
                "propertyName": "email",
                "propertyTypes": ["String"],
                "mandatory": False,
                "propertyObservations": 20,  # APOC undercount
                "totalObservations": 40,
            }
        ],
        rel_props=[],
        node_total=50,
        rel_total=0,
        node_present={"email": 30},  # the true non-null count
        rel_present={},
    )

    profile = Neo4jInspector().inspect(driver)
    email = profile.node_type_profiles["Person"].property_profiles["email"]
    assert email.present_count == 30
    assert email.total_count == 50
    assert email.completeness == 0.6


def test_apoc_null_property_row_is_skipped() -> None:
    """APOC's null-property sentinel row (property-less type) is skipped.

    Regression lock for the propertyName=None bug: APOC emits one row with
    propertyName=None for a label/rel-type that has no properties; the builder
    must skip it rather than raise.
    """
    driver = MagicMock()
    call_count = 0
    responses = [
        # _detect_strategy: apoc.meta present
        mock_execute_query([{"cnt": 3}], ["cnt"]),
        # node_labels
        mock_execute_query([{"label": "Empty"}], ["label"]),
        # rel_types
        mock_execute_query([], []),
        # constraints (read before profiles so they can be cross-referenced)
        mock_execute_query([], []),
        # apoc node_properties for Empty → only a null-property sentinel row
        mock_execute_query(
            [
                {
                    "propertyName": None,
                    "propertyTypes": None,
                    "mandatory": False,
                    "propertyObservations": 0,
                    "totalObservations": 0,
                },
            ],
        ),
    ]

    def side_effect(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        cypher = args[0] if args else kwargs.get("query_", kwargs.get("query", ""))
        # Dedicated instance-count queries are served out of band so existing
        # strict-ordered response lists stay valid (E46.x count fix).
        if "count(n) AS count" in cypher or "count(r) AS count" in cypher:
            return mock_execute_query([{"count": 0}], ["count"])
        # Property present-count queries (ADR-036) are likewise served out of
        # band so the APOC no-scan correction does not shift response indices.
        if "AS present_count" in cypher:
            return mock_execute_query([{"present_count": 0}], ["present_count"])
        result = responses[call_count]
        call_count += 1
        return result

    driver.execute_query.side_effect = side_effect

    profile = Neo4jInspector().inspect(driver)
    # The label exists but has no properties (sentinel skipped, no error).
    assert profile.node_type_profiles["Empty"].property_profiles == {}


# --- Labels ---


def test_neo4j_inspect_labels() -> None:
    driver = MagicMock()

    call_count = 0
    responses = [
        # _detect_strategy (SHOW PROCEDURES → apoc.meta present → APOC)
        mock_execute_query([{"cnt": 3}], ["cnt"]),
        # node_labels
        mock_execute_query(
            [{"label": "Person"}, {"label": "Movie"}],
            ["label"],
        ),
        # rel_types
        mock_execute_query(
            [{"relationshipType": "ACTED_IN"}],
            ["relationshipType"],
        ),
        # constraints (read before profiles so they can be cross-referenced)
        mock_execute_query([], []),
        # node_properties for Movie (sorted)
        mock_execute_query(
            [
                {
                    "propertyName": "title",
                    "propertyTypes": ["String"],
                    "mandatory": True,
                    "propertyObservations": 50,
                    "totalObservations": 50,
                },
            ],
        ),
        # node_properties for Person (sorted)
        mock_execute_query(
            [
                {
                    "propertyName": "name",
                    "propertyTypes": ["String"],
                    "mandatory": True,
                    "propertyObservations": 100,
                    "totalObservations": 100,
                },
            ],
        ),
        # rel_properties for ACTED_IN
        mock_execute_query(
            [
                {
                    "propertyName": "role",
                    "propertyTypes": ["String"],
                    "mandatory": True,
                    "propertyObservations": 200,
                    "totalObservations": 200,
                },
            ],
        ),
        # endpoint_labels for ACTED_IN (queried first to identify sources)
        mock_execute_query(
            [{"source_labels": ["Person"], "target_labels": ["Movie"]}],
        ),
        # cardinality for ACTED_IN against Person (confirmed source label)
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

    def side_effect(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        cypher = args[0] if args else kwargs.get("query_", kwargs.get("query", ""))
        # Dedicated instance-count queries are served out of band so existing
        # strict-ordered response lists stay valid (E46.x count fix).
        if "count(n) AS count" in cypher or "count(r) AS count" in cypher:
            return mock_execute_query([{"count": 0}], ["count"])
        # Property present-count queries (ADR-036) are likewise served out of
        # band so the APOC no-scan correction does not shift response indices.
        if "AS present_count" in cypher:
            return mock_execute_query([{"present_count": 0}], ["present_count"])
        result = responses[call_count]
        call_count += 1
        return result

    driver.execute_query.side_effect = side_effect

    inspector = Neo4jInspector()
    profile = inspector.inspect(driver)

    assert profile.node_labels == {"Person", "Movie"}
    assert profile.relationship_types == {"ACTED_IN"}


# --- Full profile ---


def test_neo4j_inspect_produces_profile() -> None:
    driver = MagicMock()

    call_count = 0
    responses = [
        # _detect_strategy (apoc.meta present → APOC)
        mock_execute_query([{"cnt": 3}], ["cnt"]),
        # node_labels
        mock_execute_query(
            [{"label": "Person"}, {"label": "Movie"}],
            ["label"],
        ),
        # rel_types
        mock_execute_query(
            [{"relationshipType": "ACTED_IN"}],
            ["relationshipType"],
        ),
        # constraints (read before profiles so they can be cross-referenced):
        # a UNIQUENESS on Person.name (does NOT guarantee presence) and a
        # NODE_PROPERTY_EXISTENCE on Movie.title (DOES guarantee presence).
        mock_execute_query(
            [
                {
                    "name": "constraint_person_name",
                    "type": "UNIQUENESS",
                    "entityType": "NODE",
                    "labelsOrTypes": ["Person"],
                    "properties": ["name"],
                    "propertyType": None,
                },
                {
                    "name": "constraint_movie_title_exists",
                    "type": "NODE_PROPERTY_EXISTENCE",
                    "entityType": "NODE",
                    "labelsOrTypes": ["Movie"],
                    "properties": ["title"],
                    "propertyType": None,
                },
            ],
        ),
        # node_properties for Movie
        mock_execute_query(
            [
                {
                    "propertyName": "title",
                    "propertyTypes": ["String"],
                    "mandatory": True,
                    "propertyObservations": 50,
                    "totalObservations": 50,
                },
                {
                    "propertyName": "year",
                    "propertyTypes": ["Long"],
                    "mandatory": True,
                    "propertyObservations": 50,
                    "totalObservations": 50,
                },
            ],
        ),
        # node_properties for Person
        mock_execute_query(
            [
                {
                    "propertyName": "name",
                    "propertyTypes": ["String"],
                    "mandatory": True,
                    "propertyObservations": 100,
                    "totalObservations": 100,
                },
                {
                    "propertyName": "age",
                    "propertyTypes": ["Long"],
                    "mandatory": True,
                    "propertyObservations": 100,
                    "totalObservations": 100,
                },
                {
                    "propertyName": "email",
                    "propertyTypes": ["String"],
                    "mandatory": False,
                    "propertyObservations": 50,
                    "totalObservations": 100,
                },
            ],
        ),
        # rel_properties for ACTED_IN
        mock_execute_query(
            [
                {
                    "propertyName": "role",
                    "propertyTypes": ["String"],
                    "mandatory": True,
                    "propertyObservations": 200,
                    "totalObservations": 200,
                },
            ],
        ),
        # endpoint_labels for ACTED_IN (queried first to identify sources)
        mock_execute_query(
            [{"source_labels": ["Person"], "target_labels": ["Movie"]}],
        ),
        # cardinality for ACTED_IN against Person (confirmed source label)
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

    def side_effect(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        cypher = args[0] if args else kwargs.get("query_", kwargs.get("query", ""))
        # APOC strategy + ADR-036: total_count comes from the instance count and
        # present_count from a real count() … IS NOT NULL.  Serve a quiescent-DB
        # value where APOC's reported counts were accurate so completeness == 1.0
        # for the fully-present `name` property the assertion below checks.
        if "count(n) AS count" in cypher or "count(r) AS count" in cypher:
            return mock_execute_query([{"count": 100}], ["count"])
        if "AS present_count" in cypher:
            return mock_execute_query([{"present_count": 100}], ["present_count"])
        result = responses[call_count]
        call_count += 1
        return result

    driver.execute_query.side_effect = side_effect

    inspector = Neo4jInspector()
    profile = inspector.inspect(driver)

    assert profile.source == "neo4j"
    assert profile.node_labels == {"Person", "Movie"}
    assert profile.relationship_types == {"ACTED_IN"}

    # Check node profiles
    person = profile.node_type_profiles["Person"]
    assert "name" in person.property_profiles
    assert "age" in person.property_profiles
    assert person.property_profiles["name"].observed_types == ["String"]
    assert person.property_profiles["name"].completeness == 1.0
    # UNIQUENESS alone does not guarantee presence (ADR-034 §4).
    assert person.property_profiles["name"].constraint_required is False

    movie = profile.node_type_profiles["Movie"]
    assert "title" in movie.property_profiles
    assert "year" in movie.property_profiles
    # NODE_PROPERTY_EXISTENCE on Movie.title guarantees presence.
    assert movie.property_profiles["title"].constraint_required is True
    # year is inspected with no covering constraint.
    assert movie.property_profiles["year"].constraint_required is False

    # Check rel profile
    acted_in = profile.rel_type_profiles["ACTED_IN"]
    assert "role" in acted_in.property_profiles
    assert acted_in.cardinality_stats is not None
    assert acted_in.cardinality_stats.count == 50
    # No relationship constraint → inspected, none found.
    assert acted_in.property_profiles["role"].constraint_required is False

    # endpoint labels populated
    assert acted_in.source_labels == {"Person"}
    assert acted_in.target_labels == {"Movie"}

    # Constraints
    assert len(profile.constraints) == 2
    assert {c.constraint_type for c in profile.constraints} == {
        "UNIQUENESS",
        "NODE_PROPERTY_EXISTENCE",
    }


# --- value_distribution (E45.3) ---


def test_neo4j_value_distribution_is_none() -> None:
    """Neo4j inspector yields value_distribution=None (no per-value counts query)."""
    driver = MagicMock()
    call_count = 0
    responses = [
        # node_labels (no strategy-detection call when strategy is explicit)
        mock_execute_query([{"label": "Person"}], ["label"]),
        # rel_types
        mock_execute_query([], []),
        # constraints
        mock_execute_query([], []),
        # node_properties for Person
        mock_execute_query(
            [
                {
                    "propertyName": "name",
                    "propertyTypes": ["String"],
                    "mandatory": True,
                    "propertyObservations": 10,
                    "totalObservations": 10,
                },
            ],
        ),
    ]

    def side_effect(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        cypher = args[0] if args else kwargs.get("query_", kwargs.get("query", ""))
        # Dedicated instance-count queries are served out of band so existing
        # strict-ordered response lists stay valid (E46.x count fix).
        if "count(n) AS count" in cypher or "count(r) AS count" in cypher:
            return mock_execute_query([{"count": 0}], ["count"])
        # Property present-count queries (ADR-036) are likewise served out of
        # band so the APOC no-scan correction does not shift response indices.
        if "AS present_count" in cypher:
            return mock_execute_query([{"present_count": 0}], ["present_count"])
        result = responses[call_count]
        call_count += 1
        return result

    driver.execute_query.side_effect = side_effect

    profile = Neo4jInspector(strategy=Neo4jInspectionStrategy.APOC).inspect(driver)
    name = profile.node_type_profiles["Person"].property_profiles["name"]
    assert name.value_distribution is None


# --- partitioned_cardinality (E41.4) ---


def _conditional_operation_sample_definition() -> GraphDefinition:
    """The ADR-029 deciding scenario definition: HAS_OUTPUT with conditional source."""

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


def test_neo4j_partitioned_cardinality_assembles_expected_partitions() -> None:
    """Given grouped-query rows, the inspector assembles partitioned_cardinality.

    Parity note (E41.4): variance is None on the DB side (Cypher does not
    compute it); parity assertions check min/max/count only.
    """
    driver = MagicMock()
    gd = _conditional_operation_sample_definition()

    call_count = 0
    responses = [
        # _detect_strategy: APOC present
        mock_execute_query([{"cnt": 3}], ["cnt"]),
        # node_labels
        mock_execute_query([{"label": "Operation"}, {"label": "Sample"}], ["label"]),
        # rel_types
        mock_execute_query([{"relationshipType": "HAS_OUTPUT"}], ["relationshipType"]),
        # constraints
        mock_execute_query([], []),
        # node_properties for Operation
        mock_execute_query(
            [
                {
                    "propertyName": "uid",
                    "propertyTypes": ["String"],
                    "mandatory": True,
                    "propertyObservations": 1,
                    "totalObservations": 1,
                },
                {
                    "propertyName": "kind",
                    "propertyTypes": ["String"],
                    "mandatory": True,
                    "propertyObservations": 1,
                    "totalObservations": 1,
                },
            ]
        ),
        # node_properties for Sample
        mock_execute_query(
            [
                {
                    "propertyName": "uid",
                    "propertyTypes": ["String"],
                    "mandatory": True,
                    "propertyObservations": 3,
                    "totalObservations": 3,
                },
                {
                    "propertyName": "kind",
                    "propertyTypes": ["String"],
                    "mandatory": True,
                    "propertyObservations": 3,
                    "totalObservations": 3,
                },
            ]
        ),
        # rel_properties for HAS_OUTPUT (none)
        mock_execute_query([], []),
        # endpoint_labels for HAS_OUTPUT
        mock_execute_query(
            [{"source_labels": ["Operation"], "target_labels": ["Sample"]}]
        ),
        # aggregate cardinality for HAS_OUTPUT against Operation
        mock_execute_query(
            [{"min_degree": 1, "max_degree": 3, "avg_degree": 2.0, "sample_size": 1}]
        ),
        # partitioned cardinality for HAS_OUTPUT against Operation (source label)
        mock_execute_query(
            [
                _partitioned_row("subsampling", "subsampling", 2, 2, 2.0, 1),
                _partitioned_row("subsampling", "nothing", 1, 1, 1.0, 1),
            ]
        ),
    ]

    def side_effect(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        cypher = args[0] if args else kwargs.get("query_", kwargs.get("query", ""))
        # Dedicated instance-count queries are served out of band so existing
        # strict-ordered response lists stay valid (E46.x count fix).
        if "count(n) AS count" in cypher or "count(r) AS count" in cypher:
            return mock_execute_query([{"count": 0}], ["count"])
        # Property present-count queries (ADR-036) are likewise served out of
        # band so the APOC no-scan correction does not shift response indices.
        if "AS present_count" in cypher:
            return mock_execute_query([{"present_count": 0}], ["present_count"])
        result = responses[call_count]
        call_count += 1
        return result

    driver.execute_query.side_effect = side_effect

    profile = Neo4jInspector().inspect(driver, graph_definition=gd)
    has_output = profile.rel_type_profiles["HAS_OUTPUT"]

    partitions = has_output.source_partitioned_cardinality
    assert partitions is not None

    sub_sub = str(PartitionKey(source_value="subsampling", target_value="subsampling"))
    sub_nothing = str(PartitionKey(source_value="subsampling", target_value="nothing"))
    assert set(partitions) == {sub_sub, sub_nothing}

    # min/max/count parity (variance not materialised by Cypher — None on DB side).
    assert partitions[sub_sub].min == 2
    assert partitions[sub_sub].max == 2
    assert partitions[sub_sub].count == 1
    assert partitions[sub_sub].variance is None

    assert partitions[sub_nothing].min == 1
    assert partitions[sub_nothing].max == 1
    assert partitions[sub_nothing].count == 1


def test_neo4j_partitioned_cardinality_zero_degree_rows_suppressed() -> None:
    """Zero-degree rows from OPTIONAL MATCH are suppressed (parity with NetworkX).

    NetworkX only emits observed edges; the DB query returns an (sk, null)
    row with degree=0 for source nodes with no matching edge.  Suppress it
    so both backends agree on the absent-partition convention.
    """
    driver = MagicMock()
    gd = _conditional_operation_sample_definition()

    call_count = 0
    responses = [
        mock_execute_query([{"cnt": 3}], ["cnt"]),  # APOC present
        mock_execute_query([{"label": "Operation"}, {"label": "Sample"}], ["label"]),
        mock_execute_query([{"relationshipType": "HAS_OUTPUT"}], ["relationshipType"]),
        mock_execute_query([], []),  # constraints
        mock_execute_query(
            [
                {
                    "propertyName": "kind",
                    "propertyTypes": ["String"],
                    "mandatory": True,
                    "propertyObservations": 1,
                    "totalObservations": 1,
                }
            ]
        ),  # Operation props
        mock_execute_query(
            [
                {
                    "propertyName": "kind",
                    "propertyTypes": ["String"],
                    "mandatory": True,
                    "propertyObservations": 1,
                    "totalObservations": 1,
                }
            ]
        ),  # Sample props
        mock_execute_query([], []),  # HAS_OUTPUT props
        mock_execute_query(
            [{"source_labels": ["Operation"], "target_labels": ["Sample"]}]
        ),
        mock_execute_query(
            [{"min_degree": 2, "max_degree": 2, "avg_degree": 2.0, "sample_size": 1}]
        ),
        # Partitioned rows: zero-degree null partition from OPTIONAL MATCH
        mock_execute_query(
            [
                _partitioned_row("subsampling", "subsampling", 2, 2, 2.0, 1),
                # This zero-degree row must be suppressed:
                _partitioned_row("subsampling", None, 0, 0, 0.0, 1),
            ]
        ),
    ]

    def side_effect(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        cypher = args[0] if args else kwargs.get("query_", kwargs.get("query", ""))
        # Dedicated instance-count queries are served out of band so existing
        # strict-ordered response lists stay valid (E46.x count fix).
        if "count(n) AS count" in cypher or "count(r) AS count" in cypher:
            return mock_execute_query([{"count": 0}], ["count"])
        # Property present-count queries (ADR-036) are likewise served out of
        # band so the APOC no-scan correction does not shift response indices.
        if "AS present_count" in cypher:
            return mock_execute_query([{"present_count": 0}], ["present_count"])
        result = responses[call_count]
        call_count += 1
        return result

    driver.execute_query.side_effect = side_effect

    profile = Neo4jInspector().inspect(driver, graph_definition=gd)
    has_output = profile.rel_type_profiles["HAS_OUTPUT"]
    partitions = has_output.source_partitioned_cardinality

    assert partitions is not None
    sub_sub = str(PartitionKey(source_value="subsampling", target_value="subsampling"))
    # The null-target zero-degree partition must NOT appear.
    assert set(partitions) == {sub_sub}


def test_neo4j_partitioned_cardinality_constant_type_is_none() -> None:
    """A non-conditional relationship type leaves both partitioned fields None."""
    from tests.fixtures.conftest import ActedIn, Movie, Person

    driver = MagicMock()
    gd = GraphDefinition(
        name="Film",
        node_types=[Person, Movie],
        relationship_types=[ActedIn],
    )

    call_count = 0
    responses = [
        mock_execute_query([{"cnt": 3}], ["cnt"]),  # APOC present
        mock_execute_query([{"label": "Movie"}, {"label": "Person"}], ["label"]),
        mock_execute_query([{"relationshipType": "ACTED_IN"}], ["relationshipType"]),
        mock_execute_query([], []),  # constraints
        # Movie props
        mock_execute_query(
            [
                {
                    "propertyName": "title",
                    "propertyTypes": ["String"],
                    "mandatory": True,
                    "propertyObservations": 10,
                    "totalObservations": 10,
                }
            ]
        ),
        # Person props
        mock_execute_query(
            [
                {
                    "propertyName": "name",
                    "propertyTypes": ["String"],
                    "mandatory": True,
                    "propertyObservations": 10,
                    "totalObservations": 10,
                }
            ]
        ),
        # ACTED_IN props
        mock_execute_query([], []),
        # endpoint labels
        mock_execute_query([{"source_labels": ["Person"], "target_labels": ["Movie"]}]),
        # aggregate cardinality
        mock_execute_query(
            [{"min_degree": 1, "max_degree": 2, "avg_degree": 1.5, "sample_size": 10}]
        ),
        # No partitioned cardinality query should be issued for non-conditional types.
        # (If it were, the next call would fail with IndexError.)
    ]

    def side_effect(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        cypher = args[0] if args else kwargs.get("query_", kwargs.get("query", ""))
        # Dedicated instance-count queries are served out of band so existing
        # strict-ordered response lists stay valid (E46.x count fix).
        if "count(n) AS count" in cypher or "count(r) AS count" in cypher:
            return mock_execute_query([{"count": 0}], ["count"])
        # Property present-count queries (ADR-036) are likewise served out of
        # band so the APOC no-scan correction does not shift response indices.
        if "AS present_count" in cypher:
            return mock_execute_query([{"present_count": 0}], ["present_count"])
        result = responses[call_count]
        call_count += 1
        return result

    driver.execute_query.side_effect = side_effect

    profile = Neo4jInspector().inspect(driver, graph_definition=gd)
    acted_in = profile.rel_type_profiles["ACTED_IN"]

    assert acted_in.source_partitioned_cardinality is None
    assert acted_in.target_partitioned_cardinality is None
    # Aggregate still populated.
    assert acted_in.cardinality_stats is not None


def test_neo4j_partitioned_cardinality_no_definition_is_none() -> None:
    """Without a GraphDefinition, both partitioned fields stay None (graceful)."""
    driver = MagicMock()

    call_count = 0
    responses = [
        mock_execute_query([{"cnt": 3}], ["cnt"]),  # APOC present
        mock_execute_query([{"label": "Person"}], ["label"]),
        mock_execute_query([{"relationshipType": "ACTED_IN"}], ["relationshipType"]),
        mock_execute_query([], []),  # constraints
        mock_execute_query(
            [
                {
                    "propertyName": "name",
                    "propertyTypes": ["String"],
                    "mandatory": True,
                    "propertyObservations": 5,
                    "totalObservations": 5,
                }
            ]
        ),
        mock_execute_query([], []),  # ACTED_IN props
        mock_execute_query([{"source_labels": ["Person"], "target_labels": []}]),
        mock_execute_query(
            [{"min_degree": 1, "max_degree": 1, "avg_degree": 1.0, "sample_size": 5}]
        ),
    ]

    def side_effect(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        cypher = args[0] if args else kwargs.get("query_", kwargs.get("query", ""))
        # Dedicated instance-count queries are served out of band so existing
        # strict-ordered response lists stay valid (E46.x count fix).
        if "count(n) AS count" in cypher or "count(r) AS count" in cypher:
            return mock_execute_query([{"count": 0}], ["count"])
        # Property present-count queries (ADR-036) are likewise served out of
        # band so the APOC no-scan correction does not shift response indices.
        if "AS present_count" in cypher:
            return mock_execute_query([{"present_count": 0}], ["present_count"])
        result = responses[call_count]
        call_count += 1
        return result

    driver.execute_query.side_effect = side_effect

    # inspect() without graph_definition
    profile = Neo4jInspector().inspect(driver)
    assert profile.rel_type_profiles["ACTED_IN"].source_partitioned_cardinality is None
    assert profile.rel_type_profiles["ACTED_IN"].target_partitioned_cardinality is None


# --- parity: same logical graph yields equivalent partitions on NetworkX / Neo4j ---


def test_neo4j_partitioned_cardinality_parity_with_networkx() -> None:
    """The deciding-scenario partitions match the NetworkX reference (min/max/count).

    Parity note: variance is not materialised from Cypher (None from Neo4j,
    computed by NetworkX); assertions exclude variance/std per parity contract.
    """
    import networkx as nx

    from orthograph.backends.networkx.inspector import NetworkxInspector

    gd = _conditional_operation_sample_definition()

    # Build the reference NetworkX graph.
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

    # Mocked Neo4j returning the same logical data.
    driver = MagicMock()
    call_count = 0
    responses = [
        mock_execute_query([{"cnt": 3}], ["cnt"]),  # APOC present
        mock_execute_query([{"label": "Operation"}, {"label": "Sample"}], ["label"]),
        mock_execute_query([{"relationshipType": "HAS_OUTPUT"}], ["relationshipType"]),
        mock_execute_query([], []),  # constraints
        mock_execute_query(
            [
                {
                    "propertyName": "kind",
                    "propertyTypes": ["String"],
                    "mandatory": True,
                    "propertyObservations": 1,
                    "totalObservations": 1,
                }
            ]
        ),  # Operation props
        mock_execute_query(
            [
                {
                    "propertyName": "kind",
                    "propertyTypes": ["String"],
                    "mandatory": True,
                    "propertyObservations": 3,
                    "totalObservations": 3,
                }
            ]
        ),  # Sample props
        mock_execute_query([], []),  # HAS_OUTPUT props
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

    def side_effect(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        cypher = args[0] if args else kwargs.get("query_", kwargs.get("query", ""))
        # Dedicated instance-count queries are served out of band so existing
        # strict-ordered response lists stay valid (E46.x count fix).
        if "count(n) AS count" in cypher or "count(r) AS count" in cypher:
            return mock_execute_query([{"count": 0}], ["count"])
        # Property present-count queries (ADR-036) are likewise served out of
        # band so the APOC no-scan correction does not shift response indices.
        if "AS present_count" in cypher:
            return mock_execute_query([{"present_count": 0}], ["present_count"])
        result = responses[call_count]
        call_count += 1
        return result

    driver.execute_query.side_effect = side_effect

    neo4j_profile = Neo4jInspector().inspect(driver, graph_definition=gd)
    neo4j_partitions = neo4j_profile.rel_type_profiles[
        "HAS_OUTPUT"
    ].source_partitioned_cardinality
    assert neo4j_partitions is not None

    # Keys must match.
    assert set(neo4j_partitions) == set(nx_partitions)

    # min/max/count parity per partition (variance excluded — not from Cypher).
    for key in nx_partitions:
        nx_p = nx_partitions[key]
        db_p = neo4j_partitions[key]
        assert db_p.min == nx_p.min, f"min mismatch for {key!r}"
        assert db_p.max == nx_p.max, f"max mismatch for {key!r}"
        assert db_p.count == nx_p.count, f"count mismatch for {key!r}"


def _both_sides_definition() -> GraphDefinition:
    """MAKES conditional on BOTH endpoints (E41.7).

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


def test_neo4j_partitioned_cardinality_both_sides_parity_with_networkx() -> None:
    """Both-sides conditional: each side's breakdown matches NetworkX (E41.7).

    op1 (assembler) -[MAKES]-> a1, a2 (both final).  Source side counts op1's
    outgoing degree (2); target side counts each artifact's incoming degree (1).

    The ``side_effect`` dispatches on the **rendered Cypher**, not call order, so
    the source-degree rows are returned only for the source-anchored query
    (``count(n)``) and the target-degree rows only for the target-anchored query
    (``count(m)``).  This is the regression guard for the E41.7 bug where both
    sides issued the source query: had the inspector run the source query for the
    target side, it would have received the source-degree rows and failed the
    target parity assertion below.
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
    # Non-partitioned responses are returned by call order; the two partitioned
    # queries are dispatched by their rendered Cypher (anchor + counted node).
    ordered_responses = [
        mock_execute_query([{"cnt": 3}], ["cnt"]),  # APOC present
        mock_execute_query([{"label": "Operation"}, {"label": "Sample"}], ["label"]),
        mock_execute_query([{"relationshipType": "MAKES"}], ["relationshipType"]),
        mock_execute_query([], []),  # constraints
        mock_execute_query(
            [
                {
                    "propertyName": "kind",
                    "propertyTypes": ["String"],
                    "mandatory": True,
                    "propertyObservations": 1,
                    "totalObservations": 1,
                }
            ]
        ),  # Operation props
        mock_execute_query(
            [
                {
                    "propertyName": "kind",
                    "propertyTypes": ["String"],
                    "mandatory": True,
                    "propertyObservations": 2,
                    "totalObservations": 2,
                }
            ]
        ),  # Sample props
        mock_execute_query([], []),  # MAKES props
        mock_execute_query(
            [{"source_labels": ["Operation"], "target_labels": ["Sample"]}]
        ),
        mock_execute_query(
            [{"min_degree": 2, "max_degree": 2, "avg_degree": 2.0, "sample_size": 1}]
        ),  # aggregate cardinality (MATCH (n:..) count(n), no "AS sk")
    ]
    ordered_iter = iter(ordered_responses)

    issued_partitioned: list[str] = []

    def side_effect(*args: Any, **kwargs: Any) -> Any:
        cypher = args[0] if args else kwargs.get("query", "")
        # Dedicated instance-count queries (count(n) AS count / count(r) AS count)
        # are served out of band before the count(n)/count(m) partitioned dispatch.
        if "count(n) AS count" in cypher or "count(r) AS count" in cypher:
            return mock_execute_query([{"count": 0}], ["count"])
        # Property present-count queries (ADR-036) served out of band too.
        if "AS present_count" in cypher:
            return mock_execute_query([{"present_count": 0}], ["present_count"])
        is_partitioned = "AS sk" in cypher and "AS tk" in cypher
        if not is_partitioned:
            return next(ordered_iter)
        # Partitioned: dispatch on the anchored / counted node.
        if "count(n)" in cypher:
            issued_partitioned.append("source")
            # source-side: op1 outgoing degree 2
            return mock_execute_query(
                [_partitioned_row("assembler", "final", 2, 2, 2.0, 1)]
            )
        if "count(m)" in cypher:
            issued_partitioned.append("target")
            # target-side: a1, a2 each incoming degree 1
            return mock_execute_query(
                [_partitioned_row("assembler", "final", 1, 1, 1.0, 2)]
            )
        raise AssertionError(f"Unrecognised partitioned query Cypher: {cypher!r}")

    driver.execute_query.side_effect = side_effect

    db_profile = Neo4jInspector().inspect(driver, graph_definition=gd)
    db_rtp = db_profile.rel_type_profiles["MAKES"]

    # Both sides must have issued their own (distinct) query.
    assert issued_partitioned == ["source", "target"], (
        "Each conditional side must issue its own anchored query; "
        f"got {issued_partitioned}."
    )

    for side in ("source", "target"):
        nx_part = getattr(nx_rtp, f"{side}_partitioned_cardinality")
        db_part = getattr(db_rtp, f"{side}_partitioned_cardinality")
        assert db_part is not None, f"{side} breakdown missing on DB side"
        assert set(db_part) == set(nx_part), f"{side} keys differ"
        for key in nx_part:
            assert db_part[key].min == nx_part[key].min, f"{side} min mismatch {key!r}"
            assert db_part[key].max == nx_part[key].max, f"{side} max mismatch {key!r}"
            assert db_part[key].count == nx_part[key].count, (
                f"{side} count mismatch {key!r}"
            )


# --- Bug regression tests ---


def test_neo4j_validate_database_forwards_graph_definition() -> None:
    """validate_database forwards graph_definition so partitioned_cardinality is set.

    Regression for the bug where validate_database called inspect() without
    graph_definition, silently leaving partitioned_cardinality=None.
    """
    driver = MagicMock()
    gd = _conditional_operation_sample_definition()

    call_count = 0
    responses = [
        mock_execute_query([{"cnt": 3}], ["cnt"]),  # APOC present
        mock_execute_query([{"label": "Operation"}, {"label": "Sample"}], ["label"]),
        mock_execute_query([{"relationshipType": "HAS_OUTPUT"}], ["relationshipType"]),
        mock_execute_query([], []),  # constraints
        mock_execute_query(
            [
                {
                    "propertyName": "kind",
                    "propertyTypes": ["String"],
                    "mandatory": True,
                    "propertyObservations": 1,
                    "totalObservations": 1,
                }
            ]
        ),  # Operation props
        mock_execute_query(
            [
                {
                    "propertyName": "kind",
                    "propertyTypes": ["String"],
                    "mandatory": True,
                    "propertyObservations": 3,
                    "totalObservations": 3,
                }
            ]
        ),  # Sample props
        mock_execute_query([], []),  # HAS_OUTPUT props
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

    def side_effect(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        cypher = args[0] if args else kwargs.get("query_", kwargs.get("query", ""))
        # Dedicated instance-count queries are served out of band so existing
        # strict-ordered response lists stay valid (E46.x count fix).
        if "count(n) AS count" in cypher or "count(r) AS count" in cypher:
            return mock_execute_query([{"count": 0}], ["count"])
        # Property present-count queries (ADR-036) are likewise served out of
        # band so the APOC no-scan correction does not shift response indices.
        if "AS present_count" in cypher:
            return mock_execute_query([{"present_count": 0}], ["present_count"])
        result = responses[call_count]
        call_count += 1
        return result

    driver.execute_query.side_effect = side_effect

    from orthograph.backends.neo4j.inspector import validate_database as neo4j_validate

    # validate_database must forward graph_definition so partitioned_cardinality
    # is populated on the profile passed to compare_profile_to_definition.
    # We inspect the profile indirectly: if partitioned_cardinality is None the
    # call count would be one shorter (no partitioned query fired).
    neo4j_validate(driver, gd)
    # The partitioned query (10th call) must have been issued.
    assert call_count == 10, (
        f"Expected 10 driver calls (partitioned query included), got {call_count}. "
        "validate_database likely did not forward graph_definition."
    )


def test_neo4j_unprocessable_first_side_falls_through_to_processable_second() -> None:
    """Unprocessable first conditional side does not prevent second side from running.

    Regression for the bug where break fired after any ConditionalCardinality,
    even when _extract_discriminators returned None (multi-property discriminator).
    The first side (source) uses two discriminator properties — unprocessable.
    The second side (target) uses one property — processable.  The partitioned
    query must still be issued for the target side.
    """
    # Build a definition where source cardinality uses multi-property conditions
    # and target cardinality uses a single-property condition.

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
        # Source side: multi-property discriminator → _extract_discriminators → None
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
        # Target side: single-property discriminator → processable
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
    call_count = 0
    responses = [
        mock_execute_query([{"cnt": 3}], ["cnt"]),  # APOC present
        mock_execute_query([{"label": "Artifact"}, {"label": "Producer"}], ["label"]),
        mock_execute_query([{"relationshipType": "PRODUCES"}], ["relationshipType"]),
        mock_execute_query([], []),  # constraints
        # Artifact props
        mock_execute_query(
            [
                {
                    "propertyName": "kind",
                    "propertyTypes": ["String"],
                    "mandatory": True,
                    "propertyObservations": 2,
                    "totalObservations": 2,
                }
            ]
        ),
        # Producer props
        mock_execute_query(
            [
                {
                    "propertyName": "kind",
                    "propertyTypes": ["String"],
                    "mandatory": True,
                    "propertyObservations": 1,
                    "totalObservations": 1,
                }
            ]
        ),
        mock_execute_query([], []),  # PRODUCES props
        mock_execute_query(
            [{"source_labels": ["Producer"], "target_labels": ["Artifact"]}]
        ),
        mock_execute_query(
            [{"min_degree": 2, "max_degree": 2, "avg_degree": 2.0, "sample_size": 1}]
        ),
        # Partitioned query for the target side (must be issued).
        mock_execute_query([_partitioned_row("heavy", "final", 2, 2, 2.0, 1)]),
    ]

    def side_effect(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        cypher = args[0] if args else kwargs.get("query_", kwargs.get("query", ""))
        # Dedicated instance-count queries are served out of band so existing
        # strict-ordered response lists stay valid (E46.x count fix).
        if "count(n) AS count" in cypher or "count(r) AS count" in cypher:
            return mock_execute_query([{"count": 0}], ["count"])
        # Property present-count queries (ADR-036) are likewise served out of
        # band so the APOC no-scan correction does not shift response indices.
        if "AS present_count" in cypher:
            return mock_execute_query([{"present_count": 0}], ["present_count"])
        result = responses[call_count]
        call_count += 1
        return result

    driver.execute_query.side_effect = side_effect

    profile = Neo4jInspector().inspect(driver, graph_definition=gd)
    produces = profile.rel_type_profiles["PRODUCES"]

    # The target-side partitioned query must have been issued (10 calls total).
    assert call_count == 10, (
        f"Expected 10 driver calls (target-side partitioned query included), "
        f"got {call_count}.  The unprocessable source side likely blocked iteration."
    )
    assert produces.target_partitioned_cardinality is not None, (
        "target_partitioned_cardinality must be populated from the "
        "processable target side."
    )
    # The unprocessable multi-property source side leaves source breakdown None.
    assert produces.source_partitioned_cardinality is None


# ---------------------------------------------------------------------------
# Value scan: value_counts_top_n gates type counts + histogram (E46.2)
# ---------------------------------------------------------------------------


def test_value_scan_skipped_when_top_n_is_none() -> None:
    """When value_counts_top_n is None (default), no value-scan queries are issued.

    observed_type_counts stays {} and value_distribution stays None.
    The call count must equal the baseline (no extra per-property queries).
    """
    driver = MagicMock()
    call_count = 0
    responses = [
        # node_labels (no strategy-detection call — explicit APOC)
        mock_execute_query([{"label": "Person"}], ["label"]),
        # rel_types
        mock_execute_query([], []),
        # constraints
        mock_execute_query([], []),
        # node_properties for Person
        mock_execute_query(
            [
                {
                    "propertyName": "name",
                    "propertyTypes": ["String"],
                    "mandatory": True,
                    "propertyObservations": 5,
                    "totalObservations": 5,
                },
            ],
        ),
    ]

    def side_effect(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        cypher = args[0] if args else kwargs.get("query_", kwargs.get("query", ""))
        # Dedicated instance-count queries are served out of band so existing
        # strict-ordered response lists stay valid (E46.x count fix).
        if "count(n) AS count" in cypher or "count(r) AS count" in cypher:
            return mock_execute_query([{"count": 0}], ["count"])
        # Property present-count queries (ADR-036) are likewise served out of
        # band so the APOC no-scan correction does not shift response indices.
        if "AS present_count" in cypher:
            return mock_execute_query([{"present_count": 0}], ["present_count"])
        result = responses[call_count]
        call_count += 1
        return result

    driver.execute_query.side_effect = side_effect

    # Default (no value_counts_top_n) — no extra queries.
    profile = Neo4jInspector(strategy=Neo4jInspectionStrategy.APOC).inspect(driver)
    name = profile.node_type_profiles["Person"].property_profiles["name"]
    assert name.observed_type_counts == {}
    assert name.value_distribution is None
    # 4 schema queries: labels + rel_types + constraints + props.  (Dedicated
    # instance-count queries are intercepted out of band and not tallied here;
    # this asserts the value scan was skipped, not the absolute driver-call total.)
    assert call_count == 4, (
        f"Expected 4 schema queries (no value scan), got {call_count}"
    )


def test_node_type_counts_populated_with_apoc() -> None:
    """APOC + value_counts_top_n → type counts and value_distribution populated.

    One type-count query and one histogram query are issued per property.
    The type counts carry normalised names (coerce_types vocabulary).
    """
    driver = MagicMock()
    call_count = 0
    responses = [
        # node_labels (no detection — explicit APOC)
        mock_execute_query([{"label": "Person"}], ["label"]),
        # rel_types
        mock_execute_query([], []),
        # constraints
        mock_execute_query([], []),
        # node_properties for Person (born: 7/10, name: 10/10)
        mock_execute_query(
            [
                {
                    "propertyName": "born",
                    "propertyTypes": ["Long", "String"],
                    "mandatory": False,
                    "propertyObservations": 7,
                    "totalObservations": 10,
                },
                {
                    "propertyName": "name",
                    "propertyTypes": ["String"],
                    "mandatory": True,
                    "propertyObservations": 10,
                    "totalObservations": 10,
                },
            ],
        ),
        # value-scan for Person.born — type counts (APOC)
        mock_execute_query(
            [
                {"type_name": "Long", "type_count": 5},
                {"type_name": "String", "type_count": 2},
            ],
        ),
        # value-scan for Person.born — histogram
        mock_execute_query(
            [
                {"value": "1985", "value_count": 3},
                {"value": "1980", "value_count": 2},
                {"value": "unknown", "value_count": 2},
            ],
        ),
        # value-scan for Person.name — type counts
        mock_execute_query(
            [{"type_name": "String", "type_count": 10}],
        ),
        # value-scan for Person.name — histogram
        mock_execute_query(
            [
                {"value": "Alice", "value_count": 3},
                {"value": "Bob", "value_count": 3},
                {"value": "Carol", "value_count": 4},
            ],
        ),
    ]

    def side_effect(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        cypher = args[0] if args else kwargs.get("query_", kwargs.get("query", ""))
        # Dedicated instance-count queries are served out of band so existing
        # strict-ordered response lists stay valid (E46.x count fix).
        if "count(n) AS count" in cypher or "count(r) AS count" in cypher:
            return mock_execute_query([{"count": 0}], ["count"])
        # Property present-count queries (ADR-036) are likewise served out of
        # band so the APOC no-scan correction does not shift response indices.
        if "AS present_count" in cypher:
            return mock_execute_query([{"present_count": 0}], ["present_count"])
        result = responses[call_count]
        call_count += 1
        return result

    driver.execute_query.side_effect = side_effect

    profile = Neo4jInspector(
        strategy=Neo4jInspectionStrategy.APOC, value_counts_top_n=10
    ).inspect(driver)
    person = profile.node_type_profiles["Person"]

    born = person.property_profiles["born"]
    assert born.observed_type_counts == {"Long": 5, "String": 2}
    assert born.value_distribution is not None
    assert born.value_distribution.count == 7  # present_count
    assert born.value_distribution.histogram == {"1985": 3, "1980": 2, "unknown": 2}
    assert born.value_distribution.sample_complete is True

    name = person.property_profiles["name"]
    assert name.observed_type_counts == {"String": 10}
    assert name.value_distribution is not None
    assert name.value_distribution.count == 10


def test_value_scan_empty_type_rows_preserves_fallback_present_count() -> None:
    """Empty type-count rows + positive APOC fallback → honest degradation.

    Regression guard (review E46.1/E46.2 issue #5): if the runtime-type
    aggregation classifies nothing (e.g. apoc.meta.cypher.type yields NULL and
    the GROUP BY drops every row) the scan must NOT zero out present_count.
    It keeps APOC's propertyObservations, reports observed_type_counts == {}
    and value_distribution is None (never invent, never silently regress
    presence — ADR-035 §5).
    """
    driver = MagicMock()
    call_count = 0
    responses = [
        # node_labels (explicit APOC — no detection)
        mock_execute_query([{"label": "Person"}], ["label"]),
        # rel_types
        mock_execute_query([], []),
        # constraints
        mock_execute_query([], []),
        # node_properties for Person.born: APOC says 7 present out of 10
        mock_execute_query(
            [
                {
                    "propertyName": "born",
                    "propertyTypes": ["Long"],
                    "mandatory": False,
                    "propertyObservations": 7,
                    "totalObservations": 10,
                },
            ],
        ),
        # value-scan type counts — EMPTY (type fn classified nothing)
        mock_execute_query([], []),
        # NOTE: no histogram response — the scan must short-circuit before it.
    ]

    def side_effect(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        cypher = args[0] if args else kwargs.get("query_", kwargs.get("query", ""))
        if "count(n) AS count" in cypher or "count(r) AS count" in cypher:
            return mock_execute_query([{"count": 0}], ["count"])
        result = responses[call_count]
        call_count += 1
        return result

    driver.execute_query.side_effect = side_effect

    profile = Neo4jInspector(
        strategy=Neo4jInspectionStrategy.APOC, value_counts_top_n=10
    ).inspect(driver)
    born = profile.node_type_profiles["Person"].property_profiles["born"]

    # present_count keeps the APOC fallback — NOT zeroed.
    assert born.present_count == 7
    # No counts could be derived — honest empty / None.
    assert born.observed_type_counts == {}
    assert born.value_distribution is None
    # The histogram query was never issued (short-circuit before it): only
    # labels + rel_types + constraints + props + type-counts = 5 non-count calls.
    assert call_count == 5, f"Expected 5 queries (no histogram), got {call_count}"


def test_rel_type_counts_populated_with_apoc() -> None:
    """APOC + value_counts_top_n → rel property observed_type_counts populated."""
    driver = MagicMock()
    call_count = 0
    responses = [
        # node_labels (no detection — explicit APOC)
        mock_execute_query([], []),
        # rel_types
        mock_execute_query([{"relationshipType": "ACTED_IN"}], ["relationshipType"]),
        # constraints
        mock_execute_query([], []),
        # rel_properties for ACTED_IN
        mock_execute_query(
            [
                {
                    "propertyName": "role",
                    "propertyTypes": ["String"],
                    "mandatory": True,
                    "propertyObservations": 3,
                    "totalObservations": 3,
                },
            ],
        ),
        # value-scan for ACTED_IN.role — type counts
        mock_execute_query([{"type_name": "String", "type_count": 3}]),
        # value-scan for ACTED_IN.role — histogram
        mock_execute_query(
            [
                {"value": "Lead", "value_count": 2},
                {"value": "Supporting", "value_count": 1},
            ]
        ),
        # endpoint_labels for ACTED_IN
        mock_execute_query([{"source_labels": [], "target_labels": []}]),
    ]

    def side_effect(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        cypher = args[0] if args else kwargs.get("query_", kwargs.get("query", ""))
        # Dedicated instance-count queries are served out of band so existing
        # strict-ordered response lists stay valid (E46.x count fix).
        if "count(n) AS count" in cypher or "count(r) AS count" in cypher:
            return mock_execute_query([{"count": 0}], ["count"])
        # Property present-count queries (ADR-036) are likewise served out of
        # band so the APOC no-scan correction does not shift response indices.
        if "AS present_count" in cypher:
            return mock_execute_query([{"present_count": 0}], ["present_count"])
        result = responses[call_count]
        call_count += 1
        return result

    driver.execute_query.side_effect = side_effect

    profile = Neo4jInspector(
        strategy=Neo4jInspectionStrategy.APOC, value_counts_top_n=10
    ).inspect(driver)
    role = profile.rel_type_profiles["ACTED_IN"].property_profiles["role"]
    assert role.observed_type_counts == {"String": 3}
    assert role.value_distribution is not None
    assert role.value_distribution.count == 3


def test_reconciliation_invariant_holds() -> None:
    """sum(type_counts) == value_distribution.count == present_count (ADR-035 §2)."""
    driver = MagicMock()
    call_count = 0
    responses = [
        # node_labels (no detection — explicit APOC)
        mock_execute_query([{"label": "Item"}], ["label"]),
        mock_execute_query([], []),
        mock_execute_query([], []),
        # node_properties for Item.score: 8 present out of 10
        mock_execute_query(
            [
                {
                    "propertyName": "score",
                    "propertyTypes": ["Long", "Float"],
                    "mandatory": False,
                    "propertyObservations": 8,
                    "totalObservations": 10,
                }
            ]
        ),
        # type counts for Item.score
        mock_execute_query(
            [
                {"type_name": "Long", "type_count": 6},
                {"type_name": "Double", "type_count": 2},
            ]
        ),
        # histogram for Item.score (all 8 fit, no truncation)
        mock_execute_query(
            [
                {"value": "1", "value_count": 3},
                {"value": "2", "value_count": 3},
                {"value": "1.5", "value_count": 1},
                {"value": "2.5", "value_count": 1},
            ]
        ),
    ]

    def side_effect(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        cypher = args[0] if args else kwargs.get("query_", kwargs.get("query", ""))
        # Dedicated instance-count queries are served out of band so existing
        # strict-ordered response lists stay valid (E46.x count fix).
        if "count(n) AS count" in cypher or "count(r) AS count" in cypher:
            return mock_execute_query([{"count": 0}], ["count"])
        # Property present-count queries (ADR-036) are likewise served out of
        # band so the APOC no-scan correction does not shift response indices.
        if "AS present_count" in cypher:
            return mock_execute_query([{"present_count": 0}], ["present_count"])
        result = responses[call_count]
        call_count += 1
        return result

    driver.execute_query.side_effect = side_effect

    profile = Neo4jInspector(
        strategy=Neo4jInspectionStrategy.APOC, value_counts_top_n=20
    ).inspect(driver)
    score = profile.node_type_profiles["Item"].property_profiles["score"]

    assert score.present_count == 8
    assert score.value_distribution is not None
    type_total = sum(score.observed_type_counts.values())
    assert type_total == score.value_distribution.count == score.present_count, (
        f"Reconciliation failed: type_total={type_total}, "
        f"hist_count={score.value_distribution.count}, "
        f"present_count={score.present_count}"
    )


def test_observed_type_counts_subset_of_observed_types() -> None:
    """set(observed_type_counts) ⊆ set(observed_types) (ADR-035 §3)."""
    driver = MagicMock()
    call_count = 0
    responses = [
        # node_labels (no detection — explicit APOC)
        mock_execute_query([{"label": "Node"}], ["label"]),
        mock_execute_query([], []),
        mock_execute_query([], []),
        mock_execute_query(
            [
                {
                    "propertyName": "val",
                    "propertyTypes": ["String", "Long"],
                    "mandatory": False,
                    "propertyObservations": 4,
                    "totalObservations": 5,
                }
            ]
        ),
        mock_execute_query(
            [
                {"type_name": "String", "type_count": 3},
                {"type_name": "Long", "type_count": 1},
            ]
        ),
        mock_execute_query(
            [
                {"value": "a", "value_count": 2},
                {"value": "b", "value_count": 1},
                {"value": "1", "value_count": 1},
            ]
        ),
    ]

    def side_effect(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        cypher = args[0] if args else kwargs.get("query_", kwargs.get("query", ""))
        # Dedicated instance-count queries are served out of band so existing
        # strict-ordered response lists stay valid (E46.x count fix).
        if "count(n) AS count" in cypher or "count(r) AS count" in cypher:
            return mock_execute_query([{"count": 0}], ["count"])
        # Property present-count queries (ADR-036) are likewise served out of
        # band so the APOC no-scan correction does not shift response indices.
        if "AS present_count" in cypher:
            return mock_execute_query([{"present_count": 0}], ["present_count"])
        result = responses[call_count]
        call_count += 1
        return result

    driver.execute_query.side_effect = side_effect

    profile = Neo4jInspector(
        strategy=Neo4jInspectionStrategy.APOC, value_counts_top_n=10
    ).inspect(driver)
    val = profile.node_type_profiles["Node"].property_profiles["val"]

    assert set(val.observed_type_counts) <= set(val.observed_types), (
        f"observed_type_counts keys {set(val.observed_type_counts)} "
        f"not a subset of observed_types {set(val.observed_types)}"
    )


def test_cypher_strategy_scalar_histogram_fallback_no_type_counts() -> None:
    """CYPHER + value_counts_top_n → scalar histogram fallback, no type counts.

    type counts need apoc.meta.cypher.type which
    pure-CYPHER lacks, so observed_type_counts stays {}.  But a scalar-only
    histogram is restored via the toStringOrNull pure-Cypher fallback, so a
    scalar property like Tag.name DOES get a value_distribution.
    """
    driver = MagicMock()
    call_count = 0
    responses = [
        # node_labels (no strategy detection — explicit CYPHER)
        mock_execute_query([{"label": "Tag"}], ["label"]),
        # rel_types
        mock_execute_query([], []),
        # constraints
        mock_execute_query([], []),
        # node_properties for Tag
        mock_execute_query(
            [
                {
                    "propertyName": "name",
                    "propertyTypes": [],
                    "mandatory": True,
                    "propertyObservations": 6,
                    "totalObservations": 6,
                }
            ]
        ),
    ]

    def side_effect(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        cypher = args[0] if args else kwargs.get("query_", kwargs.get("query", ""))
        # Dedicated instance-count queries are served out of band so existing
        # strict-ordered response lists stay valid (E46.x count fix).
        if "count(n) AS count" in cypher or "count(r) AS count" in cypher:
            return mock_execute_query([{"count": 0}], ["count"])
        # Property present-count queries (ADR-036) are likewise served out of
        # band so the APOC no-scan correction does not shift response indices.
        if "AS present_count" in cypher:
            return mock_execute_query([{"present_count": 0}], ["present_count"])
        # E46.6: the pure-Cypher fallback histogram (toStringOrNull) is served out
        # of band — Tag.name has 6 scalar values across 3 distinct strings.
        if "toStringOrNull" in cypher:
            return mock_execute_query(
                [
                    {"value": "a", "value_count": 3},
                    {"value": "b", "value_count": 2},
                    {"value": "c", "value_count": 1},
                ],
            )
        result = responses[call_count]
        call_count += 1
        return result

    driver.execute_query.side_effect = side_effect

    profile = Neo4jInspector(
        strategy=Neo4jInspectionStrategy.CYPHER, value_counts_top_n=10
    ).inspect(driver)
    name = profile.node_type_profiles["Tag"].property_profiles["name"]

    # CYPHER: no APOC → no runtime-type function → no type counts.
    assert name.observed_type_counts == {}
    # E46.6: the scalar histogram fallback IS populated.
    assert name.value_distribution is not None
    assert name.value_distribution.count == 6  # pure-Cypher present_count
    assert name.value_distribution.histogram == {"a": 3, "b": 2, "c": 1}
    assert name.value_distribution.sample_complete is True
    # present_count comes from the pure-Cypher property scan (unchanged).
    assert name.present_count == 6
    # 4 schema calls: labels + rel_types + constraints + props.  The fallback
    # histogram (and instance-count) queries are intercepted out of band.
    assert call_count == 4, f"Expected 4 schema queries, got {call_count}"


def test_cypher_strategy_list_property_yields_no_histogram() -> None:
    """CYPHER + a list-valued property → value_distribution is None (no crash).

    Hard regression guard for the discovered toString(list) failure.  On the
    pure-Cypher fallback toStringOrNull returns null for a list, so every row is
    dropped and the scalar histogram is empty → BoundedDistribution is None.
    The inspection completes without a TypeError.
    """
    driver = MagicMock()
    call_count = 0
    responses = [
        mock_execute_query([{"label": "Movie"}], ["label"]),
        mock_execute_query([], []),
        mock_execute_query([], []),
        mock_execute_query(
            [
                {
                    "propertyName": "genres",
                    "propertyTypes": [],
                    "mandatory": True,
                    "propertyObservations": 4,
                    "totalObservations": 4,
                }
            ]
        ),
    ]

    def side_effect(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        cypher = args[0] if args else kwargs.get("query_", kwargs.get("query", ""))
        if "count(n) AS count" in cypher or "count(r) AS count" in cypher:
            return mock_execute_query([{"count": 0}], ["count"])
        # The toStringOrNull histogram drops every (list) value → no rows.
        if "toStringOrNull" in cypher:
            return mock_execute_query([], [])
        result = responses[call_count]
        call_count += 1
        return result

    driver.execute_query.side_effect = side_effect

    profile = Neo4jInspector(
        strategy=Neo4jInspectionStrategy.CYPHER, value_counts_top_n=10
    ).inspect(driver)
    genres = profile.node_type_profiles["Movie"].property_profiles["genres"]

    # No scalar values → no histogram (honest None), no type counts, no crash.
    assert genres.observed_type_counts == {}
    assert genres.value_distribution is None
    # Presence is preserved from the pure-Cypher scan.
    assert genres.present_count == 4


def test_cypher_strategy_list_property_does_not_crash_via_real_query() -> None:
    """The fallback histogram query NEVER emits a crashing toString(list).

    Stronger guard than the response-shape test: assert the actual Cypher issued
    on the fallback path uses toStringOrNull (list-safe) and never plain
    toString( on the property value.
    """
    driver = MagicMock()
    responses = [
        mock_execute_query([{"label": "Movie"}], ["label"]),
        mock_execute_query([], []),
        mock_execute_query([], []),
        mock_execute_query(
            [
                {
                    "propertyName": "genres",
                    "propertyTypes": [],
                    "mandatory": True,
                    "propertyObservations": 4,
                    "totalObservations": 4,
                }
            ]
        ),
    ]
    call_count = 0

    def side_effect(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        cypher = args[0] if args else kwargs.get("query_", kwargs.get("query", ""))
        if "count(n) AS count" in cypher or "count(r) AS count" in cypher:
            return mock_execute_query([{"count": 0}], ["count"])
        if "toStringOrNull" in cypher:
            return mock_execute_query([], [])
        result = responses[call_count]
        call_count += 1
        return result

    driver.execute_query.side_effect = side_effect

    Neo4jInspector(
        strategy=Neo4jInspectionStrategy.CYPHER, value_counts_top_n=10
    ).inspect(driver)

    issued = [str(c) for c in driver.execute_query.call_args_list]
    # The list-safe key was used on the fallback histogram.
    assert any("toStringOrNull(n.`genres`)" in c for c in issued)
    # Plain toString(<property>) — the crashing form — was never issued.
    assert not any("toString(n.`genres`)" in c for c in issued)


def test_schema_strategy_without_apoc_scalar_histogram_fallback() -> None:
    """SCHEMA + value_counts_top_n but no APOC → scalar histogram fallback.

    SCHEMA is the auto-detected fallback precisely when apoc.meta is absent.  The
    type-count query needs apoc.meta.cypher.type, so observed_type_counts stays
    {} (no APOC).  E46.6: a scalar-only pure-Cypher histogram (toStringOrNull) is
    still produced — the APOC-keyed histogram (apoc.convert.toJson) is NOT issued.
    observed_types still comes from db.schema.* (the SCHEMA contract).
    """
    driver = MagicMock()
    call_count = 0
    responses = [
        # node_labels (explicit SCHEMA — no strategy detection)
        mock_execute_query([{"label": "Tag"}], ["label"]),
        # rel_types
        mock_execute_query([], []),
        # bulk db.schema node types
        mock_execute_query(
            [
                {
                    "nodeType": ":`Tag`",
                    "nodeLabels": ["Tag"],
                    "propertyName": "name",
                    "propertyTypes": ["String"],
                    "mandatory": True,
                },
            ],
        ),
        # bulk db.schema rel types (none)
        mock_execute_query([]),
        # _is_apoc_available probe: apoc.meta absent
        mock_execute_query([{"cnt": 0}], ["cnt"]),
        # constraints
        mock_execute_query([], []),
        # CypherNodePropertiesQuery for Tag (true counts, types from db.schema)
        mock_execute_query(
            [
                {
                    "propertyName": "name",
                    "propertyTypes": [],
                    "mandatory": True,
                    "propertyObservations": 6,
                    "totalObservations": 6,
                },
            ],
        ),
    ]

    def side_effect(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        cypher = args[0] if args else kwargs.get("query_", kwargs.get("query", ""))
        # Dedicated instance-count queries are served out of band so existing
        # strict-ordered response lists stay valid (E46.x count fix).
        if "count(n) AS count" in cypher or "count(r) AS count" in cypher:
            return mock_execute_query([{"count": 0}], ["count"])
        # Property present-count queries (ADR-036) are likewise served out of
        # band so the APOC no-scan correction does not shift response indices.
        if "AS present_count" in cypher:
            return mock_execute_query([{"present_count": 0}], ["present_count"])
        # E46.6 fallback histogram (served out of band).
        if "toStringOrNull" in cypher:
            return mock_execute_query(
                [
                    {"value": "x", "value_count": 4},
                    {"value": "y", "value_count": 2},
                ],
            )
        result = responses[call_count]
        call_count += 1
        return result

    driver.execute_query.side_effect = side_effect

    profile = Neo4jInspector(
        strategy=Neo4jInspectionStrategy.SCHEMA, value_counts_top_n=10
    ).inspect(driver)
    name = profile.node_type_profiles["Tag"].property_profiles["name"]

    # No APOC → no runtime-type function → no type counts.
    assert name.observed_type_counts == {}
    # E46.6: the scalar histogram fallback IS populated.
    assert name.value_distribution is not None
    assert name.value_distribution.histogram == {"x": 4, "y": 2}
    assert name.value_distribution.count == 6
    # Types still come from db.schema.* (SCHEMA strategy contract).
    assert name.observed_types == ["String"]
    # present_count from the pure-Cypher scan (unchanged).
    assert name.present_count == 6
    # 7 schema calls — the fallback histogram + instance-count queries are
    # intercepted out of band and not tallied here.
    assert call_count == 7, f"Expected 7 schema queries, got {call_count}"
    # Guard: no APOC-keyed value-scan query was issued (only the pure-Cypher
    # toStringOrNull fallback).
    for call in driver.execute_query.call_args_list:
        assert "apoc.meta.cypher.type" not in str(call)
        assert "apoc.convert.toJson" not in str(call)


def test_histogram_truncates_correctly() -> None:
    """When top_n < distinct values, histogram truncates with other_count set."""
    driver = MagicMock()
    call_count = 0
    responses = [
        # node_labels (no detection — explicit APOC)
        mock_execute_query([{"label": "Doc"}], ["label"]),
        mock_execute_query([], []),
        mock_execute_query([], []),
        mock_execute_query(
            [
                {
                    "propertyName": "tag",
                    "propertyTypes": ["String"],
                    "mandatory": True,
                    "propertyObservations": 10,
                    "totalObservations": 10,
                }
            ]
        ),
        # type counts: all String
        mock_execute_query([{"type_name": "String", "type_count": 10}]),
        # histogram: top_n=3, but 5 distinct values (top 3 returned, other_count=2)
        mock_execute_query(
            [
                {"value": "a", "value_count": 4},
                {"value": "b", "value_count": 2},
                {"value": "c", "value_count": 2},
                # 'd' (count=1) and 'e' (count=1) fall into other_count
            ]
        ),
    ]

    def side_effect(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        cypher = args[0] if args else kwargs.get("query_", kwargs.get("query", ""))
        # Dedicated instance-count queries are served out of band so existing
        # strict-ordered response lists stay valid (E46.x count fix).
        if "count(n) AS count" in cypher or "count(r) AS count" in cypher:
            return mock_execute_query([{"count": 0}], ["count"])
        # Property present-count queries (ADR-036) are likewise served out of
        # band so the APOC no-scan correction does not shift response indices.
        if "AS present_count" in cypher:
            return mock_execute_query([{"present_count": 0}], ["present_count"])
        result = responses[call_count]
        call_count += 1
        return result

    driver.execute_query.side_effect = side_effect

    profile = Neo4jInspector(
        strategy=Neo4jInspectionStrategy.APOC, value_counts_top_n=3
    ).inspect(driver)
    tag = profile.node_type_profiles["Doc"].property_profiles["tag"]

    assert tag.value_distribution is not None
    assert tag.value_distribution.sample_complete is False
    assert tag.value_distribution.limit == 3
    # The inspector receives exactly what the DB returned (3 rows); the remaining
    # 2 counts are inferred: other_count = present_count - sum(hist.values()).
    assert tag.value_distribution.other_count == 2  # 10 - (4+2+2) = 2
    assert tag.value_distribution.count == 10
    # Type counts exact — unaffected by histogram truncation.
    assert tag.observed_type_counts == {"String": 10}


def test_neo4j_validate_database(graph_definition: GraphDefinition) -> None:
    driver = MagicMock()

    call_count = 0
    responses = [
        # _detect_strategy (apoc.meta present → APOC)
        mock_execute_query([{"cnt": 1}], ["cnt"]),
        # node_labels
        mock_execute_query(
            [{"label": "Person"}, {"label": "Movie"}],
            ["label"],
        ),
        # rel_types
        mock_execute_query(
            [{"relationshipType": "ACTED_IN"}],
            ["relationshipType"],
        ),
        # constraints (read before profiles so they can be cross-referenced)
        mock_execute_query([], []),
        # node_properties for Movie
        mock_execute_query(
            [
                {
                    "propertyName": "title",
                    "propertyTypes": ["String"],
                    "mandatory": True,
                    "propertyObservations": 50,
                    "totalObservations": 50,
                },
                {
                    "propertyName": "year",
                    "propertyTypes": ["Long"],
                    "mandatory": True,
                    "propertyObservations": 50,
                    "totalObservations": 50,
                },
            ],
        ),
        # node_properties for Person
        mock_execute_query(
            [
                {
                    "propertyName": "name",
                    "propertyTypes": ["String"],
                    "mandatory": True,
                    "propertyObservations": 100,
                    "totalObservations": 100,
                },
                {
                    "propertyName": "age",
                    "propertyTypes": ["Long"],
                    "mandatory": True,
                    "propertyObservations": 100,
                    "totalObservations": 100,
                },
                {
                    "propertyName": "email",
                    "propertyTypes": ["String"],
                    "mandatory": False,
                    "propertyObservations": 50,
                    "totalObservations": 100,
                },
            ],
        ),
        # rel_properties for ACTED_IN
        mock_execute_query(
            [
                {
                    "propertyName": "role",
                    "propertyTypes": ["String"],
                    "mandatory": True,
                    "propertyObservations": 200,
                    "totalObservations": 200,
                },
            ],
        ),
        # endpoint_labels for ACTED_IN (queried first to identify sources)
        mock_execute_query(
            [{"source_labels": ["Person"], "target_labels": ["Movie"]}],
        ),
        # cardinality for ACTED_IN against Person (confirmed source label)
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

    def side_effect(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        cypher = args[0] if args else kwargs.get("query_", kwargs.get("query", ""))
        # Dedicated instance-count queries are served out of band so existing
        # strict-ordered response lists stay valid (E46.x count fix).
        if "count(n) AS count" in cypher or "count(r) AS count" in cypher:
            return mock_execute_query([{"count": 0}], ["count"])
        # Property present-count queries (ADR-036) are likewise served out of
        # band so the APOC no-scan correction does not shift response indices.
        if "AS present_count" in cypher:
            return mock_execute_query([{"present_count": 0}], ["present_count"])
        result = responses[call_count]
        call_count += 1
        return result

    driver.execute_query.side_effect = side_effect

    result = validate_database(driver, graph_definition)
    assert result.is_valid, [str(e) for e in result.errors]
