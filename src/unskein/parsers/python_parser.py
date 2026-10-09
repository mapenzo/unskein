"""Parse Python source files with `ast` into modules, imports and re-exports."""

import ast
from collections import defaultdict
from collections.abc import Collection, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import pathspec

from unskein.config import AnalysisConfig
from unskein.parsers.base import LanguageAdapter
from unskein.parsers.discovery import detect_encoding, walk_files
from unskein.parsers.exports import module_exports
from unskein.parsers.layout import ModuleName, build_layout, name_files
from unskein.parsers.models import (
    STAR_EXPORT,
    FileParseResult,
    ImportEdge,
    ImportKind,
    ModuleInfo,
    ParsePlan,
    ParseTask,
    ParseWarning,
    ReExport,
    StarImports,
    StarSurface,
    VirtualKind,
    VirtualModule,
    WarningCode,
)
from unskein.parsers.native import EVIDENCE_SUFFIXES, find_native_modules, is_evidence
from unskein.parsers.usage import (
    collect_dynamic_imports,
    collect_name_usage,
    collect_read_names,
)

# Import statements only occur in statement lists; ``handlers`` holds ExceptHandler
# nodes and ``cases`` holds match_case nodes, each with its own ``body``. The order
# is the one in which a compound statement's blocks appear in the source.
STATEMENT_LIST_FIELDS = ("body", "handlers", "cases", "orelse", "finalbody")


FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)
TYPE_CHECKING_NAME = "TYPE_CHECKING"
TRY_NODES = (ast.Try, ast.TryStar)
WITH_NODES = (ast.With, ast.AsyncWith)
GUARDED_BLOCK = "body"
# Handlers that catch a failed import; a bare `except:` does too.
IMPORT_ERROR_NAMES = frozenset({"ImportError", "ModuleNotFoundError", "Exception", "BaseException"})
SUPPRESS_NAME = "suppress"
# Names of non-importable files are POSIX paths; "/" never appears in a dotted name.
PATH_SEPARATOR = "/"
NAME_SEPARATOR = "."
# Text a module must contain to load modules by name; skips the walk for every other module.
DYNAMIC_IMPORT_HINTS = ("import_module", "__import__")
# Identify the object an import binds: a module, or a name taken from a module.
MODULE_OBJECT = "module:"
FROM_OBJECT = "from:"


def is_type_checking_test(test: ast.expr) -> bool:
    """Tell whether an ``if`` condition is ``TYPE_CHECKING`` or ``<module>.TYPE_CHECKING``.

    Recognized by name only: ``from typing import TYPE_CHECKING as flag`` is not.

    Args:
        test: Condition of an ``if`` statement.

    Returns:
        True when the condition names ``TYPE_CHECKING``.
    """
    if isinstance(test, ast.Name):
        return test.id == TYPE_CHECKING_NAME
    return isinstance(test, ast.Attribute) and test.attr == TYPE_CHECKING_NAME


def block_kind(node: ast.AST, field_name: str, kind: ImportKind) -> ImportKind:
    """Return the kind of the statements held in one block of a compound statement.

    The weakest context wins: a function body inside a ``TYPE_CHECKING`` block, or a
    ``TYPE_CHECKING`` block inside a function, never runs at import time either way.

    Args:
        node: Compound statement that owns the block.
        field_name: Field of ``node`` that holds the block (``body``, ``orelse``...).
        kind: Kind of ``node`` itself.

    Returns:
        The kind of the block's statements.
    """
    if isinstance(node, FUNCTION_NODES):
        return kind.weaker(ImportKind.LAZY)
    if field_name == "body" and isinstance(node, ast.If) and is_type_checking_test(node.test):
        return kind.weaker(ImportKind.TYPE_CHECKING)
    return kind


def _exception_names(node: ast.expr | None) -> list[str]:
    """Return the names an ``except`` type or ``suppress`` argument refers to.

    Args:
        node: A name (``ImportError``), an attribute (``builtins.ImportError``) or a tuple.

    Returns:
        The last segment of every name found; empty for anything else.
    """
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        return [node.attr]
    if isinstance(node, ast.Tuple):
        return [name for element in node.elts for name in _exception_names(element)]
    return []


