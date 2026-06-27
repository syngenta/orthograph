"""Render orthograph objects as text or diagrams.

* ``render_model``   — :class:`GraphDefinition` → text or Mermaid.
* ``render_profile`` — :class:`GraphProfile` → text only.
* ``render_result``  — :class:`ValidationResult` → text only.
* ``display``        — :class:`GraphDefinition` → Mermaid inline in Jupyter.

Example::

    import orthograph

    p = orthograph.profile.inspect_neo4j(driver)
    print(orthograph.rendering.render_profile(p))

``RenderFormat`` values are also accepted as strings (``"text"``, ``"mermaid"``).
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
    definition:  :class:`GraphDefinition`
    fmt:
        ``RenderFormat.TEXT`` (default) or ``RenderFormat.MERMAID``.

    Raises
    ------
    ValueError
        If ``fmt`` is unrecognised or not supported by this renderer.
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
