import pytest

from unskein.parsers.rewrite import Move, MoveKind, RewriteRefusal, rewrite_source

RUNS_AT_IMPORT = (
    "import pkg\n\n\nclass Filter:\n    def run(self):\n        return pkg.setting\n\n\n"
    "FILTER = Filter()\n"
)
CLASS_RUNNING_AT_IMPORT = (
    "\n\nclass Filter:\n    def run(self):\n        return setting, pkg, os\n\n\n"
    "FILTER = Filter()\n"
)


def lazy(source: str, *, already_loaded: bool) -> tuple[str, RewriteRefusal | None]:
    result = rewrite_source(source, [Move(MoveKind.LAZY, (1,), already_loaded=already_loaded)])
    return result.source, result.refusals[0]


def test_a_reader_that_may_run_at_import_refuses_without_the_flag() -> None:
    assert lazy(RUNS_AT_IMPORT, already_loaded=False) == (
        RUNS_AT_IMPORT,
        RewriteRefusal.READ_AT_IMPORT,
    )


def test_an_ancestor_package_import_moves_even_when_a_reader_may_run_at_import() -> None:
    new, refusal = lazy(RUNS_AT_IMPORT, already_loaded=True)
    assert refusal is None
    assert "    def run(self):\n        import pkg\n        return pkg.setting" in new


@pytest.mark.parametrize(
    "statement",
    ["from pkg import setting\n", "import pkg.sub\n", "import pkg, os\n"],
    ids=["from_import", "dotted_import", "two_aliases"],
)
def test_the_flag_only_applies_to_a_plain_whole_module_import(statement: str) -> None:
    source = statement + CLASS_RUNNING_AT_IMPORT
    assert lazy(source, already_loaded=True)[1] is not None
