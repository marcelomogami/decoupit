import pytest

from decoupit.jobs import JobState, JobStateError, recover_state, transition


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (JobState.QUEUED, JobState.RUNNING),
        (JobState.QUEUED, JobState.CANCELLED),
        (JobState.RUNNING, JobState.SUCCEEDED),
        (JobState.RUNNING, JobState.FAILED),
        (JobState.RUNNING, JobState.CANCEL_REQUESTED),
        (JobState.CANCEL_REQUESTED, JobState.CANCELLED),
    ],
)
def test_allowed_job_transitions(current: JobState, target: JobState) -> None:
    assert transition(current, target) is target


def test_terminal_job_cannot_transition() -> None:
    with pytest.raises(JobStateError, match=r"succeeded.*running"):
        transition(JobState.SUCCEEDED, JobState.RUNNING)


def test_recovery_requeues_interrupted_work_and_preserves_cancellation() -> None:
    assert recover_state(JobState.RUNNING) is JobState.QUEUED
    assert recover_state(JobState.CANCEL_REQUESTED) is JobState.CANCELLED
    assert recover_state(JobState.QUEUED) is JobState.QUEUED
    assert recover_state(JobState.FAILED) is JobState.FAILED
