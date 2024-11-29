from enum import Enum
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple, Union

from pydantic import BaseModel, Field

from orthograph.graph_schema import GraphSchema, NodeSpec, RelationshipSpec


class EntityType(Enum):
    NODE = "node"
    RELATIONSHIP = "relationship"


class ValidationConfig(BaseModel):
    allow_unknown_node_labels: bool = False
    allow_unknown_relationship_types: bool = False
    allow_extra_node_properties: bool = False
    allow_extra_relationship_properties: bool = False


class ValidationError(BaseModel):
    entity_type: EntityType
    entity_id: str
    error_message: str


class Node(BaseModel):
    label: str
    uid: Optional[str] = None
    properties: Dict[str, Any] = Field(default_factory=dict)


class Relationship(BaseModel):
    label: str
    start_node_uid: Any
    end_node_uid: Any
    start_node_label: Optional[str] = None
    end_node_label: Optional[str] = None
    directed: Optional[bool] = None
    properties: Dict[str, Any] = Field(default_factory=dict)


class ErrorMessages:
    MISSING_LABEL = "Missing required 'label' field"
    UNKNOWN_LABEL = "Unknown {} label: {}"
    MISSING_REQUIRED_PROPERTY = "Missing required property: {}"
    INVALID_PROPERTY_TYPE = "Invalid type for property {}: expected {}, got {}"
    MISSING_UID_FIELD = "Missing UID field: {}"
    INVALID_UID_TYPE = "Invalid type for UID field {}: expected {}, got {}"
    EXTRA_PROPERTIES = "Extra properties not allowed: {}"
    MISSING_NODE_UID = "Missing 'start_node_uid' or 'end_node_uid'"
    INVALID_NODE_LABEL = "Invalid {}_node_label: expected {}, got {}"
    INVALID_NODE_UID_TYPE = "Invalid type for {}_node_uid: expected {}, got {}"
    MISSING_DIRECTION = "Missing 'directed' field"
    INVALID_DIRECTION = "Invalid 'directed' value: expected {}, got {}"


class ValidationStrategy:
    @staticmethod
    def validate_properties(
        data: Dict[str, Any], spec_properties: Dict[str, str]
    ) -> List[ValidationError]:
        errors = []
        for prop, prop_type in spec_properties.items():
            if prop not in data:
                errors.append(
                    ValidationError(
                        entity_type=EntityType.NODE,
                        entity_id=str(data.get("uid", "unknown")),
                        error_message=ErrorMessages.MISSING_REQUIRED_PROPERTY.format(
                            prop
                        ),
                    )
                )
            elif not isinstance(data[prop], TYPE_MAPPING.get(prop_type, object)):
                errors.append(
                    ValidationError(
                        entity_type=EntityType.NODE,
                        entity_id=str(data.get("uid", "unknown")),
                        error_message=ErrorMessages.INVALID_PROPERTY_TYPE.format(
                            prop, prop_type, type(data[prop]).__name__
                        ),
                    )
                )
        return errors

    @staticmethod
    def validate_uid(
        data: Dict[str, Any], spec: Union[NodeSpec, RelationshipSpec]
    ) -> List[ValidationError]:
        errors = []
        if spec.uid_field:
            if spec.uid_field not in data:
                errors.append(
                    ValidationError(
                        entity_type=EntityType.NODE,
                        entity_id=str(data.get("uid", "unknown")),
                        error_message=ErrorMessages.MISSING_UID_FIELD.format(
                            spec.uid_field
                        ),
                    )
                )
            elif spec.uid_type and not isinstance(
                data[spec.uid_field], TYPE_MAPPING.get(spec.uid_type, object)
            ):
                errors.append(
                    ValidationError(
                        entity_type=EntityType.NODE,
                        entity_id=str(data.get("uid", "unknown")),
                        error_message=ErrorMessages.INVALID_UID_TYPE.format(
                            spec.uid_field,
                            spec.uid_type,
                            type(data[spec.uid_field]).__name__,
                        ),
                    )
                )
        return errors

    @staticmethod
    def check_extra_properties(
        data: Dict[str, Any],
        spec_properties: Dict[str, str],
        excluded_keys: List[str],
    ) -> List[ValidationError]:
        extra_props = (
            set(data.keys()) - set(spec_properties.keys()) - set(excluded_keys)
        )
        if extra_props:
            return [
                ValidationError(
                    entity_type=EntityType.NODE,
                    entity_id=str(data.get("uid", "unknown")),
                    error_message=ErrorMessages.EXTRA_PROPERTIES.format(
                        ", ".join(extra_props)
                    ),
                )
            ]
        return []


