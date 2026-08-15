"""Unit tests for Web UI settings and pipeline API endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from socialgraph.config.settings import Settings
from socialgraph.storage.models import Base
from socialgraph.web.deps import get_db, get_settings, init_globals
from socialgraph.web.main import create_app


@pytest.fixture
async def app_client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    settings = Settings()
    init_globals(settings)

    app = create_app(settings)

    async def _override_get_db():
        async with session_factory() as session:
            yield session
            await session.commit()

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_settings] = lambda: settings

    with TestClient(app) as client:
        yield client

    await engine.dispose()


def test_is_configured_endpoint(app_client: TestClient):
    resp = app_client.get("/api/settings/is-configured")
    assert resp.status_code == 200
    data = resp.json()
    assert "configured" in data
    assert data["configured"] is False


def test_get_and_put_settings(app_client: TestClient):
    # GET initial settings
    resp = app_client.get("/api/settings")
    assert resp.status_code == 200
    initial = resp.json()
    assert "groq_api_key" in initial

    # PUT update
    update_payload = {
        "groq_api_key": "gsk_test_key_abc",
        "groq_model": "llama-3.3-70b-versatile",
    }
    put_resp = app_client.put("/api/settings", json=update_payload)
    assert put_resp.status_code == 200
    assert put_resp.json()["ok"] is True

    # Check is-configured now returns True
    config_resp = app_client.get("/api/settings/is-configured")
    assert config_resp.json()["configured"] is True

    # GET settings should mask secret
    get_resp = app_client.get("/api/settings")
    assert get_resp.json()["groq_api_key"] == "***"
    assert get_resp.json()["groq_model"] == "llama-3.3-70b-versatile"


def test_pipeline_status_endpoint(app_client: TestClient):
    resp = app_client.get("/api/pipeline/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["state"] in ("idle", "running", "completed", "failed")
