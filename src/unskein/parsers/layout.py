"""Project layout: the distributions of a project and the packages each one ships."""

import configparser
import os
import tomllib
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from unskein.entry_points import script_modules_of
from unskein.parsers.models import DistributionInfo, ParseWarning, WarningCode
from unskein.parsers.requirements import normalize_name, read_dependencies

PYPROJECT_NAME = "pyproject.toml"
SETUP_PY_NAME = "setup.py"
SETUP_CFG_NAME = "setup.cfg"
MANIFEST_NAMES = (PYPROJECT_NAME, SETUP_PY_NAME, SETUP_CFG_NAME)
SRC_DIR = "src"
PACKAGE_INIT_FILE = "__init__.py"
PYTHON_SUFFIX = ".py"
MATURIN_MODULE_KEY = "module-name"
MATURIN_TABLE = "[tool.maturin]"
TOML_TABLE_START = "["
TOML_ASSIGNMENT = "="
# A normalized distribution name as an identifier: "litellm-enterprise" -> "litellm_enterprise".
NAME_SEPARATOR = "-"
IDENTIFIER_SEPARATOR = "_"
CFG_METADATA = "metadata"
CFG_NAME = "name"
SETUPTOOLS_BACKEND_PREFIX = "setuptools"


@dataclass(frozen=True, slots=True)
class Distribution:
    """A directory that builds one installable distribution, and what it ships.

    Attributes:
        root: Directory holding the manifest (or the project root).
        import_root: Directory dotted module names are computed from.
        packages: Top-level names it ships; None ships everything under ``import_root``.
        script_modules: Modules its ``[project.scripts]`` and ``gui-scripts`` point at.
        info: Name and declared dependencies; None when the manifest declares no name.
        native_declarations: Compiled modules its ``[tool.maturin]`` declares, each with the
            line of its ``module-name`` (None when it cannot be found).
    """

    root: Path
    import_root: Path
    packages: frozenset[str] | None
    script_modules: tuple[str, ...] = ()
    info: DistributionInfo | None = None
    native_declarations: tuple[tuple[str, int | None], ...] = ()


@dataclass(frozen=True, slots=True)
class _Declaration:
    """What a manifest says about where its packages live and which ones it ships.

    Attributes:
        import_root: Import root relative to the distribution root, when declared.
        packages: Declared top-level package names, when declared.
        name: Project name, when declared.
        script_modules: Modules its scripts point at.
        auto_discovers: Whether the build backend is setuptools (or none is declared),
            which ships every top-level package it finds when nothing is declared.
        native_declarations: Compiled modules ``[tool.maturin]`` declares, with their line.
    """

    import_root: str | None = None
    packages: frozenset[str] | None = None
    name: str | None = None
    script_modules: tuple[str, ...] = ()
    auto_discovers: bool = False
    native_declarations: tuple[tuple[str, int | None], ...] = ()


def relative_path(path: Path, root: Path | None) -> str:
    """Return a path as POSIX, relative to the project root when it lies under it.

    Args:
        path: File path.
        root: Absolute project directory, if known.

    Returns:
        The relative POSIX path, or the path as given.
    """
    absolute = _absolute(path)
    if root is not None and absolute.is_relative_to(root):
        return absolute.relative_to(root).as_posix()
    return path.as_posix()


def _absolute(path: Path) -> Path:
    """Return an absolute path without resolving symlinks.

    Args:
        path: Path to make absolute.

    Returns:
        The absolute, normalized path.
    """
    # abspath, not resolve(): a followed symlink must keep its in-project link path.
    return Path(os.path.abspath(path))


