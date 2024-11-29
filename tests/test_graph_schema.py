import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from orthograph.graph_schema import (
    GraphSchema,
    NodeSpec,
    RelationshipSpec,
    ValidationResult,
)


@pytest.fixture
def sample_schema():
    """Fixture providing a sample GraphSchema for testing."""
    return GraphSchema(
        name="TestSchema",
        node_specs={
            "Person": NodeSpec(
                label="Person", properties={"name": "str", "age": "int"}, uid_field="id"
            ),
            "City": NodeSpec(
                label="City", properties={"name": "str"}, uid_field="city_code"
            ),
        },
        relationship_specs={
            "LIVES_IN": RelationshipSpec(
                label="LIVES_IN",
                node_types=("Person", "City"),
                directed=True,
                properties={"since": "int"},
            )
        },
    )


@pytest.fixture
def empty_schema():
    """Fixture providing an empty GraphSchema for testing."""
    return GraphSchema(name="EmptySchema")


@pytest.fixture
def temp_file(tmp_path):
    """Fixture providing a temporary file path for testing file operations."""
    return tmp_path / "test_schema.json"


def test_graph_schema_creation(sample_schema):
    """
    Test the creation of a GraphSchema with nodes and relationships.
    Verifies that the schema is correctly initialized with the given specifications.
    """
    assert sample_schema.name == "TestSchema"
    assert "Person" in sample_schema.node_specs
    assert "LIVES_IN" in sample_schema.relationship_specs
    assert sample_schema.relationship_specs["LIVES_IN"].source_type == "Person"
    assert sample_schema.relationship_specs["LIVES_IN"].target_type == "City"
    assert sample_schema.node_specs["Person"].uid_field == "id"
    assert sample_schema.node_specs["City"].uid_field == "city_code"


def test_graph_schema_serialization(sample_schema, temp_file):
    """
    Test the serialization and deserialization of a GraphSchema to and from a file.
    Verifies that the schema can be saved to a file and loaded back without data loss.
    """
    sample_schema.to_file(file_path=temp_file)
    loaded_schema = GraphSchema.from_file(file_path=temp_file)
    assert loaded_schema == sample_schema


def test_graph_schema_from_json():
    """
    Test the creation of a GraphSchema from a JSON string.
    Verifies that the schema is correctly initialized from JSON data.
    """
    json_str = """
    {
        "name": "TestSchema",
        "node_specs": {
            "Person": {
                "label": "Person",
                "properties": {
                    "name": "str",
                    "age": "int"
                },
                "uid_field": "person_id"
            }
        },
        "relationship_specs": {
            "KNOWS": {
                "label": "KNOWS",
                "node_types": ["Person", "Person"],
                "directed": true,
                "properties": {
                    "since": "int"
                }
            }
        }
    }
    """
    schema = GraphSchema.from_json(json_str=json_str)
    assert schema.name == "TestSchema"
    assert "Person" in schema.node_specs
    assert schema.node_specs["Person"].properties == {"name": "str", "age": "int"}
    assert schema.node_specs["Person"].uid_field == "person_id"
    assert "KNOWS" in schema.relationship_specs
    assert schema.relationship_specs["KNOWS"].node_types == ("Person", "Person")


def test_add_node_spec_to_empty_schema(empty_schema):
    """
    Test adding a node specification to an empty schema.
    Verifies that a node can be added to an empty schema and is correctly stored.
    """
    empty_schema.add_node_spec(
        label="Person", properties={"name": "str", "age": "int"}, uid_field="id"
    )
    assert "Person" in empty_schema.node_specs
    assert empty_schema.node_specs["Person"].properties == {"name": "str", "age": "int"}
    assert empty_schema.node_specs["Person"].uid_field == "id"


