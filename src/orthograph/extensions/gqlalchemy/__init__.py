"""GQLAlchemy extension for orthograph.

Provides OGM capabilities and query builder integration with
Orthograph schema validation.  Requires ``gqlalchemy`` to be installed::

    pip install gqlalchemy

Usage::

    from gqlalchemy import Memgraph
    from orthograph.extensions.gqlalchemy import GqlAlchemyClient

    client = GqlAlchemyClient(model=model, db=Memgraph())
    client.save_node({"name": "Alice", "age": 30}, node_type="Person")
"""

from orthograph.extensions.gqlalchemy.base_models import (
    GqlAlchemyReadQuery,
    GqlAlchemyWriteQuery,
    validated_label,
)
from orthograph.extensions.gqlalchemy.client import GqlAlchemyClient
from orthograph.extensions.gqlalchemy.codegen import (
    GqlAlchemySchema,
    generate_gqlalchemy_classes,
)
from orthograph.extensions.gqlalchemy.query_builder import (
    ValidatedQueryBuilder,
)
from orthograph.extensions.gqlalchemy.result_adapter import (
    gqa_node_to_dict,
    gqa_relationship_to_dict,
    gqa_results_to_graph_data,
    validate_gqa_result,
)


__all__ = [
    # Codegen
    "GqlAlchemySchema",
    "generate_gqlalchemy_classes",
    # Client
    "GqlAlchemyClient",
    # Query builder
    "ValidatedQueryBuilder",
    # Query bases
    "GqlAlchemyReadQuery",
    "GqlAlchemyWriteQuery",
    "validated_label",
    # Result adapter
    "gqa_node_to_dict",
    "gqa_relationship_to_dict",
    "gqa_results_to_graph_data",
    "validate_gqa_result",
]
