"""Cypher query generation from GraphDefinition definitions.

Values are always parameterised (``$name``). Identifiers (labels, relationship
types, property keys) are validated against the model and the Cypher identifier
grammar; unsafe identifiers are rejected, never escaped-and-embedded.

Every method validates the produced Cypher string against the ``GraphDefinition``
via ``validate_cypher`` as its last step — both raw-string and typed-query paths.
No query string leaves the generator without passing the full model check
(unknown labels, undeclared properties, endpoint mismatches). A failure raises
``CypherModelValidationError`` carrying the ``ValidationIssue`` list.

Two output shapes:

  * **Raw-string methods** (``merge_node``, ``create_node``, ``match_node``, ...)
    return ``(cypher, params)`` tuples / ``list[str]`` for callers that want raw
    Cypher. They are hardened by identifier and model-property guards, then
    validated against the full model before being returned.
  * **Typed-query methods** (``match_by_uid_query``, ``merge_query``,
    ``create_query``, ``delete_by_uid_query``) return
    ``CypherReadQuery`` / ``CypherWriteQuery`` *instances* that register in a
    ``QueryCatalogue``, carry ``Params`` / ``Output`` models, and pass the
    definition-time ``$param`` ↔ ``Params`` alignment check. The label is fixed
    by the model at synthesis time and validated before the instance is returned.
"""

from typing import Any, cast

from pydantic import BaseModel, create_model

from orthograph.cypher.base_models import (
    CypherReadQuery,
    CypherWriteQuery,
)
from orthograph.cypher.exceptions import (
    CypherModelValidationError,
    CypherUnknownLabelError,
    CypherUnknownPropertyError,
)
from orthograph.cypher.identifiers import validate_identifier
from orthograph.cypher.parser import validate_cypher
from orthograph.graph_definition.exceptions import MissingUidFieldError
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.models import NodeModel, RelationshipModel
from orthograph.query.base_models import D


#: The single return alias used by typed read queries. The generated
#: ``RETURN n`` clause and the ``materialize`` lookup (``raw[_RETURN_ALIAS]``)
#: must agree on this name; keeping it in one place prevents the two from
#: drifting apart and producing a ``KeyError`` at materialisation time.
_RETURN_ALIAS = "n"


