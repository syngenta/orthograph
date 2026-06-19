"""Model-definition exceptions for the graph definition layer."""


class ModelDefinitionError(Exception):
    """Base for model-definition programming errors."""


class MissingClassVarError(ModelDefinitionError):
    """A model subclass omits a required class variable (e.g. ``__label__``)."""


class MissingUidFieldError(ModelDefinitionError):
    """A UID-keyed operation was requested on a node type with no ``__uid_field__``."""


class AmbiguousCardinalityError(ModelDefinitionError):
    """Two rules of equal specificity both match the same endpoint-property pair."""


class CardinalityParseError(ModelDefinitionError):
    """A cardinality notation string does not match the ``min..max`` grammar."""

    def __init__(self, value: object) -> None:
        super().__init__(f"expected 'min..max', got {value!r}")
