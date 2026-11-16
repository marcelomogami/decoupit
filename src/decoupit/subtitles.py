"""Subtitle exporters for persisted transcripts."""

from __future__ import annotations

import re
from dataclasses import dataclass

from decoupit.transcripts import TranscriptDocument, TranscriptWordRecord

MAX_CUE_DURATION_US = 7_000_000
MAX_CUE_CHARACTERS = 84
MAX_LINE_CHARACTERS = 42
SPLIT_GAP_US = 1_000_000
_TERMINAL_PUNCTUATION = re.compile(r"""[.!?…]["')\]]*$""")


@dataclass(frozen=True, slots=True)
class SubtitleCue:
    start_us: int
    end_us: int
    text: str


def _format_srt_timestamp(milliseconds: int) -> str:
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def _normalize_text(text: str) -> str:
    return " ".join(text.split())


def _words_text(words: tuple[TranscriptWordRecord, ...]) -> str:
    return " ".join(
        normalized for word in words if (normalized := _normalize_text(word.text))
    )


def _span_is_valid(
    words: tuple[TranscriptWordRecord, ...],
    start: int,
    end: int,
) -> bool:
    if end == start + 1:
        return True
    text = _words_text(words[start:end])
    duration_us = words[end - 1].end_us - words[start].start_us
    return len(text) <= MAX_CUE_CHARACTERS and duration_us <= MAX_CUE_DURATION_US


def _span_cost(words: tuple[TranscriptWordRecord, ...], start: int, end: int) -> float:
    text_load = len(_words_text(words[start:end])) / MAX_CUE_CHARACTERS
    duration_load = (
        words[end - 1].end_us - words[start].start_us
    ) / MAX_CUE_DURATION_US
    return max(text_load, duration_load) ** 2


def _partition_phrase(
    words: tuple[TranscriptWordRecord, ...],
) -> tuple[SubtitleCue, ...]:
    if not words:
        return ()
    word_count = len(words)
    plans: list[tuple[int, float, int] | None] = [None] * (word_count + 1)
    plans[word_count] = (0, 0.0, word_count)
    for start in range(word_count - 1, -1, -1):
        best: tuple[int, float, int] | None = None
        for end in range(start + 1, word_count + 1):
            if not _span_is_valid(words, start, end):
                break
            following = plans[end]
            if following is None:
                continue
            candidate = (
                following[0] + 1,
                following[1] + _span_cost(words, start, end),
                end,
            )
            if best is None or candidate[:2] < best[:2]:
                best = candidate
        plans[start] = best
    plan = plans[0]
    if plan is None:
        raise RuntimeError("não foi possível dividir as palavras em cues")
    cues: list[SubtitleCue] = []
    start = 0
    while start < word_count:
        current_plan = plans[start]
        if current_plan is None:
            raise RuntimeError("plano de cues incompleto")
        end = current_plan[2]
        cue_words = words[start:end]
        cues.append(
            SubtitleCue(
                start_us=cue_words[0].start_us,
                end_us=cue_words[-1].end_us,
                text=_words_text(cue_words),
            )
        )
        start = end
    return tuple(cues)


def build_subtitle_cues(document: TranscriptDocument) -> tuple[SubtitleCue, ...]:
    """Group aligned words into deterministic, readable subtitle cues."""

    cues: list[SubtitleCue] = []
    phrase: list[TranscriptWordRecord] = []

    def flush_phrase() -> None:
        if phrase:
            cues.extend(_partition_phrase(tuple(phrase)))
            phrase.clear()

    for segment in document.segments:
        if not segment.words:
            flush_phrase()
            text = _normalize_text(segment.text)
            if text:
                cues.append(SubtitleCue(segment.start_us, segment.end_us, text))
            continue
        for word in segment.words:
            if not _normalize_text(word.text):
                continue
            if phrase and word.start_us - phrase[-1].end_us >= SPLIT_GAP_US:
                flush_phrase()
            phrase.append(word)
            if _TERMINAL_PUNCTUATION.search(_normalize_text(word.text)):
                flush_phrase()
    flush_phrase()
    return tuple(cues)


def _wrap_text(text: str) -> tuple[str, ...]:
    words = text.split()
    if len(text) <= MAX_LINE_CHARACTERS or len(words) < 2:
        return (text,)
    candidates: list[tuple[tuple[int, int, int], tuple[str, str]]] = []
    for split in range(1, len(words)):
        left = " ".join(words[:split])
        right = " ".join(words[split:])
        longest = max(len(left), len(right))
        key = (
            0 if longest <= MAX_LINE_CHARACTERS else 1,
            longest,
            abs(len(left) - len(right)),
        )
        candidates.append((key, (left, right)))
    return min(candidates, key=lambda candidate: candidate[0])[1]


def render_srt(document: TranscriptDocument) -> str:
    """Render aligned transcript words as UTF-8 SubRip cues."""

    cues: list[str] = []
    for cue in build_subtitle_cues(document):
        start_ms = cue.start_us // 1_000
        end_ms = max(start_ms + 1, (cue.end_us + 999) // 1_000)
        cues.append(
            "\n".join(
                (
                    str(len(cues) + 1),
                    f"{_format_srt_timestamp(start_ms)} --> "
                    f"{_format_srt_timestamp(end_ms)}",
                    *_wrap_text(cue.text),
                )
            )
        )
    return "\n\n".join(cues) + ("\n" if cues else "")
