from decoupit.subtitles import (
    MAX_CUE_CHARACTERS,
    MAX_CUE_DURATION_US,
    build_subtitle_cues,
    render_srt,
)
from decoupit.transcripts import (
    TranscriptDocument,
    TranscriptSegmentRecord,
    TranscriptWordRecord,
)


def test_render_srt_uses_words_fallback_segments_and_millisecond_coverage() -> None:
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
                text="  Olá  ",
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
        "Olá\n\n"
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


def test_cues_use_words_across_model_segments_and_split_at_punctuation() -> None:
    document = TranscriptDocument(
        transcription_run_id="run-1",
        language="en",
        segments=(
            TranscriptSegmentRecord(
                0,
                0,
                700_000,
                "One incomplete model segment",
                (
                    TranscriptWordRecord(0, 300_000, " One", 0.9),
                    TranscriptWordRecord(320_000, 700_000, " incomplete", 0.9),
                ),
            ),
            TranscriptSegmentRecord(
                1,
                750_000,
                2_400_000,
                "sentence. Again",
                (
                    TranscriptWordRecord(750_000, 1_100_000, " sentence.", 0.9),
                    TranscriptWordRecord(2_000_000, 2_400_000, " Again", 0.9),
                ),
            ),
        ),
    )

    cues = build_subtitle_cues(document)

    assert [(cue.start_us, cue.end_us, cue.text) for cue in cues] == [
        (0, 1_100_000, "One incomplete sentence."),
        (2_000_000, 2_400_000, "Again"),
    ]


def test_cues_split_at_one_second_gap_without_punctuation() -> None:
    words = (
        TranscriptWordRecord(0, 500_000, " First", 0.9),
        TranscriptWordRecord(1_500_000, 2_000_000, " second", 0.9),
    )
    document = TranscriptDocument(
        transcription_run_id="run-1",
        language="en",
        segments=(TranscriptSegmentRecord(0, 0, 2_000_000, "First second", words),),
    )

    assert [cue.text for cue in build_subtitle_cues(document)] == [
        "First",
        "second",
    ]


def test_long_phrase_is_balanced_without_exceeding_cue_limits() -> None:
    texts = (
        "This",
        "sentence",
        "contains",
        "enough",
        "words",
        "to",
        "require",
        "balanced",
        "subtitle",
        "cue",
        "splitting",
        "today.",
    )
    words = tuple(
        TranscriptWordRecord(
            index * 400_000,
            (index + 1) * 400_000,
            f" {text}",
            0.9,
        )
        for index, text in enumerate(texts)
    )
    document = TranscriptDocument(
        transcription_run_id="run-1",
        language="en",
        segments=(
            TranscriptSegmentRecord(
                0,
                words[0].start_us,
                words[-1].end_us,
                " ".join(texts),
                words,
            ),
        ),
    )

    cues = build_subtitle_cues(document)

    assert len(cues) == 2
    assert all(cue.end_us - cue.start_us <= MAX_CUE_DURATION_US for cue in cues)
    assert all(len(cue.text) <= MAX_CUE_CHARACTERS for cue in cues)
    assert abs(len(cues[0].text) - len(cues[1].text)) <= 16
    assert " ".join(cue.text for cue in cues) == " ".join(texts)


def test_cues_split_when_duration_exceeds_limit() -> None:
    words = tuple(
        TranscriptWordRecord(
            index * 1_000_000,
            (index + 1) * 1_000_000,
            " word",
            0.9,
        )
        for index in range(8)
    )
    document = TranscriptDocument(
        transcription_run_id="run-1",
        language="en",
        segments=(TranscriptSegmentRecord(0, 0, words[-1].end_us, "word " * 8, words),),
    )

    cues = build_subtitle_cues(document)

    assert len(cues) == 2
    assert all(cue.end_us - cue.start_us <= MAX_CUE_DURATION_US for cue in cues)


def test_render_srt_wraps_long_cue_into_at_most_two_balanced_lines() -> None:
    texts = ("A", "subtitle", "line", "that", "needs", "a", "balanced", "wrap.")
    words = tuple(
        TranscriptWordRecord(
            index * 300_000,
            (index + 1) * 300_000,
            f" {text}",
            0.9,
        )
        for index, text in enumerate(texts)
    )
    document = TranscriptDocument(
        transcription_run_id="run-1",
        language="en",
        segments=(
            TranscriptSegmentRecord(
                0,
                0,
                words[-1].end_us,
                " ".join(texts),
                words,
            ),
        ),
    )

    cue = render_srt(document).strip().splitlines()
    text_lines = cue[2:]

    assert 1 < len(text_lines) <= 2
    assert all(len(line) <= 42 for line in text_lines)
    assert " ".join(text_lines) == " ".join(texts)