def catches_import_errors(handlers: list[ast.ExceptHandler]) -> bool:
    """Tell whether some handler of a ``try`` catches a failed import.

    Args:
        handlers: The ``except`` clauses.

    Returns:
        True for a bare ``except:`` or a handler naming one of ``IMPORT_ERROR_NAMES``,
        unless it ends in ``raise``: then the failed import still propagates.
    """
    for handler in handlers:
        if isinstance(handler.body[-1], ast.Raise):
            continue
        if handler.type is None or IMPORT_ERROR_NAMES.intersection(_exception_names(handler.type)):
            return True
    return False


def suppresses_import_errors(node: ast.With | ast.AsyncWith) -> bool:
    """Tell whether a ``with`` statement suppresses failed imports.

    Args:
        node: The ``with`` statement.

    Returns:
        True when one of its context managers is ``suppress(...)`` or ``x.suppress(...)``
        called with one of ``IMPORT_ERROR_NAMES``.
    """
    for item in node.items:
        call = item.context_expr
        if not isinstance(call, ast.Call) or SUPPRESS_NAME not in _exception_names(call.func):
            continue
        if any(IMPORT_ERROR_NAMES.intersection(_exception_names(arg)) for arg in call.args):
            return True
    return False


def block_guarded(node: ast.AST, field_name: str, is_guarded: bool) -> bool:
    """Return whether the statements of one block are guarded against failed imports.

    Only the body of a ``try`` that catches import errors, or of a ``with suppress(...)``
    for them, is guarded; handlers, ``else`` and ``finally`` are not. Guarding is inherited.

    Args:
        node: Compound statement that owns the block.
        field_name: Field of ``node`` that holds the block.
        is_guarded: Whether ``node`` itself is guarded.

    Returns:
        Whether the block's statements are guarded.
    """
    if is_guarded:
        return True
    if field_name != GUARDED_BLOCK:
        return False
    if isinstance(node, TRY_NODES):
        return catches_import_errors(node.handlers)
    if isinstance(node, WITH_NODES):
        return suppresses_import_errors(node)
    return False


def iter_statements(tree: ast.Module) -> Iterator[tuple[ast.AST, ImportKind, bool]]:
    """Yield every statement of a module with its context, nested ones included, in code order.

    Skips expressions on purpose: ``ast.walk`` visits millions of expression
    nodes that can never contain an import.

    Args:
        tree: Parsed module.

    Yields:
        Each statement, exception handler and match case, depth-first, with the
        ``ImportKind`` an import placed there would have and whether it would be guarded.
    """
    stack = [(node, ImportKind.MODULE, False) for node in reversed(tree.body)]
    while stack:
        node, kind, is_guarded = stack.pop()
        yield node, kind, is_guarded
        for field_name in reversed(STATEMENT_LIST_FIELDS):
            if children := getattr(node, field_name, None):
                child_kind = block_kind(node, field_name, kind)
                child_guarded = block_guarded(node, field_name, is_guarded)
                stack.extend((child, child_kind, child_guarded) for child in reversed(children))


