"""Unit tests for the LinkedIn connectors and utilities."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from socialgraph.config.settings import Settings
from socialgraph.connectors.linkedin import LinkedInPlaywrightConnector


@pytest.mark.asyncio
async def test_playwright_connector_fetch() -> None:
    settings = Settings(_env_file=None)
    connector = LinkedInPlaywrightConnector(settings)

    mock_raw_posts = [
        {
            "urn": "urn:li:activity:123",
            "author": "Alice",
            "subtitle": "Software Engineer",
            "date": "2d",
            "content": "Exploring pytest-mocking.",
        },
        {
            "urn": "urn:li:activity:456",
            "author": "Bob",
            "subtitle": "Product Manager",
            "date": "3d",
            "content": "Designing APIs.",
            "original_urn": "urn:li:activity:789",  # repost original
        },
    ]

    mock_client = MagicMock()
    mock_client.fetch_saved_posts = AsyncMock(return_value=mock_raw_posts)

    # Patch PlaywrightClient context manager to return our mock client
    with patch("socialgraph.browser.playwright_client.PlaywrightClient") as mock_client_cls:
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        posts = await connector.fetch_saved_posts(already_known_urns={"urn:li:activity:999"})

        # Verify raw client was called
        mock_client.fetch_saved_posts.assert_called_once_with(["urn:li:activity:999"])

        # Check post wrapping
        assert len(posts) == 2
        assert posts[0].urn == "urn:li:activity:123"
        assert posts[0].author == "Alice"
        assert posts[0].source_url == "https://www.linkedin.com/feed/update/urn:li:activity:123/"

        # Repost should map source_url to original_urn
        assert posts[1].urn == "urn:li:activity:456"
        assert posts[1].author == "Bob"
        assert posts[1].source_url == "https://www.linkedin.com/feed/update/urn:li:activity:789/"
