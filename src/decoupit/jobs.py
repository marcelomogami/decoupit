"""Job lifecycle rules independent from the worker implementation."""

from __future__ import annotations

from enum import StrEnum


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCEL_REQUESTED = "cancel_requested"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobStateError(ValueError):
    """Raised when a job transition violates the lifecycle contract."""


_ALLOWED_TRANSITIONS: dict[JobState, frozenset[JobState]] = {
    JobState.QUEUED: frozenset({JobState.RUNNING, JobState.CANCELLED}),
    JobState.RUNNING: frozenset(
        {JobState.CANCEL_REQUESTED, JobState.FAILED, JobState.SUCCEEDED}
    ),
    JobState.CANCEL_REQUESTED: frozenset({JobState.CANCELLED, JobState.FAILED}),
    JobState.SUCCEEDED: frozenset(),
    JobState.FAILED: frozenset(),
    JobState.CANCELLED: frozenset(),
}


def transition(current: JobState, target: JobState) -> JobState:
    """Validate and return a requested lifecycle transition."""

    if current is target:
        return current
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise JobStateError(
            f"transição inválida de {current.value} para {target.value}"
        )
    return target


def recover_state(state: JobState) -> JobState:
    """Return the safe state after the application restarts unexpectedly."""

    if state is JobState.RUNNING:
        return JobState.QUEUED
    if state is JobState.CANCEL_REQUESTED:
        return JobState.CANCELLED
    return state