def test_add_relationship_spec_to_schema(empty_schema):
    """
    Test adding a relationship specification to a schema.
    Verifies that a relationship can be added between existing nodes and is correctly stored.
    """  # noqa E501
    empty_schema.add_node_spec(label="Person", properties={"name": "str"})
    empty_schema.add_node_spec(label="City", properties={"name": "str"})
    empty_schema.add_relationship_spec(
        label="LIVES_IN",
        node_types=("Person", "City"),
        properties={"since": "int"},
    )
    assert "LIVES_IN" in empty_schema.relationship_specs
    assert empty_schema.relationship_specs["LIVES_IN"].node_types == ("Person", "City")
    assert empty_schema.relationship_specs["LIVES_IN"].properties == {"since": "int"}


def test_add_duplicate_node_spec(sample_schema):
    """
    Test adding a duplicate node specification.
    Verifies that an error is raised when attempting to add a node with an existing label.
    """  # noqa E501
    with pytest.raises(
        ValueError, match="Node spec with label 'Person' already exists"
    ):
        sample_schema.add_node_spec(label="Person", properties={"name": "str"})


def test_add_duplicate_relationship_spec(sample_schema):
    """
    Test adding a duplicate relationship specification.
    Verifies that an error is raised when attempting to add a relationship with an existing label.
    """  # noqa E501
    with pytest.raises(
        ValueError, match="Relationship spec with label 'LIVES_IN' already exists"
    ):
        sample_schema.add_relationship_spec(
            label="LIVES_IN", node_types=("Person", "City")
        )


def test_get_node_label_enum(sample_schema):
    """
    Test getting the node label enum from a schema.
    Verifies that the correct enum is created with the expected node labels.
    """
    node_label = sample_schema.get_node_label_enum()
    assert set(node_label.__members__.keys()) == {"Person", "City"}
    assert node_label.Person.value == "Person"
    assert node_label.City.value == "City"
    assert node_label.Person == node_label.Person
    assert node_label.Person != node_label.City


def test_get_relationship_label_enum(sample_schema):
    """
    Test getting the relationship label enum from a schema.
    Verifies that the correct enum is created with the expected relationship labels.
    """
    relationship_label = sample_schema.get_relationship_label_enum()
    assert set(relationship_label.__members__.keys()) == {"LIVES_IN"}
    assert relationship_label.LIVES_IN.value == "LIVES_IN"
    assert relationship_label.LIVES_IN == relationship_label.LIVES_IN


def test_enum_update_after_adding_specs(empty_schema):
    """
    Test that enums are updated after adding new node and relationship specifications.
    Verifies that the enums reflect the current state of the schema after modifications.
    """
    node_label_1 = empty_schema.get_node_label_enum()
    assert len(node_label_1.__members__) == 0

    empty_schema.add_node_spec(label="Person", properties={"name": "str"})
    node_label_2 = empty_schema.get_node_label_enum()
    assert set(node_label_2.__members__.keys()) == {"Person"}
    assert node_label_2.Person.value == "Person"

    empty_schema.add_relationship_spec(label="KNOWS", node_types=("Person", "Person"))
    relationship_label = empty_schema.get_relationship_label_enum()
    assert set(relationship_label.__members__.keys()) == {"KNOWS"}
    assert relationship_label.KNOWS.value == "KNOWS"


def test_from_json_with_errors():
    """
    Test schema creation from JSON with various errors.
    Verifies that all errors (duplicate labels, undefined node types) are reported together.
    """  # noqa E501
    json_str = json.dumps(
        {
            "name": "TestSchema",
            "node_specs": {
                "1": {"label": "Person", "properties": {}},
                "2": {"label": "Person", "properties": {}},
                "3": {"label": "City", "properties": {}},
            },
            "relationship_specs": {
                "1": {"label": "LIVES_IN", "node_types": ["Person", "City"]},
                "2": {"label": "LIVES_IN", "node_types": ["Person", "City"]},
                "3": {"label": "WORKS_IN", "node_types": ["Person", "Company"]},
            },
        }
    )

    with pytest.raises(ValueError) as exc_info:
        GraphSchema.from_json(json_str=json_str)

    error_message = str(exc_info.value)
    assert "Node spec with label 'Person' already exists" in error_message
    assert "Relationship spec with label 'LIVES_IN' already exists" in error_message
    assert "Node types not defined in the schema: Company" in error_message


