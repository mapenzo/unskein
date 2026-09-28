from collections.abc import Callable
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def make_project(tmp_path: Path) -> Callable[[dict[str, str]], Path]:
    """Write {relative_path: source} under tmp_path and return the project root."""

    def _make(files: dict[str, str]) -> Path:
        for rel, source in files.items():
            path = tmp_path / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source, encoding="utf-8")
        return tmp_path

    return _make


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
