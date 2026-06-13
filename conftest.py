"""Root pytest configuration: DB integration markers and CLI options.

Must live at the project root (not inside ``tests/``) because
``notebooks/conftest.py`` depends on the ``--neo4j`` and ``--memgraph`` flags
registered here.  Pytest determines the rootdir from ``pyproject.toml`` and
loads this file for every invocation — including ``pytest notebooks/`` — so
flags and skip-logic defined here are always available.

Usage:

    pytest                        # unit tests only (default, CI)
    pytest --neo4j                # also run tests that need Neo4j
    pytest --memgraph             # also run tests that need Memgraph
    pytest --neo4j --memgraph     # run all DB-dependent tests

Connection options (all have defaults that match a stock local install):

    --neo4j-uri         bolt://localhost:7687
    --neo4j-user        neo4j
    --neo4j-password    password
    --memgraph-uri      bolt://localhost:7688
    --memgraph-user     (empty)
    --memgraph-password (empty)

Markers are declared in ``pyproject.toml`` under
``[tool.pytest.ini_options] markers``; they are not re-registered here to
avoid duplication.
"""

from typing import Any, Generator

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register --neo4j / --memgraph flags and their connection-detail options."""
    parser.addoption(
        "--neo4j",
        action="store_true",
        default=False,
        help="Run tests that require a live Neo4j instance.",
    )
    parser.addoption(
        "--memgraph",
        action="store_true",
        default=False,
        help="Run tests that require a live Memgraph instance.",
    )
    parser.addoption(
        "--neo4j-uri",
        default="bolt://localhost:7687",
        help="Bolt URI for the Neo4j instance (default: bolt://localhost:7687).",
    )
    parser.addoption(
        "--neo4j-user",
        default="neo4j",
        help="Neo4j username (default: neo4j).",
    )
    parser.addoption(
        "--neo4j-password",
        default="password",
        help="Neo4j password (default: password).",
    )
    parser.addoption(
        "--memgraph-uri",
        default="bolt://localhost:7688",
        help="Bolt URI for the Memgraph instance (default: bolt://localhost:7688).",
    )
    parser.addoption(
        "--memgraph-user",
        default="",
        help="Memgraph username (default: empty).",
    )
    parser.addoption(
        "--memgraph-password",
        default="",
        help="Memgraph password (default: empty).",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Skip DB-marked tests unless the corresponding flag is provided."""
    run_neo4j = config.getoption("--neo4j")
    run_memgraph = config.getoption("--memgraph")

    skip_neo4j = pytest.mark.skip(reason="needs --neo4j flag to run")
    skip_memgraph = pytest.mark.skip(reason="needs --memgraph flag to run")

    for item in items:
        # Gate on the *applied marker*, not ``item.keywords``.  ``item.keywords``
        # also contains the names of the test's parent directories, so matching
        # "neo4j"/"memgraph" there would skip every pure unit test living under
        # ``tests/backends/{neo4j,memgraph}/`` even when it carries no marker.
        markers = {marker.name for marker in item.iter_markers()}
        if "neo4j" in markers and not run_neo4j:
            item.add_marker(skip_neo4j)
        if "memgraph" in markers and not run_memgraph:
            item.add_marker(skip_memgraph)


@pytest.fixture(scope="session")
def neo4j_driver(request: pytest.FixtureRequest) -> Generator[Any, None, None]:
    """Session-scoped Neo4j driver.

    Opened once per test session; closed at teardown.  Reads connection
    details from the CLI options registered above.
    """
    from neo4j import GraphDatabase

    uri = request.config.getoption("--neo4j-uri")
    user = request.config.getoption("--neo4j-user")
    password = request.config.getoption("--neo4j-password")
    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        yield driver
    finally:
        driver.close()


@pytest.fixture()
def neo4j_clean(neo4j_driver: Any) -> Generator[None, None, None]:
    """Wipe all nodes and relationships before and after each test.

    Ensures every test starts from a clean slate and leaves no residue,
    regardless of test execution order.
    """
    neo4j_driver.execute_query("MATCH (n) DETACH DELETE n")
    yield
    neo4j_driver.execute_query("MATCH (n) DETACH DELETE n")


@pytest.fixture(scope="session")
def memgraph_driver(request: pytest.FixtureRequest) -> Generator[Any, None, None]:
    """Session-scoped Memgraph driver.

    Opened once per test session; closed at teardown.
    """
    from neo4j import GraphDatabase

    uri = request.config.getoption("--memgraph-uri")
    user = request.config.getoption("--memgraph-user")
    password = request.config.getoption("--memgraph-password")
    auth = (user, password) if user else ("", "")
    driver = GraphDatabase.driver(uri, auth=auth)
    try:
        yield driver
    finally:
        driver.close()


@pytest.fixture()
def memgraph_clean(memgraph_driver: Any) -> Generator[None, None, None]:
    """Wipe all nodes and relationships before and after each test."""
    memgraph_driver.execute_query("MATCH (n) DETACH DELETE n")
    yield
    memgraph_driver.execute_query("MATCH (n) DETACH DELETE n")