@dataclass(frozen=True, slots=True)
class ProjectIndex:
    """Names of every module in the project, used to classify and resolve imports.

    Attributes:
        modules: Dotted names of all project modules.
        top_level: First segments of those names (the project's top-level packages).
        packages: Modules that have submodules, i.e. the package facades (their ``__init__.py``).
        unpackaged: Modules no distribution ships (named by path or by their place under the root).
        virtual: Modules with no ``.py`` file, by name: namespace packages (dotted prefixes
            of importable names that are not modules themselves), compiled extensions and
            stubs. All of them are in ``modules``; namespace packages are also in ``packages``.
    """

    modules: frozenset[str]
    top_level: frozenset[str]
    packages: frozenset[str]
    unpackaged: frozenset[str] = frozenset()
    # A dict cannot be hashed; the other fields identify the index.
    virtual: dict[str, VirtualKind] = field(default_factory=dict, hash=False)

    @classmethod
    def from_names(
        cls,
        names: set[str],
        unpackaged: frozenset[str] = frozenset(),
        native: Mapping[str, VirtualKind] | None = None,
    ) -> "ProjectIndex":
        """Build the index from the project's module names.

        Names that are paths (files no import can reach) are kept as modules but
        never become top-level packages, so they cannot make an import internal.
        Every dotted prefix of an importable name that is not a module is a namespace
        package (a directory without ``__init__.py``). Compiled extensions and stubs are
        importable names too: one in a directory with no ``.py`` makes that directory a
        namespace package, and an ``__init__.pyi`` makes its directory a regular package.

        Args:
            names: Names of all parsed project modules.
            unpackaged: Those of them no distribution ships.
            native: Compiled extensions and stubs with no ``.py`` file, by name.

        Returns:
            The index over those names.
        """
        native = native or {}
        importable = {name for name in names | native.keys() if PATH_SEPARATOR not in name}
        prefixes = {
            NAME_SEPARATOR.join(parts[:end])
            for parts in (name.split(NAME_SEPARATOR) for name in importable)
            for end in range(1, len(parts))
        }
        namespaces = prefixes - importable
        virtual = {name: VirtualKind.NAMESPACE for name in namespaces} | dict(native)
        modules = frozenset(names) | frozenset(virtual)
        top_level = frozenset(name.split(NAME_SEPARATOR)[0] for name in importable)
        packages = frozenset(prefixes & modules)
        return cls(modules, top_level, packages, unpackaged, dict(sorted(virtual.items())))

    @property
    def namespaces(self) -> frozenset[str]:
        """Return the namespace packages: packages without an ``__init__.py`` (PEP 420)."""
        return frozenset(
            name for name, kind in self.virtual.items() if kind is VirtualKind.NAMESPACE
        )

    def is_namespace(self, name: str) -> bool:
        """Return whether a name is a namespace package (a package without ``__init__.py``).

        Args:
            name: Dotted module name.

        Returns:
            True when some module lives under it but no file is it.
        """
        return self.virtual.get(name) is VirtualKind.NAMESPACE

    def is_open_namespace(self, name: str) -> bool:
        """Return whether a namespace package has no regular package above it.

        Other distributions can add portions to such a namespace (``google.cloud``), so
        a name under it that the project lacks may still be installed. A namespace under
        a regular package (``litellm.types`` under ``litellm/__init__.py``) is closed.

        Args:
            name: Dotted module name.

        Returns:
            True when the name and every ancestor of it are namespace packages.
        """
        parts = name.split(NAME_SEPARATOR)
        return all(
            self.is_namespace(NAME_SEPARATOR.join(parts[:end])) for end in range(1, len(parts) + 1)
        )

    def is_package(self, name: str) -> bool:
        """Return whether a project module has submodules.

        Args:
            name: Dotted module name.

        Returns:
            True when some other project module lives under it.
        """
        return name in self.packages

    def is_external(self, name: str) -> bool:
        """Return whether a module name lies outside the project.

        Args:
            name: Dotted module name taken from an import.

        Returns:
            True when its first segment is not one of the project's top-level packages.
        """
        return name.split(".")[0] not in self.top_level

    def closest_module(self, name: str) -> str | None:
        """Return the longest prefix of a name that is a project module.

        Args:
            name: Dotted name taken from an import.

        Returns:
            The closest existing module, or None when no prefix exists in the project.
        """
        parts = name.split(".")
        for end in range(len(parts), 0, -1):
            candidate = ".".join(parts[:end])
            if candidate in self.modules:
                return candidate
        return None


@dataclass(frozen=True, slots=True)
class Binding:
    """A name an import statement binds in the module, and what it binds it to.

    Attributes:
        name: The bound name.
        prefix: Dotted path from the bound name to the import target: ``import a.b``
            binds ``a`` with prefix ``b``; empty when the name is the target itself.
        refers_to: The object the name refers to, so that two statements binding the
            same object (``import a`` and ``import a.b``) count as one binding.
    """

    name: str
    prefix: str
    refers_to: str


