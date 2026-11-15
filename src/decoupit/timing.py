"""Canonical conversion between media timestamps and CFR 30 frames."""

from __future__ import annotations

CFR_FRAME_RATE_NUMERATOR = 30
CFR_FRAME_RATE_DENOMINATOR = 1
MICROSECONDS_PER_SECOND = 1_000_000


def timestamp_us_to_frame(timestamp_us: int) -> int:
    """Return the zero-based frame containing a non-negative timestamp."""

    if timestamp_us < 0:
        raise ValueError("o timestamp não pode ser negativo")
    return (
        timestamp_us
        * CFR_FRAME_RATE_NUMERATOR
        // (MICROSECONDS_PER_SECOND * CFR_FRAME_RATE_DENOMINATOR)
    )


def frame_start_us(frame: int) -> int:
    """Return the earliest integer timestamp contained in a zero-based frame."""

    if frame < 0:
        raise ValueError("o quadro não pode ser negativo")
    numerator = frame * MICROSECONDS_PER_SECOND * CFR_FRAME_RATE_DENOMINATOR
    return (numerator + CFR_FRAME_RATE_NUMERATOR - 1) // CFR_FRAME_RATE_NUMERATOR
