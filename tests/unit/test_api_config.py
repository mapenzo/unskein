from pathlib import Path

import pytest

from unskein.config import ApiContract, load_toml_config, resolve_findings_config
from unskein.errors import ConfigError, ErrorKey


def _load(tmp_path: Path, text: str):
    (tmp_path / ".unskein.toml").write_text(text, encoding="utf-8")
    return load_toml_config(tmp_path, user_config=tmp_path / "nope.toml")


def test_the_contract_is_empty_by_default(tmp_path: Path) -> None:
    toml = load_toml_config(tmp_path, user_config=tmp_path / "nope.toml")
    assert resolve_findings_config(toml, None).api == ApiContract()


def test_the_lists_reach_the_findings_config(tmp_path: Path) -> None:
    toml = _load(tmp_path, '[api]\npublic = ["lib.api"]\ninternal = ["lib", "lib.x"]\n')
    assert resolve_findings_config(toml, None).api == ApiContract(
        public=("lib.api",), internal=("lib", "lib.x")
    )


@pytest.mark.parametrize(
    "prefixes", ['["lib/api"]', '["1lib"]', '["lib..api"]', '[""]', '["lib", "lib"]']
)
def test_invalid_prefixes_are_a_config_error_that_does_not_echo_them(
    tmp_path: Path, prefixes: str
) -> None:
    with pytest.raises(ConfigError) as raised:
        _load(tmp_path, f"[api]\ninternal = {prefixes}\n")
    assert raised.value.key == ErrorKey.INVALID_VALUE
    assert all(bad not in str(raised.value.params) for bad in ("lib/api", "1lib", "lib..api"))


def test_the_same_prefix_in_both_lists_is_a_config_error_that_does_not_echo_it(
    tmp_path: Path,
) -> None:
    with pytest.raises(ConfigError) as raised:
        _load(tmp_path, '[api]\npublic = ["secret_pkg"]\ninternal = ["secret_pkg"]\n')
    assert raised.value.key == ErrorKey.INVALID_VALUE
    assert "secret_pkg" not in str(raised.value.params)


def test_an_unknown_key_in_api_is_a_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as raised:
        _load(tmp_path, '[api]\nprivate = ["lib"]\n')
    assert raised.value.key == ErrorKey.UNKNOWN_KEY
