"""Schema-validated GQLAlchemy client wrapper."""

from __future__ import annotations

from typing import Any

from orthograph.backends import loader
from orthograph.backends.gqlalchemy.codegen import (
    GqlAlchemySchema,
    generate_gqlalchemy_classes,
)
from orthograph.comparison.engine import compare_profile_to_definition
from orthograph.diagnostics.result import ValidationResult
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.validation import GraphValidator


class GqlAlchemyClient:
    """Schema-validated wrapper around a GQLAlchemy database client.

    Validates data against the :class:`GraphDefinition` before saving and after
    loading.  GQLAlchemy node/relationship classes are auto-generated from the
    definition at construction time.

    Parameters
    ----------
    backend:
        Inspection backend name for :meth:`validate_database`
        (``"memgraph"`` or ``"neo4j"``).  Never inferred from the client type.

    Example::

        from gqlalchemy import Memgraph
        from orthograph.backends.gqlalchemy.client import GqlAlchemyClient

        client = GqlAlchemyClient(graph_definition=graph_definition, db=Memgraph())
        client.save_node({"name": "Alice", "age": 30}, node_type="Person")
    """

    def __init__(
        self,
        graph_definition: GraphDefinition,
        db: Any,
        backend: str = "memgraph",
    ) -> None:
        self._graph_data_model = graph_definition
        self._db = db
        self._backend = backend
        self._schema = generate_gqlalchemy_classes(graph_definition)
        self._validator = GraphValidator(graph_definition)

    # --- Read-only properties ---

    @property
    def graph_definition(self) -> GraphDefinition:
        """The Orthograph graph_definition this client validates against."""
        return self._graph_data_model

    @property
    def schema(self) -> GqlAlchemySchema:
        """The generated GQLAlchemy classes."""
        return self._schema

    # --- Node operations ---

    def save_node(
        self,
        data: dict[str, Any],
        node_type: str,
    ) -> Any:
        """Validate and save a node; return the saved GQLAlchemy Node instance.

        Raises
        ------
        KeyError
            If ``node_type`` is not in the model.
        GraphValidationError
            If validation fails.
        """
        validation_dict = {**data, "__label__": node_type}
        result = self._validator.validate_nodes([validation_dict])
        result.raise_on_errors()

        gqa_cls = self._schema.get_node_class(node_type)
        gqa_node = gqa_cls(**data)
        self._db.save_node(gqa_node)
        return gqa_node

    # --- Relationship operations ---

    def save_relationship(
        self,
        data: dict[str, Any],
        rel_type: str,
        start_node_id: int,
        end_node_id: int,
    ) -> Any:
        """Validate and save a relationship; return the saved GQLAlchemy Relationship.

        Raises
        ------
        KeyError
            If ``rel_type`` is not in the model.
        GraphValidationError
            If validation fails.
        """
        validation_dict = {
            **data,
            "__label__": rel_type,
            "__source_uid__": str(start_node_id),
            "__target_uid__": str(end_node_id),
        }
        result = self._validator.validate_relationships([validation_dict])
        result.raise_on_errors()

        gqa_cls = self._schema.get_rel_class(rel_type)
        gqa_rel = gqa_cls(
            _start_node_id=start_node_id,
            _end_node_id=end_node_id,
            **data,
        )
        self._db.save_relationship(gqa_rel)
        return gqa_rel

    # --- Raw query execution ---

    def execute(
        self,
        query: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Execute a raw Cypher query; no schema validation is performed."""
        if params is not None:
            result_iter = self._db.execute_and_fetch(query, params)
        else:
            result_iter = self._db.execute_and_fetch(query)
        return list(result_iter)

    # --- Database validation ---

    def validate_database(self) -> ValidationResult:
        """Validate the entire database against the model."""
        driver = getattr(self._db, "_driver", None)
        if driver is None:
            driver = self._db.new_connection()
        inspector_cls = loader.load_inspector(name=self._backend)
        profile = inspector_cls().inspect(connection=driver)
        return compare_profile_to_definition(
            profile=profile, definition=self._graph_data_model
        )
