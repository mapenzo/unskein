"""Entry points of a distribution, read from the scripts its ``[project]`` table declares."""

SCRIPT_TABLES = ("scripts", "gui-scripts")


def script_modules_of(project: object) -> tuple[str, ...]:
    """Return the modules that a ``[project]`` table's console and GUI scripts point at.

    Args:
        project: The parsed ``[project]`` table, or anything else when the manifest has none.

    Returns:
        Sorted, unique module names (the part before ``:`` of each script target).
    """
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
