"""load_config tests — the function cli.py's both-provider fail-fast relies on."""

import pytest

from streetscape_metadata_tracker.config import load_config


def test_load_config_gsv_requires_only_its_own_key(monkeypatch):
    monkeypatch.setenv("GMAPS_API_KEY", "test-key")
    monkeypatch.delenv("MAPILLARY_ACCESS_TOKEN", raising=False)
    assert load_config("gsv") == {"api_key": "test-key"}


def test_load_config_mapillary_requires_only_its_own_token(monkeypatch):
    monkeypatch.setenv("MAPILLARY_ACCESS_TOKEN", "MLY|test|token")
    monkeypatch.delenv("GMAPS_API_KEY", raising=False)
    assert load_config("mapillary") == {"access_token": "MLY|test|token"}


@pytest.mark.parametrize(
    "provider,env_var",
    [("gsv", "GMAPS_API_KEY"), ("mapillary", "MAPILLARY_ACCESS_TOKEN")],
)
def test_load_config_missing_credential_raises_with_var_name(monkeypatch, provider, env_var):
    monkeypatch.delenv(env_var, raising=False)
    with pytest.raises(ValueError, match=env_var):
        load_config(provider)


@pytest.mark.parametrize("provider,env_var", [("gsv", "GMAPS_API_KEY")])
def test_load_config_empty_credential_raises(monkeypatch, provider, env_var):
    monkeypatch.setenv(env_var, "")
    with pytest.raises(ValueError, match=env_var):
        load_config(provider)


def test_load_config_unknown_provider_raises():
    with pytest.raises(ValueError, match="[Uu]nknown provider"):
        load_config("kartaview")
