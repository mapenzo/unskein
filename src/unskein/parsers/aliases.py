"""Find package aliases: directories a project reaches under a second, shorter name.

A project can expose a nested package at the top level with a directory symlink
(``src/admin_web -> verwaltung/admin_web``) and import it as ``admin_web``. Discovery
names files by their real path, so without the alias every such import looks external.
Where git checks symlinks out as plain files (``core.symlinks=false``, the Windows
default), the link is a small text file holding the relative target path; it is
recognized too.
"""

import os
from collections.abc import Collection, Iterable, Mapping
from pathlib import Path

from unskein.parsers.layout import PACKAGE_INIT_FILE, ProjectLayout

NAME_SEPARATOR = "."
# Names of non-importable files are POSIX paths; "/" never appears in a dotted name.
PATH_SEPARATOR = "/"
# A git symlink stub holds a single relative path; anything larger is not one.
LINK_STUB_MAX_BYTES = 1024


def resolve_alias(name: str, aliases: Mapping[str, str]) -> str:
    """Return a dotted name with its longest aliased prefix replaced by the alias target.

    Args:
        name: Dotted module name, e.g. ``admin_web.api``.
        aliases: Alias to target, both dotted names.

    Returns:
        The name under its real package, e.g. ``verwaltung.admin_web.api``; the name
        itself when no prefix of it is an alias.
    """
    if not aliases:
        return name
    parts = name.split(NAME_SEPARATOR)
    for end in range(len(parts), 0, -1):
        target = aliases.get(NAME_SEPARATOR.join(parts[:end]))
        if target is not None:
            return NAME_SEPARATOR.join([target, *parts[end:]])
    return name


def find_package_aliases(
    layout: ProjectLayout, sources: Iterable[Path], names: Collection[str]
) -> dict[str, str]:
    """Find the directory links inside the project that name a package a second time.

    Only import roots and directories that hold a source file are looked at, so no
    second walk of the tree is needed. A link counts when its own name and its target's
    name are both importable, and some module lives under one of them.

    Args:
        layout: Project layout that names the files.
        sources: Discovered source files.
        names: Module names given to those files.

    Returns:
        Alias to target, both dotted names, sorted by alias.
    """
    import_roots = {distribution.import_root for distribution in layout.distributions}
    directories = import_roots | {Path(os.path.abspath(path)).parent for path in sources}
    aliases: dict[str, str] = {}
    for directory in sorted(directories):
        for entry in _scan(directory):
            target = _link_target(entry, directory, layout.root)
            if target is None or target in import_roots:
                continue
            alias = _alias_name(layout, directory, entry.name, import_roots)
            real = _package_name(layout, target)
            if alias and real and alias != real and _has_modules(names, (alias, real)):
                aliases[alias] = real
    return dict(sorted(aliases.items()))


def _scan(directory: Path) -> list[os.DirEntry[str]]:
    """List a directory's entries, or none when it cannot be read.

    Args:
        directory: Directory to list.

    Returns:
        Its entries.
    """
    try:
        with os.scandir(directory) as entries:
            return list(entries)
    except OSError:
        return []


def _link_target(entry: os.DirEntry[str], directory: Path, root: Path) -> Path | None:
    """Return the in-project directory an entry links to, if it is a directory link.

    Args:
        entry: Directory entry to inspect.
        directory: Directory holding the entry.
        root: Absolute project directory.

    Returns:
        The target directory as an absolute path under ``root``, or None when the entry
        is not a link to a directory inside the project.
    """
    if entry.is_symlink():
        if not entry.is_dir():
            return None
        # Resolve against the real root so a project reached through a symlink still matches.
        real_root = Path(os.path.realpath(root))
        target = Path(os.path.realpath(entry.path))
        if not target.is_relative_to(real_root):
            return None
        return root / target.relative_to(real_root)
    return _stub_target(entry, directory, root)


def _stub_target(entry: os.DirEntry[str], directory: Path, root: Path) -> Path | None:
    """Return the directory a git symlink stub points to.

    A stub is a small file with no suffix whose whole content is a relative path to a
    directory, which is what git writes for a symlink when ``core.symlinks`` is off.

    Args:
        entry: Directory entry to inspect.
        directory: Directory holding the entry.
        root: Absolute project directory.

    Returns:
        The target directory as an absolute path under ``root``, or None when the entry
        is not such a stub.
    """
    if Path(entry.name).suffix or not entry.is_file(follow_symlinks=False):
        return None
    try:
        if entry.stat(follow_symlinks=False).st_size > LINK_STUB_MAX_BYTES:
            return None
        content = Path(entry.path).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    if not content or "\n" in content or "\0" in content or Path(content).is_absolute():
        return None
    target = Path(os.path.abspath(directory / content))
    if not target.is_dir() or not target.is_relative_to(root):
        return None
    return target


def _alias_name(
    layout: ProjectLayout, directory: Path, link_name: str, import_roots: set[Path]
) -> str | None:
    """Return the dotted name a link is imported by.

    Args:
        layout: Project layout.
        directory: Directory holding the link.
        link_name: File name of the link.
        import_roots: Import roots of every distribution.

    Returns:
        The dotted name, or None when it is not importable.
    """
    if not link_name.isidentifier():
        return None
    if directory in import_roots:
        return link_name
    parent = _package_name(layout, directory)
    return f"{parent}{NAME_SEPARATOR}{link_name}" if parent else None


def _package_name(layout: ProjectLayout, directory: Path) -> str | None:
    """Return the dotted name of the package a directory is, if it is importable.

    Args:
        layout: Project layout.
        directory: Directory below an import root.

    Returns:
        The dotted name, or None when the directory is not an importable package.
    """
    name = layout.name_of(directory / PACKAGE_INIT_FILE).name
    return None if PATH_SEPARATOR in name else name


def _has_modules(names: Collection[str], packages: tuple[str, ...]) -> bool:
    """Tell whether any module lives in one of the given packages.

    Args:
        names: Module names of the project.
        packages: Dotted package names.

    Returns:
        True when a name is one of the packages or lies under one.
    """
    prefixes = tuple(f"{package}{NAME_SEPARATOR}" for package in packages)
    return any(name in packages or name.startswith(prefixes) for name in names)
