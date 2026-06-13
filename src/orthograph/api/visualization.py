"""Public visualization API — render orthograph objects as text or diagrams.

* ``render_model``   — :class:`GraphDefinition` → text or Mermaid.
* ``render_profile`` — :class:`GraphProfile` → text only.
* ``render_result``  — :class:`ValidationResult` → text only.
* ``display``        — :class:`GraphDefinition` → Mermaid inline in Jupyter.

Example::

    from orthograph.api import database, visualization

    profile = database.inspect("neo4j", driver)
    print(visualization.render_profile(profile))

``RenderFormat`` values are also accepted as strings (``"text"``, ``"mermaid"``).
"""

from orthograph.diagnostics.result import ValidationResult
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_profile.models import GraphProfile
from orthograph.visualization.formats import RenderFormat
from orthograph.visualization.mermaid import display_mermaid, model_to_mermaid
from orthograph.visualization.text import model_to_text, profile_to_text, result_to_text


def render_model(
    graph_definition: GraphDefinition,
    *,
    format: RenderFormat | str = RenderFormat.TEXT,  # noqa: A002
) -> str:
    """Render a :class:`GraphDefinition` as text or a Mermaid diagram.

    Parameters
    ----------
    format:
        ``RenderFormat.TEXT`` (default) or ``RenderFormat.MERMAID``.

    Raises
    ------
    ValueError
        If ``format`` is unrecognised or not supported by this renderer.
    """
    fmt = RenderFormat(format)
    if fmt is RenderFormat.TEXT:
        return model_to_text(graph_definition=graph_definition)
    if fmt is RenderFormat.MERMAID:
        return model_to_mermaid(graph_definition=graph_definition)
    raise ValueError(
        f"render_model does not support {fmt.value!r}. "
        f"Supported: {[RenderFormat.TEXT.value, RenderFormat.MERMAID.value]}"
    )


def render_profile(
    profile: GraphProfile,
    *,
    format: RenderFormat | str = RenderFormat.TEXT,  # noqa: A002
) -> str:
    """Render a :class:`GraphProfile` as text.

    Only ``RenderFormat.TEXT`` is supported.

    Raises
    ------
    ValueError
        If ``format`` is not ``RenderFormat.TEXT``.
    """
    fmt = RenderFormat(format)
    if fmt is RenderFormat.TEXT:
        return profile_to_text(profile=profile)
    raise ValueError(
        f"render_profile only supports {RenderFormat.TEXT.value!r}, got {fmt.value!r}."
    )


def render_result(
    result: ValidationResult,
    *,
    format: RenderFormat | str = RenderFormat.TEXT,  # noqa: A002
) -> str:
    """Render a :class:`ValidationResult` as text.

    Only ``RenderFormat.TEXT`` is supported.

    Raises
    ------
    ValueError
        If ``format`` is not ``RenderFormat.TEXT``.
    """
    fmt = RenderFormat(format)
    if fmt is RenderFormat.TEXT:
        return result_to_text(result=result)
    raise ValueError(
        f"render_result only supports {RenderFormat.TEXT.value!r}, got {fmt.value!r}."
    )


def display(graph_definition: GraphDefinition) -> None:
    """Display a :class:`GraphDefinition` Mermaid diagram inline (Jupyter).

    Requires the ``notebook`` extra (IPython); raises
    :class:`~orthograph.dependencies.MissingDependencyError` if IPython is absent.
    """
    display_mermaid(obj=graph_definition)