def detect_distributions(
    root: Path, files: Iterable[Path], configured: list[str] | None
) -> tuple[tuple[Distribution, ...], list[ParseWarning]]:
    """Find the distributions of a project and what each one ships.

    Manifests are looked for in every directory, up to the root, that holds a discovered
    file: excluded directories hold none, so excludes apply without a second walk. With
    configured source roots there is no detection: each root ships everything under it.

    Args:
        root: Project directory.
        files: Discovered source files.
        configured: Source roots relative to root, or None to detect them.

    Returns:
        The distributions, deepest import root first, plus the warnings about manifests
        that could not be used.
    """
    absolute_root = _absolute(root)
    warnings: list[ParseWarning] = []
    if configured is not None:
        root_scripts = _read_declaration(absolute_root, warnings).script_modules
        roots = {_absolute(absolute_root / r) for r in configured} - {absolute_root}
        found = [Distribution(r, r, None) for r in roots]
        found.append(Distribution(absolute_root, absolute_root, None, root_scripts))
        return _deepest_first(found), warnings
    found = []
    for directory in _manifest_directories(absolute_root, files):
        found.append(_distribution_at(directory, warnings))
    if not any(d.root == absolute_root for d in found):
        # No root manifest: today's naming, `src/` (when detected) first, then the root.
        default = _default_import_root(absolute_root)
        if default != absolute_root:
            found.append(Distribution(absolute_root, default, None))
        found.append(Distribution(absolute_root, absolute_root, None))
    return _deepest_first(found), warnings


def _deepest_first(distributions: list[Distribution]) -> tuple[Distribution, ...]:
    """Order distributions so the most specific import root is tried first.

    Args:
        distributions: Distributions in any order.

    Returns:
        Distributions by decreasing import-root depth, then by path for determinism.
    """
    return tuple(sorted(distributions, key=lambda d: (-len(d.import_root.parts), str(d.root))))


def _manifest_directories(root: Path, files: Iterable[Path]) -> list[Path]:
    """Return the directories under root, root included, that hold a manifest.

    Args:
        root: Absolute project directory.
        files: Discovered source files.

    Returns:
        Directories with a manifest, sorted.
    """
    directories = {root}
    for file in files:
        parent = _absolute(file).parent
        while parent not in directories and parent.is_relative_to(root):
            directories.add(parent)
            parent = parent.parent
    return sorted(d for d in directories if any((d / name).is_file() for name in MANIFEST_NAMES))


def _distribution_at(directory: Path, warnings: list[ParseWarning]) -> Distribution:
    """Build the distribution whose manifest lives in a directory.

    Args:
        directory: Directory holding a manifest.
        warnings: Collects problems with the manifest.

    Returns:
        The distribution, with its packages declared, conventional or found by heuristic.
    """
    declaration = _read_declaration(directory, warnings)
    if declaration.import_root is None:
        import_root = _default_import_root(directory)
    else:
        import_root = _absolute(directory / declaration.import_root)
    packages: frozenset[str] | None = _existing_declared(
        import_root, declaration.packages, warnings
    )
    if not packages:
        packages = _conventional_packages(import_root, declaration.name, declaration.auto_discovers)
    info = None
    if declaration.name is not None:
        declared = read_dependencies(directory, warnings)
        info = DistributionInfo(
            normalize_name(declaration.name),
            directory,
            declared.requires,
            declared.optional,
            declared.version,
            declared.manifest,
            declared.style,
            declared.groups,
        )
    return Distribution(
        directory,
        import_root,
        packages,
        declaration.script_modules,
        info,
        declaration.native_declarations,
    )


def _default_import_root(directory: Path) -> Path:
    """Return ``src/`` when it exists and is not itself a package, else the directory.

    Args:
        directory: Distribution root.

    Returns:
        The import root.
    """
    src = directory / SRC_DIR
    if src.is_dir() and not (src / PACKAGE_INIT_FILE).exists():
        return src
    return directory


def _existing_declared(
    import_root: Path, declared: frozenset[str] | None, warnings: list[ParseWarning]
) -> frozenset[str]:
    """Keep the declared packages that exist under the import root, warning about the rest.

    Args:
        import_root: Directory the packages live in.
        declared: Declared top-level names, or None.
        warnings: Collects one warning per missing package.

    Returns:
        The declared packages found on disk; empty when none were declared.
    """
    existing = set()
    for name in sorted(declared or ()):
        if (import_root / name).is_dir() or (import_root / f"{name}{PYTHON_SUFFIX}").is_file():
            existing.add(name)
        else:
            warnings.append(
                ParseWarning(WarningCode.DECLARED_PACKAGE_MISSING, import_root, None, name)
            )
    return frozenset(existing)


