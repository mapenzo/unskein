"""Write config files: ``unskein init``'s commented template and ``unskein config save``."""

import os
from pathlib import Path

from unskein.config import TomlConfig, read_toml_file
from unskein.errors import ErrorKey, UnskeinError
from unskein.resources import read_package_text

TEMPLATE_RESOURCE = "templates/unskein.toml"
# Owner read/write only: a saved config may hold an API key.
PRIVATE_FILE_MODE = 0o600


def config_template() -> str:
    """Return the commented ``.unskein.toml`` template bundled with unskein.

    Returns:
        The template text, where every setting is commented out at its default.
    """
    return read_package_text(TEMPLATE_RESOURCE)


def write_config(target: Path, *, force: bool = False) -> None:
    """Write the template to ``target``, creating its folder if needed.

    Args:
        target: Config file to create.
        force: Whether to replace a file that already exists.

    Raises:
        UnskeinError: ``CONFIG_EXISTS`` if ``target`` exists and ``force`` is off.
    """
    _check_overwrite(target, force)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(config_template(), encoding="utf-8")


def save_user_config(source: Path, target: Path, *, force: bool = False) -> TomlConfig:
    """Validate a config file and copy it verbatim, comments included, to ``target``.

    Args:
        source: Config file to save, usually a project's ``.unskein.toml``.
        target: User-wide config file (``~/.config/unskein/config.toml``).
        force: Whether to replace a file that already exists.

    Returns:
        The validated settings, so the caller can warn about a key written in them.

    Raises:
        UnskeinError: ``CONFIG_NOT_FOUND`` if ``source`` is not a file, or
            ``CONFIG_EXISTS`` if ``target`` exists and ``force`` is off.
        ConfigError: If ``source`` is invalid; nothing is written then.
    """
    if not source.is_file():
        raise UnskeinError(ErrorKey.CONFIG_NOT_FOUND, {"path": str(source)})
    settings = TomlConfig.model_validate(read_toml_file(source))
    _check_overwrite(target, force)
    target.parent.mkdir(parents=True, exist_ok=True)
    _write_private(target, source.read_text(encoding="utf-8"))
    return settings


def _check_overwrite(target: Path, force: bool) -> None:
    """Refuse to replace an existing file unless forced.

    Args:
        target: File about to be written.
        force: Whether replacing it is allowed.

    Raises:
        UnskeinError: ``CONFIG_EXISTS`` if ``target`` exists and ``force`` is off.
    """
    if target.exists() and not force:
        raise UnskeinError(ErrorKey.CONFIG_EXISTS, {"path": str(target)})


def _write_private(target: Path, text: str) -> None:
    """Write a file only its owner can read (the mode bits do nothing on Windows).

    Args:
        target: File to create or replace.
        text: Contents, written as UTF-8.
    """
    # Created private, so the text is never readable by others, not even briefly;
    # chmod covers a file that already existed with a wider mode.
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, PRIVATE_FILE_MODE)
    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
        file.write(text)
    os.chmod(target, PRIVATE_FILE_MODE)
