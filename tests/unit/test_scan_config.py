"""Unit tests for new scan/config features."""

import json
import os
from pathlib import Path

import pytest

from specdrift.cli import (
    _ensure_string_dict,
    _load_config,
    _resolve_env_placeholders,
)


class TestBaseUrlConfig:
    """Tests for base_url config injection."""

    def test_base_url_injects_env_variable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """base_url in config is available as ${BASE_URL} in other values."""
        monkeypatch.delenv("BASE_URL", raising=False)

        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps({
                "base_url": "http://example.com",
                "headers": {"X-Upstream": "${BASE_URL}/api"},
            }),
            encoding="utf-8",
        )

        loaded = _load_config(config_file, None)
        assert loaded["headers"]["X-Upstream"] == "http://example.com/api"
        # Cleanup
        monkeypatch.delenv("BASE_URL", raising=False)

    def test_base_url_does_not_override_existing_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Existing BASE_URL env var is not overridden by config."""
        monkeypatch.setenv("BASE_URL", "http://already-set.com")

        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps({
                "base_url": "http://from-config.com",
                "headers": {"X-Upstream": "${BASE_URL}/api"},
            }),
            encoding="utf-8",
        )

        loaded = _load_config(config_file, None)
        assert loaded["headers"]["X-Upstream"] == "http://already-set.com/api"


class TestMultiEndpointConfig:
    """Tests for multi-endpoint config JSON parsing."""

    def test_endpoints_array_parsed(self, tmp_path: Path) -> None:
        """Config with endpoints array is loaded correctly."""
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps({
                "spec": "openapi.yaml",
                "endpoint": "http://localhost:8000",
                "endpoints": [
                    {"path": "/users/1", "method": "GET", "status": 200},
                    {"path": "/health", "method": "GET"},
                    {"path": "/items/1", "method": "GET", "query_params": {"currency": "USD"}},
                ],
            }),
            encoding="utf-8",
        )

        loaded = _load_config(config_file, None)
        eps = loaded["endpoints"]
        assert isinstance(eps, list)
        assert len(eps) == 3
        assert eps[0]["path"] == "/users/1"
        assert eps[0]["method"] == "GET"
        assert eps[1]["path"] == "/health"
        assert eps[2]["query_params"] == {"currency": "USD"}

    def test_endpoint_per_endpoint_overrides(self, tmp_path: Path) -> None:
        """Per-endpoint headers override global headers."""
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps({
                "spec": "openapi.yaml",
                "endpoint": "http://localhost:8000",
                "headers": {"Accept": "application/json", "X-Global": "true"},
                "endpoints": [
                    {
                        "path": "/users/1",
                        "method": "GET",
                        "headers": {"X-Custom": "per-endpoint"},
                    },
                ],
            }),
            encoding="utf-8",
        )

        loaded = _load_config(config_file, None)
        ep = loaded["endpoints"][0]

        # Merge logic is done in scan command, but config should be parsed correctly
        global_headers = _ensure_string_dict(loaded.get("headers"), "headers")
        ep_headers = _ensure_string_dict(ep.get("headers"), "headers")
        merged = {**global_headers, **ep_headers}

        assert merged["Accept"] == "application/json"
        assert merged["X-Global"] == "true"
        assert merged["X-Custom"] == "per-endpoint"


class TestModelConfig:
    """Tests for model configuration."""

    def test_model_in_config(self, tmp_path: Path) -> None:
        """Model field in config is loaded correctly."""
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps({
                "spec": "openapi.yaml",
                "endpoint": "http://localhost:8000",
                "model": "gemini-2.5-pro",
            }),
            encoding="utf-8",
        )

        loaded = _load_config(config_file, None)
        assert loaded["model"] == "gemini-2.5-pro"


class TestResolveEnvPlaceholders:
    """Tests for environment variable resolution in body/headers/query."""

    def test_resolve_in_nested_body(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """${VAR} placeholders resolve in deeply nested body structures."""
        monkeypatch.setenv("API_HOST", "https://api.example.com")

        body = {
            "callback_url": "${API_HOST}/webhook",
            "nested": {
                "url": "${API_HOST}/nested",
            },
            "list": ["${API_HOST}/a", "${API_HOST}/b"],
        }

        resolved = _resolve_env_placeholders(body)
        assert resolved["callback_url"] == "https://api.example.com/webhook"
        assert resolved["nested"]["url"] == "https://api.example.com/nested"
        assert resolved["list"] == [
            "https://api.example.com/a",
            "https://api.example.com/b",
        ]


class TestAvailableModels:
    """Tests for the AVAILABLE_MODELS list."""

    def test_models_list_not_empty(self) -> None:
        from specdrift.cli import AVAILABLE_MODELS

        assert len(AVAILABLE_MODELS) > 0

    def test_default_model_is_first(self) -> None:
        from specdrift.cli import AVAILABLE_MODELS

        assert AVAILABLE_MODELS[0] == "gemini-2.5-flash"

    def test_deprecated_models_removed(self) -> None:
        from specdrift.cli import AVAILABLE_MODELS

        assert "gemini-2.0-flash" not in AVAILABLE_MODELS


class TestResolveAuthFromConfig:
    """Tests for the _resolve_auth_from_config helper."""

    def test_empty_config_returns_defaults(self) -> None:
        from specdrift.cli import _resolve_auth_from_config

        result = _resolve_auth_from_config({})
        assert result["auth_type"] is None
        assert result["auth_token"] is None
        assert result["api_key_name"] == "X-API-Key"

    def test_cli_overrides_config(self) -> None:
        from specdrift.cli import _resolve_auth_from_config

        config = {"auth": {"token": "config-token"}}
        result = _resolve_auth_from_config(config, auth_token="cli-token")
        assert result["auth_token"] == "cli-token"

    def test_config_auth_used_when_no_cli(self) -> None:
        from specdrift.cli import _resolve_auth_from_config

        config = {"auth": {"token": "config-token", "type": "bearer"}}
        result = _resolve_auth_from_config(config)
        assert result["auth_token"] == "config-token"


class TestCliCommands:
    """Tests for CLI command registration."""

    def test_scan_command_registered(self) -> None:
        from specdrift.cli import app
        import typer.main

        click_app = typer.main.get_command(app)
        commands = list(click_app.commands.keys())
        assert "scan" in commands

    def test_analyze_command_registered(self) -> None:
        from specdrift.cli import app
        import typer.main

        click_app = typer.main.get_command(app)
        commands = list(click_app.commands.keys())
        assert "analyze" in commands

    def test_version_command_registered(self) -> None:
        from specdrift.cli import app
        import typer.main

        click_app = typer.main.get_command(app)
        commands = list(click_app.commands.keys())
        assert "version" in commands
