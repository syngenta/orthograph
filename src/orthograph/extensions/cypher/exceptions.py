"""Custom exceptions raised by the Cypher extension.

A single home for the Cypher backend's raised exceptions, distinct from
``orthograph.core.exceptions`` (whose ``ValidationResult`` family holds
validation *value-objects*, not raised exceptions, and whose
``ModelDefinitionError`` family covers backend-neutral model misuse).

All exceptions raised by this extension derive from ``CypherError``, so a caller
can catch the whole family with ``except CypherError`` or a specific subclass.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from orthograph.core.exceptions import ValidationIssue


class CypherError(Exception):
    """Base class for every exception raised by the Cypher extension."""


class CypherQueryDefinitionError(CypherError):
    """A declarative query's contract is violated at class-definition time.

    The message names the offending query class and each problem found (empty or
    unparseable ``cypher_template``, or a placeholder that does not map 1:1 to a
    declared ``Params`` / ``Identifiers`` field).
    """


class CypherSyntaxError(CypherError):
    """Cypher produced by ``build()`` does not parse.

    The message names the query and the underlying parse error.
    """


class CypherIdentifierError(CypherError):
    """An identifier failed the safe-identifier grammar check.

    Raised by :func:`orthograph.extensions.cypher.identifiers.validate_identifier`
    when a label, relationship type, or property key falls outside the unescaped
    Cypher identifier grammar (the validate-and-reject guard against identifier
    injection). The message names the offending identifier and its kind.
    """


class CypherUnknownLabelError(CypherError):
    """A node or relationship label has no matching type in the model.

    Raised by the generator when the requested ``__label__`` does not resolve to
    a declared node or relationship type. The message names the offending label.
    """


class CypherUnknownPropertyError(CypherError):
    """A property key is not declared on the model type.

    Raised by the generator when an incoming property key is not part of the
    model type's declared properties (PRD Constraint 2 — models are the single
    source of truth). The message names the offending key and the label/type.
    """


class CypherModelValidationError(CypherError):
    """A generated Cypher query does not pass model validation.

    Raised by the generator after producing a query string, when
    ``validate_cypher`` finds that the output does not conform to the
    ``GraphDataModel`` — for example, an unknown label, an undeclared property,
    or a relationship pattern whose endpoints do not match the model.

    The validation issues are available on the ``issues`` attribute so callers
    can inspect each ``ValidationIssue`` (code, severity, entity_id, message)
    without parsing the exception message string.
    """

    def __init__(self, issues: list[ValidationIssue]) -> None:
        self.issues = issues
        lines = [f"  {issue}" for issue in issues]
        super().__init__(
            f"Generated Cypher failed model validation "
            f"({len(issues)} issue(s)):\n" + "\n".join(lines)
        )