def test_from_json_without_errors():
    """
    Test schema creation from JSON without errors.
    Verifies that a valid JSON input creates a correct schema without raising exceptions.
    """  # noqa E501
    json_str = json.dumps(
        {
            "name": "TestSchema",
            "node_specs": {
                "1": {"label": "Person", "properties": {}},
                "2": {"label": "City", "properties": {}},
            },
            "relationship_specs": {
                "1": {"label": "LIVES_IN", "node_types": ["Person", "City"]},
                "2": {"label": "WORKS_IN", "node_types": ["Person", "City"]},
            },
        }
    )

    schema = GraphSchema.from_json(json_str=json_str)
    assert isinstance(schema, GraphSchema)
    assert len(schema.node_specs) == 2
    assert "Person" in schema.node_specs
    assert "City" in schema.node_specs
    assert len(schema.relationship_specs) == 2
    assert "LIVES_IN" in schema.relationship_specs
    assert "WORKS_IN" in schema.relationship_specs


def test_validate_valid_schema():
    """
    Test validation of a valid schema.
    Verifies that a correctly constructed schema passes validation without errors.
    """
    schema = GraphSchema(
        name="ValidSchema",
        node_specs={
            "Person": NodeSpec(label="Person", properties={"name": "str"}),
            "City": NodeSpec(label="City", properties={"name": "str"}),
        },
        relationship_specs={
            "LIVES_IN": RelationshipSpec(
                label="LIVES_IN",
                node_types=("Person", "City"),
                properties={"since": "int"},
            )
        },
    )
    schema.validate()  # Should not raise any exception


def test_validate_with_multiple_errors():
    """
    Test validation with multiple errors in the schema.
    Verifies that all types of errors (duplicate labels, undefined node types) are reported together.
    """  # noqa E501
    schema = GraphSchema(
        name="InvalidSchema",
        node_specs={
            "Person1": NodeSpec(label="Person", properties={"name": "str"}),
            "Person2": NodeSpec(label="Person", properties={"age": "int"}),
        },
        relationship_specs={
            "LIVES_IN": RelationshipSpec(
                label="LIVES_IN", node_types=("Person", "City")  # City is not defined
            )
        },
    )
    with pytest.raises(ValueError) as exc_info:
        schema.validate()

    error_message = str(exc_info.value)
    assert "Duplicate node labels found: Person" in error_message
    assert "Node types not defined in the schema: City" in error_message


def test_validate_with_duplicate_relationship_labels():
    """
    Test validation with duplicate relationship labels.
    """
    schema = GraphSchema(
        name="InvalidSchema",
        node_specs={
            "Person": NodeSpec(label="Person", properties={"name": "str"}),
            "City": NodeSpec(label="City", properties={"name": "str"}),
        },
        relationship_specs={
            "LIVES_IN1": RelationshipSpec(
                label="LIVES_IN", node_types=("Person", "City")
            ),
            "LIVES_IN2": RelationshipSpec(
                label="LIVES_IN", node_types=("Person", "City")
            ),
        },
    )
    with pytest.raises(ValueError) as exc_info:
        schema.validate()

    error_message = str(exc_info.value)
    assert "Duplicate relationship labels found: LIVES_IN" in error_message


def test_validate_with_isolated_nodes():
    """
    Test validation with isolated nodes (nodes not used in any relationship).
    """
    schema = GraphSchema(
        name="SchemaWithIsolatedNodes",
        node_specs={
            "Person": NodeSpec(label="Person", properties={"name": "str"}),
            "City": NodeSpec(label="City", properties={"name": "str"}),
            "Country": NodeSpec(label="Country", properties={"name": "str"}),
        },
        relationship_specs={
            "LIVES_IN": RelationshipSpec(
                label="LIVES_IN", node_types=("Person", "City")
            )
        },
    )
    result = schema.validate(raise_exception=False)
    assert result.is_valid  # Isolated nodes don't make the schema invalid
    assert "Isolated nodes found: Country" in result.warnings


