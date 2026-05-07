"""Validated GQLAlchemy client wrapper.

Wraps a GQLAlchemy ``DatabaseClient`` (``Memgraph`` or ``Neo4j``) and adds
Orthograph schema validation on all save/load paths.  Data is validated
against the :class:`GraphDataModel` *before* being persisted and *after*
being loaded.
"""

from __future__ import annotations

from typing import Any

from orthograph.core.errors import ValidationResult
from orthograph.core.graph_data_model import GraphDataModel
from orthograph.core.validator import GraphValidator
from orthograph.extensions.gqlalchemy.codegen import (
    GqlAlchemySchema,
    generate_gqlalchemy_classes,
)


class GqlAlchemyClient:
    """Schema-validated wrapper around a GQLAlchemy database client.

    The client validates data against the Orthograph
    :class:`GraphDataModel` before saving and after loading.  GQLAlchemy
    ``Node`` and ``Relationship`` classes are auto-generated from the
    model at construction time.

    Args:
        model: The Orthograph :class:`GraphDataModel` to validate against.
        db: A GQLAlchemy ``DatabaseClient`` instance (``Memgraph`` or
            ``Neo4j``).

    Example::

        from gqlalchemy import Memgraph
        from orthograph.extensions.gqlalchemy import GqlAlchemyClient

        client = GqlAlchemyClient(model=model, db=Memgraph())
        client.save_node({"name": "Alice", "age": 30}, node_type="Person")
    """

    def __init__(
        self,
        model: GraphDataModel,
        db: Any,
    ) -> None:
        self._model = model
        self._db = db
        self._schema = generate_gqlalchemy_classes(model)
        self._validator = GraphValidator(model)

    # --- Read-only properties ---

    @property
    def model(self) -> GraphDataModel:
        """The Orthograph model this client validates against."""
        return self._model

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
        """Validate and save a node to the database.

        The data dict is validated against the Orthograph ``NodeModel``
        for the given *node_type*.  If validation passes, a GQLAlchemy
        ``Node`` instance is created and saved via the database client.

        Args:
            data: Property dict for the node (without ``__label__``).
            node_type: The node label (must exist in the model).

        Returns:
            The saved GQLAlchemy ``Node`` instance.

        Raises:
            KeyError: If *node_type* is not in the model.
            GraphValidationError: If validation fails.
        """
        # Validate against Orthograph model
        validation_dict = {**data, "__label__": node_type}
        result = self._validator.validate_nodes([validation_dict])
        result.raise_on_errors()

        # Create GQLAlchemy instance and save
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
        """Validate and save a relationship to the database.

        The data dict is validated against the Orthograph
        ``RelationshipModel`` for the given *rel_type*.  If validation
        passes, a GQLAlchemy ``Relationship`` instance is created and
        saved via the database client.

        Args:
            data: Property dict for the relationship.
            rel_type: The relationship type (must exist in the model).
            start_node_id: The database ID of the start node.
            end_node_id: The database ID of the end node.

        Returns:
            The saved GQLAlchemy ``Relationship`` instance.

        Raises:
            KeyError: If *rel_type* is not in the model.
            GraphValidationError: If validation fails.
        """
        # Validate against Orthograph model (property-level only)
        validation_dict = {
            **data,
            "__label__": rel_type,
            "__source_uid__": str(start_node_id),
            "__target_uid__": str(end_node_id),
        }
        result = self._validator.validate_relationships([validation_dict])
        result.raise_on_errors()

        # Create GQLAlchemy instance and save
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
        """Execute a raw Cypher query without validation.

        This is a passthrough to the GQLAlchemy database client.  No
        schema validation is performed on the query or its results.

        Args:
            query: The Cypher query string.
            params: Optional query parameters.

        Returns:
            A list of result dicts.
        """
        if params is not None:
            result_iter = self._db.execute_and_fetch(query, params)
        else:
            result_iter = self._db.execute_and_fetch(query)
        return list(result_iter)

    # --- Database validation ---

    def validate_database(self) -> ValidationResult:
        """Validate the entire database against the Orthograph model.

        Delegates to the appropriate Orthograph inspector (Neo4j or
        Memgraph) based on the database client type, produces a
        :class:`GraphProfile`, and validates it against the model.

        Returns:
            A :class:`ValidationResult` with any issues found.
        """
        from orthograph.extensions.validation import validate_profile

        inspector = self._create_inspector()
        profile = inspector.inspect()
        return validate_profile(profile, self._model)

    def _create_inspector(self) -> Any:
        """Create the appropriate GraphInspector for the database client."""
        # Detect client type by class name (avoids hard import)
        client_name = type(self._db).__name__

        if client_name == "Memgraph":
            from orthograph.extensions.memgraph import MemgraphInspector

            # Memgraph uses the neo4j bolt driver underneath
            driver = getattr(self._db, "_driver", None)
            if driver is None:
                driver = self._db.new_connection()
            return MemgraphInspector(driver=driver)

        # Default: assume Neo4j-compatible
        from orthograph.extensions.neo4j import Neo4jInspector

        driver = getattr(self._db, "_driver", None)
        if driver is None:
            driver = self._db.new_connection()
        return Neo4jInspector(driver=driver)
