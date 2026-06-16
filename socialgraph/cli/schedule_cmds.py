"""Schedule CLI commands for social-graph."""

from __future__ import annotations

import os
import signal

import typer

from socialgraph.config.settings import Settings
from socialgraph.logging import configure_logging
from socialgraph.runner.scheduler import SchedulerDaemon


def schedule_start(
    interval_hours: float = typer.Option(
        None,
        "--interval-hours",
        help="Run interval in hours (default: SG_SCHEDULE_INTERVAL_HOURS or 6)",
    ),
) -> None:
    """Start the background scheduler daemon."""
    settings = Settings()
    settings.ensure_workspace()
    configure_logging(settings)
    hours = interval_hours or settings.schedule_interval_hours

    daemon = SchedulerDaemon(settings)
    typer.echo(f"⏱️  Starting scheduler — pipeline runs every {hours:.1f} hours")
    typer.echo("Press Ctrl+C to stop")
    try:
        daemon.start(hours)
    except KeyboardInterrupt:
        daemon.stop()
        typer.echo("\n🛑 Scheduler stopped")


def schedule_stop() -> None:
    """Stop the background scheduler (by removing PID from schedule.json)."""
    settings = Settings()
    settings.ensure_workspace()
    configure_logging(settings)
    status = SchedulerDaemon.read_status(settings)
    if not status or not status.get("pid"):
        typer.echo("No scheduler is currently running.")
        raise typer.Exit(0)

    pid = status["pid"]
    try:
        os.kill(pid, signal.SIGTERM)
        typer.echo(f"🛑 Sent SIGTERM to scheduler (PID {pid})")
    except ProcessLookupError:
        typer.echo(f"Scheduler (PID {pid}) is not running — cleaning up status")
    SchedulerDaemon.clear_status(settings)


def schedule_status() -> None:
    """Show current scheduler status."""
    settings = Settings()
    settings.ensure_workspace()
    configure_logging(settings)
    status = SchedulerDaemon.read_status(settings)
    if not status:
        typer.echo("📋 Scheduler: not running (no schedule.json)")
        return

    typer.echo("📋 Scheduler Status:")
    typer.echo(f"   PID:          {status.get('pid', '—')}")
    typer.echo(f"   Interval:     {status.get('interval_hours', '—')}h")
    typer.echo(f"   Last run:     {status.get('last_run', '—')}")
    typer.echo(f"   Next run:     {status.get('next_run', '—')}")
    typer.echo(f"   Last result:  {status.get('last_result', '—')}")
    typer.echo(f"   Posts added:  {status.get('posts_processed', '—')}")
