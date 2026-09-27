from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def simple_project() -> Path:
    return FIXTURES_DIR / "simple_project"


@pytest.fixture
def circular_imports() -> Path:
    return FIXTURES_DIR / "circular_imports"


@pytest.fixture
def reexport_chain() -> Path:
    return FIXTURES_DIR / "reexport_chain"


@pytest.fixture
def reexport_cycle() -> Path:
    return FIXTURES_DIR / "reexport_cycle"
