"""Facts about the original project that the proof computes only when a cut needs them."""

import ast

from unskein.graph.definers import DefinerIndex, build_definer_index
from unskein.graph.smells import Smell, base_knows_subclass, config_snapshot
from unskein.graph.untangle import Cut
from unskein.parsers.discovery import parse_source
from unskein.parsers.models import ParseResult
from unskein.parsers.rewrite import import_time_attributes
from unskein.parsers.usage import UseContext
from unskein.scan import ScanContext, parse_sources, resolve_parsed

PACKAGE_INIT = "__init__.py"


class ProjectFacts:
    """Lazily parsed view of the original project for the proof.

    Reading the whole project again costs seconds on a large one, so each fact is built
    the first time a cut asks for it and kept.

    Args:
        context: A prepared scan of the original project.
    """

    def __init__(self, context: ScanContext) -> None:
        self.context = context
        self._sources: ParseResult | None = None
        self._parsed: ParseResult | None = None
        self._definers: DefinerIndex | None = None
        self._trees: dict[str, ast.Module | None] = {}

    def sources(self) -> ParseResult:
        """Return the project parsed, with imports as written.

        Returns:
            The parse result, computed on the first call.
        """
        if self._sources is None:
            self._sources = parse_sources(self.context)
        return self._sources

    def parsed(self) -> ParseResult:
        """Return the project parsed, with re-exports resolved.

        Returns:
            The parse result, computed on the first call.
        """
        if self._parsed is None:
            self._parsed = resolve_parsed(self.sources(), self.context)
        return self._parsed

    def definers(self) -> DefinerIndex:
        """Return the index that finds the definer of a facade name.

        Returns:
            The index, built on the first call.
        """
        if self._definers is None:
            self._definers = build_definer_index(
                self.parsed(), self.context.analysis.default_encoding
            )
        return self._definers

    def tree(self, module: str) -> ast.Module | None:
        """Return the syntax tree of a project module.

        Args:
            module: Dotted module name.

        Returns:
            The tree, or None when the module is unknown or cannot be read.
        """
        if module not in self._trees:
            info = next((m for m in self.sources().modules if m.name == module), None)
            encoding = self.context.analysis.default_encoding
            self._trees[module] = parse_source(info.file_path, encoding) if info else None
        return self._trees[module]

    def _is_package(self, module: str) -> bool:
        """Tell whether a project module is a package ``__init__``.

        Args:
            module: Dotted module name.

        Returns:
            True when its file is ``__init__.py``.
        """
        return any(
            info.name == module and info.file_path.name == PACKAGE_INIT
            for info in self.sources().modules
        )

    def definers_read(self, cut: Cut, tree: ast.Module) -> tuple[tuple[str, str], ...]:
        """Find the definer of every attribute a module reads at import time through a package.

        Args:
            cut: A bypass cut; its target is the package.
            tree: Syntax tree of the importing module.

        Returns:
            ``(attribute, defining module)`` pairs, sorted; attributes without a stable
            definer are left out, which makes the rewriter refuse the cut.
        """
        attributes = import_time_attributes(tree, frozenset(cut.evidence.bound_names))
        if not attributes:
            return ()
        index = self.definers()
        found = ((name, index.definer(cut.target, name)) for name in attributes)
        return tuple(sorted((name, module) for name, module in found if module is not None))

    def smell(self, cut: Cut) -> Smell | None:
        """Name the design smell behind a cut that is not rewritten.

        Args:
            cut: A cut of the plan.

        Returns:
            The smell, or None when the cut shows none of the known ones.
        """
        source = self.tree(cut.source)
        target = self.tree(cut.target)
        if source is None or target is None:
            return None
        evidence = cut.evidence
        found = base_knows_subclass(source, target, evidence.symbols)
        if found is not None:
            return found
        if not self._is_package(cut.target):
            return None
        read = set(import_time_attributes(source, frozenset(evidence.bound_names)))
        if UseContext.MODULE in evidence.contexts:
            read |= set(evidence.symbols)
        return config_snapshot(target, read)
