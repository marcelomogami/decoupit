from decoupit.subtitles import render_srt
from decoupit.transcripts import (
    TranscriptDocument,
    TranscriptSegmentRecord,
    TranscriptWordRecord,
)


def test_render_srt_uses_segment_boundaries_and_millisecond_coverage() -> None:
    word = TranscriptWordRecord(
        start_us=123_456,
        end_us=1_234_001,
        text=" Olá",
        probability=0.9,
    )
    document = TranscriptDocument(
        transcription_run_id="run-1",
        language="pt",
        segments=(
            TranscriptSegmentRecord(
                segment_index=0,
                start_us=123_456,
                end_us=1_234_001,
                text="  Olá\n mundo  ",
                words=(word,),
            ),
            TranscriptSegmentRecord(
                segment_index=1,
                start_us=3_661_001_999,
                end_us=3_662_000_001,
                text="Segundo trecho",
                words=(),
            ),
        ),
    )

    assert render_srt(document) == (
        "1\n"
        "00:00:00,123 --> 00:00:01,235\n"
        "Olá mundo\n\n"
        "2\n"
        "01:01:01,001 --> 01:01:02,001\n"
        "Segundo trecho\n"
    )


def test_render_srt_skips_empty_segments_and_keeps_numbers_contiguous() -> None:
    document = TranscriptDocument(
        transcription_run_id="run-1",
        language="pt",
        segments=(
            TranscriptSegmentRecord(0, 0, 1_000_000, "  \n ", ()),
            TranscriptSegmentRecord(1, 1_000_000, 2_000_000, " Texto ", ()),
        ),
    )

    assert render_srt(document).startswith("1\n00:00:01,000")
    assert "\n2\n" not in render_srt(document)