class _ImportCollector:
    """Collect the imports, re-exports and warnings of one parsed module.

    Args:
        file_path: Source file being parsed (used in warnings).
        source: Dotted name of the module being parsed.
        index: Index of all project modules.

    Attributes:
        package_bindings: Bound name to the edges of the packages it reaches, each with the
            prefix that leads from the name to that package.
        bound_objects: Objects each name is bound to by an import statement.
    """

    def __init__(self, file_path: Path, source: str, index: ProjectIndex):
        self.file_path = file_path
        self.source = source
        self.index = index
        self.is_package = file_path.name == "__init__.py"
        self.edges: list[ImportEdge] = []
        self.re_exports: list[ReExport] = []
        self.wildcards: list[tuple[int, str]] = []
        self.has_external_star = False
        self.warnings: list[ParseWarning] = []
        self.package_bindings: defaultdict[str, list[tuple[int, str]]] = defaultdict(list)
        self.bound_objects: defaultdict[str, set[str]] = defaultdict(set)

    def warn(self, code: WarningCode, line: int, detail: str) -> None:
        """Record a warning located at a line of the current file.

        Args:
            code: Kind of problem.
            line: Line number the warning refers to.
            detail: Language-neutral data describing the occurrence.
        """
        self.warnings.append(ParseWarning(code, self.file_path, line, detail))

    def add(
        self,
        name: str,
        symbol: str | None,
        line: int,
        *,
        kind: ImportKind = ImportKind.MODULE,
        binding: Binding | None = None,
        is_guarded: bool = False,
    ) -> str | None:
        """Record an import edge towards a module.

        Internal names that do not exist fall back to the closest existing
        ancestor (with a warning); self-imports produce no edge.

        Args:
            name: Dotted name of the imported module.
            symbol: Imported symbol, or None for a whole-module import.
            line: Line of the import statement.
            kind: Where the statement sits.
            binding: The name the statement binds, when it binds one.
            is_guarded: Whether the statement is guarded against failed imports.

        Returns:
            The internal target module, or None if external or unresolved.
        """
        if binding is not None:
            self.bound_objects[binding.name].add(binding.refers_to)
        if self.index.is_external(name):
            self.edges.append(
                ImportEdge(self.source, name, True, symbol, line, kind, is_guarded=is_guarded)
            )
            return None
        target = self.index.closest_module(name)
        if target is None or (target != name and self.index.is_open_namespace(target)):
            # An open namespace can get portions from other distributions: what the project
            # lacks there may be installed, so it is only a warning, with no edge.
            self.warn(WarningCode.UNRESOLVED_IMPORT, line, name)
            return None
        if target != name:
            self.warn(WarningCode.UNRESOLVED_IMPORT, line, f"{name} -> {target}")
        if target != self.source:
            requested = name if target != name else None
            self.edges.append(
                ImportEdge(
                    self.source,
                    target,
                    False,
                    symbol,
                    line,
                    kind,
                    is_guarded=is_guarded,
                    requested=requested,
                )
            )
            if binding is not None and self.binds_package(
                binding, symbol, target, is_exact=target == name
            ):
                self.package_bindings[binding.name].append((len(self.edges) - 1, binding.prefix))
        return target

    def binds_package(
        self, binding: Binding | None, symbol: str | None, target: str, *, is_exact: bool
    ) -> bool:
        """Tell whether an import binds a name to a package worth analyzing.

        Args:
            binding: The name the statement binds, if any.
            symbol: Imported symbol, or None for a whole-module import.
            target: Internal module the edge points to.
            is_exact: Whether the target is the module the statement names, not a fallback ancestor.

        Returns:
            True when the bound name reaches the package ``target`` itself, directly or
            through the binding's prefix (``import a.b`` reaches ``a.b`` through ``a``).
        """
        return binding is not None and symbol is None and is_exact and self.index.is_package(target)

    def relative_base(self, node: ast.ImportFrom) -> str | None:
        """Return the absolute module a relative `from` import refers to.

        Args:
            node: Relative `from ... import` statement.

        Returns:
            The absolute dotted base, or None (with a warning) when the import
            goes beyond the top-level package.
        """
        package = self.source.split(".") if self.is_package else self.source.split(".")[:-1]
        up = node.level - 1
        if up >= len(package):
            relative = "." * node.level + (node.module or "")
            self.warn(WarningCode.RELATIVE_BEYOND_TOP, node.lineno, relative)
            return None
        parts = package[: len(package) - up]
        if node.module:
            parts += node.module.split(".")
        return ".".join(parts)

    def visit(self, tree: ast.Module) -> None:
        """Collect every import in a module, including nested ones, in code order.

        Args:
            tree: Parsed module.
        """
        for node, kind, is_guarded in iter_statements(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top, _, rest = alias.name.partition(".")
                    if alias.asname:
                        bound = Binding(alias.asname, "", f"{MODULE_OBJECT}{alias.name}")
                    else:
                        bound = Binding(top, rest, f"{MODULE_OBJECT}{top}")
                    self.add(
                        alias.name,
                        None,
                        node.lineno,
                        kind=kind,
                        binding=bound,
                        is_guarded=is_guarded,
                    )
            elif isinstance(node, ast.ImportFrom):
                base = self.relative_base(node) if node.level else node.module
                if base:
                    self.visit_from(base, node, kind=kind, is_guarded=is_guarded)

    def visit_from(
        self, base: str, node: ast.ImportFrom, *, kind: ImportKind, is_guarded: bool = False
    ) -> None:
        """Record the names of a `from base import ...` statement.

        A name that is a submodule of base becomes a module import; any other
        name is a symbol of base. Symbol imports in a package `__init__.py` are
        recorded as re-exports under their exported (alias) name. A star import in a
        package `__init__.py` of an existing project module is recorded as a star
        re-export (``STAR_EXPORT``). A star import elsewhere of a project module is
        recorded in ``wildcards``; a star import of an external module is only an edge.

        Args:
            base: Absolute dotted module the names are imported from.
            node: The `from ... import` statement.
            kind: Where the statement sits.
            is_guarded: Whether the statement is guarded against failed imports.
        """
        for alias in node.names:
            if alias.name == "*":
                is_star_reexport = (
                    self.is_package and base in self.index.modules and base != self.source
                )
                if self.index.is_external(base):
                    self.has_external_star = True
                elif not is_star_reexport:
                    self.wildcards.append((node.lineno, base))
                self.add(base, None, node.lineno, kind=kind, is_guarded=is_guarded)
                if is_star_reexport:
                    self.re_exports.append(ReExport(self.source, base, STAR_EXPORT, is_guarded))
                continue
            binding = Binding(alias.asname or alias.name, "", f"{FROM_OBJECT}{base}.{alias.name}")
            submodule = f"{base}.{alias.name}"
            # A namespace package has no code: a name taken from it can only be a submodule.
            if submodule in self.index.modules or self.index.is_namespace(base):
                self.add(
                    submodule, None, node.lineno, kind=kind, binding=binding, is_guarded=is_guarded
                )
                continue
            target = self.add(
                base, alias.name, node.lineno, kind=kind, binding=binding, is_guarded=is_guarded
            )
            if self.is_package and target is not None and target != self.source:
                exported = alias.asname or alias.name
                self.re_exports.append(ReExport(self.source, target, exported, is_guarded))

    def attach_usage(self, tree: ast.Module) -> None:
        """Record on each package import how the module uses the name it binds.

        Only names bound to a single object are analyzed (``import a`` and ``import a.b``
        bind the same ``a``); a name bound to two objects could make the attribute uses
        belong to either. Each chain goes to the import with the longest matching prefix:
        ``a.b.c.f`` read through ``a`` belongs to ``import a.b.c`` as ``f``. A chain equal
        to a prefix means that package is used by itself. The tree is walked only when the
        module imports at least one package.

        Args:
            tree: Parsed module the collector visited.
        """
        tracked = {
            name: entries
            for name, entries in self.package_bindings.items()
            if len(self.bound_objects[name]) == 1
        }
        if not tracked:
            return
        usages = collect_name_usage(tree, tracked)
        for name, entries in tracked.items():
            chains, used_alone = _split_chains(usages[name].chains, entries)
            for index, _ in entries:
                edge = self.edges[index]
                edge.accessed = tuple(sorted(chains[index]))
                edge.escapes = usages[name].escapes or index in used_alone


def _split_chains(
    chains: Collection[str], entries: list[tuple[int, str]]
) -> tuple[dict[int, set[str]], set[int]]:
    """Give each attribute chain read through a name to the import it goes through.

    Args:
        chains: Dotted attribute chains read through the name.
        entries: Edge index and prefix of each package import that binds the name.

    Returns:
        The chains of each edge, below its prefix, and the edges whose package is used by
        itself (a chain equal to its prefix). A chain that matches no prefix is dropped.
    """
    by_prefix = sorted(entries, key=lambda entry: -len(entry[1]))
    split: dict[int, set[str]] = {index: set() for index, _ in entries}
    used_alone: set[int] = set()
    for chain in chains:
        for index, prefix in by_prefix:
            if not prefix:
                split[index].add(chain)
                break
            if chain == prefix:
                used_alone.add(index)
                break
            if chain.startswith(f"{prefix}{NAME_SEPARATOR}"):
                split[index].add(chain[len(prefix) + len(NAME_SEPARATOR) :])
                break
    return split, used_alone


def parse_file(
    file_path: Path, name: str, index: ProjectIndex, config: AnalysisConfig
) -> FileParseResult:
    """Parse one Python file; problems become warnings instead of exceptions.

    Pure and picklable, so it can run as the unit of work of a process pool.
    Oversized files are skipped without being read.

    Args:
        file_path: Python source file.
        name: Dotted module name of the file.
        index: Index of all project modules.
        config: Analysis settings (size limit, fallback encoding).

    Returns:
        The parsed module, or None plus a warning when the file was skipped.
    """
    try:
        size = file_path.stat().st_size
        if size > config.max_file_size_bytes:
            detail = f"{size} > {config.max_file_size_bytes}"
            warning = ParseWarning(WarningCode.FILE_TOO_LARGE, file_path, None, detail)
            return FileParseResult(None, warnings=[warning])
        encoding = detect_encoding(file_path, config.default_encoding)
        source = file_path.read_text(encoding=encoding)
        tree = ast.parse(source, filename=str(file_path))
    except (OSError, SyntaxError, UnicodeDecodeError, RecursionError) as e:
        line = e.lineno if isinstance(e, SyntaxError) else None
        detail = f"{type(e).__name__}: {e}"
        warning = ParseWarning(WarningCode.PARSE_ERROR, file_path, line, detail)
        return FileParseResult(None, warnings=[warning])
    collector = _ImportCollector(file_path, name, index)
    collector.visit(tree)
    collector.attach_usage(tree)
    exports = module_exports(tree)
    reads: tuple[str, ...] = ()
    if collector.wildcards:
        reads = collect_read_names(tree)
        if exports.declares_all:
            reads = tuple(sorted({*reads, *exports.names}))
    dynamic = (
        collect_dynamic_imports(tree)
        if any(hint in source for hint in DYNAMIC_IMPORT_HINTS)
        else ()
    )
    stars = StarImports(tuple(collector.wildcards), reads, dynamic)
    surface = StarSurface(
        exports.has_dynamic_all,
        exports.is_uncertain or collector.has_external_star,
        exports.conditional_names,
    )
    module = ModuleInfo(
        name,
        file_path,
        collector.edges,
        exports.names,
        exports.declares_all,
        exports.bound_names,
        is_packaged=name not in index.unpackaged,
        defined_names=exports.defined_names,
        stars=stars,
        surface=surface,
    )
    return FileParseResult(module, collector.re_exports, collector.warnings)


def _namespace_owners(
    index: ProjectIndex, names: list[ModuleName], module_distributions: dict[str, str]
) -> dict[str, bool]:
    """Tell, for each namespace package, whether its modules are shipped and by whom.

    One pass over the module names: each name updates the namespaces above it. A
    namespace whose modules all belong to one named distribution is added to
    ``module_distributions``.

    Args:
        index: Project index with the namespace packages.
        names: Every file's module name.
        module_distributions: Distribution per module; namespaces are added to it.

    Returns:
        Whether a distribution ships every module under each namespace, by namespace.
    """
    shipped: dict[str, bool] = {}
    owners: defaultdict[str, set[str | None]] = defaultdict(set)
    for name in names:
        parts = name.name.split(NAME_SEPARATOR)
        for end in range(1, len(parts)):
            prefix = NAME_SEPARATOR.join(parts[:end])
            if index.is_namespace(prefix):
                shipped[prefix] = shipped.get(prefix, True) and name.is_packaged
                owners[prefix].add(name.distribution)
    for namespace, found in owners.items():
        if len(found) == 1 and None not in found:
            module_distributions[namespace] = next(iter(found))
    return dict(sorted(shipped.items()))


class PythonAdapter(LanguageAdapter):
    """Language adapter for Python, built on the standard library `ast` module.

    Args:
        config: Analysis settings; defaults are used when omitted.
    """

    def __init__(self, config: AnalysisConfig | None = None):
        self.config = config or AnalysisConfig()

    @property
    def language_name(self) -> str:
        """Name of the language this adapter handles: "python"."""
        return "python"

    @property
    def file_extensions(self) -> list[str]:
        """File extensions of Python source files."""
        return [".py"]

    def discover_files(
        self,
        root: Path,
        exclude_spec: pathspec.PathSpec,
        follow_symlinks: bool = False,
        *,
        evidence_spec: pathspec.PathSpec | None = None,
    ) -> Iterator[Path]:
        """Yield the Python files under root that are not excluded, plus stubs and binaries.

        Args:
            root: Project directory to walk.
            exclude_spec: Combined exclude patterns; matching paths are skipped.
            follow_symlinks: Whether to descend into symlinked directories.
            evidence_spec: Patterns for stubs and binaries instead of ``exclude_spec``
                (see ``load_evidence_spec``); None uses ``exclude_spec``.

        Returns:
            An iterator over the Python files to analyze and the files that prove a module
            exists without a ``.py`` (stubs, binaries, Cython sources).
        """
        extensions = (*self.file_extensions, *EVIDENCE_SUFFIXES)
        file_specs = dict.fromkeys(EVIDENCE_SUFFIXES, evidence_spec) if evidence_spec else None
        return walk_files(root, extensions, exclude_spec, follow_symlinks, file_specs=file_specs)

    def normalize_module_name(self, file_path: Path, root: Path) -> str:
        """Return the module name of a file, from the distribution that ships it.

        The layout is built from that single file, so in a workspace with name collisions
        the result may differ from the names ``plan_parse`` gives.

        Args:
            file_path: Python source file.
            root: Project directory the file belongs to.

        Returns:
            The dotted module name, e.g. "pkg.core" for "src/pkg/core.py", or the
            file's path when no import can reach it.
        """
        layout, _ = build_layout(root, [file_path], self.config.source_roots)
        return layout.name_of(file_path).name

    def plan_parse(self, files: list[Path], root: Path) -> ParsePlan:
        """Name every file first, so imports can be classified against the whole project.

        Args:
            files: Python source files to parse, and evidence files (stubs, binaries,
                Cython sources) that are only named.
            root: Project directory the files belong to.

        Returns:
            One task per file, in the given order, sharing the project index, plus the
            layout warnings, the entry points its distributions declare, the named
            distributions with the distribution of each module, and the project root.
        """
        sources = [path for path in files if not is_evidence(path)]
        layout, warnings = build_layout(root, sources, self.config.source_roots)
        named, collisions = name_files(layout, sources)
        tasks = [(path, name.name) for path, name in named]
        names = {name for _, name in tasks}
        native, native_distributions = find_native_modules(
            layout, [path for path in files if is_evidence(path)], names
        )
        unpackaged = frozenset(name.name for _, name in named if not name.is_packaged)
        index = ProjectIndex.from_names(
            names, unpackaged, {name: module.kind for name, module in native.items()}
        )
        module_distributions = {
            name.name: name.distribution for _, name in named if name.distribution is not None
        }
        module_distributions.update(native_distributions)
        native_names = [
            ModuleName(name, module.is_packaged, native_distributions.get(name))
            for name, module in native.items()
        ]
        namespaces = _namespace_owners(
            index, [*(name for _, name in named), *native_names], module_distributions
        )
        virtual = {
            name: VirtualModule(VirtualKind.NAMESPACE, shipped)
            for name, shipped in namespaces.items()
        } | native
        return ParsePlan(
            tasks,
            index,
            [*warnings, *collisions],
            layout.script_modules,
            layout.distribution_infos,
            module_distributions,
            layout.root,
            virtual=dict(sorted(virtual.items())),
        )

    def parse_task(self, task: ParseTask, shared: ProjectIndex) -> FileParseResult:
        """Parse one Python file against the project index.

        Args:
            task: File and module name, from `plan_parse`.
            shared: The project index built by `plan_parse`.

        Returns:
            The parsed module, or None plus a warning when the file was skipped.
        """
        path, name = task
        return parse_file(path, name, shared, self.config)
