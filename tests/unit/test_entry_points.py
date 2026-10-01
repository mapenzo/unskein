import logging
from pathlib import Path

import pytest

from unskein.entry_points import read_script_modules


def write_pyproject(root: Path, text: str) -> None:
    """Write a ``pyproject.toml`` at the project root.

    Args:
        root: Project root.
        text: TOML content.
    """
    (root / "pyproject.toml").write_text(text, encoding="utf-8")


def test_scripts_and_gui_scripts_give_their_modules(tmp_path: Path) -> None:
    write_pyproject(
        tmp_path,
        '[project.scripts]\ntool = "pkg.cli:run"\nother = "pkg.cli:main"\n'
        '[project.gui-scripts]\nwin = "pkg.gui:start"\n',
    )

    assert read_script_modules(tmp_path) == ("pkg.cli", "pkg.gui")


def test_target_without_a_function_is_the_module_itself(tmp_path: Path) -> None:
    write_pyproject(tmp_path, '[project.scripts]\ntool = "pkg.cli"\n')

    assert read_script_modules(tmp_path) == ("pkg.cli",)


def test_missing_pyproject_is_not_an_error(tmp_path: Path) -> None:
    assert read_script_modules(tmp_path) == ()


@pytest.mark.parametrize(
    "text",
    [
        "[tool.ruff]\nline-length = 100\n",
        'project = "not a table"\n',
        '[project]\nscripts = "not a table"\n',
        '[project.scripts]\ntool = 3\nother = ""\n',
    ],
)
def test_unusable_scripts_give_no_entry_points_and_no_crash(tmp_path: Path, text: str) -> None:
    write_pyproject(tmp_path, text)

    assert read_script_modules(tmp_path) == ()


def test_invalid_toml_warns_and_is_ignored(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_pyproject(tmp_path, "[project\n")
    # The CLI tests turn propagation off on this logger; caplog needs it on.
    logger = logging.getLogger("unskein")
    monkeypatch.setattr(logger, "handlers", [])
    monkeypatch.setattr(logger, "propagate", True)

    with caplog.at_level(logging.WARNING, logger="unskein"):
        result = read_script_modules(tmp_path)

    assert result == ()
    assert [record.levelno for record in caplog.records] == [logging.WARNING]
    assert "pyproject.toml" in caplog.records[0].getMessage()


def test_invalid_utf8_warns_and_is_ignored(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "pyproject.toml").write_bytes(b'[project]\nname = "\xff"\n')
    # The CLI tests turn propagation off on this logger; caplog needs it on.
    logger = logging.getLogger("unskein")
    monkeypatch.setattr(logger, "handlers", [])
    monkeypatch.setattr(logger, "propagate", True)

    with caplog.at_level(logging.WARNING, logger="unskein"):
        result = read_script_modules(tmp_path)

    assert result == ()
    assert [record.levelno for record in caplog.records] == [logging.WARNING]
    assert "pyproject.toml" in caplog.records[0].getMessage()
