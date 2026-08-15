"""Persistent app configuration store backed by SQLite.

Stores key/value configuration (API keys, credentials, pipeline settings)
in the existing SQLite database, encrypted at rest with a machine-local
Fernet key derived from hostname + username.

Usage:
    store = ConfigStore(session)
    await store.set("groq_api_key", "gsk_...")
    key = await store.get("groq_api_key")
"""

from __future__ import annotations

import base64
import hashlib
import os
import socket
from datetime import datetime, timezone
from typing import Any

from cryptography.fernet import Fernet
from sqlalchemy import Column, DateTime, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession

from socialgraph.storage.models import Base

# ---------------------------------------------------------------------------
# SQLAlchemy model
# ---------------------------------------------------------------------------


class AppConfig(Base):
    """Key/value config table for app settings stored in the DB."""

    __tablename__ = "app_config"

    key: str = Column(String(120), primary_key=True, nullable=False)
    value: str = Column(Text, nullable=True)  # Fernet-encrypted if sensitive
    is_secret: bool = Column(  # type: ignore[assignment]
        String(1), nullable=False, default="0"
    )
    updated_at: datetime = Column(  # type: ignore[assignment]
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Encryption helpers
# ---------------------------------------------------------------------------

# Keys that should be stored encrypted
SECRET_KEYS = {
    "groq_api_key",
    "linkedin_password",
    "linkedin_cookie",
    "vllm_api_key",
}


def _derive_fernet_key() -> bytes:
    """Derive a stable Fernet key from machine identity.

    Not vault-grade security, but appropriate for a local self-hosted tool.
    The key is deterministic per machine so data survives process restarts.
    """
    identity = f"{socket.gethostname()}:{os.getlogin() if hasattr(os, 'getlogin') else 'user'}"
    # Use an env override if the user wants a fixed key
    identity = os.environ.get("SG_ENCRYPTION_SEED", identity)
    digest = hashlib.sha256(identity.encode()).digest()
    return base64.urlsafe_b64encode(digest)


_FERNET: Fernet | None = None


def _get_fernet() -> Fernet:
    global _FERNET
    if _FERNET is None:
        _FERNET = Fernet(_derive_fernet_key())
    return _FERNET


def _encrypt(value: str) -> str:
    return _get_fernet().encrypt(value.encode()).decode()


def _decrypt(value: str) -> str:
    try:
        return _get_fernet().decrypt(value.encode()).decode()
    except Exception:
        # If decryption fails (e.g. key changed), return as-is
        return value


# ---------------------------------------------------------------------------
# ConfigStore
# ---------------------------------------------------------------------------


class ConfigStore:
    """Async CRUD wrapper around the app_config table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, key: str, default: str | None = None) -> str | None:
        """Return the (decrypted if secret) value for *key*, or *default*."""
        row = await self._session.scalar(select(AppConfig).where(AppConfig.key == key))
        if row is None:
            return default
        raw = row.value or ""
        if key in SECRET_KEYS and raw:
            return _decrypt(raw)
        return raw

    async def set(self, key: str, value: str) -> None:
        """Persist (encrypting if secret) *value* under *key*."""
        is_secret = key in SECRET_KEYS
        stored = _encrypt(value) if is_secret else value

        row = await self._session.scalar(select(AppConfig).where(AppConfig.key == key))
        if row is None:
            row = AppConfig(
                key=key,
                value=stored,
                is_secret="1" if is_secret else "0",
                updated_at=datetime.now(timezone.utc),
            )
            self._session.add(row)
        else:
            row.value = stored
            row.is_secret = "1" if is_secret else "0"
            row.updated_at = datetime.now(timezone.utc)

        await self._session.flush()

    async def delete(self, key: str) -> None:
        """Remove a config key if it exists."""
        row = await self._session.scalar(select(AppConfig).where(AppConfig.key == key))
        if row:
            await self._session.delete(row)
            await self._session.flush()

    async def get_all(self) -> dict[str, Any]:
        """Return all config as a dict (secrets are masked)."""
        rows = await self._session.scalars(select(AppConfig))
        result: dict[str, Any] = {}
        for row in rows:
            if row.key in SECRET_KEYS:
                raw = row.value or ""
                # Return masked version: show only that a value is set
                result[row.key] = "***" if raw else ""
            else:
                result[row.key] = row.value or ""
        return result

    async def get_all_decrypted(self) -> dict[str, str]:
        """Return all config with secrets decrypted (for Settings→Settings merge)."""
        rows = await self._session.scalars(select(AppConfig))
        result: dict[str, str] = {}
        for row in rows:
            raw = row.value or ""
            if row.key in SECRET_KEYS and raw:
                result[row.key] = _decrypt(raw)
            else:
                result[row.key] = raw
        return result

    async def is_configured(self) -> bool:
        """Return True if at minimum a Groq API key has been saved."""
        key = await self.get("groq_api_key")
        return bool(key and key.strip())


# ---------------------------------------------------------------------------
# Settings key catalogue (canonical names used in the web UI)
# ---------------------------------------------------------------------------

SETTINGS_KEYS = [
    # Groq
    "groq_api_key",
    "groq_model",
    # vLLM / local model
    "vllm_base_url",
    "vllm_model",
    "vllm_api_key",
    # Embeddings
    "embedding_model",
    "embedding_device",
    # LinkedIn
    "linkedin_email",
    "linkedin_password",
    "linkedin_cookie",
    # Pipeline
    "batch_size",
    "llm_timeout",
    "max_comments",
    "schedule_interval_hours",
    # Paths
    "db_path",
    "workspace_dir",
    "obsidian_vault_path",
    # Web
    "web_port",
    "log_level",
]
