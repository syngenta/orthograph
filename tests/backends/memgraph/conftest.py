"""Shared fixtures for Memgraph extension tests."""

# Import shared backend fixtures from parent conftest
from tests.backends.conftest import make_record, mock_execute_query  # noqa: F401