class CypherGenerator:
    def __init__(self, graph_definition: GraphDefinition) -> None:
        self.graph_definition = graph_definition

    @staticmethod
    def _check_model_properties(
        props: dict[str, Any],
        entity_cls: type[NodeModel] | type[RelationshipModel],
        label: str,
    ) -> None:
        """Raise ``CypherUnknownPropertyError`` for any key not declared on
        the model."""
        allowed = entity_cls.get_all_property_names()
        for key in props:
            if key not in allowed:
                raise CypherUnknownPropertyError(
                    f"Unknown property key {key!r} for {label}: "
                    f"not declared on the model"
                )

    def merge_node(self, data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        label = data["__label__"]
        node_type = self.graph_definition.get_node_type(label)
        if node_type is None:
            raise CypherUnknownLabelError(f"Unknown node label: {label}")

        uid_field = node_type.__uid_field__
        props = {k: v for k, v in data.items() if not k.startswith("__")}
        self._check_model_properties(props, node_type, label)

        if uid_field is None or uid_field not in props:
            return self.create_node(data)

        query, params = _build_merge_by_uid(label, uid_field, props)
        self._assert_valid(query)
        return query, params

    def create_node(self, data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        label = data["__label__"]
        props = {k: v for k, v in data.items() if not k.startswith("__")}

        node_type = self.graph_definition.get_node_type(label)
        if node_type is not None:
            self._check_model_properties(props, node_type, label)

        safe_label = validate_identifier(label, kind="label")
        prop_str = ", ".join(
            f"{validate_identifier(k, kind='property key')}: ${k}" for k in props
        )
        query = f"CREATE (n:{safe_label} {{{prop_str}}}) RETURN n"
        self._assert_valid(query)
        return query, dict(props)

    def create_relationship(self, data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        return self._rel_query("CREATE", data)

    def merge_relationship(self, data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        return self._rel_query("MERGE", data)

    def generate_constraints(self) -> list[str]:
        """Generate uniqueness constraints for node types with UID fields."""
        constraints: list[str] = []
        for nt in self.graph_definition.node_types:
            if nt.__uid_field__ is not None:
                label = nt.__label__
                uid = nt.__uid_field__
                safe_label = validate_identifier(label, kind="label")
                safe_uid = validate_identifier(uid, kind="property key")
                safe_name = f"constraint_{safe_label}_{safe_uid}".lower()
                constraints.append(
                    f"CREATE CONSTRAINT {safe_name} "
                    f"IF NOT EXISTS "
                    f"FOR (n:{safe_label}) "
                    f"REQUIRE n.{safe_uid} IS UNIQUE"
                )
        for constraint in constraints:
            self._assert_valid(constraint)
        return constraints

    def match_node(self, node_type: type[NodeModel]) -> str:
        label = node_type.__label__
        safe_label = validate_identifier(label, kind="label")
        query = f"MATCH (n:{safe_label}) RETURN n"
        self._assert_valid(query)
        return query

    def match_relationship(self, rel_type: type[RelationshipModel]) -> str:
        """Generate a MATCH query for a relationship pattern.

        Endpoint node labels are read directly from ``rel_type.__source_label__``
        and ``rel_type.__target_label__``. The caller is expected to pass a
        ``rel_type`` belonging to ``self.graph_definition``, whose endpoint
        labels are guaranteed registered by model assembly validation.
        """
        src = rel_type.__source_label__
        tgt = rel_type.__target_label__
        label = rel_type.__label__
        safe_src = validate_identifier(src, kind="label")
        safe_tgt = validate_identifier(tgt, kind="label")
        safe_label = validate_identifier(label, kind="relationship type")
        arrow = "->" if rel_type.__directed__ else "-"
        query = (
            f"MATCH (a:{safe_src})-[r:{safe_label}]{arrow}(b:{safe_tgt}) RETURN a, r, b"
        )
        self._assert_valid(query)
        return query

    def _rel_query(self, verb: str, data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        label = data["__label__"]
        src_uid = data["__source_uid__"]
        tgt_uid = data["__target_uid__"]

        rel_type = self.graph_definition.get_relationship_type(label)
        if rel_type is None:
            raise CypherUnknownLabelError(f"Unknown relationship label: {label}")

        safe_src_label, safe_src_uid_field, safe_tgt_label, safe_tgt_uid_field = (
            _resolve_rel_endpoints(rel_type, label, self.graph_definition)
        )
        safe_label = validate_identifier(label, kind="relationship type")

        props = {k: v for k, v in data.items() if not k.startswith("__")}
        self._check_model_properties(props, rel_type, label)

        params: dict[str, Any] = {"src_uid": src_uid, "tgt_uid": tgt_uid}
        query = (
            f"MATCH (a:{safe_src_label} {{{safe_src_uid_field}: $src_uid}}), "
            f"(b:{safe_tgt_label} {{{safe_tgt_uid_field}: $tgt_uid}}) "
        )

        # CREATE and MERGE require a directed arrow in Cypher — undirected '-'
        # is only valid in MATCH. For undirected relationship types we always
        # emit '->' (source → target as declared); the undirected semantics
        # apply at read time (MATCH), not write time.
        if props:
            prop_str = ", ".join(
                f"{validate_identifier(k, kind='property key')}: ${k}" for k in props
            )
            query += f"{verb} (a)-[r:{safe_label} {{{prop_str}}}]->(b)"
            params.update(props)
        else:
            query += f"{verb} (a)-[r:{safe_label}]->(b)"

        query += " RETURN r"
        self._assert_valid(query)
        return query, params

    # --- Typed-query emission -------------------------------------------
    #
    # These return CypherReadQuery / CypherWriteQuery instances whose
    # cypher_template bakes in the model-fixed label as a validated literal and
    # whose $param names equal the synthesised Params fields. They are pure —
    # no session touched.

    def match_by_uid_query(
        self, node_type: type[NodeModel]
    ) -> CypherReadQuery[BaseModel, NodeModel]:
        """A typed read that matches one node of ``node_type`` by its UID field."""
        label, uid_field = self._require_uid(node_type)
        params_model = _params_model(node_type, label, [uid_field])
        cypher = (
            f"MATCH ({_RETURN_ALIAS}:{label} "
            f"{{{uid_field}: ${uid_field}}}) RETURN {_RETURN_ALIAS}"
        )
        self._assert_valid(cypher)
        return _read_query(
            name=f"match_{label}_by_uid".lower(),
            cypher=cypher,
            params_model=params_model,
            output_model=node_type,
        )

    def merge_query(
        self, node_type: type[NodeModel]
    ) -> CypherWriteQuery[BaseModel, int]:
        """A typed write that merges a node of ``node_type`` by its UID field."""
        label, uid_field = self._require_uid(node_type)
        prop_names = sorted(node_type.get_all_property_names())
        params_model = _params_model(node_type, label, prop_names)
        set_props = [p for p in prop_names if p != uid_field]
        cypher = f"MERGE (n:{label} {{{uid_field}: ${uid_field}}})"
        if set_props:
            set_clauses = ", ".join(f"n.{p} = ${p}" for p in set_props)
            cypher += f" SET {set_clauses}"
        cypher += " RETURN n"
        self._assert_valid(cypher)
        return _write_query(
            name=f"merge_{label}".lower(),
            cypher=cypher,
            params_model=params_model,
            counter="nodes_created",
        )

    def create_query(
        self, node_type: type[NodeModel]
    ) -> CypherWriteQuery[BaseModel, int]:
        """A typed write that creates a node of ``node_type``."""
        label = validate_identifier(node_type.__label__, kind="label")
        prop_names = sorted(node_type.get_all_property_names())
        params_model = _params_model(node_type, label, prop_names)
        prop_str = ", ".join(f"{p}: ${p}" for p in prop_names)
        cypher = f"CREATE (n:{label} {{{prop_str}}}) RETURN n"
        self._assert_valid(cypher)
        return _write_query(
            name=f"create_{label}".lower(),
            cypher=cypher,
            params_model=params_model,
            counter="nodes_created",
        )

    def delete_by_uid_query(
        self, node_type: type[NodeModel]
    ) -> CypherWriteQuery[BaseModel, int]:
        """A typed write that deletes one node of ``node_type`` by its UID field."""
        label, uid_field = self._require_uid(node_type)
        params_model = _params_model(node_type, label, [uid_field])
        cypher = f"MATCH (n:{label} {{{uid_field}: ${uid_field}}}) DETACH DELETE n"
        self._assert_valid(cypher)
        return _write_query(
            name=f"delete_{label}_by_uid".lower(),
            cypher=cypher,
            params_model=params_model,
            counter="nodes_deleted",
        )

    def _assert_valid(self, cypher: str) -> None:
        """Validate ``cypher`` against the model; raise
        ``CypherModelValidationError`` on errors."""
        result = validate_cypher(cypher, self.graph_definition)
        if not result.is_valid:
            raise CypherModelValidationError(result.errors)

    @staticmethod
    def _require_uid(node_type: type[NodeModel]) -> tuple[str, str]:
        """Return ``(label, uid_field)`` or raise ``MissingUidFieldError`` if absent."""
        uid_field = node_type.__uid_field__
        if uid_field is None:
            raise MissingUidFieldError(
                f"Cannot generate a UID-keyed query for {node_type.__label__!r}: "
                "node type declares no __uid_field__"
            )
        label = validate_identifier(node_type.__label__, kind="label")
        validate_identifier(uid_field, kind="property key")
        return label, uid_field

    @staticmethod
    def _require_uid_for_endpoint(
        node_type: type[NodeModel],
        rel_label: str,
        role: str,
    ) -> tuple[str, str]:
        """Return ``(label, uid_field)`` for a relationship endpoint node type.

        Raises ``MissingUidFieldError`` naming the relationship and the failing
        endpoint role (``"source"`` or ``"target"``) if the node type has no
        ``__uid_field__``.
        """
        uid_field = node_type.__uid_field__
        if uid_field is None:
            raise MissingUidFieldError(
                f"Cannot generate a relationship query for {rel_label!r}: "
                f"the {role} node type {node_type.__label__!r} "
                "declares no __uid_field__."
            )
        label = validate_identifier(node_type.__label__, kind="label")
        validate_identifier(uid_field, kind="property key")
        return label, uid_field


def _build_merge_by_uid(
    label: str,
    uid_field: str,
    props: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Build a MERGE…SET…RETURN query for a node with a known UID field.

    ``props`` must contain ``uid_field``; all other props become SET assignments.
    Returns ``(query, params)``.
    """
    uid_val = props[uid_field]
    set_props = {k: v for k, v in props.items() if k != uid_field}

    safe_label = validate_identifier(label, kind="label")
    safe_uid_field = validate_identifier(uid_field, kind="property key")
    query = f"MERGE (n:{safe_label} {{{safe_uid_field}: ${uid_field}}})"
    params: dict[str, Any] = {uid_field: uid_val}

    if set_props:
        set_clauses = ", ".join(
            f"n.{validate_identifier(k, kind='property key')} = ${k}" for k in set_props
        )
        query += f" SET {set_clauses}"
        params.update(set_props)

    return query + " RETURN n", params


def _resolve_rel_endpoints(
    rel_type: type[RelationshipModel],
    rel_label: str,
    graph_definition: GraphDefinition,
) -> tuple[str, str, str, str]:
    """Return (safe_src_label, safe_src_uid_field, safe_tgt_label, safe_tgt_uid_field).

    Raises ``CypherUnknownLabelError`` when an endpoint node type is absent from
    the graph definition, and ``MissingUidFieldError`` when an endpoint node type
    has no ``__uid_field__``.
    """
    src_label = rel_type.__source_label__
    tgt_label = rel_type.__target_label__

    src_node_type = graph_definition.get_node_type(src_label)
    if src_node_type is None:
        raise CypherUnknownLabelError(f"Unknown source node label: {src_label}")
    tgt_node_type = graph_definition.get_node_type(tgt_label)
    if tgt_node_type is None:
        raise CypherUnknownLabelError(f"Unknown target node label: {tgt_label}")

    _, src_uid_field = CypherGenerator._require_uid_for_endpoint(
        src_node_type, rel_label, "source"
    )
    _, tgt_uid_field = CypherGenerator._require_uid_for_endpoint(
        tgt_node_type, rel_label, "target"
    )

    return (
        validate_identifier(src_label, kind="label"),
        validate_identifier(src_uid_field, kind="property key"),
        validate_identifier(tgt_label, kind="label"),
        validate_identifier(tgt_uid_field, kind="property key"),
    )


def _params_model(
    node_type: type[NodeModel], label: str, field_names: list[str]
) -> type[BaseModel]:
    """Synthesise a Pydantic ``Params`` model from declared node properties."""
    specs = node_type.get_property_specs()
    fields: dict[str, Any] = {}
    for name in field_names:
        if name not in specs:
            raise CypherUnknownPropertyError(
                f"Unknown property key {name!r} for {label}: not declared on the model"
            )
        validate_identifier(name, kind="property key")
        info = specs[name]
        if info.is_required:
            fields[name] = (info.python_type, ...)
        else:
            fields[name] = (info.python_type | None, info.default)
    return create_model(f"{label}Params", **fields)


def _read_query(
    *,
    name: str,
    cypher: str,
    params_model: type[BaseModel],
    output_model: type[D],
) -> CypherReadQuery[BaseModel, D]:
    """Synthesise and instantiate a concrete declarative ``CypherReadQuery``."""

    def materialize(self: Any, raw: dict[str, Any]) -> D:
        return output_model.model_validate(raw[_RETURN_ALIAS])

    cls = type(
        f"{name}_Query",
        (CypherReadQuery,),
        {
            "Params": params_model,
            "Output": output_model,
            "name": name,
            "cypher_template": cypher,
            "materialize": materialize,
        },
    )
    return cast(CypherReadQuery[BaseModel, D], cls())


def _write_query(
    *,
    name: str,
    cypher: str,
    params_model: type[BaseModel],
    counter: str,
) -> CypherWriteQuery[BaseModel, int]:
    """Synthesise and instantiate a concrete declarative ``CypherWriteQuery``.

    ``counter`` is the ``SummaryCounters`` attribute to read from the driver
    result (e.g. ``"nodes_created"``, ``"nodes_deleted"``).  A mapping-shaped
    ``raw`` carrying the counter key directly is also accepted for test doubles.
    """

    def interpret_result(self: Any, raw: Any) -> int:
        # Mapping-shaped result (test doubles): read the counter key directly.
        if isinstance(raw, dict):
            return int(raw[counter])
        # Real driver Result: consume() -> ResultSummary, .counters.<counter>.
        summary = raw.consume()
        return int(getattr(summary.counters, counter))

    cls = type(
        f"{name}_Query",
        (CypherWriteQuery,),
        {
            "Params": params_model,
            "name": name,
            "cypher_template": cypher,
            "interpret_result": interpret_result,
        },
    )
    return cast(CypherWriteQuery[BaseModel, int], cls())
