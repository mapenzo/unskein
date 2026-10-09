"""Dependencies a distribution declares in its manifest, keyed by distribution name."""

import configparser
import re
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from unskein.parsers.models import ParseWarning, WarningCode

PYPROJECT_NAME = "pyproject.toml"
SETUP_CFG_NAME = "setup.cfg"
DYNAMIC_DEPENDENCIES = "dependencies"
DYNAMIC_VERSION = "version"
INCLUDE_GROUP = "include-group"
COMMENT_PREFIX = "#"
CFG_OPTIONS = "options"
CFG_INSTALL_REQUIRES = "install_requires"
CFG_EXTRAS = "options.extras_require"
CFG_METADATA = "metadata"
CFG_VERSION = "version"
# PEP 508: a name starts the specifier; versions, extras, markers and URLs follow it.
_REQUIREMENT_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
# PEP 503 normalization.
_NAME_SEPARATORS = re.compile(r"[-_.]+")


@dataclass(frozen=True, slots=True)
class DeclaredDependencies:
    """What a distribution's manifest declares it needs.

    Attributes:
        requires: Names of its required dependencies; None when unknown (dynamic,
            ``setup.py`` only, or no readable declaration).
        optional: Names per extra (``[project.optional-dependencies]``,
            ``[options.extras_require]``) and per dependency group.
        version: Its literal version; None when dynamic or missing.
        manifest: File that declares them; None when there is none.
    """

    requires: frozenset[str] | None = None
    optional: dict[str, frozenset[str]] = field(default_factory=dict)
    version: str | None = None
    manifest: Path | None = None


@dataclass(frozen=True, slots=True)
class _Source:
    """A manifest being read and where to report its problems.

    Attributes:
        manifest: Manifest path.
        warnings: Collects problems.
    """

    manifest: Path
    warnings: list[ParseWarning]


def normalize_name(name: str) -> str:
    """Return a distribution name normalized as PEP 503 does.

    Args:
        name: Distribution name as written.

    Returns:
        Lowercase, with runs of ``-``, ``_`` and ``.`` turned into ``-``.
    """
    return _NAME_SEPARATORS.sub("-", name).lower()


def requirement_name(spec: str) -> str | None:
    """Return the normalized distribution name a PEP 508 specifier starts with.

    Args:
        spec: A dependency specifier such as ``pkg[x]>=1; python_version<'3.10'``.

    Returns:
        The normalized name, or None when the specifier does not start with one.
    """
    match = _REQUIREMENT_NAME.match(spec)
    return normalize_name(match.group(1)) if match else None


def read_dependencies(directory: Path, warnings: list[ParseWarning]) -> DeclaredDependencies:
    """Read what the manifest of a distribution declares; ``setup.py`` is never executed.

    ``pyproject.toml`` with a ``[project]`` table wins; otherwise ``setup.cfg``. Unreadable
    manifests give unknown dependencies quietly: the layout already warned about them.

    Args:
        directory: Distribution root.
        warnings: Collects one ``INVALID_REQUIREMENT`` per unusable entry.

    Returns:
        The declared dependencies.
    """
    pyproject = directory / PYPROJECT_NAME
    data = _quiet_toml(pyproject)
    project = data.get("project")
    if isinstance(project, dict):
        return _from_project(project, data, _Source(pyproject, warnings))
    return _from_setup_cfg(directory / SETUP_CFG_NAME, warnings)


def _quiet_toml(path: Path) -> dict:
    """Load a TOML file, giving an empty table when it is missing or unreadable.

    Args:
        path: TOML file.

    Returns:
        The parsed table or an empty one.
    """
    try:
        with path.open("rb") as file:
            return tomllib.load(file)
    except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError):
        return {}


def _names(specs: Iterable[object], source: _Source) -> frozenset[str]:
    """Turn dependency specifiers into names, warning about unusable ones.

    Args:
        specs: Specifiers; non-strings are skipped (they are not specifiers).
        source: The manifest the specifiers come from and its warnings.

    Returns:
        Normalized names.
    """
    names = set()
    for spec in specs:
        if not isinstance(spec, str):
            continue
        name = requirement_name(spec)
        if name is None:
            source.warnings.append(
                ParseWarning(WarningCode.INVALID_REQUIREMENT, source.manifest, None, spec)
            )
        else:
            names.add(name)
    return frozenset(names)


def _as_list(value: object) -> list:
    """Return a TOML value when it is an array, an empty list otherwise.

    Args:
        value: Value read from the manifest.

    Returns:
        The array, or an empty list for anything else.
    """
    return value if isinstance(value, list) else []