def _conventional_packages(
    import_root: Path, name: str | None, auto_discovers: bool
) -> frozenset[str] | None:
    """Return what a distribution ships when its manifest declares no packages.

    Setuptools auto-discovery ships the package named after the distribution plus every
    regular package; other backends ship the named one, else every regular package.

    Args:
        import_root: Directory the packages live in.
        name: Project name, when the manifest declares one.
        auto_discovers: Whether the backend ships every top-level package it finds.

    Returns:
        Top-level names, or None when none is found, so everything under the import root
        is shipped.
    """
    named: frozenset[str] = frozenset()
    if name is not None:
        normalized = normalize_name(name).replace(NAME_SEPARATOR, IDENTIFIER_SEPARATOR)
        if (import_root / normalized).is_dir() or (
            import_root / f"{normalized}{PYTHON_SUFFIX}"
        ).is_file():
            named = frozenset({normalized})
    if named and not auto_discovers:
        return named
    if not import_root.is_dir():
        return named or None
    regular = frozenset(
        entry.name
        for entry in import_root.iterdir()
        if entry.is_dir() and entry.name.isidentifier() and (entry / PACKAGE_INIT_FILE).is_file()
    )
    return (named | regular) or None


def _read_declaration(directory: Path, warnings: list[ParseWarning]) -> _Declaration:
    """Read what the manifests of a directory declare; ``setup.py`` is never executed.

    ``pyproject.toml`` wins over ``setup.cfg`` when both declare something.

    Args:
        directory: Directory holding the manifests.
        warnings: Collects one warning per manifest that cannot be read.

    Returns:
        The declaration; empty when nothing usable is declared.
    """
    pyproject = _load_toml(directory / PYPROJECT_NAME, warnings)
    declaration = (
        _declaration_from_pyproject(pyproject) if pyproject else _Declaration(auto_discovers=True)
    )
    if declaration.packages is None or declaration.name is None:
        from_cfg = _declaration_from_setup_cfg(directory / SETUP_CFG_NAME, warnings)
        declaration = _Declaration(
            declaration.import_root
            if declaration.import_root is not None
            else from_cfg.import_root,
            declaration.packages if declaration.packages is not None else from_cfg.packages,
            declaration.name or from_cfg.name,
            declaration.script_modules,
            declaration.auto_discovers,
        )
    return replace(
        declaration,
        native_declarations=_maturin_declarations(directory / PYPROJECT_NAME, pyproject, warnings),
    )


def _load_toml(path: Path, warnings: list[ParseWarning]) -> dict:
    """Load a TOML manifest, turning read and syntax errors into a warning.

    Args:
        path: Manifest path; a missing file gives an empty table.
        warnings: Collects the warning when the file cannot be used.

    Returns:
        The parsed table, or an empty one.
    """
    if not path.is_file():
        return {}
    try:
        with path.open("rb") as file:
            return tomllib.load(file)
    except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError) as error:
        warnings.append(ParseWarning(WarningCode.MANIFEST_UNREADABLE, path, None, str(error)))
        return {}


def _table(data: object, *keys: str) -> dict:
    """Walk nested TOML tables, returning an empty table when any step is not one.

    Args:
        data: Parsed TOML.
        *keys: Table names to descend through.

    Returns:
        The nested table, or an empty one.
    """
    for key in keys:
        data = data.get(key) if isinstance(data, dict) else None
    return data if isinstance(data, dict) else {}


def _string(value: object) -> str | None:
    """Return a value when it is a string, else None.

    Args:
        value: Any TOML value.

    Returns:
        The string or None.
    """
    return value if isinstance(value, str) else None


def _first_segments(names: Iterable[object]) -> frozenset[str] | None:
    """Return the first dotted segment of each string, or None when there is none.

    Args:
        names: Declared module or package names; non-strings are ignored.

    Returns:
        Top-level names, or None when nothing usable was declared.
    """
    segments = {name.split(".")[0] for name in names if isinstance(name, str) and name}
    return frozenset(segments) or None


