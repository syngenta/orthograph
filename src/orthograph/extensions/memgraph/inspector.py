"""Memgraph graph inspector using the GraphProfile model.

``MemgraphQueries`` (the old untyped helper class) has been retired
(ADR-009 / E17 T8).  Introspection now uses typed ``CypherReadQuery``
subclasses registered in an internal ``QueryCatalogue``.

Parity gaps vs. NetworkX / Neo4j — documented explicitly:

  * ``NodeTypeProfile.count`` is always 0:
    ``schema.node_type_properties()`` yields no observation counts.
  * ``RelationshipTypeProfile.count`` is always 0, same reason.
  * ``PropertyProfile.present_count`` / ``.total_count`` use a mandatory
    heuristic (``present=int(mandatory), total=1``) because the Memgraph
    schema procedures yield a boolean, not observation counts.

``cardinality_stats`` and ``source_labels``/``target_labels`` ARE populated
(using the same Cypher as Neo4j — the queries are identical across backends).
"""

from typing import Any

from orthograph.catalogue.registry import QueryCatalogue
from orthograph.core.exceptions import ValidationResult
from orthograph.core.graph_data_model import GraphDataModel
from orthograph.extensions.base import GraphInspector
from orthograph.extensions.cypher.bindings import NoParams
from orthograph.extensions.memgraph.queries import (
    MemgraphCardinalityQuery,
    MemgraphConstraintsQuery,
    MemgraphEndpointLabelsQuery,
    MemgraphNodePropertiesQuery,
    MemgraphRelPropertiesQuery,
    build_memgraph_catalogue,
)
from orthograph.extensions.models import (
    CardinalityStats,
    ConstraintInfo,
    GraphProfile,
    NodeTypeProfile,
    PropertyProfile,
    RelationshipTypeProfile,
)
from orthograph.extensions.validation import validate_profile


class MemgraphInspector(GraphInspector):
    """Inspects a Memgraph database and produces a GraphProfile."""

    def __init__(self, driver: Any) -> None:
        self._driver = driver
        self._catalogue: QueryCatalogue = build_memgraph_catalogue()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def inspect(self) -> GraphProfile:
        """Inspect the Memgraph database and return a complete GraphProfile."""
        node_profiles = self._build_node_profiles()
        rel_profiles = self._build_rel_profiles()
        constraints = self._get_constraints()

        return GraphProfile(
            source="memgraph",
            node_type_profiles=node_profiles,
            rel_type_profiles=rel_profiles,
            constraints=constraints,
        )

    # ------------------------------------------------------------------
    # Internal — query execution helpers
    # ------------------------------------------------------------------

    def _run(self, query: str) -> list[dict[str, Any]]:
        """Execute a raw Cypher string and return results as list of dicts."""
        records, _, _ = self._driver.execute_query(query)
        return [dict(record) for record in records]

    def _run_query(
        self, query: Any, identifiers: dict[str, str] | None = None
    ) -> list[Any]:
        """Build a typed query instance, render its Cypher, and execute it."""
        instance = query(identifiers=identifiers or {})
        cypher, _ = instance.build(NoParams())
        rows = self._run(cypher)
        return [instance.materialize(row) for row in rows]

    # ------------------------------------------------------------------
    # Internal — profile builders
    # ------------------------------------------------------------------

    def _build_node_profiles(self) -> dict[str, NodeTypeProfile]:
        rows = self._run_query(MemgraphNodePropertiesQuery)

        # Collect labels and per-label property rows
        label_props: dict[str, list[Any]] = {}
        for row in rows:
            # Ensure every label from nodeLabels is represented even if
            # this row carries no property (propertyName is None).
            for lbl in row.node_labels:
                label_props.setdefault(lbl, [])

            if not row.property_name:
                # Row indicates the label exists but has no properties
                # (or Memgraph emitted a label-only sentinel row).
                raw_type = row.node_type
                lbl = raw_type.strip(":` ")
                label_props.setdefault(lbl, [])
                continue

            # Primary key: strip the raw nodeType string to recover the label.
            raw_type = row.node_type
            lbl = raw_type.strip(":` ")
            label_props.setdefault(lbl, []).append(row)

        profiles: dict[str, NodeTypeProfile] = {}
        for label, prop_rows in sorted(label_props.items()):
            props: dict[str, PropertyProfile] = {}
            for r in prop_rows:
                name = r.property_name
                # Parity gap: Memgraph yields mandatory bool, not counts.
                # present_count/total_count use the mandatory heuristic.
                props[name] = PropertyProfile(
                    name=name,
                    present_count=1 if r.mandatory else 0,
                    total_count=1,
                    observed_types=r.property_types,
                )
            # Parity gap: count is unavailable from schema procedures.
            profiles[label] = NodeTypeProfile(
                label=label, count=0, property_profiles=props
            )

        return profiles

    def _build_rel_profiles(self) -> dict[str, RelationshipTypeProfile]:
        rows = self._run_query(MemgraphRelPropertiesQuery)

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

            # Cardinality parity — use first node label that has data
            # We don't have the node labels here, so we must get them first
            # from the endpoint query, or fall back to None if no node data.
            # Cardinality is queried below after endpoint labels are available.
            profiles[rel_type] = RelationshipTypeProfile(
                rel_type=rel_type,
                count=0,  # Parity gap — unavailable from schema procedures
                property_profiles=props,
            )

        # Enrich each rel profile with cardinality + endpoint labels
        for rel_type in list(profiles.keys()):
            profiles[rel_type] = self._enrich_rel_profile(profiles[rel_type])

        return profiles

    def _enrich_rel_profile(
        self, profile: RelationshipTypeProfile
    ) -> RelationshipTypeProfile:
        """Add cardinality_stats and source/target labels to a rel profile."""
        rel_type = profile.rel_type

        # Endpoint labels
        source_labels: set[str] = set()
        target_labels: set[str] = set()
        endpoint_rows = self._run_query(
            MemgraphEndpointLabelsQuery, identifiers={"rel_type": rel_type}
        )
        for erow in endpoint_rows:
            source_labels.update(erow.source_labels)
            target_labels.update(erow.target_labels)

        # Cardinality — try each source label
        card_stats: CardinalityStats | None = None
        for label in sorted(source_labels):
            card_rows: list[CardinalityStats] = self._run_query(
                MemgraphCardinalityQuery,
                identifiers={"label": label, "rel_type": rel_type},
            )
            if card_rows and card_rows[0].sample_size > 0:
                card_stats = card_rows[0]
                break

        return RelationshipTypeProfile(
            rel_type=profile.rel_type,
            count=profile.count,
            property_profiles=profile.property_profiles,
            cardinality_stats=card_stats,
            source_labels=source_labels,
            target_labels=target_labels,
        )

    def _get_constraints(self) -> list[ConstraintInfo]:
        rows = self._run_query(MemgraphConstraintsQuery)
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
    driver: Any,
    model: GraphDataModel,
) -> ValidationResult:
    """Validate a Memgraph database against a GraphDataModel."""
    inspector = MemgraphInspector(driver)
    profile = inspector.inspect()
    return validate_profile(profile, model)
