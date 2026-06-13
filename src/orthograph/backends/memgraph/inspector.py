"""Memgraph graph inspector (stateless; connection injected per call).

Parity gaps vs. NetworkX / Neo4j — documented explicitly:

  * ``NodeTypeProfile.count`` is always 0: ``schema.node_type_properties()``
    yields no observation counts.
  * ``RelationshipTypeProfile.count`` is always 0, same reason.
  * ``PropertyProfile.present_count`` / ``.total_count`` use a mandatory
    heuristic (``present=int(mandatory), total=1``) because the Memgraph schema
    procedures yield a boolean, not observation counts.

``cardinality_stats`` and ``source_labels``/``target_labels`` ARE populated
(using the vendor-neutral shared Cypher).
"""

from typing import Any

from orthograph.backends.memgraph.queries import (
    MemgraphCardinalityQuery,
    MemgraphConstraintsQuery,
    MemgraphEndpointLabelsQuery,
    MemgraphNodePropertiesQuery,
    MemgraphRelPropertiesQuery,
)
from orthograph.comparison.engine import compare
from orthograph.diagnostics.result import ValidationResult
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_profile.inspection import CypherInspector
from orthograph.graph_profile.models import (
    ConstraintInfo,
    GraphProfile,
    NodeTypeProfile,
    PropertyProfile,
    RelationshipTypeProfile,
)


class MemgraphInspector(CypherInspector):
    """Inspects a Memgraph database and produces a :class:`GraphProfile`.

    Stateless: the driver is passed to :meth:`inspect` per call, never stored.
    """

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def inspect(self, connection: Any) -> GraphProfile:
        """Inspect the Memgraph database and return a :class:`GraphProfile`."""
        node_profiles = self._build_node_profiles(connection)
        rel_profiles = self._build_rel_profiles(connection)
        constraints = self._get_constraints(connection)

        return GraphProfile(
            source="memgraph",
            node_type_profiles=node_profiles,
            rel_type_profiles=rel_profiles,
            constraints=constraints,
        )

    # ------------------------------------------------------------------
    # Internal — profile builders
    # ------------------------------------------------------------------

    def _build_node_profiles(self, connection: Any) -> dict[str, NodeTypeProfile]:
        rows = self._run_query(connection, MemgraphNodePropertiesQuery)

        label_props: dict[str, list[Any]] = {}
        for row in rows:
            for lbl in row.node_labels:
                label_props.setdefault(lbl, [])

            if not row.property_name:
                raw_type = row.node_type
                lbl = raw_type.strip(":` ")
                label_props.setdefault(lbl, [])
                continue

            raw_type = row.node_type
            lbl = raw_type.strip(":` ")
            label_props.setdefault(lbl, []).append(row)

        profiles: dict[str, NodeTypeProfile] = {}
        for label, prop_rows in sorted(label_props.items()):
            props: dict[str, PropertyProfile] = {}
            for r in prop_rows:
                name = r.property_name
                props[name] = PropertyProfile(
                    name=name,
                    present_count=1 if r.mandatory else 0,
                    total_count=1,
                    observed_types=r.property_types,
                )
            profiles[label] = NodeTypeProfile(
                label=label, count=0, property_profiles=props
            )

        return profiles

    def _build_rel_profiles(
        self, connection: Any
    ) -> dict[str, RelationshipTypeProfile]:
        rows = self._run_query(connection, MemgraphRelPropertiesQuery)

        type_rows: dict[str, list[Any]] = {}
        for row in rows:
            raw_type = row.rel_type
            rel_type = raw_type.strip(":` ")
            type_rows.setdefault(rel_type, []).append(row)

        profiles: dict[str, RelationshipTypeProfile] = {}
        for rel_type, prop_rows in sorted(type_rows.items()):
            props: dict[str, PropertyProfile] = {}
            for r in prop_rows:
                name = r.property_name
                if not name:
                    continue
                props[name] = PropertyProfile(
                    name=name,
                    present_count=1 if r.mandatory else 0,
                    total_count=1,
                    observed_types=r.property_types,
                )

            profiles[rel_type] = RelationshipTypeProfile(
                rel_type=rel_type,
                count=0,  # Parity gap — unavailable from schema procedures
                property_profiles=props,
            )

        for rel_type in list(profiles.keys()):
            profiles[rel_type] = self._enrich_with_endpoints_and_cardinality(
                connection,
                profiles[rel_type],
                MemgraphEndpointLabelsQuery,
                MemgraphCardinalityQuery,
            )

        return profiles

    def _get_constraints(self, connection: Any) -> list[ConstraintInfo]:
        rows = self._run_query(connection, MemgraphConstraintsQuery)
        return [
            ConstraintInfo(
                name=None,
                constraint_type=row.constraint_type,
                entity_type=row.entity_type,
                labels=[row.label] if row.label else [],
                properties=row.properties,
            )
            for row in rows
        ]


def validate_database(
    connection: Any,
    graph_definition: GraphDefinition,
) -> ValidationResult:
    """Validate a Memgraph database against a GraphDefinition."""
    profile = MemgraphInspector().inspect(connection)
    return compare(profile, graph_definition)
