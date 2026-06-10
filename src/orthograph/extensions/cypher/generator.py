"""Cypher query generation from GraphDataModel definitions.

Values are always parameterised (``$name``). Identifiers (labels, relationship
types, property keys) are validated against the model and the Cypher identifier
grammar; unsafe identifiers are rejected, never escaped-and-embedded.

Every method validates the produced Cypher string against the ``GraphDataModel``
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
    ``create_query``, ``delete_by_uid_query``) return E16
    ``CypherReadQuery`` / ``CypherWriteQuery`` *instances* that register in a
    ``QueryCatalogue``, carry ``Params`` / ``Output`` models, and pass the
    definition-time ``$param`` ↔ ``Params`` alignment check. The label is fixed
    by the model at synthesis time and validated before the instance is returned.
"""

from typing import Any, cast

from pydantic import BaseModel, create_model

from orthograph.catalogue.typed import D
from orthograph.core.exceptions import MissingUidFieldError
from orthograph.core.graph_data_model import GraphDataModel
from orthograph.core.node_model import NodeModel
from orthograph.core.relationship_model import RelationshipModel
from orthograph.extensions.cypher.base_models import (
    CypherReadQuery,
    CypherWriteQuery,
)
from orthograph.extensions.cypher.exceptions import (
    CypherModelValidationError,
    CypherUnknownLabelError,
    CypherUnknownPropertyError,
)
from orthograph.extensions.cypher.identifiers import validate_identifier
from orthograph.extensions.cypher.parser import validate_cypher


#: The single return alias used by typed read queries. The generated
#: ``RETURN n`` clause and the ``materialize`` lookup (``raw[_RETURN_ALIAS]``)
#: must agree on this name; keeping it in one place prevents the two from
#: drifting apart and producing a ``KeyError`` at materialisation time.
_RETURN_ALIAS = "n"


