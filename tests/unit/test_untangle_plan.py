from collections.abc import Callable
from pathlib import Path

import pytest

from unskein.errors import UnskeinError
from unskein.graph.steps import StepKind
from unskein.graph.untangle import UntanglePlan
from unskein.i18n import Lang, t
from unskein.report.untangle import render_untangle
from unskein.scan import parse_project
from unskein.untangle import (
    UntangleOptions,
    build_untangle_plan,
    facade_own_names,
    prepare_untangle,
)

MakeProject = Callable[[dict[str, str]], Path]

CYCLE = {
    "app/__init__.py": "",
    "app/a.py": "from app.b import helper\n\nVALUE = helper()\n",
    "app/b.py": (
        "from app.a import VALUE\n\n\ndef helper():\n    return 1\n\n\n"
        "def show():\n    return VALUE\n"
    ),
}
TYPE_ONLY = {
    "app/__init__.py": "",
    "app/a.py": "from app.b import B, C, D\n\nx = (B(), C(), D())\n",
    "app/b.py": (
        "from typing import TYPE_CHECKING\n\nif TYPE_CHECKING:\n    from app.a import x\n\n"
        "class B: ...\nclass C: ...\nclass D: ...\n"
    ),
}


def plan_for(root: Path, *, all_edges: bool = False) -> UntanglePlan:
    """Prepare and build the untangle plan of a project.

    Args:
        root: Project directory.
        all_edges: Whether hidden coupling is included.

    Returns:
        The plan.
    """
    context = prepare_untangle(UntangleOptions(path=root, all_edges=all_edges), env={})
    return build_untangle_plan(context, all_edges=all_edges)


def test_plan_cuts_the_lazy_side_of_a_cycle(make_project: MakeProject) -> None:
    plan = plan_for(make_project(CYCLE))
    [tangle] = plan.tangles
    [cut] = tangle.cuts
    assert (cut.source, cut.target, cut.step) == ("app.b", "app.a", StepKind.LAZY)
    assert cut.evidence.lines == (1,) and cut.evidence.symbols == ("VALUE",)
    assert (plan.simulation.tangles_before, plan.simulation.tangles_after) == (1, 0)


def test_type_only_cycle_is_hidden_unless_all_edges(make_project: MakeProject) -> None:
    root = make_project(TYPE_ONLY)
    import_time = plan_for(root)
    assert import_time.tangles == () and import_time.hidden_tangles == 1
    everything = plan_for(root, all_edges=True)
    [tangle] = everything.tangles
    assert [(c.source, c.target, c.step) for c in tangle.cuts] == [
        ("app.b", "app.a", StepKind.MOVE_SYMBOL)
    ]


def test_report_lists_cuts_with_step_and_evidence(make_project: MakeProject) -> None:
    root = make_project(CYCLE)
    report = render_untangle(plan_for(root), root, Lang.EN, max_tangles=5)
    assert report.startswith(f"# Untangle plan for {root.resolve().name}")
    assert "`app.b` → `app.a`" in report
    assert "Lazy import" in report
    assert "`app/b.py:1`" in report and "`VALUE`" in report
    assert "tangles 1 → 0, cycles 1 → 0" in report
    assert "## What each step means" in report


def test_report_in_spanish(make_project: MakeProject) -> None:
    root = make_project(CYCLE)
    report = render_untangle(plan_for(root), root, Lang.ES, max_tangles=5)
    assert report.startswith(f"# Plan de desenredo de {root.resolve().name}")
    assert "Import perezoso" in report and "## Qué significa cada paso" in report


def test_report_without_tangles_points_to_all_edges(make_project: MakeProject) -> None:
    root = make_project(TYPE_ONLY)
    report = render_untangle(plan_for(root), root, Lang.EN, max_tangles=5)
    assert "No import-time tangles: nothing to untangle." in report
    assert "`unskein untangle --all-edges`" in report


def test_report_limits_tangles_and_cuts(make_project: MakeProject) -> None:
    files = {"app/__init__.py": ""}
    for group in range(3):
        files[f"app/g{group}a.py"] = f"from app.g{group}b import B\nx = B\n"
        files[f"app/g{group}b.py"] = f"from app.g{group}a import x\nB = x\n"
    root = make_project(files)
    report = render_untangle(plan_for(root), root, Lang.EN, max_tangles=2)
    assert report.count("## Tangle ") == 2
    assert "Showing 2 of 3 tangles" in report


