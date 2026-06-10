"""Cypher parameter/identifier bindings — the parser-free templating core.

This module holds the parts of the typed Cypher query system that bind the two
declared parameter groups to a ``cypher_template``, and that carry **no parser /
graphglot dependency**:

  * the two canonical empty models ``NoParams`` / ``NoIdentifiers``,
  * the placeholder patterns and extractors for ``$value`` and ``<<name>>``,
  * the identifier-kind resolution rule,
  * the ``<<name>>`` render-and-validate splice,
  * the pure 1:1 placeholder-to-field alignment checks.

It exists so that other Cypher-emitting backends (e.g. the GQLAlchemy query
catalogue, which renders Cypher through a builder) can reuse this surface
without pulling in the graphglot parser that ``base_models`` depends on for its
dialect check. ``base_models`` builds the abstract ``CypherReadQuery`` /
``CypherWriteQuery`` ABCs on top of this module and adds the dialect-parse step.
Only string rules, pydantic, and ``identifiers`` are imported here.
"""

import re
from typing import Any

from pydantic import BaseModel

from orthograph.extensions.cypher.exceptions import CypherQueryDefinitionError
from orthograph.extensions.cypher.identifiers import validate_identifier


CypherQuery = tuple[str, dict[str, Any]]
"""A built Cypher query: the Cypher string and its parameter dict."""


class NoParams(BaseModel):
    """A query that accepts no value parameters declares ``Params = NoParams``.

    Use this canonical empty model instead of hand-rolling an empty ``BaseModel``
    per query. ``Params`` is the generic type parameter ``P`` of
    ``ReadQuery[P, D]`` and is always declared explicitly (so ``P`` stays
    precisely typed); when a query takes no ``$value`` parameters, name this.
    """


class NoIdentifiers(BaseModel):
    """The empty ``Identifiers`` model — the default at the Cypher query bases.

    A query whose ``Identifiers`` is ``NoIdentifiers`` declares no dynamic
    identifiers and uses no ``<<placeholder>>`` — it is byte-for-byte a plain
    value-only query. ``Identifiers`` is opt-in: omit it (it defaults to this)
    or name it explicitly for symmetry with ``Params = NoParams``.
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
    """Replace every ``<<name>>`` placeholder with ``replacement``.

    Used by the dialect-parse step (in ``base_models``) to swap a safe dummy
    identifier in before parsing, since ``<<name>>`` is not valid Cypher.
    """
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

    For each field on the bound ``Identifiers`` instance, validate its value
    through ``validate_identifier`` (rejecting anything outside the safe
    identifier grammar) and substitute it into the matching ``<<name>>`` slot.
    An empty ``Identifiers`` (``NoIdentifiers``) leaves the string untouched —
    so a value-only query renders byte-for-byte unchanged.

    Any ``<<name>>`` placeholder left unsubstituted (the identifiers model has no
    matching field) raises ``CypherQueryDefinitionError`` here, rather than
    letting a literal ``<<name>>`` reach the driver as an opaque syntax error.
    Declarative queries already catch this 1:1 at definition time via
    ``check_placeholder_alignment``; this guard covers direct/imperative use.
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
    """Return the 1:1 placeholder-to-field alignment problems for a query class.

    Pure (no parser, no graphglot). Checks two strict 1:1 mappings:

      * every ``$param`` ↔ a ``Params`` field, and
      * every ``<<name>>`` ↔ an ``Identifiers`` field.

    A placeholder with no field, or a field with no placeholder, is a problem
    (the latter is dead input — usually a rename/typo — and must fail fast).
    Returns a list of human-readable problem strings; the caller (the Cypher
    base) raises ``CypherQueryDefinitionError`` if it is non-empty.
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
