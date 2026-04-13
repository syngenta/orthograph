"""Cypher query generation from GraphDataModel definitions."""

from typing import Any

from orthograph.core.graph_data_model import GraphDataModel
from orthograph.core.node_model import NodeModel
from orthograph.core.relationship_model import RelationshipModel


class CypherGenerator:
    """Generates Cypher queries from a GraphDataModel."""

    def __init__(self, model: GraphDataModel) -> None:
        self.model = model

    def merge_node(self, data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Generate a MERGE query for a node using its UID field."""
        label = data["__label__"]
        node_type = self.model.get_node_type(label)
        if node_type is None:
            raise ValueError(f"Unknown node label: {label}")

        uid_field = node_type.__uid_field__
        props = {k: v for k, v in data.items() if not k.startswith("__")}

        if uid_field is None or uid_field not in props:
            return self.create_node(data)

        uid_val = props[uid_field]
        set_props = {k: v for k, v in props.items() if k != uid_field}

        query = f"MERGE (n:{label} {{{uid_field}: ${uid_field}}})"
        params: dict[str, Any] = {uid_field: uid_val}

        if set_props:
            set_clauses = ", ".join(f"n.{k} = ${k}" for k in set_props)
            query += f" SET {set_clauses}"
            params.update(set_props)

        query += " RETURN n"
        return query, params

    def create_node(self, data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Generate a CREATE query for a node."""
        label = data["__label__"]
        props = {k: v for k, v in data.items() if not k.startswith("__")}

        prop_str = ", ".join(f"{k}: ${k}" for k in props)
        query = f"CREATE (n:{label} {{{prop_str}}}) RETURN n"
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
                safe_name = f"constraint_{label}_{uid}".lower()
                constraints.append(
                    f"CREATE CONSTRAINT {safe_name} "
                    f"IF NOT EXISTS "
                    f"FOR (n:{label}) "
                    f"REQUIRE n.{uid} IS UNIQUE"
                )
        return constraints

    def match_node(self, node_type: type[NodeModel]) -> str:
        """Generate a MATCH query for all nodes of a given type."""
        label = node_type.__label__
        return f"MATCH (n:{label}) RETURN n"

    def match_relationship(self, rel_type: type[RelationshipModel]) -> str:
        """Generate a MATCH query for a relationship pattern."""
        src = rel_type.__source_type__.__label__
        tgt = rel_type.__target_type__.__label__
        label = rel_type.__label__
        arrow = "->" if rel_type.__directed__ else "-"
        return f"MATCH (a:{src})-[r:{label}]{arrow}(b:{tgt}) RETURN a, r, b"

    def _rel_query(self, verb: str, data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Generate a relationship CREATE/MERGE query."""
        label = data["__label__"]
        src_uid = data["__source_uid__"]
        tgt_uid = data["__target_uid__"]

        rel_type = self.model.get_relationship_type(label)
        if rel_type is None:
            raise ValueError(f"Unknown relationship label: {label}")

        src_label = rel_type.__source_type__.__label__
        tgt_label = rel_type.__target_type__.__label__
        src_uid_field = rel_type.__source_type__.__uid_field__ or "uid"
        tgt_uid_field = rel_type.__target_type__.__uid_field__ or "uid"

        props = {k: v for k, v in data.items() if not k.startswith("__")}

        params: dict[str, Any] = {
            "src_uid": src_uid,
            "tgt_uid": tgt_uid,
        }

        query = (
            f"MATCH (a:{src_label} {{{src_uid_field}: $src_uid}}), "
            f"(b:{tgt_label} {{{tgt_uid_field}: $tgt_uid}}) "
        )

        if props:
            prop_str = ", ".join(f"{k}: ${k}" for k in props)
            query += f"{verb} (a)-[r:{label} {{{prop_str}}}]->(b)"
            params.update(props)
        else:
            query += f"{verb} (a)-[r:{label}]->(b)"

        query += " RETURN r"
        return query, params
