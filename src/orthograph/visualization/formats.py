"""Render output formats — the switchable, extensible format vocabulary.

A plain string-valued enum so callers may pass either the enum member
(``RenderFormat.MERMAID``) or coerce from a string (``RenderFormat("mermaid")``).
Adding a new output format is one new member here plus one branch in the
renderer(s) that support it — no call-signature changes required.
"""

from enum import Enum


class RenderFormat(str, Enum):
    """Supported render output formats."""

    TEXT = "text"
    MERMAID = "mermaid"
