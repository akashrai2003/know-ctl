"""Unit tests for the SchedulerDaemon and incremental pipeline state."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from socialgraph.config.settings import Settings
from socialgraph.runner.scheduler import SchedulerDaemon


@pytest.fixture
def temp_settings(tmp_path):
    # Use workspace dir under temp folder
    ws = tmp_path / ".socialgraph"
    ws.mkdir()
    return Settings(workspace_dir=ws, db_path=ws / "socialgraph.db")


def test_write_and_read_status(temp_settings):
    daemon = SchedulerDaemon(temp_settings)
    daemon.write_status(
        pid=999999,  # Non-existent PID or we will mock it
        interval_hours=2.5,
        last_result="success",
    )

    status_file = temp_settings.workspace_dir / "schedule.json"
    assert status_file.exists()

    # If the PID is not running, read_status will clear it and return None
    # Let's verify that read_status checks for alive PID
    status = SchedulerDaemon.read_status(temp_settings)
    assert status is None
    assert not status_file.exists()

    # Now write with our actual alive PID
    my_pid = os.getpid()
    daemon.write_status(
        pid=my_pid,
        interval_hours=2.5,
        last_result="scheduled",
    )
    status = SchedulerDaemon.read_status(temp_settings)
    assert status is not None
    assert status["pid"] == my_pid
    assert status["interval_hours"] == 2.5
    assert status["last_result"] == "scheduled"


def test_clear_status(temp_settings):
    daemon = SchedulerDaemon(temp_settings)
    daemon.write_status(pid=os.getpid(), last_result="scheduled")
    status_file = temp_settings.workspace_dir / "schedule.json"
    assert status_file.exists()

    SchedulerDaemon.clear_status(temp_settings)
    assert not status_file.exists()


@patch("socialgraph.runner.scheduler.BackgroundScheduler")
def test_scheduler_daemon_start_stop(mock_scheduler_cls, temp_settings):
    mock_sched = MagicMock()
    mock_scheduler_cls.return_value = mock_sched

    daemon = SchedulerDaemon(temp_settings)

    # We mock stop event so start exits immediately
    daemon._stop_event.set()

    with (
        patch("socialgraph.runner.scheduler.time.sleep"),
        patch.object(SchedulerDaemon, "clear_status"),
    ):
        daemon.start(interval_hours=1.0)

    # Assert scheduler was started and signals were hooked/added
    assert mock_sched.start.called
    assert mock_sched.add_job.called
    # Assert schedule.json was created
    status = SchedulerDaemon.read_status(temp_settings)
    assert status is not None
    assert status["interval_hours"] == 1.0

    # Stop should stop scheduler
    daemon.stop()
    assert daemon._stop_event.is_set()
