from pathlib import Path

from decoupit.database import connect_database, initialize_database
from decoupit.job_store import (
    claim_next_job,
    enqueue_job,
    get_job,
    recover_incomplete_jobs,
    request_cancellation,
)
from decoupit.jobs import JobState


def test_job_is_claimed_once_and_attempt_is_incremented(tmp_path: Path) -> None:
    database_path = tmp_path / "decoupit.sqlite3"
    initialize_database(database_path)
    with connect_database(database_path) as connection:
        job_id = enqueue_job(connection, kind="system.noop")
        claimed = claim_next_job(connection)
        second_claim = claim_next_job(connection)

    assert claimed is not None
    assert claimed.id == job_id
    assert claimed.state is JobState.RUNNING
    assert claimed.attempt == 1
    assert second_claim is None


def test_queued_job_is_cancelled_without_running(tmp_path: Path) -> None:
    database_path = tmp_path / "decoupit.sqlite3"
    initialize_database(database_path)
    with connect_database(database_path) as connection:
        job_id = enqueue_job(connection, kind="system.noop")
        state = request_cancellation(connection, job_id)
        job = get_job(connection, job_id)

    assert state is JobState.CANCELLED
    assert job.state is JobState.CANCELLED


def test_recovery_requeues_running_and_finishes_requested_cancel(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "decoupit.sqlite3"
    initialize_database(database_path)
    with connect_database(database_path) as connection:
        running_id = enqueue_job(connection, kind="system.noop")
        cancel_id = enqueue_job(connection, kind="system.noop")
        connection.execute(
            "UPDATE jobs SET state = 'running', process_id = 123 WHERE id = ?",
            (running_id,),
        )
        connection.execute(
            "UPDATE jobs SET state = 'cancel_requested', process_id = 456 WHERE id = ?",
            (cancel_id,),
        )
        connection.commit()

        recovered = recover_incomplete_jobs(connection)
        running = get_job(connection, running_id)
        cancelled = get_job(connection, cancel_id)

    assert recovered == 2
    assert running.state is JobState.QUEUED
    assert running.process_id is None
    assert cancelled.state is JobState.CANCELLED
    assert cancelled.process_id is None
