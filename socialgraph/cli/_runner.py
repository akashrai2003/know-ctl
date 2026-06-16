"""Shared runner utilities for the social-graph CLI commands."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from socialgraph.config.settings import Settings
from socialgraph.logging import configure_logging
from socialgraph.storage.db import build_session_factory, get_session


def run_async(
    func: Callable[[Settings, Any], Awaitable[None]],
    **settings_overrides: Any,
) -> None:
    """Run an async CLI function with a database session and configured logging.

    Args:
        func: Async function accepting (settings, session).
        settings_overrides: Environment/settings overrides to apply before running.
    """
    settings = Settings()
    for key, value in settings_overrides.items():
        if value is not None:
            setattr(settings, key, value)

    settings.ensure_workspace()
    configure_logging(settings)

    async def _main() -> None:
        factory = build_session_factory(settings.db_path)
        async with get_session(factory) as session:
            await func(settings, session)

    asyncio.run(_main())


def get_taxonomy(settings: Settings) -> Any:
    """Load taxonomy from the settings path, exit with error if not found."""
    import typer

    from socialgraph.knowledge.taxonomy import Taxonomy

    if settings.taxonomy_path.exists():
        return Taxonomy.from_file(settings.taxonomy_path)
    typer.echo(
        f"Taxonomy not found at {settings.taxonomy_path}. Run `make bootstrap-taxonomy` first.",
        err=True,
    )
    raise typer.Exit(1)
