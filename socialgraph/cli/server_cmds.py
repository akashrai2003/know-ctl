"""Server CLI commands for social-graph."""

from __future__ import annotations

from typing import Any

import typer

from socialgraph.cli._runner import run_async


def mcp_serve(
    transport: str = typer.Option("stdio", "--transport", help="Transport: stdio or http"),
    port: int = typer.Option(8765, "--port", help="Port for HTTP transport"),
) -> None:
    """Start the MCP server (stdio for Claude Desktop, http for web clients)."""
    from socialgraph.mcp.server import run_sse, run_stdio

    async def _run(settings: Any, _session: Any) -> None:
        if transport == "stdio":
            typer.echo("Starting MCP server (stdio)...", err=True)
            await run_stdio(settings)
        elif transport == "http":
            typer.echo(f"Starting MCP server (HTTP/SSE) on port {port}...", err=True)
            await run_sse(settings, port=port)
        else:
            typer.echo(f"Unknown transport: {transport}. Use stdio or http.", err=True)
            raise typer.Exit(1)

    run_async(_run)


def web(
    port: int = typer.Option(8080, "--port", help="Port to run web server on"),
    host: str = typer.Option("0.0.0.0", "--host", help="Host to bind to"),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open browser on start"),
) -> None:
    """Start the web dashboard (REST API + frontend)."""
    import uvicorn

    # Since we need settings to instantiate and run the web server, we can get settings:
    from socialgraph.config.settings import Settings
    from socialgraph.logging import configure_logging
    from socialgraph.web.main import create_app

    settings = Settings()
    settings.ensure_workspace()
    configure_logging(settings)

    app_instance = create_app(settings)

    if open_browser:
        import threading
        import time
        import webbrowser

        def _open() -> None:
            time.sleep(1.5)
            webbrowser.open(f"http://localhost:{port}")

        threading.Thread(target=_open, daemon=True).start()

    typer.echo(f"🌐 Starting Social Graph dashboard on http://localhost:{port}")
    uvicorn.run(app_instance, host=host, port=port, log_level="warning")
