"""Parser-free templating core for the typed Cypher query system.

Handles the two declared parameter groups (``$value`` and ``<<name>>``):
placeholder extraction, identifier-kind resolution, safe-identifier splicing,
and 1:1 field-to-placeholder alignment checks.  No graphglot dependency here.
"""

import re
from typing import Any

from pydantic import BaseModel

from orthograph.cypher.exceptions import CypherQueryDefinitionError
from orthograph.cypher.identifiers import validate_identifier


CypherQuery = tuple[str, dict[str, Any]]
"""A built Cypher query: the Cypher string and its parameter dict."""


class NoParams(BaseModel):
    """Canonical empty value-parameter model.

    Declare ``Params = NoParams`` for queries that take no ``$value`` parameters.
    """


class NoIdentifiers(BaseModel):
    """Canonical empty identifiers model — the default at the Cypher query bases.

    A query with no ``Identifiers`` and no ``<<placeholder>>`` renders unchanged.
    """


# A Cypher named parameter: ``$name`` where name is an identifier. The name is
# matched against the ASCII identifier grammar (``[A-Za-z_][A-Za-z0-9_]*``) used
# by ``identifiers.is_safe_identifier`` — not ``\w``, which under the default
# ``re.UNICODE`` flag would also match e.g. accented letters and so be wider
# than the grammar a ``$param``/``<<name>>`` can legally bind to.
_NAME = r"[A-Za-z_][A-Za-z0-9_]*"
_PARAM_PATTERN = re.compile(rf"\$({_NAME})")

# A declared-identifier placeholder: ``<<name>>``, distinct from ``$value`` so
# values and identifiers never collide.
_IDENTIFIER_PATTERN = re.compile(rf"<<({_NAME})>>")


def extract_cypher_params(cypher: str) -> set[str]:
    """Return the set of ``$name`` parameter placeholders used in a Cypher string."""
    return set(_PARAM_PATTERN.findall(cypher))


def extract_cypher_identifiers(cypher: str) -> set[str]:
    """Return the set of ``<<name>>`` identifier placeholders in a Cypher string."""
    return set(_IDENTIFIER_PATTERN.findall(cypher))


def substitute_identifier_placeholders(cypher: str, replacement: str) -> str:
    """Replace every ``<<name>>`` placeholder with ``replacement``."""
    return _IDENTIFIER_PATTERN.sub(replacement, cypher)


def identifier_kind(field_name: str) -> str:
    """Resolve the ``validate_identifier`` kind for an ``Identifiers`` field.

    A field named ``rel_type`` or ending in ``_rel_type`` is a
    ``"relationship type"``; every other field is a ``"label"``.
    """
    if field_name == "rel_type" or field_name.endswith("_rel_type"):
        return "relationship type"
    return "label"


def render_with_identifiers(cypher: str, identifiers: BaseModel) -> str:
    """Splice validated identifier values into ``<<name>>`` slots.

    Each field on ``identifiers`` is validated through ``validate_identifier``
    and substituted into the matching ``<<name>>`` slot.  An empty
    ``NoIdentifiers`` leaves the string unchanged.

    Raises ``CypherQueryDefinitionError`` if any ``<<name>>`` slot remains
    unsubstituted after all fields are processed.
    """
    values = identifiers.model_dump()
    rendered = cypher
    for field_name, raw_value in values.items():
        safe = validate_identifier(str(raw_value), kind=identifier_kind(field_name))
        rendered = rendered.replace(f"<<{field_name}>>", safe)
    leftover = extract_cypher_identifiers(rendered)
    if leftover:
        raise CypherQueryDefinitionError(
            f"unresolved identifier placeholder(s) "
            f"{sorted('<<' + name + '>>' for name in leftover)}: no matching field "
            f"on {type(identifiers).__name__}"
        )
    return rendered


def check_placeholder_alignment(cls: type, cypher: str) -> list[str]:
    """Return 1:1 placeholder-to-field alignment problems for a query class.

    Checks both ``$param`` ↔ ``Params`` fields and ``<<name>>`` ↔
    ``Identifiers`` fields.  A placeholder with no field, or a field with no
    placeholder, is reported.  Returns a list of human-readable strings; the
    caller raises ``CypherQueryDefinitionError`` if non-empty.
    """
    problems: list[str] = []

    params_model = getattr(cls, "Params", None)
    if isinstance(params_model, type) and issubclass(params_model, BaseModel):
        declared = set(params_model.model_fields.keys())
        used = extract_cypher_params(cypher)
        missing = used - declared
        if missing:
            problems.append(
                f"cypher_template uses parameter(s) "
                f"{sorted('$' + m for m in missing)} not declared on "
                f"{params_model.__name__}"
            )
        unused = declared - used
        if unused:
            problems.append(
                f"{params_model.__name__} declares field(s) "
                f"{sorted('$' + u for u in unused)} with no matching placeholder "
                f"in cypher_template"
            )

    identifiers_model = getattr(cls, "Identifiers", None)
    if isinstance(identifiers_model, type) and issubclass(identifiers_model, BaseModel):
        declared_ids = set(identifiers_model.model_fields.keys())
        used_ids = extract_cypher_identifiers(cypher)
        missing_ids = used_ids - declared_ids
        if missing_ids:
            problems.append(
                f"cypher_template uses identifier placeholder(s) "
                f"{sorted('<<' + m + '>>' for m in missing_ids)} not declared on "
                f"{identifiers_model.__name__}"
            )
        unused_ids = declared_ids - used_ids
        if unused_ids:
            problems.append(
                f"{identifiers_model.__name__} declares field(s) "
                f"{sorted('<<' + u + '>>' for u in unused_ids)} with no matching "
                f"placeholder in cypher_template"
            )

    return problems