def test_add_node_spec_with_empty_label():
    """
    Test adding a node specification with an empty label.
    """
    schema = GraphSchema(name="TestSchema")
    with pytest.raises(ValueError, match="Node label cannot be empty"):
        schema.add_node_spec(label="", properties={})


def test_add_relationship_spec_with_empty_label():
    """
    Test adding a relationship specification with an empty label.
    """
    schema = GraphSchema(name="TestSchema")
    schema.add_node_spec(label="Person", properties={})
    schema.add_node_spec(label="City", properties={})
    with pytest.raises(ValueError, match="Relationship label cannot be empty"):
        schema.add_relationship_spec(label="", node_types=("Person", "City"))


def test_add_relationship_spec_with_same_source_and_target():
    """
    Test adding a relationship specification with the same source and target node types.
    """
    schema = GraphSchema(name="TestSchema")
    schema.add_node_spec(label="Person", properties={})
    schema.add_relationship_spec(label="KNOWS", node_types=("Person", "Person"))
    assert "KNOWS" in schema.relationship_specs
    assert schema.relationship_specs["KNOWS"].node_types == ("Person", "Person")


def test_validate_empty_schema():
    """
    Test validation of an empty schema.
    """
    schema = GraphSchema(name="EmptySchema")
    result = schema.validate(raise_exception=False)
    assert result.is_valid
    assert len(result.warnings) == 0
    assert len(result.errors) == 0


def test_from_json_with_invalid_json():
    """
    Test schema creation from invalid JSON string.
    """
    invalid_json = "{'name': 'InvalidSchema'}"  # Invalid JSON (single quotes)
    with pytest.raises(json.JSONDecodeError):
        GraphSchema.from_json(json_str=invalid_json)


def test_to_file_with_invalid_path(sample_schema):
    """
    Test serialization to an invalid file path.
    """
    invalid_path = "/invalid/path/schema.json"
    with pytest.raises(IOError):
        sample_schema.to_file(file_path=Path(invalid_path))


def test_from_file_with_invalid_path():
    """
    Test deserialization from an invalid file path.
    """
    invalid_path = "/invalid/path/schema.json"
    with pytest.raises(IOError):
        GraphSchema.from_file(file_path=Path(invalid_path))


# mark this test as failed
@pytest.mark.xfail(
    reason="Behavior changed: errors are now collected instead of raised immediately"
)
def test_validate_with_multiple_empty_labels():
    """
    Test validation with multiple empty labels in both nodes and relationships.
    """
    schema = GraphSchema(
        name="InvalidSchema",
        node_specs={
            "Valid": NodeSpec(label="Valid", properties={}),
            "Empty1": NodeSpec(label="", properties={}),
            "Empty2": NodeSpec(label="", properties={}),
        },
        relationship_specs={
            "Valid": RelationshipSpec(label="Valid", node_types=("Valid", "Valid")),
            "Empty1": RelationshipSpec(label="", node_types=("Valid", "Valid")),
            "Empty2": RelationshipSpec(label="", node_types=("Valid", "Valid")),
        },
    )
    result = schema.validate(raise_exception=False)
    assert not result.is_valid
    assert len(result.errors) == 4
    assert "Node label cannot be empty" in result.errors
    assert "Relationship label cannot be empty" in result.errors


def test_add_multiple_specs_with_empty_labels():
    """
    Test adding multiple specs with empty labels and validate afterward.
    """
    schema = GraphSchema(name="TestSchema")

    # Add nodes with empty labels
    with pytest.raises(ValueError, match="Node label cannot be empty"):
        schema.add_node_spec(label="", properties={})

    # Add a valid node
    schema.add_node_spec(label="ValidNode", properties={}, validate=False)

    # Add relationships with empty labels
    with pytest.raises(ValueError, match="Relationship label cannot be empty"):
        schema.add_relationship_spec(label="", node_types=("ValidNode", "ValidNode"))

    # Validate the schema
    result = schema.validate(raise_exception=False)
    assert result.is_valid
    assert len(result.errors) == 0


