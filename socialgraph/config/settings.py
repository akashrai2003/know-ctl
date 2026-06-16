from __future__ import annotations

from pathlib import Path

from pydantic import Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application-wide configuration settings loaded from environment variables or .env file."""

    model_config = SettingsConfigDict(
        env_prefix="SG_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── vLLM (small model) ──────────────────────────────────────────────
    vllm_base_url: str = Field(default="", description="ngrok base URL for vLLM server")
    vllm_api_key: str = Field(default="sk-placeholder")
    vllm_model: str = Field(default="Qwen/Qwen3.5-9B-FP8")
    vllm_batch_url: str = Field(
        default="",
        description="Override batch endpoint. Defaults to {vllm_base_url}/v1/chat/completions/batch",
    )
    batch_size: int = Field(default=10, ge=1, le=50)
    llm_timeout: float = Field(default=580.0, gt=0)

    # ── Embeddings ───────────────────────────────────────────────────────
    embedding_model: str = Field(
        default="Qwen/Qwen3-Embedding-0.6B",
        description="Model to use for local embeddings.",
    )
    embedding_device: str = Field(
        default="cuda",
        description="Device to load local embedding model on ('cuda' or 'cpu').",
    )

    # ── Groq (large model) ──────────────────────────────────────────────
    groq_api_key: str = Field(default="")
    groq_model: str = Field(default="llama-3.3-70b-versatile")
    groq_fallback_models: list[str] = Field(
        default=["meta-llama/llama-4-scout-17b-16e-instruct", "qwen/qwen3-32b"],
        description="Tried in order when primary model hits rate limits",
    )
    groq_base_url: str = Field(default="https://api.groq.com/openai/v1")

    # ── LinkedIn browser credentials ─────────────────────────────────────
    linkedin_email: str = Field(default="")
    linkedin_password: str = Field(default="")

    # ── Paths ────────────────────────────────────────────────────────────
    db_path: Path = Field(default=Path(".socialgraph/socialgraph.db"))
    workspace_dir: Path = Field(default=Path(".socialgraph"))
    obsidian_vault_path: Path = Field(default=Path("./vault"))
    taxonomy_path: Path = Field(default=Path("topic_taxonomy.json"))

    # ── Playwright ───────────────────────────────────────────────────────
    playwright_headless: bool = Field(default=True)

    # ── Pipeline knobs ───────────────────────────────────────────────────
    max_comments: int = Field(default=5, ge=0)
    log_level: str = Field(default="INFO")

    # ── Web UI (M7) ──────────────────────────────────────────────────────
    web_port: int = Field(default=8080, ge=1, le=65535)

    # ── Scheduler (M6) ───────────────────────────────────────────────────
    schedule_interval_hours: float = Field(default=6.0, gt=0)

    @field_validator("vllm_batch_url", mode="after")
    @classmethod
    def default_batch_url(cls, v: str, info: ValidationInfo) -> str:
        if not v:
            # info.data available after other fields are set
            try:
                base = info.data["vllm_base_url"]  # type: ignore[union-attr]
                return f"{base.rstrip('/')}/v1/chat/completions/batch"
            except (AttributeError, KeyError):
                return v
        return v

    def ensure_workspace(self) -> None:
        """Create workspace directories if they do not exist."""
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        (self.workspace_dir / "logs").mkdir(exist_ok=True)
        self.obsidian_vault_path.mkdir(parents=True, exist_ok=True)
        (self.obsidian_vault_path / "posts").mkdir(exist_ok=True)
        (self.obsidian_vault_path / "topics").mkdir(exist_ok=True)
        (self.obsidian_vault_path / "authors").mkdir(exist_ok=True)
