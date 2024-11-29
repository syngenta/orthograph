from pathlib import Path

import pytest


@pytest.fixture
def data_folder_path():
    tests_folder_path = Path(__file__)
    data_folder_path = tests_folder_path.parent / "data"
    return data_folder_path
