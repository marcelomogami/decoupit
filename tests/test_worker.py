import os
import sys
import threading
import time
from pathlib import Path

import pytest

from decoupit.database import connect_database, initialize_database
from decoupit.job_store import enqueue_job, get_job, request_cancellation
from decoupit.jobs import JobState
from decoupit.worker import (
    _normalization_command,
    _transcription_command,
    _waveform_command,
    run_next_job,
)


def test_normalization_command_has_explicit_resource_limits(tmp_path: Path) -> None:
    database_path = tmp_path / "decoupit.sqlite3"
    command = tuple(_normalization_command(database_path)({"source_id": "source-1"}))

    assert command[:4] == ("systemd-run", "--user", "--scope", "--quiet")
    assert "MemoryMax=2G" in command
    assert "MemorySwapMax=1G" in command
    assert "RuntimeMaxSec=2h" in command
    assert command[-4:] == (
        "--database",
        str(database_path),
        "--source-id",
        "source-1",
    )


def test_waveform_command_has_explicit_resource_limits(tmp_path: Path) -> None:
    database_path = tmp_path / "decoupit.sqlite3"
    cache_root = tmp_path / "cache"
    command = tuple(
        _waveform_command(database_path, cache_root)({"source_id": "source-1"})
    )

    assert command[:4] == ("systemd-run", "--user", "--scope", "--quiet")
    assert "MemoryMax=512M" in command
    assert "MemorySwapMax=256M" in command
    assert "RuntimeMaxSec=30m" in command
    assert command[-6:] == (
        "--database",
        str(database_path),
        "--cache-root",
        str(cache_root),
        "--source-id",
        "source-1",
    )


def test_transcription_command_has_explicit_resource_limits(tmp_path: Path) -> None:
    database_path = tmp_path / "decoupit.sqlite3"
    command = tuple(_transcription_command(database_path)({"source_id": "source-1"}))

    assert command[:4] == ("systemd-run", "--user", "--scope", "--quiet")
    assert "MemoryMax=8G" in command
    assert "MemorySwapMax=2G" in command
    assert "CPUQuota=400%" in command
    assert "RuntimeMaxSec=2h" in command
    assert not any(part.startswith("LD_LIBRARY_PATH=") for part in command)
    assert command[-4:] == (
        "--database",
        str(database_path),
        "--source-id",
        "source-1",
    )


def test_worker_completes_registered_job_in_subprocess(tmp_path: Path) -> None:
    database_path = tmp_path / "decoupit.sqlite3"
    initialize_database(database_path)
    with connect_database(database_path) as connection:
        job_id = enqueue_job(connection, kind="system.noop")

    assert run_next_job(database_path) is True

    with connect_database(database_path) as connection:
        job = get_job(connection, job_id)
    assert job.state is JobState.SUCCEEDED
    assert job.process_id is None


def test_worker_fails_unknown_job_without_spawning(tmp_path: Path) -> None:
    database_path = tmp_path / "decoupit.sqlite3"
    initialize_database(database_path)
    with connect_database(database_path) as connection:
        job_id = enqueue_job(connection, kind="unknown")

    assert run_next_job(database_path) is True

    with connect_database(database_path) as connection:
        job = get_job(connection, job_id)
    assert job.state is JobState.FAILED
    assert job.process_id is None
    assert job.error_message == "tipo de job não registrado: unknown"


def test_worker_records_failed_subprocess_output(tmp_path: Path) -> None:
    database_path = tmp_path / "decoupit.sqlite3"
    initialize_database(database_path)
    with connect_database(database_path) as connection:
        job_id = enqueue_job(connection, kind="test.failure")

    handlers = {
        "test.failure": lambda _: [
            sys.executable,
            "-c",
            "import sys;sys.stderr.write('diagnóstico útil');raise SystemExit(7)",
        ]
    }

    assert run_next_job(database_path, handlers=handlers) is True

    with connect_database(database_path) as connection:
        job = get_job(connection, job_id)
    assert job.state is JobState.FAILED
    assert job.error_message is not None
    assert "código 7" in job.error_message
    assert "diagnóstico útil" in job.error_message
    assert (tmp_path / "jobs" / f"{job_id}.log").is_file()


def test_worker_cancels_complete_process_group(tmp_path: Path) -> None:
    database_path = tmp_path / "decoupit.sqlite3"
    child_pid_file = tmp_path / "child.pid"
    initialize_database(database_path)
    with connect_database(database_path) as connection:
        job_id = enqueue_job(connection, kind="test.tree")

    child_program = (
        "import subprocess,sys,time;"
        "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);"
        f"open({str(child_pid_file)!r},'w').write(str(p.pid));"
        "time.sleep(30)"
    )
    handlers = {"test.tree": lambda _: [sys.executable, "-c", child_program]}
    worker = threading.Thread(
        target=run_next_job,
        args=(database_path,),
        kwargs={"handlers": handlers, "poll_interval": 0.01},
    )
    worker.start()

    deadline = time.monotonic() + 5
    while not child_pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert child_pid_file.exists()
    child_pid = int(child_pid_file.read_text())

    with connect_database(database_path) as connection:
        assert request_cancellation(connection, job_id) is JobState.CANCEL_REQUESTED

    worker.join(timeout=5)
    assert not worker.is_alive()
    with connect_database(database_path) as connection:
        job = get_job(connection, job_id)
    assert job.state is JobState.CANCELLED
    assert job.process_id is None

    deadline = time.monotonic() + 2
    while _process_exists(child_pid) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not _process_exists(child_pid)


def test_interrupted_worker_stops_process_and_requeues_job(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "decoupit.sqlite3"
    initialize_database(database_path)
    with connect_database(database_path) as connection:
        job_id = enqueue_job(connection, kind="test.sleep")

    handlers = {
        "test.sleep": lambda _: [sys.executable, "-c", "import time;time.sleep(30)"]
    }

    def interrupt(_: float) -> None:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_next_job(
            database_path,
            handlers=handlers,
            terminate_timeout=0.1,
            sleep=interrupt,
        )

    with connect_database(database_path) as connection:
        job = get_job(connection, job_id)
    assert job.state is JobState.QUEUED
    assert job.process_id is None


def _process_exists(process_id: int) -> bool:
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return False
    return True
