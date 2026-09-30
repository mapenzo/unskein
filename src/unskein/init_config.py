"""Commented configuration template shipped with the package, and ``unskein init``'s writer."""

from importlib.resources import files
from pathlib import Path

from unskein.errors import ErrorKey, UnskeinError

TEMPLATE_RESOURCE = "templates/unskein.toml"


def config_template() -> str:
    """Return the commented ``.unskein.toml`` template bundled with unskein.

    Returns:
        The template text, where every setting is commented out at its default.
    """
    return files("unskein").joinpath(TEMPLATE_RESOURCE).read_text(encoding="utf-8")


def write_config(target: Path, *, force: bool = False) -> None:
    """Write the template to ``target``, creating its folder if needed.

    Args:
        target: Config file to create.
        force: Whether to replace a file that already exists.

    Raises:
        UnskeinError: ``CONFIG_EXISTS`` if ``target`` exists and ``force`` is off.
    """
    if target.exists() and not force:
        raise UnskeinError(ErrorKey.CONFIG_EXISTS, {"path": str(target)})
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(config_template(), encoding="utf-8")
