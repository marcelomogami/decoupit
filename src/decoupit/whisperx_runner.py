"""Heavy WhisperX runtime entry point executed by an isolated Python."""

from __future__ import annotations

import argparse
import gc
import json
import os
import resource
import sys
import time
from collections.abc import Sequence
from importlib.metadata import version
from pathlib import Path
from typing import Any


def _detect_language(pipeline: Any, audio: Any) -> tuple[str, float]:
    from whisperx.audio import N_SAMPLES, log_mel_spectrogram

    padding = N_SAMPLES - audio.shape[0] if audio.shape[0] < N_SAMPLES else 0
    model_n_mels = pipeline.model.feat_kwargs.get("feature_size")
    segment = log_mel_spectrogram(
        audio[:N_SAMPLES],
        n_mels=model_n_mels if model_n_mels is not None else 80,
        padding=padding,
    )
    encoder_output = pipeline.model.encode(segment)
    language_token, probability = pipeline.model.model.detect_language(encoder_output)[
        0
    ][0]
    return language_token[2:-2], float(probability)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial_path = path.with_suffix(f"{path.suffix}.part")
    partial_path.unlink(missing_ok=True)
    try:
        with partial_path.open("x", encoding="utf-8") as output:
            json.dump(payload, output, ensure_ascii=False, separators=(",", ":"))
            output.flush()
            os.fsync(output.fileno())
        os.replace(partial_path, path)
    finally:
        partial_path.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--media", type=Path, required=True)
    parser.add_argument("--whisper-model", type=Path, required=True)
    parser.add_argument("--align-model-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, required=True)
    parser.add_argument("--chunk-size", type=int, required=True)
    arguments = parser.parse_args(argv)

    import torch
    import whisperx
    from whisperx.alignment import align, load_align_model
    from whisperx.asr import load_model

    torch.cuda.reset_peak_memory_stats()
    started_at = time.monotonic()
    transcriber = load_model(
        str(arguments.whisper_model),
        "cuda",
        compute_type="float16",
        vad_method="pyannote",
        local_files_only=True,
        threads=4,
    )
    transcriber_loaded_at = time.monotonic()
    audio = whisperx.load_audio(str(arguments.media))
    audio_loaded_at = time.monotonic()
    language, language_probability = _detect_language(transcriber, audio)
    language_detected_at = time.monotonic()
    transcription = transcriber.transcribe(
        audio,
        batch_size=arguments.batch_size,
        chunk_size=arguments.chunk_size,
        language=language,
    )
    transcribed_at = time.monotonic()
    transcription["language_probability"] = language_probability
    transcription["duration"] = len(audio) / 16_000
    transcription["duration_after_vad"] = sum(
        max(0.0, float(segment["end"]) - float(segment["start"]))
        for segment in transcription["segments"]
    )

    del transcriber
    gc.collect()
    torch.cuda.empty_cache()
    transcriber_released_at = time.monotonic()

    if transcription["segments"]:
        aligner, metadata = load_align_model(
            language_code=language,
            device="cuda",
            model_name="WAV2VEC2_ASR_BASE_960H",
            model_dir=str(arguments.align_model_dir),
            model_cache_only=True,
        )
        aligner_loaded_at = time.monotonic()
        aligned = align(
            transcription["segments"],
            aligner,
            metadata,
            audio,
            "cuda",
            return_char_alignments=False,
        )
        aligned_at = time.monotonic()
    else:
        aligner_loaded_at = transcriber_released_at
        aligned_at = transcriber_released_at
        aligned = {"segments": [], "word_segments": []}

    payload = {
        "profile": {
            "libraries": {
                package: version(package)
                for package in (
                    "faster-whisper",
                    "pyannote.audio",
                    "torch",
                    "torchaudio",
                    "whisperx",
                )
            }
        },
        "metrics": {
            "load_transcriber_seconds": transcriber_loaded_at - started_at,
            "load_audio_seconds": audio_loaded_at - transcriber_loaded_at,
            "language_detection_seconds": language_detected_at - audio_loaded_at,
            "transcription_seconds": transcribed_at - language_detected_at,
            "release_transcriber_seconds": (transcriber_released_at - transcribed_at),
            "load_aligner_seconds": aligner_loaded_at - transcriber_released_at,
            "alignment_seconds": aligned_at - aligner_loaded_at,
            "total_seconds": aligned_at - started_at,
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "peak_cuda_allocated_bytes": torch.cuda.max_memory_allocated(),
            "peak_cuda_reserved_bytes": torch.cuda.max_memory_reserved(),
        },
        "transcription": transcription,
        "aligned": aligned,
    }
    _write_json(arguments.output, payload)


if __name__ == "__main__":
    main(sys.argv[1:])