class CypherGenerator:
    """Generates Cypher queries from a GraphDataModel."""

    def __init__(self, model: GraphDataModel) -> None:
        self.model = model

    @staticmethod
    def _check_model_properties(
        props: dict[str, Any],
        entity_cls: type[NodeModel] | type[RelationshipModel],
        label: str,
    ) -> None:
        """Reject property keys not declared on the model.

        Per PRD Constraint 2 (models are the single source of truth), the
        writable property set is derived from the model. Any incoming key not
        declared on ``entity_cls`` is a structured error, never silently
        embedded into the generated Cypher.
        """
        allowed = entity_cls.get_all_property_names()
        for key in props:
            if key not in allowed:
                raise CypherUnknownPropertyError(
                    f"Unknown property key {key!r} for {label}: "
                    f"not declared on the model"
                )

    def merge_node(self, data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Generate a MERGE query for a node using its UID field."""
        label = data["__label__"]
        node_type = self.model.get_node_type(label)
        if node_type is None:
            raise CypherUnknownLabelError(f"Unknown node label: {label}")

        uid_field = node_type.__uid_field__
        props = {k: v for k, v in data.items() if not k.startswith("__")}
        self._check_model_properties(props, node_type, label)

        if uid_field is None or uid_field not in props:
            return self.create_node(data)

        uid_val = props[uid_field]
        set_props = {k: v for k, v in props.items() if k != uid_field}

        safe_label = validate_identifier(label, kind="label")
        safe_uid_field = validate_identifier(uid_field, kind="property key")
        query = f"MERGE (n:{safe_label} {{{safe_uid_field}: ${uid_field}}})"
        params: dict[str, Any] = {uid_field: uid_val}

        if set_props:
            set_clauses = ", ".join(
                f"n.{validate_identifier(k, kind='property key')} = ${k}"
                for k in set_props
            )
            query += f" SET {set_clauses}"
            params.update(set_props)

        query += " RETURN n"
        self._assert_valid(query)
        return query, params

    def create_node(self, data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Generate a CREATE query for a node."""
        label = data["__label__"]
        props = {k: v for k, v in data.items() if not k.startswith("__")}

        node_type = self.model.get_node_type(label)
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
        """Generate a CREATE query for a relationship."""
        return self._rel_query("CREATE", data)

    def merge_relationship(self, data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Generate a MERGE query for a relationship."""
        return self._rel_query("MERGE", data)

    def generate_constraints(self) -> list[str]:
        """Generate uniqueness constraints for node types with UID fields."""
        constraints: list[str] = []
        for nt in self.model.node_types:
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
        """Generate a MATCH query for all nodes of a given type."""
        label = node_type.__label__
        safe_label = validate_identifier(label, kind="label")
        query = f"MATCH (n:{safe_label}) RETURN n"
        self._assert_valid(query)
        return query

    def match_relationship(self, rel_type: type[RelationshipModel]) -> str:
        """Generate a MATCH query for a relationship pattern."""
        src = rel_type.__source_type__.__label__
        tgt = rel_type.__target_type__.__label__
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
        """Generate a relationship CREATE/MERGE query."""
        label = data["__label__"]
        src_uid = data["__source_uid__"]
        tgt_uid = data["__target_uid__"]

        rel_type = self.model.get_relationship_type(label)
        if rel_type is None:
            raise CypherUnknownLabelError(f"Unknown relationship label: {label}")

        src_label = rel_type.__source_type__.__label__
        tgt_label = rel_type.__target_type__.__label__
        src_uid_field = rel_type.__source_type__.__uid_field__ or "uid"
        tgt_uid_field = rel_type.__target_type__.__uid_field__ or "uid"

        safe_label = validate_identifier(label, kind="relationship type")
        safe_src_label = validate_identifier(src_label, kind="label")
        safe_tgt_label = validate_identifier(tgt_label, kind="label")
        safe_src_uid_field = validate_identifier(src_uid_field, kind="property key")
        safe_tgt_uid_field = validate_identifier(tgt_uid_field, kind="property key")

        props = {k: v for k, v in data.items() if not k.startswith("__")}
        self._check_model_properties(props, rel_type, label)

        params: dict[str, Any] = {
            "src_uid": src_uid,
            "tgt_uid": tgt_uid,
        }

        query = (
            f"MATCH (a:{safe_src_label} {{{safe_src_uid_field}: $src_uid}}), "
            f"(b:{safe_tgt_label} {{{safe_tgt_uid_field}: $tgt_uid}}) "
        )

        # CREATE and MERGE require a directed arrow in Cypher — undirected '-'
        # is only valid in MATCH. For undirected relationship types we always
        # emit '->' (source → target as declared); the undirected semantics
        # apply at read time (MATCH), not write time.
        arrow = "->"

        if props:
            prop_str = ", ".join(
                f"{validate_identifier(k, kind='property key')}: ${k}" for k in props
            )
            query += f"{verb} (a)-[r:{safe_label} {{{prop_str}}}]{arrow}(b)"
            params.update(props)
        else:
            query += f"{verb} (a)-[r:{safe_label}]{arrow}(b)"

        query += " RETURN r"
        self._assert_valid(query)
        return query, params

    # --- Typed-query emission (T4) ---------------------------------------
    #
    # These return E16 CypherReadQuery / CypherWriteQuery *instances* whose
    # cypher_template bakes in the model-fixed label as a validated literal and
    # whose $param names equal the synthesised Params fields (the alignment
    # E16 checks at class-definition time). They are pure — no session touched.

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
        """Validate the produced Cypher string against the model.

        Called as the last step of every generation method — both raw-string
        and typed-query paths — so the guarantee is structural: no query string
        leaves the generator without passing the full ``validate_cypher`` check
        (unknown labels, undeclared properties, endpoint mismatches).

        Raises ``CypherModelValidationError`` carrying the ``ValidationIssue``
        list if any errors are found.
        """
        result = validate_cypher(cypher, self.model)
        if not result.is_valid:
            raise CypherModelValidationError(result.errors)

    @staticmethod
    def _require_uid(node_type: type[NodeModel]) -> tuple[str, str]:
        """Return the validated ``(label, uid_field)`` or raise if no UID exists.

        UID-keyed typed queries (match/merge/delete-by-uid) cannot identify a
        node without a UID field, so a node type whose ``__uid_field__`` is
        ``None`` raises ``MissingUidFieldError`` — a model-definition fault,
        not a Cypher fault — rather than producing a silently-malformed query.
        """
        uid_field = node_type.__uid_field__
        if uid_field is None:
            raise MissingUidFieldError(
                f"Cannot generate a UID-keyed query for {node_type.__label__!r}: "
                "node type declares no __uid_field__"
            )
        label = validate_identifier(node_type.__label__, kind="label")
        validate_identifier(uid_field, kind="property key")
        return label, uid_field


def _params_model(
    node_type: type[NodeModel], label: str, field_names: list[str]
) -> type[BaseModel]:
    """Synthesise a Pydantic ``Params`` model from declared node properties.

    Each field name must be declared on the model (PRD Constraint 2) and is a
    safe identifier (it becomes a ``$param`` placeholder). The field type is the
    model's resolved property type; all synthesised params are required.
    """
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

    ``interpret_result`` reads the affected-node count from the driver result's
    summary counters. ``counter`` selects which ``SummaryCounters`` attribute to
    read (e.g. ``"nodes_created"`` for create/merge, ``"nodes_deleted"`` for
    delete). The executor passes the raw driver ``Result`` object returned by
    ``tx.run(...)``; ``Result.consume()`` yields a ``ResultSummary`` whose
    ``counters`` exposes those attributes.

    To remain usable with simple test doubles, a mapping-shaped ``raw`` that
    carries the counter key directly is also accepted.
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