TYPE_MAPPING = {
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "list": list,
    "dict": dict,
}


class GraphDataModel:
    def __init__(self, schema: GraphSchema, config: Optional[ValidationConfig] = None):
        self.schema = schema
        self.config = config or ValidationConfig()
        self.validation_strategy = ValidationStrategy()

    @lru_cache(maxsize=128)
    def get_node_spec(self, label: str) -> Optional[NodeSpec]:
        return self.schema.node_specs.get(label)

    @lru_cache(maxsize=128)
    def get_relationship_spec(self, label: str) -> Optional[RelationshipSpec]:
        return self.schema.relationship_specs.get(label)

    def _validate_node_label_and_uid(
        self, rel_data: Dict[str, Any], rel_spec: RelationshipSpec, node_end: str
    ) -> List[ValidationError]:
        errors = []
        node_label_key = f"{node_end}_node_label"
        node_uid_key = f"{node_end}_node_uid"
        spec_type_key = "source_type" if node_end == "start" else "target_type"

        if node_label_key in rel_data:
            node_label = rel_data[node_label_key]
            expected_label = getattr(rel_spec, spec_type_key)
            if node_label != expected_label:
                errors.append(
                    ValidationError(
                        entity_type=EntityType.RELATIONSHIP,
                        entity_id=f"{rel_data.get('start_node_uid', 'unknown')}->"
                        f"{rel_data.get('end_node_uid', 'unknown')}",
                        error_message=ErrorMessages.INVALID_NODE_LABEL.format(
                            node_end, expected_label, node_label
                        ),
                    )
                )
            else:
                node_spec = self.get_node_spec(node_label)
                if node_spec and node_spec.uid_type:
                    expected_uid_type = TYPE_MAPPING.get(node_spec.uid_type, object)
                    if not isinstance(rel_data[node_uid_key], expected_uid_type):
                        errors.append(
                            ValidationError(
                                entity_type=EntityType.RELATIONSHIP,
                                entity_id=f"{rel_data.get('start_node_uid', 'unknown')}"
                                f"->{rel_data.get('end_node_uid', 'unknown')}",
                                error_message=ErrorMessages.INVALID_NODE_UID_TYPE.format(
                                    node_end,
                                    node_spec.uid_type,
                                    type(rel_data[node_uid_key]).__name__,
                                ),
                            )
                        )
        return errors

    def validate_node(
        self, node_data: Dict[str, Any], collect_errors: bool = False
    ) -> Tuple[Optional[Node], List[ValidationError]]:
        errors = []
        node_label = node_data.get("label")

        if not node_label:
            errors.append(
                ValidationError(
                    entity_type=EntityType.NODE,
                    entity_id=str(node_data.get("uid", "unknown")),
                    error_message=ErrorMessages.MISSING_LABEL,
                )
            )
            return None, errors if collect_errors else self._raise_if_errors(errors)

        node_spec = self.get_node_spec(node_label)
        if not node_spec:
            if not self.config.allow_unknown_node_labels:
                errors.append(
                    ValidationError(
                        entity_type=EntityType.NODE,
                        entity_id=str(node_data.get("uid", "unknown")),
                        error_message=ErrorMessages.UNKNOWN_LABEL.format(
                            EntityType.NODE.value, node_label
                        ),
                    )
                )
                return None, errors if collect_errors else self._raise_if_errors(errors)
            return Node(label=node_label, uid=node_data.get("uid")), []

        validated_properties = {}

        errors.extend(
            self.validation_strategy.validate_properties(
                node_data, node_spec.properties
            )
        )
        errors.extend(self.validation_strategy.validate_uid(node_data, node_spec))

        if not self.config.allow_extra_node_properties:
            errors.extend(
                self.validation_strategy.check_extra_properties(
                    node_data, node_spec.properties, ["label", "uid"]
                )
            )

        if errors and not collect_errors:
            self._raise_if_errors(errors)
            return None, []

        for prop, value in node_data.items():
            if prop not in ["label", "uid"] and (
                prop in node_spec.properties or self.config.allow_extra_node_properties
            ):
                validated_properties[prop] = value

        return (
            Node(
                label=node_label,
                uid=node_data.get("uid"),
                properties=validated_properties,
            ),
            errors,
        )

    def validate_relationship(
        self, rel_data: Dict[str, Any], collect_errors: bool = False
    ) -> Tuple[Optional[Relationship], List[ValidationError]]:

        errors = []
        rel_label = rel_data.get("label")

        if not rel_label:
            errors.append(
                ValidationError(
                    entity_type=EntityType.RELATIONSHIP,
                    entity_id=f"{rel_data.get('start_node_uid', 'unknown')}->"
                    f"{rel_data.get('end_node_uid', 'unknown')}",
                    error_message=ErrorMessages.MISSING_LABEL,
                )
            )
            return None, errors if collect_errors else self._raise_if_errors(errors)

        rel_spec = self.get_relationship_spec(rel_label)
        if not rel_spec:
            if not self.config.allow_unknown_relationship_types:
                errors.append(
                    ValidationError(
                        entity_type=EntityType.RELATIONSHIP,
                        entity_id=f"{rel_data.get('start_node_uid', 'unknown')}->"
                        f"{rel_data.get('end_node_uid', 'unknown')}",
                        error_message=ErrorMessages.UNKNOWN_LABEL.format(
                            EntityType.RELATIONSHIP.value, rel_label
                        ),
                    )
                )
                return None, errors if collect_errors else self._raise_if_errors(errors)
            return (
                Relationship(
                    label=rel_label,
                    start_node_uid=rel_data.get("start_node_uid", ""),
                    end_node_uid=rel_data.get("end_node_uid", ""),
                    start_node_label=rel_data.get("start_node_label"),
                    end_node_label=rel_data.get("end_node_label"),
                    directed=rel_data.get("directed", True),
                ),
                [],
            )

        validated_properties = {}

        errors.extend(
            self.validation_strategy.validate_properties(rel_data, rel_spec.properties)
        )

        if not self.config.allow_extra_relationship_properties:
            errors.extend(
                self.validation_strategy.check_extra_properties(
                    rel_data,
                    rel_spec.properties,
                    [
                        "label",
                        "start_node_uid",
                        "end_node_uid",
                        "start_node_label",
                        "end_node_label",
                        "directed",
                    ],
                )
            )

        if "start_node_uid" not in rel_data or "end_node_uid" not in rel_data:
            errors.append(
                ValidationError(
                    entity_type=EntityType.RELATIONSHIP,
                    entity_id=f"{rel_data.get('start_node_uid', 'unknown')}->{rel_data.get('end_node_uid', 'unknown')}",
                    error_message=ErrorMessages.MISSING_NODE_UID,
                )
            )

        # Validate node labels and UID types if provided
        errors.extend(self._validate_node_label_and_uid(rel_data, rel_spec, "start"))
        errors.extend(self._validate_node_label_and_uid(rel_data, rel_spec, "end"))

        # Validate directed field
        data_directed = rel_data.get(
            "directed", False
        )  # Default to False if not provided
        if rel_spec.directed != data_directed:
            errors.append(
                ValidationError(
                    entity_type=EntityType.RELATIONSHIP,
                    entity_id=f"{rel_data.get('start_node_uid', 'unknown')}->"
                    f"{rel_data.get('end_node_uid', 'unknown')}",
                    error_message=ErrorMessages.INVALID_DIRECTION.format(
                        rel_spec.directed, data_directed
                    ),
                )
            )

        if errors and not collect_errors:
            self._raise_if_errors(errors)
            return None, []

        for prop, value in rel_data.items():
            if prop not in [
                "label",
                "start_node_uid",
                "end_node_uid",
                "start_node_label",
                "end_node_label",
                "directed",
            ] and (
                prop in rel_spec.properties
                or self.config.allow_extra_relationship_properties
            ):
                validated_properties[prop] = value

        return (
            Relationship(
                label=rel_label,
                start_node_uid=rel_data["start_node_uid"],
                end_node_uid=rel_data["end_node_uid"],
                start_node_label=rel_data.get("start_node_label"),
                end_node_label=rel_data.get("end_node_label"),
                directed=data_directed,  # Use the validated directed value
                properties=validated_properties,
            ),
            errors,
        )

    @staticmethod
    def _raise_if_errors(errors: List[ValidationError]):
        if errors:
            raise ValueError(
                "\n".join(
                    f"{error.entity_type.value.capitalize()} Error: {error.error_message}"
                    for error in errors
                )
            )