def _from_project(project: dict, data: dict, source: _Source) -> DeclaredDependencies:
    """Read ``[project]`` dependencies, extras and version, plus ``[dependency-groups]``.

    Args:
        project: The ``[project]`` table.
        data: The whole parsed ``pyproject.toml``.
        source: The manifest and its warnings.

    Returns:
        The declared dependencies.
    """
    dynamic = set(_as_list(project.get("dynamic")))
    requires = None
    if DYNAMIC_DEPENDENCIES not in dynamic:
        requires = _names(_as_list(project.get("dependencies")), source)
    optional: dict[str, frozenset[str]] = {}
    extras = project.get("optional-dependencies")
    if isinstance(extras, dict):
        for extra in sorted(extras):
            optional[extra] = _names(_as_list(extras[extra]), source)
    groups = data.get("dependency-groups")
    if isinstance(groups, dict):
        optional.update(_GroupResolver(groups, source).resolve_all())
    version = project.get("version")
    literal = version if isinstance(version, str) and DYNAMIC_VERSION not in dynamic else None
    return DeclaredDependencies(requires, optional, literal, source.manifest)


@dataclass(slots=True)
class _GroupResolver:
    """Resolve PEP 735 dependency groups, following ``include-group`` without loops.

    Attributes:
        groups: The ``[dependency-groups]`` table.
        source: The manifest and its warnings.
    """

    groups: dict
    source: _Source

    def resolve_all(self) -> dict[str, frozenset[str]]:
        """Return the names every group declares, includes resolved.

        Returns:
            Names per group, by group name.
        """
        return {name: frozenset(self.names(name, ())) for name in sorted(self.groups)}

    def names(self, group: str, visiting: tuple[str, ...]) -> set[str]:
        """Return the names one group declares, following its includes.

        Args:
            group: Group name.
            visiting: Groups being resolved above this one, to stop include loops.

        Returns:
            Normalized names; an include of a missing group or a loop is warned and skipped.
        """
        names: set[str] = set()
        for entry in _as_list(self.groups.get(group)):
            if not isinstance(entry, dict):
                names |= _names([entry], self.source)
                continue
            included = entry.get(INCLUDE_GROUP)
            path = (*visiting, group)
            if not isinstance(included, str) or included not in self.groups or included in path:
                detail = included if isinstance(included, str) else str(entry)
                self.source.warnings.append(
                    ParseWarning(
                        WarningCode.INVALID_REQUIREMENT, self.source.manifest, None, detail
                    )
                )
                continue
            names |= self.names(included, path)
        return names


def _cfg_lines(value: str) -> list[str]:
    """Split a multi-line ``setup.cfg`` value into its entries.

    Args:
        value: Raw option value.

    Returns:
        Stripped, non-empty lines that are not comments.
    """
    lines = (line.strip() for line in value.splitlines())
    return [line for line in lines if line and not line.startswith(COMMENT_PREFIX)]


def _from_setup_cfg(path: Path, warnings: list[ParseWarning]) -> DeclaredDependencies:
    """Read ``install_requires``, ``extras_require`` and the version from ``setup.cfg``.

    Args:
        path: The ``setup.cfg`` file, which may not exist.
        warnings: Collects one ``INVALID_REQUIREMENT`` per unusable entry.

    Returns:
        The declared dependencies; unknown when the file is missing, unreadable or
        declares none of them.
    """
    if not path.is_file():
        return DeclaredDependencies()
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(path, encoding="utf-8")
    except (configparser.Error, OSError, UnicodeDecodeError):
        return DeclaredDependencies()
    has_requires = parser.has_option(CFG_OPTIONS, CFG_INSTALL_REQUIRES)
    if not has_requires and not parser.has_section(CFG_EXTRAS):
        return DeclaredDependencies()
    source = _Source(path, warnings)
    requires = _names(
        _cfg_lines(parser.get(CFG_OPTIONS, CFG_INSTALL_REQUIRES, fallback="")), source
    )
    optional = {}
    if parser.has_section(CFG_EXTRAS):
        for extra in sorted(parser.options(CFG_EXTRAS)):
            optional[extra] = _names(_cfg_lines(parser.get(CFG_EXTRAS, extra)), source)
    version = parser.get(CFG_METADATA, CFG_VERSION, fallback="").strip() or None
    return DeclaredDependencies(requires, optional, version, path)