def test_from_json_with_empty_labels():
    """
    Test schema creation from JSON with empty labels.
    """
    json_str = json.dumps(
        {
            "name": "TestSchema",
            "node_specs": {
                "1": {"label": "", "properties": {}},
                "2": {"label": "ValidNode", "properties": {}},
            },
            "relationship_specs": {
                "1": {"label": "", "node_types": ["ValidNode", "ValidNode"]},
                "2": {"label": "ValidRel", "node_types": ["ValidNode", "ValidNode"]},
            },
        }
    )

    with pytest.raises(ValueError) as exc_info:
        GraphSchema.from_json(json_str=json_str)

    error_message = str(exc_info.value)
    assert "Node label cannot be empty" in error_message
    assert "Relationship label cannot be empty" in error_message


def test_validation_result_get_all_issues():
    """
    Test the get_all_issues method of ValidationResult class.
    """
    result = ValidationResult()

    # Add some errors and warnings
    result.add_error("Error 1")
    result.add_error("Error 2")
    result.add_warning("Warning 1")
    result.add_warning("Warning 2")
    result.add_error("Error 3")

    # Get all issues
    all_issues = result.get_all_issues()

    # Check the total number of issues
    assert len(all_issues) == 5

    # Check that all errors and warnings are present
    assert "Error 1" in all_issues
    assert "Error 2" in all_issues
    assert "Error 3" in all_issues
    assert "Warning 1" in all_issues
    assert "Warning 2" in all_issues

    # Check the order (errors should come before warnings)
    assert all_issues[:3] == ["Error 1", "Error 2", "Error 3"]
    assert all_issues[3:] == ["Warning 1", "Warning 2"]

    # Check that the original lists are unchanged
    assert len(result.errors) == 3
    assert len(result.warnings) == 2

    # Test with empty result
    empty_result = ValidationResult()
    assert len(empty_result.get_all_issues()) == 0


def test_node_spec_validation():
    """
    Test NodeSpec validation for various scenarios.
    """
    # Valid NodeSpec
    valid_node = NodeSpec(
        label="Person", properties={"name": "str", "age": "int"}, uid_field="id"
    )
    assert valid_node.label == "Person"
    assert valid_node.properties == {"name": "str", "age": "int"}
    assert valid_node.uid_field == "id"

    # NodeSpec with empty label
    with pytest.raises(ValidationError, match="label"):
        NodeSpec(label="", properties={})

    # NodeSpec with uid_type but no uid_field
    with pytest.raises(
        ValueError, match="uid_type can only be specified if uid_field is provided"
    ):
        NodeSpec(label="Test", properties={}, uid_type="int")

    # NodeSpec with invalid uid_type
    with pytest.raises(ValidationError, match="uid_type"):
        NodeSpec(label="Test", properties={}, uid_field="id", uid_type="float")


def test_relationship_spec_validation():
    """
    Test RelationshipSpec validation for various scenarios.
    """
    # Valid RelationshipSpec
    valid_rel = RelationshipSpec(
        label="KNOWS", node_types=("Person", "Person"), properties={"since": "int"}
    )
    assert valid_rel.label == "KNOWS"
    assert valid_rel.node_types == ("Person", "Person")
    assert valid_rel.properties == {"since": "int"}

    # RelationshipSpec with empty label
    with pytest.raises(ValidationError, match="label"):
        RelationshipSpec(label="", node_types=("Person", "Person"))

    # RelationshipSpec with invalid node_types
    with pytest.raises(ValidationError, match="node_types"):
        RelationshipSpec(label="KNOWS", node_types=("Person",))

    # RelationshipSpec with uid_type but no uid_field
    with pytest.raises(
        ValueError, match="uid_type can only be specified if uid_field is provided"
    ):
        RelationshipSpec(label="KNOWS", node_types=("Person", "Person"), uid_type="int")


