import pathspec
from test_api_leaks import LIB, analyzed

from unskein.config import AnalysisConfig, ApiContract, FindingsConfig
from unskein.graph.findings import FindingKind
from unskein.graph.metrics import analyze
from unskein.parsers.indirection import resolve_indirection
from unskein.parsers.models import WarningCode
from unskein.parsers.python_parser import PythonAdapter


def _findings(root):
    return [f for f in analyzed(root).findings if f.kind is FindingKind.API_LEAK]


def _without_the_rule(root, config: FindingsConfig | None = None):
    adapter = PythonAdapter(AnalysisConfig())
    files = sorted(adapter.discover_files(root, pathspec.PathSpec([])))
    return analyze(resolve_indirection(adapter.parse(files, root)), config)


def test_one_finding_per_written_module_with_its_evidence(make_project) -> None:
    files = {
        **LIB,
        "app/a.py": "from lib._private import SECRET\nfrom lib.core.logger import Logger\n",
        "app/b.py": "from lib._private import SECRET\n",
    }
    internal, bypass = _findings(make_project(files))
    assert internal.modules == ("lib._private",)
    assert internal.evidence == {
        "kind": "internal",
        "reason": "convention",
        "consumers": 2,
        "roots": "app 2",
        "statements": 2,
        "fixed": 0,
        "no_fix": 2,
        "fixes": "app/a.py:1 no_fix (no_public_path); app/b.py:1 no_fix (no_public_path)",
        "fixes_total": 2,
    }
    assert bypass.modules == ("lib.core.logger",)
    assert bypass.evidence["fixes"] == "app/a.py:2 from lib import Logger"


def test_the_evidence_shows_at_most_five_fixes(make_project) -> None:
    files = {**LIB, **{f"app/m{i}.py": "from lib._private import SECRET\n" for i in range(8)}}
    (finding,) = _findings(make_project(files))
    assert finding.evidence["fixes_total"] == 8
    assert finding.evidence["fixes"].count("no_fix") == 5


def test_findings_off_computes_nothing(make_project) -> None:
    root = make_project({**LIB, "app/a.py": "from lib._private import SECRET\n"})
    adapter = PythonAdapter(AnalysisConfig())
    files = sorted(adapter.discover_files(root, pathspec.PathSpec([])))
    result = analyze(resolve_indirection(adapter.parse(files, root)), FindingsConfig(enabled=False))
    assert result.leaks == [] and result.findings == []


def test_a_declared_contract_with_the_rule_off_warns(make_project) -> None:
    root = make_project({**LIB, "app/a.py": "from lib._private import SECRET\n"})
    config = FindingsConfig(api=ApiContract(internal=("lib.internal",)))
    codes = [w.code for w in _without_the_rule(root, config).parse_warnings]
    assert WarningCode.API_CONTRACT_IGNORED in codes
    plain = [w.code for w in _without_the_rule(root).parse_warnings]
    assert WarningCode.API_CONTRACT_IGNORED not in plain


def test_with_the_rule_on_the_contract_does_not_warn(make_project) -> None:
    root = make_project({**LIB, "app/a.py": "from lib.internal.tool import tool\n"})
    result = analyzed(root, ApiContract(internal=("lib.internal",)))
    assert WarningCode.API_CONTRACT_IGNORED not in [w.code for w in result.parse_warnings]


def test_the_graph_is_the_same_with_and_without_the_rule(make_project) -> None:
    root = make_project({**LIB, "app/a.py": "from lib.core.logger import Logger\n"})
    off = _without_the_rule(root)
    on = analyzed(root)
    assert sorted(on.graph.edges) == sorted(off.graph.edges)
    assert on.cycles == off.cycles and on.tangles == off.tangles
