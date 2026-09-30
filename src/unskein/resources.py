"""Read text files shipped inside the unskein package."""

from importlib.resources import files


def read_package_text(relative_path: str) -> str:
    """Return a text file bundled with unskein, wherever it is installed.

    Args:
        relative_path: Path inside the ``unskein`` package, with ``/`` separators.

    Returns:
        The file's text, decoded as UTF-8.
    """
    return files("unskein").joinpath(relative_path).read_text(encoding="utf-8")
