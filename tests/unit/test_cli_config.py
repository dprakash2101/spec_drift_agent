"""Unit tests for config/env parsing in CLI."""

import os
from pathlib import Path

import pytest

from specdrift.cli import (
    _coerce_body_from_text,
    _ensure_string_dict,
    _load_config,
    _parse_key_value_pairs,
)


def test_parse_key_value_pairs_valid() -> None:
    parsed = _parse_key_value_pairs(["A=1", "B=two"], "header")
    assert parsed == {"A": "1", "B": "two"}


def test_parse_key_value_pairs_invalid() -> None:
    with pytest.raises(ValueError):
        _parse_key_value_pairs(["invalid"], "header")


def test_coerce_body_from_text_json_and_raw() -> None:
    assert _coerce_body_from_text('{"a": 1}') == {"a": 1}
    assert _coerce_body_from_text("plain-text") == "plain-text"


def test_ensure_string_dict_normalizes_types() -> None:
    result = _ensure_string_dict({"num": 1, 2: True}, "headers")
    assert result == {"num": "1", "2": "True"}


def test_load_config_resolves_env_from_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("API_TOKEN", raising=False)

    env_file = tmp_path / ".env"
    env_file.write_text("API_TOKEN=test-token\n", encoding="utf-8")

    config_file = tmp_path / "spec_drift_agent.config.json"
    config_file.write_text(
        '{"auth": {"type": "bearer", "token": "${API_TOKEN}"}}',
        encoding="utf-8",
    )

    loaded = _load_config(config_file, env_file)
    assert loaded["auth"]["token"] == "test-token"
    assert os.environ.get("API_TOKEN") == "test-token"