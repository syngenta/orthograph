"""Visualization package for orthograph.

Provides renderers that convert orthograph data structures into
human-readable formats (Mermaid diagrams, plain text tables).

Quick start::

    from orthograph.visualization import render

    mermaid_text = render(model, format="mermaid")
    table_text = render(profile, format="text")
    summary = render(result, format="text")

Or use direct imports::

    from orthograph.visualization.mermaid import model_to_mermaid
    from orthograph.visualization.text import profile_to_text, result_to_text
"""

from orthograph.core.errors import ValidationResult
from orthograph.core.graph_data_model import GraphDataModel
from orthograph.extensions.models import GraphProfile
from orthograph.visualization.mermaid import display_mermaid, model_to_mermaid
from orthograph.visualization.text import (
    model_to_text,
    profile_to_text,
    result_to_text,
)


__all__ = [
    "render",
    "display_mermaid",
    "model_to_mermaid",
    "model_to_text",
    "profile_to_text",
    "result_to_text",
]

_FORMATS = {"mermaid", "text"}


def render(
    obj: GraphDataModel | GraphProfile | ValidationResult,
    *,
    format: str = "text",
) -> str:
    """Render an orthograph object in the requested format.

    Parameters
    ----------
    obj : GraphDataModel | GraphProfile | ValidationResult
        The object to render.
    format : str
        Output format: ``"mermaid"`` or ``"text"``.  Mermaid format is
        only supported for ``GraphDataModel``.

    Returns
    -------
    str
        The rendered output.

    Raises
    ------
    ValueError
        If the format is unsupported or the input type has no renderer
        for the requested format.
    """
    if format not in _FORMATS:
        raise ValueError(
            f"Unsupported format {format!r}. Choose from: {sorted(_FORMATS)}"
        )

    if isinstance(obj, GraphDataModel):
        if format == "mermaid":
            return model_to_mermaid(obj)
        return model_to_text(obj)

    if isinstance(obj, GraphProfile):
        if format == "mermaid":
            raise ValueError(
                "Mermaid format is not supported for GraphProfile. "
                "Use format='text' instead."
            )
        return profile_to_text(obj)

    if isinstance(obj, ValidationResult):
        if format == "mermaid":
            raise ValueError(
                "Mermaid format is not supported for ValidationResult. "
                "Use format='text' instead."
            )
        return result_to_text(obj)

    raise TypeError(
        f"Cannot render object of type {type(obj).__name__}. "
        "Expected GraphDataModel, GraphProfile, or ValidationResult."
    )
