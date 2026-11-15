import pytest

from decoupit.timing import frame_start_us, timestamp_us_to_frame


@pytest.mark.parametrize(
    ("timestamp_us", "frame"),
    [(0, 0), (33_333, 0), (33_334, 1), (1_000_000, 30), (60_033_333, 1800)],
)
def test_timestamp_maps_to_containing_cfr30_frame(
    timestamp_us: int, frame: int
) -> None:
    assert timestamp_us_to_frame(timestamp_us) == frame


@pytest.mark.parametrize("frame", [0, 1, 29, 30, 1800])
def test_frame_start_maps_back_to_same_frame(frame: int) -> None:
    assert timestamp_us_to_frame(frame_start_us(frame)) == frame


def test_negative_timestamps_and_frames_are_rejected() -> None:
    with pytest.raises(ValueError):
        timestamp_us_to_frame(-1)
    with pytest.raises(ValueError):
        frame_start_us(-1)
