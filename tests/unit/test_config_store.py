"""Unit tests for ConfigStore and Fernet encryption."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from socialgraph.storage.config_store import ConfigStore
from socialgraph.storage.models import Base


@pytest.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_config_store_set_and_get(db_session: AsyncSession):
    store = ConfigStore(db_session)
    await store.set("vllm_model", "Qwen/Qwen3.5-9B-FP8")

    val = await store.get("vllm_model")
    assert val == "Qwen/Qwen3.5-9B-FP8"


@pytest.mark.asyncio
async def test_config_store_encrypted_secret(db_session: AsyncSession):
    store = ConfigStore(db_session)
    secret = "gsk_test_key_123456789"
    await store.set("groq_api_key", secret)

    # get() decrypts secret
    decrypted = await store.get("groq_api_key")
    assert decrypted == secret

    # get_all() masks secret
    all_masked = await store.get_all()
    assert all_masked.get("groq_api_key") == "***"

    # get_all_decrypted() returns unmasked secret
    all_decrypted = await store.get_all_decrypted()
    assert all_decrypted.get("groq_api_key") == secret


@pytest.mark.asyncio
async def test_config_store_delete(db_session: AsyncSession):
    store = ConfigStore(db_session)
    await store.set("web_port", "9090")
    assert await store.get("web_port") == "9090"

    await store.delete("web_port")
    assert await store.get("web_port") is None


@pytest.mark.asyncio
async def test_is_configured(db_session: AsyncSession):
    store = ConfigStore(db_session)
    assert not await store.is_configured()

    await store.set("groq_api_key", "gsk_valid_key")
    assert await store.is_configured()


def test_derive_fernet_key_headless_fallback(monkeypatch: pytest.MonkeyPatch):
    import getpass

    from socialgraph.storage.config_store import _derive_fernet_key, _get_username

    # Simulate headless CI with no tty: getpass raises OSError
    def _mock_getuser():
        raise OSError(25, "Inappropriate ioctl for device")

    monkeypatch.setattr(getpass, "getuser", _mock_getuser)
    monkeypatch.setenv("USER", "runner")

    user = _get_username()
    assert user == "runner"

    key = _derive_fernet_key()
    assert isinstance(key, bytes)
    assert len(key) == 44
