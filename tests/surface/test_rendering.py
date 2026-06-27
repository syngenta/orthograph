"""Tests for orthograph.rendering.

Covers render_model, render_profile, render_result, and display.
"""

from datetime import datetime
from unittest.mock import patch

import pytest

from orthograph.diagnostics.result import ValidationResult
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.models import NodeModel, RelationshipModel
from orthograph.graph_profile.models import (
    GraphProfile,
    NodeTypeProfile,
    PropertyProfile,
)
from orthograph.rendering import (
    display,
    render_model,
    render_profile,
    render_result,
)
from orthograph.visualization.formats import RenderFormat


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class Alpha(NodeModel):
    __label__ = "Alpha"
    __uid_field__ = "uid"
    uid: str


class Beta(NodeModel):
    __label__ = "Beta"
    __uid_field__ = "uid"
    uid: str


class AlphaToBeta(RelationshipModel):
    __label__ = "ALPHA_TO_BETA"
    __source_label__ = "Alpha"
    __target_label__ = "Beta"


@pytest.fixture()
def graph_definition() -> GraphDefinition:
    return GraphDefinition(
        name="Test",
        node_types=[Alpha, Beta],
        relationship_types=[AlphaToBeta],
    )


@pytest.fixture()
def profile() -> GraphProfile:
    return GraphProfile(
        source="test-db",
        timestamp=datetime(2026, 1, 1),
        node_type_profiles={
            "Alpha": NodeTypeProfile(
                label="Alpha",
                count=2,
                property_profiles={
                    "uid": PropertyProfile(
                        name="uid",
                        present_count=2,
                        total_count=2,
                        observed_types=["str"],
                    )
                },
            )
        },
        relationship_type_profiles={},
        constraint_profiles={},
    )


@pytest.fixture()
def result() -> ValidationResult:
    return ValidationResult()


# ---------------------------------------------------------------------------
# render_model
# ---------------------------------------------------------------------------


def test_render_model_default_is_text(graph_definition: GraphDefinition) -> None:
    out = render_model(graph_definition)
    assert isinstance(out, str)
    assert len(out) > 0


def test_render_model_text_explicit(graph_definition: GraphDefinition) -> None:
    assert render_model(graph_definition, fmt=RenderFormat.TEXT) == render_model(
        graph_definition
    )


def test_render_model_mermaid_enum(graph_definition: GraphDefinition) -> None:
    out = render_model(graph_definition, fmt=RenderFormat.MERMAID)
    assert "graph TD" in out


def test_render_model_mermaid_string(graph_definition: GraphDefinition) -> None:
    out = render_model(graph_definition, fmt="mermaid")
    assert "graph TD" in out


def test_render_model_invalid_format_raises(graph_definition: GraphDefinition) -> None:
    with pytest.raises(ValueError):
        render_model(graph_definition, fmt="html")


# ---------------------------------------------------------------------------
# render_profile
# ---------------------------------------------------------------------------


def test_render_profile_default_is_text(profile: GraphProfile) -> None:
    out = render_profile(profile)
    assert isinstance(out, str)
    assert "test-db" in out


def test_render_profile_text_explicit(profile: GraphProfile) -> None:
    assert render_profile(profile, fmt=RenderFormat.TEXT) == render_profile(profile)


def test_render_profile_string_coercion(profile: GraphProfile) -> None:
    assert render_profile(profile, fmt="text") == render_profile(profile)


def test_render_profile_mermaid_raises(profile: GraphProfile) -> None:
    with pytest.raises(ValueError, match="only supports"):
        render_profile(profile, fmt=RenderFormat.MERMAID)


def test_render_profile_invalid_format_raises(profile: GraphProfile) -> None:
    with pytest.raises(ValueError):
        render_profile(profile, fmt="dot")


# ---------------------------------------------------------------------------
# render_result
# ---------------------------------------------------------------------------


def test_render_result_default_is_text(result: ValidationResult) -> None:
    out = render_result(result)
    assert isinstance(out, str)


def test_render_result_text_explicit(result: ValidationResult) -> None:
    assert render_result(result, fmt=RenderFormat.TEXT) == render_result(result)


def test_render_result_string_coercion(result: ValidationResult) -> None:
    assert render_result(result, fmt="text") == render_result(result)


def test_render_result_shows_pass_for_valid() -> None:
    assert "PASS" in render_result(ValidationResult())


def test_render_result_mermaid_raises(result: ValidationResult) -> None:
    with pytest.raises(ValueError, match="only supports"):
        render_result(result, fmt=RenderFormat.MERMAID)


# ---------------------------------------------------------------------------
# display
# ---------------------------------------------------------------------------


def test_display_delegates_to_display_mermaid(
    graph_definition: GraphDefinition,
) -> None:
    with patch("orthograph.rendering.display_mermaid") as mock_display:
        display(graph_definition)
    mock_display.assert_called_once_with(obj=graph_definition)
