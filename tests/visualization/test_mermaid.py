"""Tests for orthograph.visualization.mermaid."""

import pytest

from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.models import (
    CardinalitySpec,
    ConditionalCardinality,
    ConditionalRule,
    NodeModel,
    PropMatch,
    RelationshipModel,
)
from orthograph.visualization.mermaid import (
    _mermaid_ink_url,
    display_mermaid,
    model_to_mermaid,
)
from tests.fixtures.conftest import ActedIn, Directed, Movie, Person


# --- Model definitions for tests ---


# Note: Person, Movie, ActedIn, Directed imported from tests.fixtures.conftest


class FriendOf(RelationshipModel):
    __label__ = "FRIEND_OF"
    __source_label__ = "Person"
    __target_label__ = "Person"
    __directed__ = False


class Company(NodeModel):
    __label__ = "Company"
    __uid_field__ = "name"
    name: str


class Collaborates(RelationshipModel):
    __label__ = "COLLABORATES"
    __source_label__ = "Person"
    __target_label__ = "Company"
    __directed__ = False


class LivesIn(RelationshipModel):
    __label__ = "LIVES_IN"
    __source_label__ = "Person"
    __target_label__ = "Company"
    __source_cardinality__ = "1..1"
    __target_cardinality__ = "0..*"


# --- Fixtures ---


@pytest.fixture()
def graph_definition() -> GraphDefinition:
    return GraphDefinition(
        name="Film",
        node_types=[Person, Movie],
        relationship_types=[ActedIn, Directed],
    )


@pytest.fixture()
def undirected_model() -> GraphDefinition:
    return GraphDefinition(
        name="Social",
        node_types=[Person],
        relationship_types=[FriendOf],
    )


# ============================================================
# model_to_mermaid tests
# ============================================================


def test_mermaid_basic(graph_definition: GraphDefinition):
    mermaid = model_to_mermaid(graph_definition)
    assert "graph TD" in mermaid
    assert "Person" in mermaid
    assert "Movie" in mermaid
    assert "ACTED_IN" in mermaid
    assert "DIRECTED" in mermaid


def test_mermaid_directed_arrow(graph_definition: GraphDefinition):
    mermaid = model_to_mermaid(graph_definition)
    assert "-->" in mermaid


def test_mermaid_undirected_arrow(undirected_model: GraphDefinition):
    mermaid = model_to_mermaid(undirected_model)
    assert "---" in mermaid


def test_mermaid_node_properties(graph_definition: GraphDefinition):
    mermaid = model_to_mermaid(graph_definition)
    assert "name" in mermaid
    assert "age" in mermaid


def test_mermaid_uid_field_highlighted(graph_definition: GraphDefinition):
    """UID fields should be marked with UID in the output."""
    mermaid = model_to_mermaid(graph_definition)
    assert "UID" in mermaid


def test_mermaid_no_square_brackets_in_labels(graph_definition: GraphDefinition):
    """Output should not contain [UID] since brackets break Mermaid syntax."""
    mermaid = model_to_mermaid(graph_definition)
    assert "[UID]" not in mermaid


def test_mermaid_cardinality_labels():
    """Edges should show cardinality labels."""
    m = GraphDefinition(
        name="Card",
        node_types=[Person, Company],
        relationship_types=[LivesIn],
    )
    mermaid = model_to_mermaid(m)
    assert "1..1" in mermaid
    assert "0..*" in mermaid


def test_mermaid_required_optional_markers(graph_definition: GraphDefinition):
    """Required and optional properties should be distinguished."""
    mermaid = model_to_mermaid(graph_definition)
    assert "name: str" in mermaid


def test_mermaid_undirected_cross_type():
    """Undirected cross-type relationship uses '---' arrow."""
    m = GraphDefinition(
        name="Cross",
        node_types=[Person, Company],
        relationship_types=[Collaborates],
    )
    mermaid = model_to_mermaid(m)
    assert "---" in mermaid
    assert "Person" in mermaid
    assert "Company" in mermaid
    assert "COLLABORATES" in mermaid


def test_mermaid_mixed_directed_and_undirected():
    """Model with both directed and undirected uses correct arrows."""
    m = GraphDefinition(
        name="Mixed",
        node_types=[Person, Movie, Company],
        relationship_types=[ActedIn, FriendOf, Collaborates],
    )
    mermaid = model_to_mermaid(m)
    assert "---" in mermaid
    assert "-->" in mermaid


def test_mermaid_relationship_properties(graph_definition: GraphDefinition):
    """Relationship properties should appear in the edge label."""
    mermaid = model_to_mermaid(graph_definition)
    assert "role: str" in mermaid


# ============================================================
# _mermaid_ink_url tests
# ============================================================


def test_mermaid_ink_url_produces_valid_url():
    url = _mermaid_ink_url("graph TD\n    A --> B")
    assert url.startswith("https://mermaid.ink/img/")
    assert len(url) > len("https://mermaid.ink/img/")


def test_mermaid_ink_url_is_deterministic():
    graph = "graph TD\n    A --> B"
    assert _mermaid_ink_url(graph) == _mermaid_ink_url(graph)


