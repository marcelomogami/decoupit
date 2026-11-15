"""Persistent queue operations for local jobs."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from typing import Any

from decoupit.jobs import JobState, transition


@dataclass(frozen=True, slots=True)
class Job:
    id: str
    kind: str
    state: JobState
    payload: dict[str, Any]
    attempt: int
    process_id: int | None
    error_message: str | None


def _job_from_row(row: sqlite3.Row) -> Job:
    return Job(
        id=row["id"],
        kind=row["kind"],
        state=JobState(row["state"]),
        payload=json.loads(row["payload_json"]),
        attempt=row["attempt"],
        process_id=row["process_id"],
        error_message=row["error_message"],
    )


def enqueue_job(
    connection: sqlite3.Connection,
    *,
    kind: str,
    payload: dict[str, Any] | None = None,
    project_id: str | None = None,
    job_id: str | None = None,
) -> str:
    identifier = str(uuid.uuid4()) if job_id is None else job_id
    connection.execute(
        """
        INSERT INTO jobs (id, project_id, kind, state, payload_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            identifier,
            project_id,
            kind,
            JobState.QUEUED.value,
            json.dumps(payload or {}, ensure_ascii=False, separators=(",", ":")),
        ),
    )
    connection.commit()
    return identifier


def get_job(connection: sqlite3.Connection, job_id: str) -> Job:
    row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        raise KeyError(job_id)
    return _job_from_row(row)


def find_active_normalization_job(
    connection: sqlite3.Connection, source_id: str
) -> Job | None:
    row = connection.execute(
        """
        SELECT * FROM jobs
        WHERE kind = 'media.normalize_cfr30'
          AND json_extract(payload_json, '$.source_id') = ?
          AND state IN ('queued', 'running', 'cancel_requested')
        ORDER BY created_at, id
        LIMIT 1
        """,
        (source_id,),
    ).fetchone()
    return None if row is None else _job_from_row(row)


def claim_next_job(connection: sqlite3.Connection) -> Job | None:
    """Atomically claim the oldest queued job."""

    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT id FROM jobs WHERE state = ? ORDER BY created_at, id LIMIT 1",
            (JobState.QUEUED.value,),
        ).fetchone()
        if row is None:
            connection.commit()
            return None
        connection.execute(
            """
            UPDATE jobs
            SET state = ?, attempt = attempt + 1,
                started_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                finished_at = NULL, error_message = NULL
            WHERE id = ? AND state = ?
            """,
            (JobState.RUNNING.value, row["id"], JobState.QUEUED.value),
        )
        claimed = get_job(connection, row["id"])
        connection.commit()
        return claimed
    except Exception:
        connection.rollback()
        raise


def set_process_id(
    connection: sqlite3.Connection, job_id: str, process_id: int
) -> None:
    connection.execute(
        "UPDATE jobs SET process_id = ?, updated_at = "
        "strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ? AND state IN (?, ?)",
        (
            process_id,
            job_id,
            JobState.RUNNING.value,
            JobState.CANCEL_REQUESTED.value,
        ),
    )
    connection.commit()


def finish_job(
    connection: sqlite3.Connection,
    job_id: str,
    target: JobState,
    *,
    error_message: str | None = None,
) -> JobState:
    current = get_job(connection, job_id).state
    new_state = transition(current, target)
    connection.execute(
        """
        UPDATE jobs
        SET state = ?, process_id = NULL, error_message = ?,
            finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        WHERE id = ?
        """,
        (new_state.value, error_message, job_id),
    )
    connection.commit()
    return new_state


def request_cancellation(connection: sqlite3.Connection, job_id: str) -> JobState:
    try:
        connection.execute("BEGIN IMMEDIATE")
        job = get_job(connection, job_id)
        if job.state is JobState.QUEUED:
            target = JobState.CANCELLED
            finished = "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"
        elif job.state is JobState.RUNNING:
            target = JobState.CANCEL_REQUESTED
            finished = "NULL"
        else:
            connection.commit()
            return job.state
        transition(job.state, target)
        connection.execute(
            f"""
            UPDATE jobs
            SET state = ?, cancellation_requested_at =
                    strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                finished_at = {finished},
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE id = ? AND state = ?
            """,
            (target.value, job_id, job.state.value),
        )
        connection.commit()
        return target
    except Exception:
        connection.rollback()
        raise


def recover_incomplete_jobs(connection: sqlite3.Connection) -> int:
    running = connection.execute(
        """
        UPDATE jobs
        SET state = 'queued', process_id = NULL, started_at = NULL,
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        WHERE state = 'running'
        """
    ).rowcount
    cancelled = connection.execute(
        """
        UPDATE jobs
        SET state = 'cancelled', process_id = NULL,
            finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        WHERE state = 'cancel_requested'
        """
    ).rowcount
    connection.commit()
    return running + cancelled


def recover_job(connection: sqlite3.Connection, job_id: str) -> JobState:
    """Recover one interrupted job after its process tree has stopped."""

    job = get_job(connection, job_id)
    if job.state is JobState.RUNNING:
        connection.execute(
            """
            UPDATE jobs
            SET state = 'queued', process_id = NULL, started_at = NULL,
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE id = ? AND state = 'running'
            """,
            (job_id,),
        )
        target = JobState.QUEUED
    elif job.state is JobState.CANCEL_REQUESTED:
        connection.execute(
            """
            UPDATE jobs
            SET state = 'cancelled', process_id = NULL,
                finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE id = ? AND state = 'cancel_requested'
            """,
            (job_id,),
        )
        target = JobState.CANCELLED
    else:
        return job.state
    connection.commit()
    return target
