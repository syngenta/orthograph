"""Tests for orthograph.visualization.mermaid."""

import pytest

from orthograph.core.graph_data_model import GraphDataModel
from orthograph.core.node_model import NodeModel
from orthograph.core.relationship_model import RelationshipModel
from orthograph.core.types import Cardinality
from orthograph.visualization.mermaid import (
    _mermaid_ink_url,
    display_mermaid,
    model_to_mermaid,
)


# --- Model definitions for tests ---


class Person(NodeModel):
    __label__ = "Person"
    __uid_field__ = "name"
    name: str
    age: int


class Movie(NodeModel):
    __label__ = "Movie"
    __uid_field__ = "title"
    title: str
    year: int


class ActedIn(RelationshipModel):
    __label__ = "ACTED_IN"
    __source_type__ = Person
    __target_type__ = Movie
    role: str


class Directed(RelationshipModel):
    __label__ = "DIRECTED"
    __source_type__ = Person
    __target_type__ = Movie
    __directed__ = True


class FriendOf(RelationshipModel):
    __label__ = "FRIEND_OF"
    __source_type__ = Person
    __target_type__ = Person
    __directed__ = False


class Company(NodeModel):
    __label__ = "Company"
    __uid_field__ = "name"
    name: str


class Collaborates(RelationshipModel):
    __label__ = "COLLABORATES"
    __source_type__ = Person
    __target_type__ = Company
    __directed__ = False


class LivesIn(RelationshipModel):
    __label__ = "LIVES_IN"
    __source_type__ = Person
    __target_type__ = Company
    __source_cardinality__ = Cardinality.ONE
    __target_cardinality__ = Cardinality.ZERO_OR_MORE


# --- Fixtures ---


@pytest.fixture()
def model() -> GraphDataModel:
    return GraphDataModel(
        name="Film",
        node_types=[Person, Movie],
        relationship_types=[ActedIn, Directed],
    )


@pytest.fixture()
def undirected_model() -> GraphDataModel:
    return GraphDataModel(
        name="Social",
        node_types=[Person],
        relationship_types=[FriendOf],
    )


# ============================================================
# model_to_mermaid tests
# ============================================================


def test_mermaid_basic(model: GraphDataModel):
    mermaid = model_to_mermaid(model)
    assert "graph TD" in mermaid
    assert "Person" in mermaid
    assert "Movie" in mermaid
    assert "ACTED_IN" in mermaid
    assert "DIRECTED" in mermaid


def test_mermaid_directed_arrow(model: GraphDataModel):
    mermaid = model_to_mermaid(model)
    assert "-->" in mermaid


def test_mermaid_undirected_arrow(undirected_model: GraphDataModel):
    mermaid = model_to_mermaid(undirected_model)
    assert "---" in mermaid


def test_mermaid_node_properties(model: GraphDataModel):
    mermaid = model_to_mermaid(model)
    assert "name" in mermaid
    assert "age" in mermaid


def test_mermaid_uid_field_highlighted(model: GraphDataModel):
    """UID fields should be marked with UID in the output."""
    mermaid = model_to_mermaid(model)
    assert "UID" in mermaid


def test_mermaid_no_square_brackets_in_labels(model: GraphDataModel):
    """Output should not contain [UID] since brackets break Mermaid syntax."""
    mermaid = model_to_mermaid(model)
    assert "[UID]" not in mermaid


def test_mermaid_cardinality_labels():
    """Edges should show cardinality labels."""
    m = GraphDataModel(
        name="Card",
        node_types=[Person, Company],
        relationship_types=[LivesIn],
    )
    mermaid = model_to_mermaid(m)
    assert "1..1" in mermaid
    assert "0..*" in mermaid


def test_mermaid_required_optional_markers(model: GraphDataModel):
    """Required and optional properties should be distinguished."""
    mermaid = model_to_mermaid(model)
    assert "name: str" in mermaid


def test_mermaid_undirected_cross_type():
    """Undirected cross-type relationship uses '---' arrow."""
    m = GraphDataModel(
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
    m = GraphDataModel(
        name="Mixed",
        node_types=[Person, Movie, Company],
        relationship_types=[ActedIn, FriendOf, Collaborates],
    )
    mermaid = model_to_mermaid(m)
    assert "---" in mermaid
    assert "-->" in mermaid


def test_mermaid_relationship_properties(model: GraphDataModel):
    """Relationship properties should appear in the edge label."""
    mermaid = model_to_mermaid(model)
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


def test_display_mermaid_with_model(mocker, model: GraphDataModel):
    """display_mermaid accepts a GraphDataModel and converts it."""
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

    display_mermaid(model)

    mock_image.assert_called_once()
    mock_display.assert_called_once()


def test_display_mermaid_rejects_unsupported_type():
    """display_mermaid raises TypeError for unsupported input."""
    with pytest.raises(TypeError, match="Cannot render"):
        display_mermaid(42)  # type: ignore[arg-type]
