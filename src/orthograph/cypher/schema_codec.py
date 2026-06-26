"""JSON-Schema round-trip helpers for CypherQuery Params / Identifiers models.

Two public functions:

* :func:`model_to_json_schema` — serialize a Pydantic model class to a JSON-Schema dict.
* :func:`model_from_json_schema` — reconstruct a Pydantic model from a JSON-Schema dict.

Only scalar types are supported on the file-authored path (int, str, float, bool).
Nested objects, arrays, enums, $ref, and anyOf/allOf/oneOf are rejected with a
:class:`~orthograph.cypher.exceptions.CypherQueryDefinitionError`.
"""

from typing import Any

from pydantic import BaseModel, create_model

from orthograph.cypher.exceptions import CypherQueryDefinitionError


# Supported JSON-Schema scalar types → Python types.
_SCALAR_TYPE_MAP: dict[str, type] = {
    "integer": int,
    "string": str,
    "number": float,
    "boolean": bool,
}

# Constructs that are explicitly unsupported on the file-authored path.
_UNSUPPORTED_CONSTRUCTS = ("$ref", "enum", "anyOf", "allOf", "oneOf")


def model_to_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Thin wrapper over ``model.model_json_schema()``.

    Exists for symmetry and as a single seam to evolve the wire format later.
    """
    return model.model_json_schema()


def model_from_json_schema(
    schema: dict[str, Any],
    *,
    model_name: str | None = None,
) -> type[BaseModel]:
    """Reconstruct a Pydantic model from a JSON-Schema ``"object"`` dict.

    Field rules
    -----------
    * Field names  ← ``schema["properties"].keys()``
    * Required field ← name IN ``schema.get("required", [])``   → ``(T, ...)``
    * Optional field ← name NOT in required                     → ``(T | None, default)``
      where ``default = property.get("default", None)``
    * Model name   ← ``model_name`` arg, else ``schema.get("title")``, else
      ``"ReconstructedParams"``

    JSON-Schema type → Python type (scalar only)
    ---------------------------------------------
    ``"integer"`` → ``int``, ``"string"`` → ``str``,
    ``"number"``  → ``float``, ``"boolean"`` → ``bool``

    Raises
    ------
    CypherQueryDefinitionError
        * ``schema["type"] != "object"`` or ``"properties"`` missing.
        * A property uses an unsupported construct: ``$ref``, ``enum``,
          ``"type": "array"``/``"object"``, ``anyOf``/``allOf``/``oneOf``,
          or a ``"type"`` not in the scalar table.
    """  # NOQA E501
    if schema.get("type") != "object":
        raise CypherQueryDefinitionError(
            f"schema_codec: expected schema type 'object', got {schema.get('type')!r}"
        )
    if "properties" not in schema:
        raise CypherQueryDefinitionError("schema_codec: schema is missing 'properties'")

    name = model_name or schema.get("title") or "ReconstructedParams"
    properties: dict[str, Any] = schema["properties"]
    required_names: set[str] = set(schema.get("required", []))

    field_definitions: dict[str, Any] = {}

    for field_name, prop in properties.items():
        _check_unsupported(field_name, prop)

        raw_type = prop.get("type")
        if raw_type not in _SCALAR_TYPE_MAP:
            raise CypherQueryDefinitionError(
                f"schema_codec: field {field_name!r} "
                f"uses unsupported type {raw_type!r}. "
                f"Supported: {sorted(_SCALAR_TYPE_MAP)}"
            )
        python_type = _SCALAR_TYPE_MAP[raw_type]

        if field_name in required_names:
            field_definitions[field_name] = (python_type, ...)
        else:
            default = prop.get("default", None)
            field_definitions[field_name] = (python_type | None, default)

    return create_model(name, **field_definitions)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _check_unsupported(field_name: str, prop: dict[str, Any]) -> None:
    """Raise CypherQueryDefinitionError if prop uses an unsupported construct."""
    for construct in _UNSUPPORTED_CONSTRUCTS:
        if construct in prop:
            raise CypherQueryDefinitionError(
                f"schema_codec: field {field_name!r}"
                f" uses unsupported construct {construct!r}"
            )
    raw_type = prop.get("type")
    if raw_type in ("array", "object"):
        raise CypherQueryDefinitionError(
            f"schema_codec: field {field_name!r} "
            f"uses unsupported construct {raw_type!r}"
        )
