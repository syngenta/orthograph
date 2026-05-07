"""Root pytest configuration: DB integration markers and CLI options.

This conftest registers custom markers for tests that require a live
database connection and provides CLI flags to opt in to running them:

    pytest                        # unit tests only (default)
    pytest --neo4j                # also run tests that need Neo4j
    pytest --memgraph             # also run tests that need Memgraph
    pytest --neo4j --memgraph     # run all DB-dependent tests

Tests are marked with ``@pytest.mark.neo4j`` or ``@pytest.mark.memgraph``.
Without the corresponding CLI flag, marked tests are automatically skipped.

For notebook execution via nbval, the same flags are respected by
``notebooks/conftest.py`` which controls collection of DB-requiring
notebooks.
"""

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add --neo4j and --memgraph CLI flags."""
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


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line("markers", "neo4j: test requires a live Neo4j database")
    config.addinivalue_line(
        "markers", "memgraph: test requires a live Memgraph database"
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
        if "neo4j" in item.keywords and not run_neo4j:
            item.add_marker(skip_neo4j)
        if "memgraph" in item.keywords and not run_memgraph:
            item.add_marker(skip_memgraph)