def _declaration_from_pyproject(data: dict) -> _Declaration:
    """Extract import root, packages, name and scripts from a parsed ``pyproject.toml``.

    Args:
        data: Parsed ``pyproject.toml``.

    Returns:
        What the backends (uv, maturin, hatch, poetry, setuptools) declare.
    """
    project = _table(data, "project")
    poetry = _table(data, "tool", "poetry")
    name = _string(project.get("name")) or _string(poetry.get("name"))
    backend = _string(_table(data, "build-system").get("build-backend"))
    scripts = script_modules_of(project)
    for extract in (_uv_build, _maturin, _hatch, _poetry, _setuptools):
        import_root, packages = extract(data)
        if import_root is not None or packages is not None:
            # Without a [build-system], a backend's own tool table says which backend it is.
            auto_discovers = _auto_discovers(backend, extract is _setuptools)
            return _Declaration(import_root, packages, name, scripts, auto_discovers)
    return _Declaration(None, None, name, scripts, _auto_discovers(backend, True))


def _auto_discovers(backend: str | None, is_setuptools_table: bool) -> bool:
    """Tell whether the build backend is setuptools, which ships every package it finds.

    Args:
        backend: ``[build-system] build-backend``, when declared.
        is_setuptools_table: Whether the declaration came from setuptools or from nothing,
            as opposed to another backend's tool table.

    Returns:
        True for a setuptools backend, or when none is declared and no other backend's
        tool table is present.
    """
    if backend is None:
        return is_setuptools_table
    return backend.startswith(SETUPTOOLS_BACKEND_PREFIX)


def _uv_build(data: dict) -> tuple[str | None, frozenset[str] | None]:
    """Read ``[tool.uv.build-backend]`` ``module-root`` and ``module-name``.

    Args:
        data: Parsed ``pyproject.toml``.

    Returns:
        Import root and packages, each None when not declared.
    """
    backend = _table(data, "tool", "uv", "build-backend")
    module_name = backend.get("module-name")
    names = module_name if isinstance(module_name, list) else [module_name]
    return _string(backend.get("module-root")), _first_segments(names)


def _maturin(data: dict) -> tuple[str | None, frozenset[str] | None]:
    """Read ``[tool.maturin]`` ``python-source`` and ``module-name``.

    Args:
        data: Parsed ``pyproject.toml``.

    Returns:
        Import root and packages, each None when not declared.
    """
    maturin = _table(data, "tool", "maturin")
    return _string(maturin.get("python-source")), _first_segments([maturin.get("module-name")])


def _maturin_declarations(
    path: Path, data: dict, warnings: list[ParseWarning]
) -> tuple[tuple[str, int | None], ...]:
    """Return the compiled module ``[tool.maturin]`` declares, with its line.

    Args:
        path: The ``pyproject.toml``.
        data: Its parsed content.
        warnings: Collects an ``INVALID_MODULE_NAME`` when the name is not dotted identifiers.

    Returns:
        The full ``module-name`` and the line it is on; empty when none is declared.
    """
    name = _string(_table(data, "tool", "maturin").get(MATURIN_MODULE_KEY))
    if name is None:
        return ()
    if not all(part.isidentifier() for part in name.split(".")):
        warnings.append(ParseWarning(WarningCode.INVALID_MODULE_NAME, path, None, name))
        return ()
    return ((name, _key_line(path, MATURIN_TABLE, MATURIN_MODULE_KEY)),)


