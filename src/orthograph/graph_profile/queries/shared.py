"""Vendor-neutral Cypher introspection queries.

Uses only plain ``MATCH``/``RETURN``; no APOC or vendor-specific procedures.
Runs identically on any Cypher backend.
"""

from typing import Any

from orthograph.cypher.base_models import CypherReadQuery
from orthograph.cypher.bindings import NoParams
from orthograph.graph_profile.models import (
    CardinalityIdentifiers,
    CardinalityStats,
    EndpointLabelsRow,
    RelTypeIdentifiers,
)


def coerce_types(raw_types: Any) -> list[str]:
    """Normalise a ``propertyTypes`` value to a list of strings."""
    if isinstance(raw_types, list):
        return raw_types
    return [raw_types] if raw_types else []


class InspectCardinalityQuery(CypherReadQuery[NoParams, CardinalityStats]):
    """Cardinality statistics for one (label, rel_type) pair."""

    Params = NoParams
    Output = CardinalityStats
    name = "inspect.cardinality"
    Identifiers = CardinalityIdentifiers
    cypher_template = (
        "MATCH (n:`<<label>>`)"
        " OPTIONAL MATCH (n)-[r:`<<rel_type>>`]->()"
        " WITH n, count(r) AS degree"
        " RETURN min(degree) AS min_degree, max(degree) AS max_degree,"
        " avg(degree) AS avg_degree, count(n) AS sample_size"
    )

    def materialize(self, raw: Any) -> CardinalityStats:
        return CardinalityStats(
            min_degree=raw["min_degree"],
            max_degree=raw["max_degree"],
            avg_degree=float(raw["avg_degree"]),
            sample_size=raw["sample_size"],
        )


class InspectEndpointLabelsQuery(CypherReadQuery[NoParams, EndpointLabelsRow]):
    """Collect distinct source and target labels for a relationship type."""

    Params = NoParams
    Output = EndpointLabelsRow
    name = "inspect.endpoint_labels"
    Identifiers = RelTypeIdentifiers
    cypher_template = (
        "MATCH (src)-[r:`<<rel_type>>`]->(tgt)"
        " RETURN DISTINCT labels(src) AS source_labels, labels(tgt) AS target_labels"
    )

    def materialize(self, raw: Any) -> EndpointLabelsRow:
        return EndpointLabelsRow(
            source_labels=list(raw["source_labels"]),
            target_labels=list(raw["target_labels"]),
        )