@pytest.mark.xfail(
    reason="Behavior changed: errors are now collected instead of raised immediately"
)
def test_graph_schema_comprehensive_instantiation():
    """
    Test comprehensive GraphSchema instantiation with various error scenarios.
    """
    # Attempt to create a GraphSchema with invalid components
    with pytest.raises(ValidationError) as exc_info:
        GraphSchema(
            name="InvalidSchema",
            node_specs={
                "Person": NodeSpec(label="Person", properties={"name": "str"}),
                "Empty": NodeSpec(label="", properties={}),  # Invalid empty label
            },
            relationship_specs={
                "KNOWS": RelationshipSpec(
                    label="KNOWS", node_types=("Person", "NonExistent")
                ),  # Invalid node type
                "": RelationshipSpec(
                    label="", node_types=("Person", "Person")
                ),  # Invalid empty label
            },
        )

    # Check that all expected errors are present in the exception message
    error_msg = str(exc_info.value)
    assert "label" in error_msg  # For empty node and relationship labels
    assert "node_types" in error_msg  # For invalid node type in relationship


def test_graph_schema_modifications():
    """
    Test GraphSchema modifications and error handling during modifications.
    """
    schema = GraphSchema(name="TestSchema")

    # Add valid node and relationship specs
    schema.add_node_spec(label="Person", properties={"name": "str"})
    schema.add_node_spec(label="City", properties={"name": "str"})
    schema.add_relationship_spec(label="LIVES_IN", node_types=("Person", "City"))

    # Attempt to add duplicate node spec
    with pytest.raises(
        ValueError, match="Node spec with label 'Person' already exists"
    ):
        schema.add_node_spec(label="Person", properties={"age": "int"})

    # Attempt to add duplicate relationship spec
    with pytest.raises(
        ValueError, match="Relationship spec with label 'LIVES_IN' already exists"
    ):
        schema.add_relationship_spec(label="LIVES_IN", node_types=("Person", "City"))

    # Attempt to add relationship with non-existent node type
    with pytest.raises(
        ValueError, match="Node types not defined in the schema: Country"
    ):
        schema.add_relationship_spec(label="BORN_IN", node_types=("Person", "Country"))

    # Validate the final state of the schema
    validation_result = schema.validate(raise_exception=False)
    assert validation_result.is_valid
    assert len(schema.node_specs) == 2
    assert len(schema.relationship_specs) == 1


def test_graph_schema_complex_scenario():
    """
    Test a complex scenario involving multiple operations on GraphSchema.
    """
    schema = GraphSchema(name="ComplexSchema")

    # Add multiple node specs
    schema.add_node_spec(label="Person", properties={"name": "str", "age": "int"})
    schema.add_node_spec(label="City", properties={"name": "str", "population": "int"})
    schema.add_node_spec(label="Company", properties={"name": "str", "founded": "int"})

    # Add multiple relationship specs
    schema.add_relationship_spec(label="LIVES_IN", node_types=("Person", "City"))
    schema.add_relationship_spec(label="WORKS_FOR", node_types=("Person", "Company"))
    schema.add_relationship_spec(label="BASED_IN", node_types=("Company", "City"))

    # Attempt invalid operations
    with pytest.raises(
        ValueError, match="Node spec with label 'Person' already exists"
    ):
        schema.add_node_spec(label="Person", properties={"name": "str"})

    with pytest.raises(
        ValueError, match="Node types not defined in the schema: Country"
    ):
        schema.add_relationship_spec(label="VISITED", node_types=("Person", "Country"))

    # Validate the schema
    validation_result = schema.validate(raise_exception=False)
    assert validation_result.is_valid
    assert len(schema.node_specs) == 3
    assert len(schema.relationship_specs) == 3

    # Test node and relationship label enums
    node_labels = schema.get_node_label_enum()
    relationship_labels = schema.get_relationship_label_enum()

    assert set(node_labels.__members__.keys()) == {"Person", "City", "Company"}
    assert set(relationship_labels.__members__.keys()) == {
        "LIVES_IN",
        "WORKS_FOR",
        "BASED_IN",
    }

    # Serialize and deserialize the schema
    schema_json = schema.model_dump_json()
    deserialized_schema = GraphSchema.from_json(schema_json)

    assert deserialized_schema == schema
