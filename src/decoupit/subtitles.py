"""Subtitle exporters for persisted transcripts."""

from __future__ import annotations

from decoupit.transcripts import TranscriptDocument


def _format_srt_timestamp(milliseconds: int) -> str:
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def render_srt(document: TranscriptDocument) -> str:
    """Render transcript segments as UTF-8 SubRip cues."""

    cues: list[str] = []
    for segment in document.segments:
        text = " ".join(segment.text.split())
        if not text:
            continue
        start_ms = segment.start_us // 1_000
        end_ms = max(start_ms + 1, (segment.end_us + 999) // 1_000)
        cues.append(
            "\n".join(
                (
                    str(len(cues) + 1),
                    f"{_format_srt_timestamp(start_ms)} --> "
                    f"{_format_srt_timestamp(end_ms)}",
                    text,
                )
            )
        )
    return "\n\n".join(cues) + ("\n" if cues else "")
