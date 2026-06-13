"""Model-definition exceptions for the graph definition layer."""


class ModelDefinitionError(Exception):
    """Base for model-definition programming errors."""


class MissingClassVarError(ModelDefinitionError):
    """A model subclass omits a required class variable (e.g. ``__label__``)."""


class MissingUidFieldError(ModelDefinitionError):
    """A UID-keyed operation was requested on a node type with no ``__uid_field__``."""
