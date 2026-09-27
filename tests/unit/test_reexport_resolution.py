from unskein.parsers.base import ReExport
from unskein.parsers.indirection import (
    MAX_RESOLUTION_DEPTH,
    build_reexport_index,
    resolve_target,
)


def test_follows_multilevel_chain() -> None:
    index = build_reexport_index(
        [
            ReExport("app", "app.core", "Engine"),
            ReExport("app.core", "app.core.impl.engine", "Engine"),
        ]
    )
    assert resolve_target("app", "Engine", index) == ("app.core.impl.engine", [])


def test_module_import_is_not_resolved() -> None:
    index = build_reexport_index([ReExport("app", "app.core", "Engine")])
    assert resolve_target("app", None, index) == ("app", [])


def test_cycle_degrades_with_warning() -> None:
    index = build_reexport_index(
        [ReExport("app.a", "app.b", "Thing"), ReExport("app.b", "app.a", "Thing")]
    )
    target, warnings = resolve_target("app.a", "Thing", index)
    assert target == "app.a"
    assert len(warnings) == 1


def test_depth_limit_degrades_with_warning() -> None:
    chain = [ReExport(f"m{i}", f"m{i + 1}", "X") for i in range(MAX_RESOLUTION_DEPTH + 5)]
    target, warnings = resolve_target("m0", "X", build_reexport_index(chain))
    assert target == f"m{MAX_RESOLUTION_DEPTH}"
    assert len(warnings) == 1
