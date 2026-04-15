"""Mermaid diagram renderers for GraphDataModel."""

import base64

from orthograph.core.graph_data_model import GraphDataModel
from orthograph.core.types import CardinalitySpec


def _format_cardinality(spec: CardinalitySpec) -> str:
    """Format a CardinalitySpec as a compact string (e.g., '0..1', '1..*')."""
    max_str = "*" if spec.max is None else str(spec.max)
    return f"{spec.min}..{max_str}"


def _mermaid_ink_url(graph: str) -> str:
    """Build a mermaid.ink image URL from a Mermaid diagram string."""
    graph_bytes = graph.encode("utf-8")
    base64_string = base64.urlsafe_b64encode(graph_bytes).decode("ascii")
    return f"https://mermaid.ink/img/{base64_string}"


def display_mermaid(obj: "GraphDataModel | str") -> None:
    """Render a Mermaid diagram inline in a Jupyter notebook.

    Accepts a raw Mermaid string or a ``GraphDataModel``.  Model objects
    are automatically converted to Mermaid text before rendering.

    Uses the mermaid.ink service to convert the diagram to an image.
    Requires an active internet connection and an IPython environment
    (Jupyter notebook or JupyterLab).

    Parameters
    ----------
    obj : GraphDataModel | str
        The object to render.  Strings are used as-is; models are
        converted via ``model_to_mermaid``.

    Raises
    ------
    ImportError
        If IPython is not available (not running in a notebook).
    TypeError
        If *obj* is not a supported type.
    """
    try:
        from IPython.display import Image, display
    except ImportError:
        raise ImportError(
            "display_mermaid() requires IPython. "
            "Run this function inside a Jupyter notebook."
        ) from None

    if isinstance(obj, str):
        mermaid_text = obj
    elif isinstance(obj, GraphDataModel):
        mermaid_text = model_to_mermaid(obj)
    else:
        raise TypeError(
            f"Cannot render object of type {type(obj).__name__}. "
            "Expected a Mermaid string or GraphDataModel."
        )

    url = _mermaid_ink_url(mermaid_text)
    display(Image(url=url))  # type: ignore[no-untyped-call]


def model_to_mermaid(model: GraphDataModel) -> str:
    """Convert a GraphDataModel to an enriched Mermaid diagram string.

    Node boxes show properties with type, required/optional marker, and
    UID field highlighting.  Relationship edges include cardinality labels.

    All output uses Mermaid-safe syntax: no square brackets in labels
    (UID fields use a ``#9670;`` diamond marker instead).
    """
    lines = ["graph TD"]

    for nt in model.node_types:
        specs = nt.get_property_specs()
        prop_parts: list[str] = []
        for name, info in specs.items():
            type_name = info.python_type.__name__
            marker = "" if info.is_required else "?"
            uid_marker = " UID" if name == nt.__uid_field__ else ""
            prop_parts.append(f"{name}: {type_name}{marker}{uid_marker}")
        props = ", ".join(prop_parts)
        lines.append(f'    {nt.__label__}["{nt.__label__}<br>{props}"]')

    for rt in model.relationship_types:
        src = rt.__source_type__.__label__
        tgt = rt.__target_type__.__label__
        arrow = "-->" if rt.__directed__ else "---"

        # Build label with relationship name, properties, and cardinality
        label_parts: list[str] = [rt.__label__]

        specs = rt.get_property_specs()
        if specs:
            props = ", ".join(
                f"{name}: {info.python_type.__name__}" for name, info in specs.items()
            )
            label_parts.append(props)

        src_card = _format_cardinality(rt.__source_cardinality__)
        tgt_card = _format_cardinality(rt.__target_cardinality__)
        label_parts.append(f"{src_card} : {tgt_card}")

        label_str = "<br>".join(label_parts)
        lines.append(f"    {src} {arrow}|{label_str}| {tgt}")

    return "\n".join(lines)