def test_mermaid_ink_url_uses_urlsafe_base64():
    """URL should use urlsafe base64 (no + or / characters)."""
    url = _mermaid_ink_url("graph TD\n    A --> B")
    encoded_part = url.split("/img/")[1]
    assert "+" not in encoded_part
    assert "/" not in encoded_part


# ============================================================
# display_mermaid tests
# ============================================================


def test_display_mermaid_with_string(mocker):
    """display_mermaid accepts a raw Mermaid string."""
    mock_display = mocker.patch(
        "orthograph.visualization.mermaid.display",
        create=True,
    )
    mock_image = mocker.patch(
        "orthograph.visualization.mermaid.Image",
        create=True,
    )
    mocker.patch.dict(
        "sys.modules",
        {
            "IPython": mocker.MagicMock(),
            "IPython.display": mocker.MagicMock(Image=mock_image, display=mock_display),
        },
    )

    display_mermaid("graph TD\n    A --> B")

    mock_image.assert_called_once()
    call_kwargs = mock_image.call_args
    assert "mermaid.ink" in call_kwargs.kwargs["url"]
    mock_display.assert_called_once()


def test_display_mermaid_with_model(mocker, graph_definition: GraphDefinition):
    """display_mermaid accepts a GraphDefinition and converts it."""
    mock_display = mocker.patch(
        "orthograph.visualization.mermaid.display",
        create=True,
    )
    mock_image = mocker.patch(
        "orthograph.visualization.mermaid.Image",
        create=True,
    )
    mocker.patch.dict(
        "sys.modules",
        {
            "IPython": mocker.MagicMock(),
            "IPython.display": mocker.MagicMock(Image=mock_image, display=mock_display),
        },
    )

    display_mermaid(graph_definition)

    mock_image.assert_called_once()
    mock_display.assert_called_once()


def test_display_mermaid_rejects_unsupported_type():
    """display_mermaid raises TypeError for unsupported input."""
    with pytest.raises(TypeError, match="Cannot render"):
        display_mermaid(42)  # type: ignore[arg-type]


# ============================================================
# Conditional cardinality tests
# ============================================================


class Operation(NodeModel):
    """Test node type for conditional cardinality."""

    __label__ = "Operation"
    __uid_field__ = "id"
    id: str
    kind: str


class Sample(NodeModel):
    """Test node type for conditional cardinality."""

    __label__ = "Sample"
    __uid_field__ = "id"
    id: str
    kind: str


class HasOutput(RelationshipModel):
    """Test relationship with conditional cardinality."""

    __label__ = "HAS_OUTPUT"
    __source_label__ = "Operation"
    __target_label__ = "Sample"
    __source_cardinality__ = ConditionalCardinality(
        rules=(
            ConditionalRule(
                source=PropMatch({"kind": "subsampling"}),
                target=PropMatch({"kind": "subsampling"}),
                spec=CardinalitySpec(min=1, max=2),
            ),
            ConditionalRule(
                source=PropMatch({"kind": "split"}),
                target=PropMatch({"kind": "nothing"}),
                spec="0..0",
            ),
        ),
        default="0..*",
    )


def test_mermaid_conditional_cardinality_renders():
    """model_to_mermaid renders conditional cardinality without crashing."""
    m = GraphDefinition(
        name="ConditionalTest",
        node_types=[Operation, Sample],
        relationship_types=[HasOutput],
    )
    mermaid = model_to_mermaid(m)
    assert "graph TD" in mermaid
    assert "Operation" in mermaid
    assert "Sample" in mermaid
    assert "HAS_OUTPUT" in mermaid
    # Should contain some representation of the conditional cardinality
    assert "{" in mermaid  # Conditional summary starts with {


def test_mermaid_constant_cardinality_unchanged():
    """Constant cardinality rendering in mermaid is unchanged (regression)."""
    m = GraphDefinition(
        name="ConstantTest",
        node_types=[Person, Movie],
        relationship_types=[ActedIn, Directed],
    )
    mermaid = model_to_mermaid(m)
    assert "ACTED_IN" in mermaid
    # Should render as simple min..max
    assert "0..*" in mermaid


def test_mermaid_pipe_labels_contain_no_br_tags():
    """Edge pipe labels must not contain <br> — Mermaid does not support HTML there."""
    m = GraphDefinition(
        name="BrTest",
        node_types=[Person, Company],
        relationship_types=[LivesIn],
    )
    mermaid = model_to_mermaid(m)
    # Extract only the pipe-label sections (between | ... |) and assert no <br>
    import re

    pipe_labels = re.findall(r"\|([^|]+)\|", mermaid)
    for label in pipe_labels:
        assert "<br>" not in label, f"Pipe label contains <br>: {label!r}"


def test_mermaid_edge_label_parts_joined_with_space():
    """Multi-part edge labels (name + props + cardinality) are joined with a space."""
    m = GraphDefinition(
        name="SepTest",
        node_types=[Person, Company],
        relationship_types=[LivesIn],
    )
    mermaid = model_to_mermaid(m)
    # The pipe label should contain the rel name and cardinality separated by spaces,
    # not by <br> or any other HTML tag.
    assert "LIVES_IN 1..1 : 0..*" in mermaid
