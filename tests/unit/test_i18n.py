import locale
import string

import pytest

from unskein.ai.models import AIFailure
from unskein.errors import ConfigError, ErrorKey, UnskeinError
from unskein.graph.findings import FindingKind
from unskein.i18n import STRINGS, Lang, detect_lang, t, translate_error, translate_warning
from unskein.parsers.models import ParseWarning, WarningCode


def test_every_key_has_both_languages() -> None:
    for key, translations in STRINGS.items():
        assert set(translations) == set(Lang), key


def test_t_formats_placeholders() -> None:
    assert t("no_files_found", Lang.EN, path="src") == "No .py files found in 'src'"


@pytest.mark.parametrize(
    ("cli_lang", "env_lang", "toml_lang", "expected"),
    [
        ("en", "es", "es", Lang.EN),
        (None, "es", "en", Lang.ES),
        (None, None, "es", Lang.ES),
        ("fr", "es", None, Lang.ES),
    ],
)
def test_flag_wins_then_env_then_toml(
    cli_lang: str | None, env_lang: str | None, toml_lang: str | None, expected: Lang
) -> None:
    env = {"UNSKEIN_LANG": env_lang} if env_lang else {}
    assert detect_lang(cli_lang=cli_lang, toml_lang=toml_lang, env=env) is expected


def test_defaults_to_english_for_non_spanish_locale(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UNSKEIN_LANG", raising=False)
    monkeypatch.setattr(locale, "getlocale", lambda: ("fr_FR", "UTF-8"))
    assert detect_lang() is Lang.EN


def test_spanish_locale_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UNSKEIN_LANG", raising=False)
    monkeypatch.setattr(locale, "getlocale", lambda: ("es_CO", "UTF-8"))
    assert detect_lang() is Lang.ES


def placeholders(template: str) -> set[str]:
    """Return the ``{field}`` names used in a message template.

    Args:
        template: Message with ``str.format`` placeholders.

    Returns:
        The placeholder names.
    """
    return {field for _, field, _, _ in string.Formatter().parse(template) if field}


def test_translations_use_the_same_placeholders() -> None:
    for key, translations in STRINGS.items():
        assert placeholders(translations[Lang.ES]) == placeholders(translations[Lang.EN]), key


def test_every_error_key_is_translated() -> None:
    for key in ErrorKey:
        assert key in STRINGS, key


def test_every_warning_code_has_message_and_title() -> None:
    for code in WarningCode:
        assert f"warning.{code}" in STRINGS, code
        assert f"warning_title.{code}" in STRINGS, code


def test_config_error_is_a_structured_unskein_error() -> None:
    error = ConfigError(ErrorKey.UNKNOWN_KEY, {"file": "a.toml", "field": "x"})
    assert isinstance(error, UnskeinError)
    assert error.key is ErrorKey.UNKNOWN_KEY


def test_translate_error_fills_params() -> None:
    error = UnskeinError(ErrorKey.PATH_NOT_FOUND, {"path": "nope"})
    assert "nope" in translate_error(error, Lang.ES)
    assert translate_error(error, Lang.ES) != translate_error(error, Lang.EN)


def test_translate_warning_uses_detail() -> None:
    warning = ParseWarning(WarningCode.STAR_IMPORT, None, 3, "app.b")
    assert "app.b" in translate_warning(warning, Lang.EN)


def test_every_ai_failure_has_a_message_in_both_languages() -> None:
    for failure in AIFailure:
        for lang in Lang:
            assert t(f"report.ai.failed.{failure}", lang, error_type="X")


def test_every_finding_kind_has_title_explanation_and_recommendation() -> None:
    for kind in FindingKind:
        for part in ("title", "explanation", "recommendation"):
            assert f"finding.{kind}.{part}" in STRINGS, (kind, part)
