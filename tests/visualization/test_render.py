"""Tests for orthograph.visualization.render dispatcher."""

from datetime import datetime

import pytest

from orthograph.core.exceptions import ValidationResult
from orthograph.core.graph_data_model import GraphDataModel
from orthograph.core.node_model import NodeModel
from orthograph.core.relationship_model import RelationshipModel
from orthograph.extensions.models import (
    GraphProfile,
    NodeTypeProfile,
    PropertyProfile,
)
from orthograph.visualization import render


# --- Minimal models for dispatcher tests ---


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
    __source_type__ = Alpha
    __target_type__ = Beta


@pytest.fixture()
def model() -> GraphDataModel:
    return GraphDataModel(
        name="Dispatch",
        node_types=[Alpha, Beta],
        relationship_types=[AlphaToBeta],
    )


@pytest.fixture()
def profile() -> GraphProfile:
    return GraphProfile(
        source="test",
        timestamp=datetime(2026, 1, 1),
        node_type_profiles={
            "Alpha": NodeTypeProfile(
                label="Alpha",
                count=3,
                property_profiles={
                    "uid": PropertyProfile(
                        name="uid",
                        present_count=3,
                        total_count=3,
                        observed_types=["str"],
                    ),
                },
            ),
        },
    )


@pytest.fixture()
def result() -> ValidationResult:
    return ValidationResult()


# --- Dispatcher tests ---


def test_render_model_mermaid(model: GraphDataModel):
    output = render(model, format="mermaid")
    assert "graph TD" in output
    assert "Alpha" in output


def test_render_model_text(model: GraphDataModel):
    output = render(model, format="text")
    assert "Model: Dispatch" in output
    assert "Alpha" in output


def test_render_profile_mermaid_raises(profile: GraphProfile):
    with pytest.raises(ValueError, match="Mermaid format is not supported"):
        render(profile, format="mermaid")


def test_render_profile_text(profile: GraphProfile):
    output = render(profile, format="text")
    assert "Profile: test" in output
    assert "Alpha" in output


def test_render_result_text(result: ValidationResult):
    output = render(result, format="text")
    assert "Validation: PASS" in output


def test_render_result_mermaid_raises(result: ValidationResult):
    with pytest.raises(ValueError, match="Mermaid format is not supported"):
        render(result, format="mermaid")


def test_render_unsupported_format(model: GraphDataModel):
    with pytest.raises(ValueError, match="Unsupported format"):
        render(model, format="html")


def test_render_unsupported_type():
    with pytest.raises(TypeError, match="Cannot render"):
        render("not a model", format="text")  # type: ignore[arg-type]
