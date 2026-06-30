"""Render orthograph objects as text or diagrams.

* ``render_model``   — :class:`GraphDefinition` → text or Mermaid.
* ``render_profile`` — :class:`GraphProfile` → text only.
* ``render_result``  — :class:`ValidationResult` → text only.
* ``display``        — :class:`GraphDefinition` → Mermaid inline in Jupyter.

``RenderFormat`` values are also accepted as strings (``"text"``, ``"mermaid"``).

Examples
--------
Render a definition as a human-readable text summary:

>>> from typing import Optional
>>> from orthograph.definition import GraphDefinition, NodeModel, RelationshipModel
>>> from orthograph.rendering import render_model
>>> class Person(NodeModel):
...     __label__ = "Person"
...     __uid_field__ = "name"
...     name: str
...     born: Optional[int] = None
>>> class Movie(NodeModel):
...     __label__ = "Movie"
...     __uid_field__ = "title"
...     title: str
...     year: int
>>> class ActedIn(RelationshipModel):
...     __label__ = "ACTED_IN"
...     __source_label__ = "Person"
...     __target_label__ = "Movie"
...     role: str
>>> definition = GraphDefinition(
...     name="Filmography",
...     node_types=[Person, Movie],
...     relationship_types=[ActedIn],
... )
>>> text = render_model(definition)
>>> text.startswith("Model: Filmography")
True
>>> "ACTED_IN" in text
True

Render as a Mermaid diagram:

>>> mermaid = render_model(definition, fmt="mermaid")
>>> mermaid.startswith("graph TD")
True
>>> "ACTED_IN" in mermaid
True
"""

from orthograph.diagnostics.result import ValidationResult
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_profile.models import GraphProfile
from orthograph.visualization.formats import RenderFormat
from orthograph.visualization.mermaid import display_mermaid, model_to_mermaid
from orthograph.visualization.text import model_to_text, profile_to_text, result_to_text


__all__ = ["render_model", "render_profile", "render_result", "display", "RenderFormat"]


def render_model(
    definition: GraphDefinition, *, fmt: RenderFormat | str = RenderFormat.TEXT
) -> str:
    """Render a :class:`GraphDefinition` as text or a Mermaid diagram.

    Parameters
    ----------
    definition : :class:`GraphDefinition`
        The graph definition to render.
    fmt :
        ``RenderFormat.TEXT`` (default) or ``RenderFormat.MERMAID``.
        String values ``"text"`` and ``"mermaid"`` are also accepted.

    Raises
    ------
    ValueError
        If ``fmt`` is unrecognised or not supported by this renderer.

    Examples
    --------
    Render as text (default):

    >>> from orthograph.definition import GraphDefinition, NodeModel
    >>> from orthograph.rendering import render_model
    >>> class Person(NodeModel):
    ...     __label__ = "Person"
    ...     __uid_field__ = "name"
    ...     name: str
    >>> definition = GraphDefinition(
    ...     name="Social", node_types=[Person], relationship_types=[]
    ... )
    >>> text = render_model(definition)
    >>> text.startswith("Model: Social")
    True
    >>> "Person" in text
    True

    Render as a Mermaid diagram:

    >>> mermaid = render_model(definition, fmt="mermaid")
    >>> mermaid.startswith("graph TD")
    True
    """
    fmt = RenderFormat(fmt)
    if fmt is RenderFormat.TEXT:
        return model_to_text(graph_definition=definition)
    if fmt is RenderFormat.MERMAID:
        return model_to_mermaid(graph_definition=definition)
    raise ValueError(
        f"render_model does not support {fmt.value!r}. "
        f"Supported: {[RenderFormat.TEXT.value, RenderFormat.MERMAID.value]}"
    )


def render_profile(
    profile: GraphProfile, *, fmt: RenderFormat | str = RenderFormat.TEXT
) -> str:
    """Render a :class:`GraphProfile` as text.

    Only ``RenderFormat.TEXT`` is supported.

    Raises
    ------
    ValueError
        If ``fmt`` is not ``RenderFormat.TEXT``.
    """
    fmt = RenderFormat(fmt)
    if fmt is RenderFormat.TEXT:
        return profile_to_text(profile=profile)
    raise ValueError(
        f"render_profile only supports {RenderFormat.TEXT.value!r}, got {fmt.value!r}."
    )


def render_result(
    validation_result: ValidationResult, *, fmt: RenderFormat | str = RenderFormat.TEXT
) -> str:
    """Render a :class:`ValidationResult` as text.

    Only ``RenderFormat.TEXT`` is supported.

    Raises
    ------
    ValueError
        If ``fmt`` is not ``RenderFormat.TEXT``.

    Examples
    --------
    A passing result renders with a ``PASS`` banner:

    >>> from orthograph.definition import (
    ...     GraphDefinition, NodeModel, RelationshipModel,
    ...     validate_data, validate_definition,
    ... )
    >>> from orthograph.rendering import render_result
    >>> class Person(NodeModel):
    ...     __label__ = "Person"
    ...     __uid_field__ = "name"
    ...     name: str
    >>> class Movie(NodeModel):
    ...     __label__ = "Movie"
    ...     __uid_field__ = "title"
    ...     title: str
    ...     year: int
    >>> class ActedIn(RelationshipModel):
    ...     __label__ = "ACTED_IN"
    ...     __source_label__ = "Person"
    ...     __target_label__ = "Movie"
    ...     role: str
    >>> definition = GraphDefinition(
    ...     name="Filmography",
    ...     node_types=[Person, Movie],
    ...     relationship_types=[ActedIn],
    ... )
    >>> nodes = [
    ...     {"__label__": "Person", "name": "Alice"},
    ...     {"__label__": "Movie", "title": "Inception", "year": 2010},
    ... ]
    >>> result = validate_data(definition, nodes)
    >>> "PASS" in render_result(result)
    True

    A failing result renders with a ``FAIL`` banner and error details:

    >>> bad = [{"__label__": "Movie", "title": "Dune"}]  # missing year
    >>> output = render_result(validate_data(definition, bad))
    >>> "FAIL" in output
    True
    >>> "PROPERTY_VALIDATION_ERROR" in output
    True
    """
    fmt = RenderFormat(fmt)
    if fmt is RenderFormat.TEXT:
        return result_to_text(result=validation_result)
    raise ValueError(
        f"render_result only supports {RenderFormat.TEXT.value!r}, got {fmt.value!r}."
    )


def display(definition: GraphDefinition) -> None:
    """Display a :class:`GraphDefinition` Mermaid diagram inline (Jupyter).

    Requires the ``notebook`` extra (IPython); raises
    :class:`~orthograph.dependencies.MissingDependencyError` if IPython is absent.
    """
    display_mermaid(obj=definition)