def _key_line(path: Path, table: str, key: str) -> int | None:
    """Return the line of a TOML file that assigns a key inside one table.

    Args:
        path: TOML file.
        table: Table header, e.g. ``[tool.maturin]``.
        key: Bare key name.

    Returns:
        The 1-based line number, or None when the file cannot be read or has no such line.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    in_table = False
    for number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith(TOML_TABLE_START):
            in_table = stripped == table
        elif (
            in_table
            and stripped.startswith(key)
            and stripped[len(key) :].lstrip().startswith(TOML_ASSIGNMENT)
        ):
            return number
    return None


def _hatch(data: dict) -> tuple[str | None, frozenset[str] | None]:
    """Read ``[tool.hatch.build.targets.wheel] packages`` (paths such as ``src/pkg``).

    Args:
        data: Parsed ``pyproject.toml``.

    Returns:
        Import root (the parent of the first path) and packages, each None when not declared.
    """
    paths = _table(data, "tool", "hatch", "build", "targets", "wheel").get("packages")
    if not isinstance(paths, list):
        return None, None
    usable = [Path(p) for p in paths if isinstance(p, str) and p]
    if not usable:
        return None, None
    return usable[0].parent.as_posix(), frozenset(p.name for p in usable)


def _poetry(data: dict) -> tuple[str | None, frozenset[str] | None]:
    """Read ``[tool.poetry] packages`` (``include`` and ``from``).

    Args:
        data: Parsed ``pyproject.toml``.

    Returns:
        Import root and packages, each None when not declared.
    """
    entries = _table(data, "tool", "poetry").get("packages")
    if not isinstance(entries, list):
        return None, None
    tables = [e for e in entries if isinstance(e, dict)]
    import_root = next((_string(e.get("from")) for e in tables if _string(e.get("from"))), None)
    return import_root, _first_segments(e.get("include") for e in tables)


def _setuptools(data: dict) -> tuple[str | None, frozenset[str] | None]:
    """Read ``[tool.setuptools]`` ``packages`` (explicit list) and ``package-dir`` ``""``.

    Args:
        data: Parsed ``pyproject.toml``.

    Returns:
        Import root and packages, each None when not declared.
    """
    setuptools = _table(data, "tool", "setuptools")
    packages = setuptools.get("packages")
    names = packages if isinstance(packages, list) else []
    return _string(_table(setuptools, "package-dir").get("")), _first_segments(names)


def _declaration_from_setup_cfg(path: Path, warnings: list[ParseWarning]) -> _Declaration:
    """Read ``[options] packages`` (explicit list), ``package_dir`` and the name from ``setup.cfg``.

    ``packages = find:`` is not a list of names, so it leaves packages undeclared.

    Args:
        path: ``setup.cfg`` path; a missing file declares nothing.
        warnings: Collects the warning when the file cannot be read.

    Returns:
        The declaration.
    """
    if not path.is_file():
        return _Declaration()
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(path, encoding="utf-8")
    except (configparser.Error, OSError, UnicodeDecodeError) as error:
        warnings.append(ParseWarning(WarningCode.MANIFEST_UNREADABLE, path, None, str(error)))
        return _Declaration()
    raw_packages = parser.get("options", "packages", fallback="").split()
    names = [n for n in raw_packages if not n.endswith(":")]
    import_root = None
    for line in parser.get("options", "package_dir", fallback="").splitlines():
        key, _, value = line.partition("=")
        if not key.strip() and value.strip():
            import_root = value.strip()
    name = parser.get(CFG_METADATA, CFG_NAME, fallback="").strip() or None
    return _Declaration(import_root, _first_segments(names), name)


@dataclass(frozen=True, slots=True)
class ModuleName:
    """The name a file takes in the dependency graph.

    Attributes:
        name: Dotted module name, or a POSIX path relative to the project root when
            the file cannot be imported (a path segment is not an identifier).
        is_packaged: Whether a distribution ships the file.
        distribution: Name of the distribution that ships the file; None when none with
            a name does.
    """

    name: str
    is_packaged: bool
    distribution: str | None = None


@dataclass(frozen=True, slots=True)
class ProjectLayout:
    """The distributions of a project and how they name its files.

    Attributes:
        root: Absolute project directory.
        distributions: Distributions, deepest import root first.
    """

    root: Path
    distributions: tuple[Distribution, ...]

    def name_of(self, file_path: Path) -> ModuleName:
        """Return the name a file takes: from the deepest distribution that ships it.

        Args:
            file_path: Python source file under the project root.

        Returns:
            The module name and whether a distribution ships it.
        """
        name, _ = _name_with_depth(self, _absolute(file_path))
        return name

    @property
    def script_modules(self) -> tuple[str, ...]:
        """Return the modules every distribution's scripts point at, sorted and unique."""
        return tuple(sorted({m for d in self.distributions for m in d.script_modules}))

    @property
    def distribution_infos(self) -> tuple[DistributionInfo, ...]:
        """Return the named distributions, sorted by name."""
        return tuple(
            sorted((d.info for d in self.distributions if d.info), key=lambda info: info.name)
        )


