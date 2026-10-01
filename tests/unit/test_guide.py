from typing import Any

import pytest
import typer

from unskein import __version__
from unskein.cli import app
from unskein.graph.findings import FindingKind
from unskein.guide import usage_guide
from unskein.i18n import Lang, t

EXIT_CODES = ("`0`", "`1`", "`2`", "`3`")


def unskein_commands() -> dict[str, Any]:
    """Return unskein's runnable commands by their full name, subcommands of groups included.

    Typer vendors its own click, so the objects are inspected by attribute,
    never checked against ``click`` types.

    Returns:
        The click command of every command, keyed by what follows ``unskein``,
        such as ``scan`` or ``config save``.
    """
    found: dict[str, Any] = {}
    pending = list(typer.main.get_command(app).commands.items())
    while pending:
        name, command = pending.pop()
        subcommands = getattr(command, "commands", None)
        if subcommands:
            pending.extend((f"{name} {sub}", child) for sub, child in subcommands.items())
        else:
            found[name] = command
    return found


def documented_options() -> set[str]:
    """Return every long option of every unskein command, both forms of on/off flags.

    Returns:
        Option names such as ``--no-ai`` and ``--no-include-tests``, without ``--help``.
    """
    names: set[str] = set()
    for command in unskein_commands().values():
        for param in command.params:
            if param.param_type_name == "option":
                names.update(param.opts + param.secondary_opts)
    return {name for name in names if name.startswith("--") and name != "--help"}


@pytest.mark.parametrize("lang", list(Lang))
def test_guide_names_the_installed_version(lang: Lang) -> None:
    assert usage_guide(lang).startswith(f"# unskein {__version__} — ")


@pytest.mark.parametrize("lang", list(Lang))
def test_guide_documents_every_command_option(lang: Lang) -> None:
    guide = usage_guide(lang)

    missing = sorted(name for name in documented_options() if f"`{name}" not in guide)

    assert not missing, f"{lang} guide lacks {missing}"


@pytest.mark.parametrize("lang", list(Lang))
def test_guide_documents_every_command(lang: Lang) -> None:
    guide = usage_guide(lang)

    assert all(f"unskein {name}" in guide for name in unskein_commands())


@pytest.mark.parametrize("lang", list(Lang))
def test_guide_lists_every_exit_code(lang: Lang) -> None:
    guide = usage_guide(lang)

    assert all(f"| {code} |" in guide for code in EXIT_CODES)


def test_both_guides_have_the_same_sections() -> None:
    sections = {lang: usage_guide(lang).count("\n## ") for lang in Lang}

    assert sections[Lang.ES] == sections[Lang.EN] > 0


@pytest.mark.parametrize("lang", list(Lang))
def test_guide_explains_every_finding_kind(lang: Lang) -> None:
    titles = [t(f"finding.{kind}.title", lang) for kind in FindingKind]

    assert all(title in usage_guide(lang) for title in titles)


@pytest.mark.parametrize("lang", list(Lang))
def test_guide_explains_packages_and_impact(lang: Lang) -> None:
    guide = usage_guide(lang)

    assert f"**{t('report.packages', lang)}**" in guide
    assert f"**{t('report.impact', lang)}**" in guide


@pytest.mark.parametrize("lang", list(Lang))
def test_guide_explains_how_to_declare_layers(lang: Lang) -> None:
    guide = usage_guide(lang)

    assert "[layers]" in guide
    assert "order = [" in guide
