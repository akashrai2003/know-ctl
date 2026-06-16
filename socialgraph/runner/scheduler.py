"""Scheduler daemon for social-graph.

Runs the incremental pipeline on a configurable cadence using APScheduler.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import threading
import time
from datetime import datetime, timezone

import structlog
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from socialgraph.config.settings import Settings
from socialgraph.runner.incremental import run_incremental_pipeline

UTC = timezone.utc

logger = structlog.get_logger(__name__)


class SchedulerDaemon:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._scheduler = BackgroundScheduler()
        self._status_file = settings.workspace_dir / "schedule.json"
        self._stop_event = threading.Event()

    def start(self, interval_hours: float) -> None:
        """Start the background scheduler and block until stopped."""

        # Setup signal handlers for graceful shutdown on SIGTERM
        def handle_sigterm(_signum, _frame):
            logger.info("scheduler.sigterm_received")
            self.stop()

        signal.signal(signal.SIGTERM, handle_sigterm)

        # Trigger immediate run + scheduled intervals
        trigger = IntervalTrigger(hours=interval_hours, start_date=datetime.now())
        self._scheduler.add_job(
            self.run_job,
            trigger=trigger,
            id="incremental_pipeline_job",
            replace_existing=True,
        )
        self._scheduler.start()

        # Find initial next run time
        next_run = None
        for job in self._scheduler.get_jobs():
            if job.next_run_time:
                next_run = job.next_run_time.isoformat()
                break

        # Write initial status to file
        self.write_status(
            pid=os.getpid(),
            interval_hours=interval_hours,
            next_run=next_run,
            last_result="scheduled",
        )

        try:
            # Block until stop() is called or SIGTERM/KeyboardInterrupt
            while not self._stop_event.is_set():
                time.sleep(1)
        finally:
            logger.info("scheduler.shutdown_started")
            self._scheduler.shutdown()
            self.clear_status(self._settings)
            logger.info("scheduler.shutdown_complete")

    def stop(self) -> None:
        """Signal the daemon to stop blocking."""
        self._stop_event.set()

    def run_job(self) -> None:
        """The scheduled task executed on each tick."""
        logger.info("scheduler.job_triggered")
        last_run = datetime.now(UTC).isoformat()

        # Trigger knows next run time
        next_run = None
        for job in self._scheduler.get_jobs():
            if job.next_run_time:
                next_run = job.next_run_time.isoformat()
                break

        self.write_status(
            last_run=last_run,
            next_run=next_run,
            last_result="running",
        )

        try:
            # Run the asynchronous pipeline incrementally
            res = asyncio.run(run_incremental_pipeline(self._settings))
            last_result = res.get("status", "success")
            posts_processed = res.get("posts_processed", 0)
            logger.info("scheduler.job_success", posts_processed=posts_processed)
        except Exception as e:
            logger.exception("scheduler.job_failed", error=str(e))
            last_result = "failed"
            posts_processed = 0

        self.write_status(
            last_run=last_run,
            next_run=next_run,
            last_result=last_result,
            posts_processed=posts_processed,
        )

    def write_status(self, **kwargs) -> None:
        """Write metadata to schedule.json."""
        data = {}
        if self._status_file.exists():
            try:
                with open(self._status_file, encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                pass

        data.update(kwargs)
        self._status_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self._status_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning("scheduler.write_status_failed", error=str(e))

    @staticmethod
    def read_status(settings: Settings) -> dict | None:
        """Read status from schedule.json, validating the PID is still alive."""
        status_file = settings.workspace_dir / "schedule.json"
        if not status_file.exists():
            return None
        try:
            with open(status_file, encoding="utf-8") as f:
                data = json.load(f)
            pid = data.get("pid")
            if pid:
                try:
                    os.kill(pid, 0)
                except OSError:
                    # PID not running, status file is stale
                    SchedulerDaemon.clear_status(settings)
                    return None
            return data
        except Exception:
            return None

    @staticmethod
    def clear_status(settings: Settings) -> None:
        """Remove the schedule.json file."""
        status_file = settings.workspace_dir / "schedule.json"
        if status_file.exists():
            with contextlib.suppress(Exception):
                status_file.unlink()
