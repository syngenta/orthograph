"""Core error types: validation value-objects and raised model-definition exceptions.

Two distinct concerns share this module:

  * **Validation value-objects** — ``ValidationIssue`` / ``ValidationResult``
    collect issues (error, warning, info) discovered while *validating* graph
    data against a model. They are accumulated and inspected, not raised;
    ``ValidationResult.raise_on_errors()`` is the bridge that turns collected
    errors into a raised ``GraphValidationError``.

  * **Model-definition exceptions** — ``ModelDefinitionError`` and subclasses
    signal that a model is *defined* or *used* incorrectly at the Python level
    (a programming error), surfaced as soon as the misdefinition is reached,
    independent of any backend (Cypher, SQLAlchemy, ...). ``ModelDefinitionError``
    derives from ``TypeError`` so the fault reads as a type-definition error and
    existing ``except TypeError`` handlers keep working, while callers wanting
    specificity can catch ``ModelDefinitionError`` or a subclass.
"""

from typing import Any

from pydantic import BaseModel, Field

from orthograph.core.types import EntityType, Severity


# --- Validation value-objects ----------------------------------------------


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


# --- Model-definition exceptions --------------------------------------------


class ModelDefinitionError(TypeError):
    """A graph model is defined or used incorrectly at the Python level.

    Base for every model-definition exception. Derives from ``TypeError`` so the
    fault reads as a type-definition error and existing ``except TypeError``
    handlers keep working, while callers wanting specificity can catch
    ``ModelDefinitionError`` or a subclass.
    """


class MissingClassVarError(ModelDefinitionError):
    """A model subclass omits a required class variable.

    Raised when a ``NodeModel`` / ``RelationshipModel`` subclass does not declare
    a class variable it must (e.g. ``__label__``, ``__source_type__``). The
    message names the class and the missing variable.
    """


class MissingUidFieldError(ModelDefinitionError):
    """A UID-keyed operation was requested for a node type that has no UID field.

    Raised when code needs a node type's ``__uid_field__`` to identify a node
    (e.g. generating a match/merge/delete-by-uid query) but the type declares
    ``__uid_field__ = None``. The message names the offending label.
    """
