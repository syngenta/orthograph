import json
from collections import Counter
from enum import Enum
from pathlib import Path
from typing import Dict, List, Literal, Optional, Set, Tuple

from pydantic import BaseModel, Field, field_validator, model_validator


class NodeSpec(BaseModel):
    """
    Specification for a node in a graph data model.

    Attributes:
        label (str): The label of the node. Must not be empty or consist only of whitespace.
        properties (Dict[str, str]): A dictionary of property names and their types.
        uid_field (Optional[str]): The name of the unique identifier field, if any.
        uid_type (Optional[Literal["int", "str"]]): The type of the unique identifier,
        either "int" or "str", if specified.

    Raises:
        ValueError: If uid_type is specified without uid_field.
    """  # noqa: E501

    label: str
    properties: Dict[str, str] = Field(default_factory=dict)
    uid_field: Optional[str] = None
    uid_type: Optional[Literal["int", "str"]] = None

    @model_validator(mode="after")
    def validate_uid_fields(self) -> "NodeSpec":
        if self.uid_type is not None and self.uid_field is None:
            raise ValueError("uid_type can only be specified if uid_field is provided")
        return self

    @field_validator("label")
    def validate_label(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Label must not be empty or consist only of whitespace")
        return v


class RelationshipSpec(BaseModel):
    """
    Specification for a relationship in the graph schema.

    Attributes:
        label (str): The label of the relationship. Must not be empty or consist only of whitespace.
        node_types (Tuple[str, str]): The types of nodes this relationship connects.
        directed (bool): Whether the relationship is directed or not.
        properties (Dict[str, str]): A dictionary of property names and their types.
        uid_field (Optional[str]): The name of the unique identifier field, if any.
        uid_type (Optional[Literal["int", "str"]]): The type of the unique identifier,
        either "int" or "str", if specified.

    Raises:
        ValueError: If uid_type is specified without uid_field.
    """  # noqa: E501

    label: str
    node_types: Tuple[str, str]
    directed: bool = True
    properties: Dict[str, str] = Field(default_factory=dict)
    uid_field: Optional[str] = None
    uid_type: Optional[Literal["int", "str"]] = None

    @model_validator(mode="after")
    def validate_uid_fields(self) -> "RelationshipSpec":
        if self.uid_type is not None and self.uid_field is None:
            raise ValueError("uid_type can only be specified if uid_field is provided")
        return self

    @field_validator("label")
    def validate_label(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Label must not be empty or consist only of whitespace")
        return v

    @property
    def source_type(self) -> str:
        """Returns the type of the source node."""
        return self.node_types[0]

    @property
    def target_type(self) -> str:
        """Returns the type of the target node."""
        return self.node_types[1]


class ValidationResult:
    """
    Stores the results of a schema validation.

    Attributes:
        errors (List[str]): A list of error messages.
        warnings (List[str]): A list of warning messages.
    """

    def __init__(self):
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def add_error(self, error: str) -> None:
        """
        Add an error message to the validation result.

        Args:
            error (str): The error message to add.
        """
        self.errors.append(error)

    def add_warning(self, warning: str) -> None:
        """
        Add a warning message to the validation result.

        Args:
            warning (str): The warning message to add.
        """
        self.warnings.append(warning)

    def get_all_issues(self) -> List[str]:
        """
        Get all issues (errors and warnings) as a single list.

        Returns:
            List[str]: A list containing all errors followed by all warnings.
        """
        return self.errors + self.warnings

    @property
    def is_valid(self) -> bool:
        """
        Check if the validation result is valid (no errors).

        Returns:
            bool: True if there are no errors, False otherwise.
        """
        return len(self.errors) == 0


class GraphSchema(BaseModel):
    """
    Represents a graph schema, defining the structure of a graph database.

    The GraphSchema class is designed to define and validate the structure of a graph database.
    It allows users to specify node types, relationship types, and their properties, ensuring
    that the graph adheres to a predefined structure. This is crucial for maintaining data
    integrity and consistency in graph databases.

    Key features and purposes:
    1. Define node and relationship types with their properties.
    2. Validate the schema for consistency and completeness.
    3. Detect issues like isolated nodes or undefined references.
    4. Provide a standardized way to represent graph structures.
    5. Enable serialization and deserialization of schema definitions.

    This class is particularly useful in scenarios where a strict graph structure needs to be
    maintained, such as in data modeling, ETL processes, or when ensuring compatibility between
    different systems that interact with the graph database.

    Attributes:
        name (str): The name of the schema.
        node_specs (Dict[str, NodeSpec]): A dictionary of node specifications.
        relationship_specs (Dict[str, RelationshipSpec]): A dictionary of relationship specifications.
    """  # noqa: E501

    name: str
    node_specs: Dict[str, NodeSpec] = Field(default_factory=dict)
    relationship_specs: Dict[str, RelationshipSpec] = Field(default_factory=dict)

    @staticmethod
    def _check_empty_label(label: str, item_type: str) -> Optional[str]:
        """
        Check if a label is empty and return an error message if it is.

        Args:
            label (str): The label to check.
            item_type (str): The type of item (e.g., "Node" or "Relationship").

        Returns:
            Optional[str]: An error message if the label is empty, None otherwise.
        """
        if not label:
            return f"{item_type} label cannot be empty"
        return None

    @staticmethod
    def _check_duplicate_labels(items: Dict) -> Set[str]:
        """
        Check for duplicate labels in a dictionary of items.

        Args:
            items (Dict): A dictionary of items to check for duplicate labels.

        Returns:
            Set[str]: A set of duplicate labels found.
        """
        label_counts = Counter(spec.label for spec in items.values())
        return {label for label, count in label_counts.items() if count > 1}

    def _check_undefined_node_types(self) -> Set[str]:
        """
        Check for node types referenced in relationships but not defined in node specs.

        Returns:
            Set[str]: A set of undefined node types.
        """
        undefined_nodes = set()
        for rel_spec in self.relationship_specs.values():
            for node_type in rel_spec.node_types:
                if node_type not in self.node_specs:
                    undefined_nodes.add(node_type)
        return undefined_nodes

    def _check_isolated_nodes(self) -> Set[str]:
        """
        Check for isolated nodes (nodes not connected by any relationship).

        Returns:
            Set[str]: A set of isolated node types.
        """
        connected_nodes = set()
        for rel_spec in self.relationship_specs.values():
            connected_nodes.update(rel_spec.node_types)
        return set(self.node_specs.keys()) - connected_nodes

    def validate(self, raise_exception: bool = True) -> ValidationResult:
        """
        Validate the graph schema.

        Args:
            raise_exception (bool): Whether to raise an exception for validation errors.

        Returns:
            ValidationResult: The result of the validation.

        Raises:
            ValueError: If raise_exception is True and validation fails.
        """
        result = ValidationResult()

        specs = {"Node": self.node_specs, "Relationship": self.relationship_specs}

        for item_type, spec_dict in specs.items():
            for label, spec in spec_dict.items():
                error = self._check_empty_label(spec.label, item_type)
                if error:
                    result.add_error(error)

        # Check for duplicate labels, excluding empty labels
        non_empty_node_specs = {k: v for k, v in self.node_specs.items() if v.label}
        duplicate_nodes = self._check_duplicate_labels(non_empty_node_specs)
        if duplicate_nodes:
            result.add_error(
                f"Duplicate node labels found: {', '.join(duplicate_nodes)}"
            )

        non_empty_relationship_specs = {
            k: v for k, v in self.relationship_specs.items() if v.label
        }
        duplicate_relationships = self._check_duplicate_labels(
            non_empty_relationship_specs
        )
        if duplicate_relationships:
            result.add_error(
                f"Duplicate relationship labels found: "
                f"{', '.join(duplicate_relationships)}"
            )

        undefined_nodes = self._check_undefined_node_types()
        if undefined_nodes:
            result.add_error(
                f"Node types not defined in the schema: "
                f"{', '.join(sorted(undefined_nodes))}"
            )

        isolated_nodes = self._check_isolated_nodes()
        if isolated_nodes:
            result.add_warning(
                f"Isolated nodes found: {', '.join(sorted(isolated_nodes))}"
            )

        if raise_exception and not result.is_valid:
            raise ValueError(". ".join(result.errors))

        return result

    def add_node_spec(
        self,
        label: str,
        properties: Dict[str, str],
        uid_field: Optional[str] = None,
        validate: bool = True,
    ):
        """
        Add a new node specification to the schema.

        Args:
            label (str): The label of the node.
            properties (Dict[str, str]): A dictionary of property names and their types.
            uid_field (Optional[str]): The name of the unique identifier field, if any.
            validate (bool): Whether to validate the schema after adding the node spec.

        Raises:
            ValueError: If the label is empty or already exists.
        """
        error = self._check_empty_label(label=label, item_type="Node")
        if error:
            raise ValueError(error)
        if label in self.node_specs:
            raise ValueError(f"Node spec with label '{label}' already exists")
        self.node_specs[label] = NodeSpec(
            label=label, properties=properties, uid_field=uid_field
        )
        if validate:
            self.validate()

    def add_relationship_spec(
        self,
        label: str,
        node_types: Tuple[str, str],
        directed: bool = True,
        properties: Dict[str, str] = None,
        validate: bool = True,
    ):
        """
        Add a new relationship specification to the schema.

        Args:
            label (str): The label of the relationship.
            node_types (Tuple[str, str]): The types of nodes this relationship connects.
            directed (bool): Whether the relationship is directed or not.
            properties (Dict[str, str]): A dictionary of property names and their types.
            validate (bool): Whether to validate the schema after adding
            the relationship spec.

        Raises:
            ValueError: If the label is empty, already exists,
            or references undefined node types.
        """
        error = self._check_empty_label(label=label, item_type="Relationship")
        if error:
            raise ValueError(error)
        if not properties:
            properties = {}

        if label in self.relationship_specs:
            raise ValueError(f"Relationship spec with label '{label}' already exists")

        undefined_nodes = [
            node_type for node_type in node_types if node_type not in self.node_specs
        ]
        if undefined_nodes:
            raise ValueError(
                f"Node types not defined in the schema: {', '.join(undefined_nodes)}"
            )

        self.relationship_specs[label] = RelationshipSpec(
            label=label,
            node_types=node_types,
            directed=directed,
            properties=properties,
        )
        if validate:
            self.validate()

    @classmethod
    def from_json(cls, json_str: str) -> "GraphSchema":
        """
        Create a GraphSchema instance from a JSON string.

        Args:
            json_str (str): A JSON string representation of the graph schema.

        Returns:
            GraphSchema: A new GraphSchema instance.

        Raises:
            ValueError: If there are any errors in the JSON schema definition.
        """
        data = json.loads(json_str)
        schema = cls(name=data["name"])
        errors = []

        # Add nodes
        for spec in data.get("node_specs", {}).values():
            try:
                schema.add_node_spec(
                    spec["label"],
                    spec.get("properties", {}),
                    spec.get("uid_field"),
                    validate=False,
                )
            except ValueError as e:
                errors.append(str(e))

        # Add relationships
        for spec in data.get("relationship_specs", {}).values():
            try:
                schema.add_relationship_spec(
                    spec["label"],
                    spec["node_types"],
                    spec.get("directed", True),
                    spec.get("properties", {}),
                    validate=False,
                )
            except ValueError as e:
                errors.append(str(e))

        # Validate the schema
        validation_result = schema.validate(raise_exception=False)
        errors.extend(validation_result.errors)

        if errors:
            raise ValueError(". \n".join(errors))

        return schema

    @classmethod
    def from_file(cls, file_path: Path) -> "GraphSchema":
        """
        Create a GraphSchema instance from a JSON file.

        Args:
            file_path (Path): The path to the JSON file
            containing the schema definition.

        Returns:
            GraphSchema: A new GraphSchema instance.
        """
        return cls.from_json(file_path.read_text())

    def to_file(self, file_path: Path):
        """
        Write the GraphSchema to a JSON file.

        Args:
            file_path (Path): The path where the JSON file should be written.
        """
        json_data = self.model_dump_json(indent=2)
        file_path.write_text(json_data)

    def get_node_label_enum(self):
        """
        Create an Enum of node labels.

        Returns:
            Enum: An Enum containing all node labels in the schema.
        """
        return Enum("NodeLabel", {label: label for label in self.node_specs.keys()})

    def get_relationship_label_enum(self):
        """
        Create an Enum of relationship labels.

        Returns:
            Enum: An Enum containing all relationship labels in the schema.
        """
        return Enum(
            "RelationshipType",
            {rel_type: rel_type for rel_type in self.relationship_specs.keys()},
        )