def _name_with_depth(layout: ProjectLayout, absolute: Path) -> tuple[ModuleName, int]:
    """Name a file and tell how deep the distribution that named it is.

    Args:
        layout: Project layout.
        absolute: Absolute file path.

    Returns:
        The name plus the depth of the naming import root (-1 when none ships it).
    """
    for distribution in layout.distributions:
        if not absolute.is_relative_to(distribution.import_root):
            continue
        parts = _module_parts(absolute.relative_to(distribution.import_root))
        depth = len(distribution.import_root.parts)
        owner = distribution.info.name if distribution.info else None
        if distribution.packages is None and not parts:
            return ModuleName(distribution.import_root.name, True, owner), depth
        if parts and _ships(distribution, parts):
            return ModuleName(".".join(parts), True, owner), depth
    parts = _module_parts(absolute.relative_to(layout.root))
    if all(part.isidentifier() for part in parts):
        return ModuleName(".".join(parts) or layout.root.name, False), -1
    return ModuleName(absolute.relative_to(layout.root).as_posix(), False), -1


def _module_parts(relative: Path) -> list[str]:
    """Return the dotted segments of a relative file path; ``__init__`` collapses.

    Args:
        relative: File path relative to an import root.

    Returns:
        Module name segments.
    """
    parts = list(relative.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return parts


def _ships(distribution: Distribution, parts: list[str]) -> bool:
    """Tell whether a distribution ships the module with these segments.

    Args:
        distribution: Candidate distribution.
        parts: Module name segments relative to its import root.

    Returns:
        True when every segment is an identifier and the first is one of its packages.
    """
    if not all(part.isidentifier() for part in parts):
        return False
    return distribution.packages is None or parts[0] in distribution.packages


def build_layout(
    root: Path, files: Sequence[Path], configured: list[str] | None
) -> tuple[ProjectLayout, list[ParseWarning]]:
    """Detect the distributions of a project and wrap them in a layout.

    Args:
        root: Project directory.
        files: Discovered source files.
        configured: Source roots relative to root, or None to detect them.

    Returns:
        The layout plus the warnings about unusable manifests.
    """
    distributions, warnings = detect_distributions(root, files, configured)
    distributions = _unique_names(distributions, warnings)
    return ProjectLayout(_absolute(root), distributions), warnings


def _unique_names(
    distributions: tuple[Distribution, ...], warnings: list[ParseWarning]
) -> tuple[Distribution, ...]:
    """Keep one distribution per name: the shallowest; the others lose their name.

    Two manifests with one name cannot both be installed, and judging the imports of one
    against the manifest of the other would hide real problems.

    Args:
        distributions: Distributions, deepest import root first.
        warnings: Collects one ``DUPLICATE_DISTRIBUTION_NAME`` per distribution that loses
            its name.

    Returns:
        The distributions in the same order, repeated names cleared on the deeper ones.
    """
    named = sorted(
        (d for d in distributions if d.info), key=lambda d: (len(d.root.parts), d.root.as_posix())
    )
    owners: dict[str, Path] = {}
    for distribution in named:
        owners.setdefault(distribution.info.name, distribution.root)
    for distribution in named:
        if owners[distribution.info.name] != distribution.root:
            warnings.append(
                ParseWarning(
                    WarningCode.DUPLICATE_DISTRIBUTION_NAME,
                    distribution.root,
                    None,
                    distribution.info.name,
                )
            )
    return tuple(
        replace(d, info=None) if d.info and owners[d.info.name] != d.root else d
        for d in distributions
    )


def name_files(
    layout: ProjectLayout, files: Sequence[Path]
) -> tuple[list[tuple[Path, ModuleName]], list[ParseWarning]]:
    """Name every file; a name taken twice stays with the deepest distribution.

    Args:
        layout: Project layout.
        files: Source files, in the order results must keep.

    Returns:
        Each file with its name, in the given order, plus one warning per renamed file.
    """
    named = [_name_with_depth(layout, _absolute(path)) for path in files]
    holders: dict[str, list[int]] = defaultdict(list)
    for index, (name, _) in enumerate(named):
        holders[name.name].append(index)
    result = [(path, name) for path, (name, _) in zip(files, named, strict=True)]
    warnings = []
    for indexes in holders.values():
        if len(indexes) < 2:
            continue
        ranked = sorted(indexes, key=lambda i: (-named[i][1], str(files[i])))
        for index in ranked[1:]:
            path = files[index]
            relative = _absolute(path).relative_to(layout.root).as_posix()
            result[index] = (path, ModuleName(relative, False))
            detail = f"{named[index][0].name} -> {relative}"
            warnings.append(ParseWarning(WarningCode.MODULE_NAME_COLLISION, path, None, detail))
    return result, warnings
