"""Entry points of a project, read from the scripts its ``pyproject.toml`` declares."""

import logging
import tomllib
from pathlib import Path

logger = logging.getLogger("unskein")

PYPROJECT_NAME = "pyproject.toml"
SCRIPT_TABLES = ("scripts", "gui-scripts")


def read_script_modules(root: Path) -> tuple[str, ...]:
    """Return the modules that the project's console and GUI scripts point at.

    A missing file or a project without scripts gives no entry points. A file
    that cannot be read or parsed is reported once through the ``unskein``
    logger and ignored: the scan must not depend on it.

    Args:
        root: Project root, where ``pyproject.toml`` lives.

    Returns:
        Sorted, unique module names (the part before ``:`` of each script target).
    """
    path = root / PYPROJECT_NAME
    if not path.is_file():
        return ()
    try:
        with path.open("rb") as file:
            project = tomllib.load(file).get("project")
    except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError) as error:
        logger.warning("Ignoring %s for entry points: %s", path, error)
        return ()
    if not isinstance(project, dict):
        return ()
    modules: set[str] = set()
    for table in SCRIPT_TABLES:
        scripts = project.get(table)
        if not isinstance(scripts, dict):
            continue
        for target in scripts.values():
            if isinstance(target, str):
                modules.add(target.partition(":")[0].strip())
    modules.discard("")
    return tuple(sorted(modules))
