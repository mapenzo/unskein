from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class ImportEdge:
    source: str
    target: str
    is_external: bool
    symbol_name: str | None = None
    line_number: int | None = None


@dataclass(slots=True)
class ModuleInfo:
    name: str
    file_path: Path
    imports: list[ImportEdge] = field(default_factory=list)


@dataclass(slots=True)
class ReExport:
    exporting_module: str
    original_module: str
    symbol_name: str


@dataclass
class ParseResult:
    modules: list[ModuleInfo]
    language: str
    re_exports: list[ReExport] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
