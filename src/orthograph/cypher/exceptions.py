"""Exceptions raised by the Cypher extension."""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from orthograph.diagnostics.result import ValidationIssue


class CypherError(Exception):
    """Base class for every exception raised by the Cypher extension."""


class CypherQueryDefinitionError(CypherError):
    """A declarative query's contract is violated at class-definition time.

    Covers: empty/unparseable ``cypher_template``, or a placeholder that does
    not map 1:1 to a declared ``Params`` / ``Identifiers`` field.
    """


class CypherSyntaxError(CypherError):
    """Cypher produced by ``build()`` does not parse.

    The message names the query and the underlying parse error.
    """


class CypherIdentifierError(CypherError):
    """An identifier failed the safe-identifier grammar check."""


class CypherUnknownLabelError(CypherError):
    """A node or relationship label has no matching type in the model."""


class CypherUnknownPropertyError(CypherError):
    """A property key is not declared on the model type."""


class CypherModelValidationError(CypherError):
    """A generated Cypher query does not pass model validation.

    Validation issues are available on ``.issues`` for programmatic inspection.
    """

    def __init__(self, issues: list[ValidationIssue]) -> None:
        self.issues = issues
        lines = [f"  {issue}" for issue in issues]
        super().__init__(
            f"Generated Cypher failed model validation "
            f"({len(issues)} issue(s)):\n" + "\n".join(lines)
        )
