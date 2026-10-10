from pathlib import Path

import pathspec

from unskein.config import AnalysisConfig, OptionalRules
from unskein.graph.findings import FindingKind
from unskein.graph.metrics import analyze
from unskein.i18n import Lang
from unskein.parsers.indirection import resolve_indirection
from unskein.parsers.models import WarningCode
from unskein.parsers.python_parser import PythonAdapter
from unskein.report.markdown import AIStatus, ReportContext, render_report

FIXTURE = Path(__file__).parent.parent / "fixtures" / "star_project"


def _analyzed(star_fixes: bool):
    """Discover, parse, resolve and analyze the star fixture."""
    adapter = PythonAdapter(AnalysisConfig(optional_rules=OptionalRules(star_fixes=star_fixes)))
    files = sorted(adapter.discover_files(FIXTURE, pathspec.PathSpec([])))
    return analyze(resolve_indirection(adapter.parse(files, FIXTURE)))


def test_the_rule_is_off_by_default() -> None:
    result = _analyzed(star_fixes=False)
    assert result.wildcards == []
    assert all(f.kind is not FindingKind.WILDCARD_IMPORT for f in result.findings)


def test_the_rule_runs_when_enabled() -> None:
    result = _analyzed(star_fixes=True)
    assert result.wildcards
    assert any(f.kind is FindingKind.WILDCARD_IMPORT for f in result.findings)


def test_without_the_option_every_internal_star_is_reported_as_not_analyzed() -> None:
    warnings = _analyzed(star_fixes=False).parse_warnings
    stars = sorted(
        (w.path.name, w.detail) for w in warnings if w.code is WarningCode.STAR_NOT_ANALYZED
    )
    assert ("api.py", "app.types") in stars
    assert ("dead.py", "app.types") in stars
    assert all(name != "ext.py" for name, _ in stars)
    assert all(name != "__init__.py" for name, _ in stars)
    assert all(w.code is not WarningCode.STAR_IMPORT for w in warnings)


def test_with_the_option_the_not_analyzed_warnings_disappear() -> None:
    warnings = _analyzed(star_fixes=True).parse_warnings
    assert all(w.code is not WarningCode.STAR_NOT_ANALYZED for w in warnings)


def test_the_not_analyzed_warning_names_the_option_in_both_languages() -> None:
    result = _analyzed(star_fixes=False)
    for lang, text in ((Lang.EN, "--star-fixes"), (Lang.ES, "--star-fixes")):
        report = render_report(
            ReportContext(root=FIXTURE, result=result, ai_report=None, ai_status=AIStatus.DISABLED),
            lang,
        )
        assert text in report


def test_the_default_scan_reads_no_extra_data_for_the_rule() -> None:
    adapter = PythonAdapter(AnalysisConfig())
    files = sorted(adapter.discover_files(FIXTURE, pathspec.PathSpec([])))
    parsed = adapter.parse(files, FIXTURE)
    assert parsed.star_fixes is False
    assert all(not module.stars.reads for module in parsed.modules)
