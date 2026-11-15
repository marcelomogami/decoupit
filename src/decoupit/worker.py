"""Single-job worker with process-group cancellation."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from pathlib import Path
from typing import Any

from decoupit.database import connect_database, initialize_database
from decoupit.job_store import (
    Job,
    claim_next_job,
    finish_job,
    get_job,
    recover_job,
    set_process_id,
)
from decoupit.jobs import JobState
from decoupit.paths import resolve_app_paths

JobHandler = Callable[[Mapping[str, Any]], Sequence[str]]


def _noop_command(_: Mapping[str, Any]) -> Sequence[str]:
    return (sys.executable, "-c", "raise SystemExit(0)")


DEFAULT_HANDLERS: dict[str, JobHandler] = {"system.noop": _noop_command}


class WorkerInterrupted(Exception):
    def __init__(self, signal_number: int) -> None:
        self.signal_number = signal_number
        super().__init__(f"worker interrompido pelo sinal {signal_number}")


def _record_failure(database_path: Path, job: Job, message: str) -> None:
    with connect_database(database_path) as connection:
        finish_job(connection, job.id, JobState.FAILED, error_message=message)


def _terminate_process_group(process: subprocess.Popen[bytes], timeout: float) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait()


def run_next_job(
    database_path: Path,
    *,
    handlers: Mapping[str, JobHandler] | None = None,
    poll_interval: float = 0.05,
    terminate_timeout: float = 2.0,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Claim and execute at most one job, returning whether one was claimed."""

    available_handlers = DEFAULT_HANDLERS if handlers is None else handlers
    with connect_database(database_path) as connection:
        job = claim_next_job(connection)
    if job is None:
        return False
    handler = available_handlers.get(job.kind)
    if handler is None:
        _record_failure(database_path, job, f"tipo de job não registrado: {job.kind}")
        return True
    try:
        command = tuple(handler(job.payload))
        if not command or not all(isinstance(part, str) and part for part in command):
            raise ValueError("comando vazio ou inválido")
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    except (OSError, ValueError) as error:
        _record_failure(database_path, job, f"falha ao iniciar subprocesso: {error}")
        return True

    with connect_database(database_path) as connection:
        set_process_id(connection, job.id, process.pid)

    try:
        while process.poll() is None:
            with connect_database(database_path) as connection:
                state = get_job(connection, job.id).state
            if state is JobState.CANCEL_REQUESTED:
                _terminate_process_group(process, terminate_timeout)
                with connect_database(database_path) as connection:
                    finish_job(connection, job.id, JobState.CANCELLED)
                return True
            sleep(poll_interval)
    except BaseException:
        try:
            _terminate_process_group(process, terminate_timeout)
        finally:
            with connect_database(database_path) as connection:
                recover_job(connection, job.id)
        raise

    with connect_database(database_path) as connection:
        state = get_job(connection, job.id).state
        if state is JobState.CANCEL_REQUESTED:
            finish_job(connection, job.id, JobState.CANCELLED)
        elif process.returncode == 0:
            finish_job(connection, job.id, JobState.SUCCEEDED)
        else:
            finish_job(
                connection,
                job.id,
                JobState.FAILED,
                error_message=f"subprocesso terminou com código {process.returncode}",
            )
    return True


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="decoupit-worker", description="Executa um job local do DecoupIt."
    )
    parser.add_argument("--once", action="store_true", help="executa no máximo um job")
    arguments = parser.parse_args(argv)
    if not arguments.once:
        parser.error("somente o modo --once está disponível")

    paths = resolve_app_paths()
    initialize_database(paths.database)

    def interrupt_worker(signal_number: int, _: object) -> None:
        raise WorkerInterrupted(signal_number)

    previous_sigterm = signal.signal(signal.SIGTERM, interrupt_worker)
    previous_sigint = signal.signal(signal.SIGINT, interrupt_worker)
    try:
        run_next_job(paths.database)
    except WorkerInterrupted as error:
        raise SystemExit(128 + error.signal_number) from error
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)
        signal.signal(signal.SIGINT, previous_sigint)


if __name__ == "__main__":
    main()
