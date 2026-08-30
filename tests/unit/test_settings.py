"""Unit tests for Settings class."""

from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

from socialgraph.config.settings import Settings


def test_settings_defaults() -> None:
    settings = Settings(_env_file=None)
    assert settings.vllm_model == "Qwen/Qwen3.5-9B-FP8"
    assert settings.groq_model == "llama-3.3-70b-versatile"
    assert settings.db_path == Path(".socialgraph/socialgraph.db")
    assert settings.playwright_headless is True


def test_settings_env_prefix() -> None:
    with mock.patch.dict(
        os.environ, {"SG_VLLM_MODEL": "CustomModel", "SG_PLAYWRIGHT_HEADLESS": "False"}
    ):
        settings = Settings(_env_file=None)
        assert settings.vllm_model == "CustomModel"
        assert settings.playwright_headless is False


def test_vllm_batch_url_validator() -> None:
    # default base URL is empty, so batch URL will just be /v1/chat/completions/batch
    settings = Settings(vllm_base_url="https://api.example.com", _env_file=None)
    assert settings.vllm_batch_url == "https://api.example.com/v1/chat/completions/batch"

    # explicit override
    settings_override = Settings(
        vllm_base_url="https://api.example.com",
        vllm_batch_url="https://custom.com/batch",
        _env_file=None,
    )
    assert settings_override.vllm_batch_url == "https://custom.com/batch"


def test_ensure_workspace(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "work"
    vault_dir = tmp_path / "vault"

    settings = Settings(
        workspace_dir=workspace_dir,
        obsidian_vault_path=vault_dir,
        _env_file=None,
    )

    # verify directories do not exist initially
    assert not workspace_dir.exists()
    assert not vault_dir.exists()

    settings.ensure_workspace()

    # verify directories were created
    assert workspace_dir.exists()
    assert (workspace_dir / "logs").exists()
    assert vault_dir.exists()
