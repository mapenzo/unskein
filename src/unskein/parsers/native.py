"""Modules with no ``.py`` source: stubs, compiled extensions and what proves they exist."""

from collections import defaultdict
from collections.abc import Collection, Iterable
from pathlib import Path

from unskein.parsers.layout import PYPROJECT_NAME, ProjectLayout, relative_path
from unskein.parsers.models import VirtualKind, VirtualModule

PYTHON_SUFFIX = ".py"
STUB_SUFFIX = ".pyi"
# Binaries and Cython sources: the module exists as compiled code.
COMPILED_SUFFIXES = (".so", ".pyd", ".pyx")
EVIDENCE_SUFFIXES = (STUB_SUFFIX, *COMPILED_SUFFIXES)
NAME_SEPARATOR = "."
PATH_SEPARATOR = "/"
LINE_SEPARATOR = ":"


def is_evidence(path: Path) -> bool:
    """Tell whether a discovered file proves a module exists without being its source.

    Args:
        path: Discovered file.

    Returns:
        True for stubs, binaries and Cython sources.
    """
    return path.suffix in EVIDENCE_SUFFIXES


def _as_source_path(path: Path) -> Path:
    """Return the ``.py`` path an evidence file stands for, to name it like a source.

    Args:
        path: Stub, binary or Cython file.

    Returns:
        The same directory and the name up to the first dot, with ``.py``:
        ``_speed.cpython-314-x86_64-linux-gnu.so`` stands for ``_speed.py`` and
        ``__init__.pyi`` for ``__init__.py``.
    """
    stem = path.name.split(NAME_SEPARATOR, 1)[0]
    return path.with_name(f"{stem}{PYTHON_SUFFIX}")


def find_native_modules(
    layout: ProjectLayout, evidence: Iterable[Path], sources: Collection[str]
) -> tuple[dict[str, VirtualModule], dict[str, str]]:
    """Name the compiled extensions and stubs of a project, with what proves each one.

    A name that is already a ``.py`` module keeps its source (the stub of a pure module is
    ignored), and one outside the project's top-level packages makes nothing internal.

    Args:
        layout: Project layout, with the maturin declarations of its distributions.
        evidence: Discovered stubs, binaries and Cython sources.
        sources: Names of the parsed ``.py`` modules.

    Returns:
        The native modules by name, sorted, and the named distribution of each one a
        named distribution ships.
    """
    top_level = {name.split(NAME_SEPARATOR)[0] for name in sources if PATH_SEPARATOR not in name}
    proofs: defaultdict[str, set[str]] = defaultdict(set)
    compiled: set[str] = set()
    packaged: dict[str, bool] = {}
    distributions: dict[str, str] = {}
    for path in evidence:
        if not path.exists():
            # A dangling symlink proves nothing.
            continue
        module = layout.name_of(_as_source_path(path))
        proofs[module.name].add(relative_path(path, layout.root))
        if path.suffix in COMPILED_SUFFIXES:
            compiled.add(module.name)
        packaged[module.name] = packaged.get(module.name, False) or module.is_packaged
        if module.distribution is not None:
            distributions[module.name] = module.distribution
    for distribution in layout.distributions:
        manifest = relative_path(distribution.root / PYPROJECT_NAME, layout.root)
        for name, line in distribution.native_declarations:
            proofs[name].add(f"{manifest}{LINE_SEPARATOR}{line}" if line else manifest)
            compiled.add(name)
            packaged[name] = True
            if distribution.info is not None:
                distributions[name] = distribution.info.name
    native = {}
    for name in sorted(proofs):
        if name in sources or PATH_SEPARATOR in name:
            continue
        if name.split(NAME_SEPARATOR)[0] not in top_level:
            continue
        kind = VirtualKind.COMPILED if name in compiled else VirtualKind.STUB
        native[name] = VirtualModule(kind, packaged[name], tuple(sorted(proofs[name])))
    return native, {name: d for name, d in distributions.items() if name in native}