def test_parse_project_failure_is_a_usage_error(tmp_path: Path) -> None:
    context = prepare_untangle(UntangleOptions(path=tmp_path / "missing"), env={})
    with pytest.raises(UnskeinError):
        build_untangle_plan(context, all_edges=False)


def test_report_truncates_cuts_beyond_the_limit(
    make_project: MakeProject, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = {"app/__init__.py": ""}
    for name, other in (("a", "b"), ("b", "c"), ("c", "a")):
        files[f"app/{name}.py"] = f"from app.{other} import x\nx = 1\n"
    root = make_project(files)
    plan = plan_for(root)
    assert sum(len(tangle.cuts) for tangle in plan.tangles) >= 1
    monkeypatch.setattr("unskein.report.untangle.MAX_CUTS_SHOWN", 0)
    report = render_untangle(plan, root, Lang.EN, max_tangles=5)
    assert "Cuts not shown: 1." in report


@pytest.mark.parametrize(
    ("header", "expected"),
    [("", StepKind.MOVE_SYMBOL), ("from __future__ import annotations\n", StepKind.LAZY)],
    ids=["signature_evaluated_at_import", "signature_postponed"],
)
def test_lazy_needs_postponed_annotations_when_a_signature_reads_the_name(
    make_project: MakeProject, header: str, expected: StepKind
) -> None:
    root = make_project(
        {
            "app/__init__.py": "",
            "app/x.py": (
                f"{header}from app.y import Engine\n\n\n"
                "def run(e: Engine):\n    return Engine()\n\n\nA = B = C = 1\n"
            ),
            "app/y.py": (
                "from app.x import A, B, C\n\n\nclass Engine:\n    pass\n\n\nWIDE = [A, B, C]\n"
            ),
        }
    )
    [tangle] = plan_for(root).tangles
    [cut] = tangle.cuts
    assert (cut.source, cut.target, cut.step) == ("app.x", "app.y", expected)


def test_a_name_defined_in_the_facade_is_not_bypassed(make_project: MakeProject) -> None:
    root = make_project(
        {
            "pkg/__init__.py": "CONST = 1\nfrom pkg.a import helper\n",
            "pkg/a.py": "from pkg import CONST\n\nLIMIT = CONST * 2\n\n\ndef helper():\n"
            "    return LIMIT\n",
        }
    )
    [tangle] = plan_for(root).tangles
    [cut] = tangle.cuts
    assert (cut.source, cut.target, cut.step) == ("pkg.a", "pkg", StepKind.MOVE_SYMBOL)


def test_facade_own_names_leave_out_re_exports_and_submodules(make_project: MakeProject) -> None:
    root = make_project(
        {
            "pkg/__init__.py": "from pkg import sub\nfrom pkg.a import helper\nCONST = 1\n",
            "pkg/a.py": "def helper():\n    return 1\n",
            "pkg/sub.py": "",
        }
    )
    parsed = parse_project(prepare_untangle(UntangleOptions(path=root), env={}))
    assert facade_own_names(parsed) == {"pkg": frozenset({"CONST"})}


FUNCTION_READ_CYCLE = {
    "q/__init__.py": "",
    "q/a.py": "from q.b import B\n\n\ndef use():\n    return B()\n\n\n"
    "def more(): ...\n\n\ndef extra(): ...\n",
    "q/b.py": "from q.a import use, more, extra\n\n\nclass B: ...\n\n\nX = [use, more, extra]\n",
}


@pytest.mark.parametrize(
    ("all_edges", "expected"),
    [(False, StepKind.LAZY), (True, StepKind.MOVE_SYMBOL)],
    ids=["import_time", "all_edges"],
)
def test_all_edges_offers_only_structural_steps(
    make_project: MakeProject, all_edges: bool, expected: StepKind
) -> None:
    [tangle] = plan_for(make_project(FUNCTION_READ_CYCLE), all_edges=all_edges).tangles
    [cut] = tangle.cuts
    assert (cut.source, cut.target, cut.step) == ("q.a", "q.b", expected)


RE_IMPORTED = {
    "reexp/__init__.py": "",
    "reexp/a.py": "from reexp.b import Thing\n\n\ndef make():\n    return Thing()\n\n\n"
    "def more(): ...\n\n\ndef extra(): ...\n",
    "reexp/b.py": "from reexp.a import make, more, extra\n\n\nclass Thing: ...\n\n\n"
    "X = [make, more, extra]\n",
}


@pytest.mark.parametrize(
    ("consumer", "expected"),
    [
        ("from reexp.b import Thing\n", StepKind.LAZY),
        ("from reexp.a import Thing\n", StepKind.MOVE_SYMBOL),
    ],
    ids=["imported_from_its_definer", "imported_through_the_cut_module"],
)
def test_no_lazy_step_for_a_name_other_modules_import_from_the_source(
    make_project: MakeProject, consumer: str, expected: StepKind
) -> None:
    root = make_project({**RE_IMPORTED, "reexp/c.py": consumer})
    [tangle] = plan_for(root).tangles
    [cut] = tangle.cuts
    assert (cut.source, cut.target, cut.step) == ("reexp.a", "reexp.b", expected)


@pytest.mark.parametrize(
    ("files", "expected"),
    [
        (
            {"reexp/c.py": "from reexp import a\n\n\ndef f():\n    return a.Thing\n"},
            StepKind.MOVE_SYMBOL,
        ),
        ({"reexp/c.py": "import reexp.a\n\nY = reexp.a.Thing\n"}, StepKind.MOVE_SYMBOL),
        ({"reexp/c.py": "import reexp.a as m\n\nY = m.Thing\n"}, StepKind.MOVE_SYMBOL),
        ({"reexp/c.py": "from reexp.a import *\n"}, StepKind.MOVE_SYMBOL),
        ({"reexp/c.py": "from reexp import a\n\nY = getattr(a, 'Thing')\n"}, StepKind.MOVE_SYMBOL),
        (
            {
                "reexp/__init__.py": "from reexp.a import Thing\n",
                "reexp/c.py": "import reexp as r\n\nY = r.Thing\n",
            },
            StepKind.MOVE_SYMBOL,
        ),
        ({"reexp/c.py": "from reexp import a\n\nY = a.make\n"}, StepKind.LAZY),
        (
            {"reexp/c.py": "import reexp.a\n\nY = reexp.a.make\nZ = getattr(reexp, 'b')\n"},
            StepKind.LAZY,
        ),
        (
            {
                "reexp/__init__.py": "from reexp.b import Thing\n",
                "reexp/c.py": "import reexp as r\n\nY = r.Thing\n",
            },
            StepKind.LAZY,
        ),
        (
            {"reexp/c.py": "import reexp.a\n\nY = getattr(reexp.a, 'Thing')\n"},
            StepKind.MOVE_SYMBOL,
        ),
        (
            {
                "reexp/__init__.py": "from reexp import a\n",
                "reexp/c.py": "import reexp\n\nY = getattr(reexp.a, 'Thing')\n",
            },
            StepKind.MOVE_SYMBOL,
        ),
        ({"reexp/c.py": "from . import a\n\nY = a.Thing\n"}, StepKind.MOVE_SYMBOL),
        (
            {"reexp/c.py": "import os; from reexp import a\n\nY = a.Thing, os.sep\n"},
            StepKind.MOVE_SYMBOL,
        ),
        (
            {"reexp/c.py": "from reexp import b as m\nfrom reexp import a as m\n\nY = m.Thing\n"},
            StepKind.MOVE_SYMBOL,
        ),
        ({"reexp/c.py": "import reexp.a.nope\n\nY = reexp.a.Thing\n"}, StepKind.MOVE_SYMBOL),
        (
            {"reexp/c.py": "def f():\n    from reexp import a\n\n    return a.Thing\n"},
            StepKind.MOVE_SYMBOL,
        ),
        (
            {
                "reexp/c.py": "from typing import TYPE_CHECKING\n\n"
                "if TYPE_CHECKING:\n    from reexp.a import Thing\n"
            },
            StepKind.LAZY,
        ),
    ],
    ids=[
        "attribute_of_a_from_import",
        "attribute_of_a_dotted_import",
        "attribute_of_an_aliased_import",
        "star_import",
        "module_used_by_itself",
        "attribute_of_a_package_re_export",
        "other_attribute_only",
        "package_name_used_by_itself",
        "same_name_read_from_the_package",
        "module_reached_through_a_dotted_import_used_by_itself",
        "module_reached_through_the_package_used_by_itself",
        "relative_from_import",
        "two_statements_on_one_line",
        "rebound_alias",
        "fallback_ancestor_target",
        "reader_inside_a_function",
        "type_only_import",
    ],
)
def test_no_lazy_step_for_a_name_other_modules_read_through_the_source(
    make_project: MakeProject, files: dict[str, str], expected: StepKind
) -> None:
    [tangle] = plan_for(make_project({**RE_IMPORTED, **files})).tangles
    [cut] = tangle.cuts
    assert (cut.source, cut.target, cut.step) == ("reexp.a", "reexp.b", expected)


BROKEN_FILE_CYCLE = {
    "r/__init__.py": "",
    "r/a.py": "from r.b import x\n\ny = 1\n",
    "r/b.py": "from r.a import y\n\nx = 2\n",
    "r/c.py": "def broken(:\n",
    "r/d.py": "from r.a import y\n",
}


@pytest.mark.parametrize(
    ("lang", "expected"),
    [
        (Lang.EN, "Analysis warnings: 1 (details with `unskein scan`)."),
        (Lang.ES, "Advertencias del análisis: 1 (detalle con `unskein scan`)."),
    ],
)
def test_report_counts_parse_warnings(make_project: MakeProject, lang: Lang, expected: str) -> None:
    root = make_project(BROKEN_FILE_CYCLE)
    plan = plan_for(root)
    assert plan.warnings == 1
    assert expected in render_untangle(plan, root, lang, max_tangles=5)


def test_report_without_tangles_still_counts_parse_warnings(make_project: MakeProject) -> None:
    root = make_project({"r/__init__.py": "", "r/a.py": "x = 1\n", "r/c.py": "def broken(:\n"})
    report = render_untangle(plan_for(root), root, Lang.EN, max_tangles=5)
    assert "No import-time tangles" in report
    assert "Analysis warnings: 1 (details with `unskein scan`)." in report


def test_report_without_warnings_has_no_warning_line(make_project: MakeProject) -> None:
    root = make_project(CYCLE)
    assert "Analysis warnings" not in render_untangle(plan_for(root), root, Lang.EN, max_tangles=5)


@pytest.mark.parametrize("lang", list(Lang))
def test_type_checking_help_warns_about_runtime_annotation_readers(lang: Lang) -> None:
    help_text = t("untangle.step.type_checking.help", lang)
    for reader in ("pydantic", "FastAPI", "typing.get_type_hints", "functools.singledispatch"):
        assert reader in help_text


@pytest.mark.parametrize("lang", list(Lang))
def test_lazy_help_mentions_postponed_annotations(lang: Lang) -> None:
    assert "from __future__ import annotations" in t("untangle.step.lazy.help", lang)


@pytest.mark.parametrize("lang", list(Lang))
def test_lazy_help_warns_about_runtime_annotation_readers(lang: Lang) -> None:
    help_text = t("untangle.step.lazy.help", lang)
    for reader in ("pydantic", "FastAPI", "typing.get_type_hints"):
        assert reader in help_text


TEST_FILE_CYCLE = {
    "app/__init__.py": "",
    "app/a.py": "from app.test_b import helper\n\nVALUE = helper()\n",
    "app/test_b.py": CYCLE["app/b.py"],
}


@pytest.mark.parametrize(
    ("files", "toml", "tangles"),
    [
        (CYCLE, "", 1),
        (CYCLE, '[analysis]\nexclude = ["app/b.py"]\n', 0),
        (TEST_FILE_CYCLE, "", 0),
        (TEST_FILE_CYCLE, "[analysis]\ninclude_tests = true\n", 1),
    ],
    ids=["no_config", "excluded_by_toml", "tests_left_out", "tests_included_by_toml"],
)
def test_untangle_honors_the_project_config(
    make_project: MakeProject, files: dict[str, str], toml: str, tangles: int
) -> None:
    root = make_project({**files, ".unskein.toml": toml})
    assert len(plan_for(root).tangles) == tangles
