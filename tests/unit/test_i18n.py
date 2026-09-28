import locale

import pytest

from unskein.i18n import STRINGS, Lang, detect_lang, t


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
