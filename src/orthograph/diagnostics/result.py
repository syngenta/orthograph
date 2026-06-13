"""Validation result value-objects.

Issues are accumulated and inspected, not raised.
:meth:`ValidationResult.raise_on_errors` converts collected errors into a
:class:`GraphValidationError`.
"""

from typing import Any

from pydantic import BaseModel, Field

from orthograph.diagnostics.classification import EntityType, Severity


class ValidationIssue(BaseModel):
    """A single validation issue (error, warning, or info)."""

    model_config = {"frozen": True}

    code: str
    severity: Severity
    entity_type: EntityType
    entity_id: str
    message: str
    context: dict[str, Any] = Field(default_factory=dict)

    def __str__(self) -> str:
        return (
            f"[{self.severity.value.upper()}] {self.code}: "
            f"{self.message} (entity={self.entity_id})"
        )


class GraphValidationError(Exception):
    """Raised when graph validation fails."""

    def __init__(self, issues: list["ValidationIssue"]) -> None:
        self.issues = issues
        messages = [str(i) for i in issues]
        super().__init__("\n".join(messages))


class ValidationResult:
    """Collects validation issues and provides summary access."""

    def __init__(self) -> None:
        self._issues: list[ValidationIssue] = []

    @property
    def issues(self) -> list[ValidationIssue]:
        return list(self._issues)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self._issues if i.severity == Severity.ERROR]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self._issues if i.severity == Severity.WARNING]

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def add(self, issue: ValidationIssue) -> None:
        self._issues.append(issue)

    def merge(self, other: "ValidationResult") -> None:
        self._issues.extend(other._issues)

    def raise_on_errors(self) -> None:
        if not self.is_valid:
            raise GraphValidationError(self.errors)
