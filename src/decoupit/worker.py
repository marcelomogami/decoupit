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


def _normalization_command(
    database_path: Path,
) -> JobHandler:
    def command(payload: Mapping[str, Any]) -> Sequence[str]:
        source_id = payload.get("source_id")
        if not isinstance(source_id, str) or not source_id:
            raise ValueError("source_id ausente ou inválido")
        return (
            "systemd-run",
            "--user",
            "--scope",
            "--quiet",
            "-p",
            "MemoryMax=2G",
            "-p",
            "MemorySwapMax=1G",
            "-p",
            "RuntimeMaxSec=2h",
            sys.executable,
            "-m",
            "decoupit.normalization",
            "--database",
            str(database_path),
            "--source-id",
            source_id,
        )

    return command


def _waveform_command(database_path: Path, cache_root: Path) -> JobHandler:
    def command(payload: Mapping[str, Any]) -> Sequence[str]:
        source_id = payload.get("source_id")
        if not isinstance(source_id, str) or not source_id:
            raise ValueError("source_id ausente ou inválido")
        return (
            "systemd-run",
            "--user",
            "--scope",
            "--quiet",
            "-p",
            "MemoryMax=512M",
            "-p",
            "MemorySwapMax=256M",
            "-p",
            "RuntimeMaxSec=30m",
            sys.executable,
            "-m",
            "decoupit.waveform",
            "--database",
            str(database_path),
            "--cache-root",
            str(cache_root),
            "--source-id",
            source_id,
        )

    return command


def _transcription_command(database_path: Path) -> JobHandler:
    def command(payload: Mapping[str, Any]) -> Sequence[str]:
        source_id = payload.get("source_id")
        if not isinstance(source_id, str) or not source_id:
            raise ValueError("source_id ausente ou inválido")
        return (
            "systemd-run",
            "--user",
            "--scope",
            "--quiet",
            "-p",
            "MemoryMax=8G",
            "-p",
            "MemorySwapMax=2G",
            "-p",
            "CPUQuota=400%",
            "-p",
            "RuntimeMaxSec=2h",
            sys.executable,
            "-m",
            "decoupit.transcripts",
            "--database",
            str(database_path),
            "--source-id",
            source_id,
        )

    return command


def _default_handlers(database_path: Path, cache_root: Path) -> dict[str, JobHandler]:
    return {
        "system.noop": _noop_command,
        "media.normalize_cfr30": _normalization_command(database_path),
        "media.generate_waveform": _waveform_command(database_path, cache_root),
        "media.transcribe_words": _transcription_command(database_path),
    }


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


def _log_tail(path: Path, limit: int = 4000) -> str | None:
    try:
        content = path.read_bytes()[-(limit * 4) :].decode(errors="replace").strip()
    except OSError:
        return None
    return content[-limit:] or None


def run_next_job(
    database_path: Path,
    *,
    handlers: Mapping[str, JobHandler] | None = None,
    cache_root: Path | None = None,
    poll_interval: float = 0.05,
    terminate_timeout: float = 2.0,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Claim and execute at most one job, returning whether one was claimed."""

    resolved_cache_root = (
        database_path.parent / "cache" if cache_root is None else cache_root
    )
    available_handlers = (
        _default_handlers(database_path, resolved_cache_root)
        if handlers is None
        else handlers
    )
    with connect_database(database_path) as connection:
        job = claim_next_job(connection)
    if job is None:
        return False
    handler = available_handlers.get(job.kind)
    if handler is None:
        _record_failure(database_path, job, f"tipo de job não registrado: {job.kind}")
        return True
    log_directory = database_path.parent / "jobs"
    log_directory.mkdir(parents=True, exist_ok=True)
    log_path = log_directory / f"{job.id}.log"
    log_stream = None
    try:
        command = tuple(handler(job.payload))
        if not command or not all(isinstance(part, str) and part for part in command):
            raise ValueError("comando vazio ou inválido")
        log_stream = log_path.open("wb")
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log_stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
    except (OSError, ValueError) as error:
        if log_stream is not None:
            log_stream.close()
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
                log_stream.close()
                with connect_database(database_path) as connection:
                    finish_job(connection, job.id, JobState.CANCELLED)
                return True
            sleep(poll_interval)
    except BaseException:
        try:
            _terminate_process_group(process, terminate_timeout)
        finally:
            log_stream.close()
            with connect_database(database_path) as connection:
                recover_job(connection, job.id)
        raise

    log_stream.close()
    with connect_database(database_path) as connection:
        state = get_job(connection, job.id).state
        if state is JobState.CANCEL_REQUESTED:
            finish_job(connection, job.id, JobState.CANCELLED)
        elif process.returncode == 0:
            finish_job(connection, job.id, JobState.SUCCEEDED)
            log_path.unlink(missing_ok=True)
        else:
            detail = _log_tail(log_path)
            message = f"subprocesso terminou com código {process.returncode}"
            if detail:
                message = f"{message}: {detail}"
            finish_job(
                connection,
                job.id,
                JobState.FAILED,
                error_message=message,
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
        run_next_job(paths.database, cache_root=paths.cache)
    except WorkerInterrupted as error:
        raise SystemExit(128 + error.signal_number) from error
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)
        signal.signal(signal.SIGINT, previous_sigint)


if __name__ == "__main__":
    main()
