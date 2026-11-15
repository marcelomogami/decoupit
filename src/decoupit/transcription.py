"""Local Faster Whisper transcription with word-level timestamps."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from importlib.metadata import version
from importlib.util import find_spec
from pathlib import Path
from typing import Any, Protocol

MODEL_ID = "Systran/faster-whisper-medium"
MODEL_REVISION = "08e178d48790749d25932bbc082711ddcfdfbc4f"
PROFILE = {
    "model": MODEL_ID,
    "model_revision": MODEL_REVISION,
    "device": "cuda",
    "compute_type": "float16",
    "cpu_threads": 4,
    "num_workers": 1,
    "beam_size": 5,
    "vad_filter": True,
    "word_timestamps": True,
}


class TranscriptionError(RuntimeError):
    """Raised when local transcription cannot produce a valid result."""


@dataclass(frozen=True, slots=True)
class TranscriptWord:
    start_us: int
    end_us: int
    text: str
    probability: float


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    start_us: int
    end_us: int
    text: str
    words: tuple[TranscriptWord, ...]


@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    language: str
    language_probability: float
    duration_us: int
    duration_after_vad_us: int
    segments: tuple[TranscriptSegment, ...]
    profile: dict[str, Any]

    def to_json(self) -> str:
        return json.dumps(
            asdict(self), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )


class ModelFactory(Protocol):
    def __call__(self, model_name: str, **kwargs: Any) -> Any: ...


def _seconds_to_us(value: float) -> int:
    return round(value * 1_000_000)


def cuda_library_directories() -> tuple[Path, Path]:
    directories: list[Path] = []
    for package in ("nvidia.cublas", "nvidia.cudnn"):
        spec = find_spec(package)
        locations = [] if spec is None else list(spec.submodule_search_locations or ())
        if not locations:
            raise TranscriptionError(f"runtime CUDA ausente: {package}")
        library_directory = Path(locations[0]) / "lib"
        if not library_directory.is_dir():
            raise TranscriptionError(f"bibliotecas CUDA ausentes: {library_directory}")
        directories.append(library_directory)
    return directories[0], directories[1]


def cuda_library_path(environment: dict[str, str] | None = None) -> str:
    current_environment = os.environ if environment is None else environment
    entries = [str(path) for path in cuda_library_directories()]
    existing = current_environment.get("LD_LIBRARY_PATH")
    if existing:
        entries.append(existing)
    return os.pathsep.join(entries)


def resolve_model_path(
    *,
    environment: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    current_environment = os.environ if environment is None else environment
    user_home = Path.home() if home is None else home
    cache_roots: list[Path] = []
    if hub_cache := current_environment.get("HUGGINGFACE_HUB_CACHE"):
        cache_roots.append(Path(hub_cache))
    if hf_home := current_environment.get("HF_HOME"):
        cache_roots.append(Path(hf_home) / "hub")
    if xdg_cache := current_environment.get("XDG_CACHE_HOME"):
        cache_roots.append(Path(xdg_cache) / "huggingface" / "hub")
    cache_roots.append(user_home / ".cache" / "huggingface" / "hub")
    repository_directory = "models--Systran--faster-whisper-medium"
    for cache_root in dict.fromkeys(cache_roots):
        candidate = cache_root / repository_directory / "snapshots" / MODEL_REVISION
        if (candidate / "model.bin").is_file() and (
            candidate / "config.json"
        ).is_file():
            return candidate
    raise TranscriptionError(
        "o modelo Faster Whisper medium não está instalado no cache local"
    )


def _ensure_cuda_runtime(arguments: Sequence[str]) -> None:
    required = [str(path) for path in cuda_library_directories()]
    current = os.environ.get("LD_LIBRARY_PATH", "").split(os.pathsep)
    if all(path in current for path in required):
        return
    environment = os.environ.copy()
    environment["LD_LIBRARY_PATH"] = cuda_library_path(environment)
    os.execve(
        sys.executable,
        [sys.executable, "-m", "decoupit.transcription", *arguments],
        environment,
    )


def _validate_interval(start_us: int, end_us: int, label: str) -> None:
    if start_us < 0 or end_us < start_us:
        raise TranscriptionError(f"intervalo inválido em {label}")


def runtime_profile() -> dict[str, Any]:
    profile = dict(PROFILE)
    profile["libraries"] = {
        package: version(package)
        for package in (
            "av",
            "ctranslate2",
            "faster-whisper",
            "nvidia-cublas-cu12",
            "nvidia-cudnn-cu12",
        )
    }
    return profile


def _collect_segments(segments: Iterable[Any]) -> tuple[TranscriptSegment, ...]:
    result: list[TranscriptSegment] = []
    for segment_index, segment in enumerate(segments):
        segment_start = _seconds_to_us(segment.start)
        segment_end = _seconds_to_us(segment.end)
        _validate_interval(segment_start, segment_end, f"segmento {segment_index}")
        words: list[TranscriptWord] = []
        for word_index, word in enumerate(segment.words or ()):
            word_start = _seconds_to_us(word.start)
            word_end = _seconds_to_us(word.end)
            _validate_interval(
                word_start,
                word_end,
                f"palavra {word_index} do segmento {segment_index}",
            )
            words.append(
                TranscriptWord(
                    start_us=word_start,
                    end_us=word_end,
                    text=word.word,
                    probability=float(word.probability),
                )
            )
        result.append(
            TranscriptSegment(
                start_us=segment_start,
                end_us=segment_end,
                text=segment.text,
                words=tuple(words),
            )
        )
    return tuple(result)


def transcribe_media(
    media_path: Path,
    *,
    model_factory: ModelFactory | None = None,
    model_path: Path | None = None,
) -> TranscriptionResult:
    try:
        canonical_path = media_path.resolve(strict=True)
    except OSError as error:
        raise TranscriptionError("a mídia normalizada não está acessível") from error
    if not canonical_path.is_file():
        raise TranscriptionError("a mídia normalizada não é um arquivo regular")
    if model_factory is None:
        from faster_whisper import WhisperModel

        model_factory = WhisperModel
    resolved_model_path = resolve_model_path() if model_path is None else model_path
    model = model_factory(
        str(resolved_model_path),
        device=PROFILE["device"],
        compute_type=PROFILE["compute_type"],
        cpu_threads=PROFILE["cpu_threads"],
        num_workers=PROFILE["num_workers"],
        local_files_only=True,
        revision=MODEL_REVISION,
    )
    segments, info = model.transcribe(
        str(canonical_path),
        beam_size=PROFILE["beam_size"],
        vad_filter=PROFILE["vad_filter"],
        word_timestamps=PROFILE["word_timestamps"],
    )
    collected_segments = _collect_segments(segments)
    if collected_segments and not any(segment.words for segment in collected_segments):
        raise TranscriptionError("o modelo não retornou timestamps por palavra")
    return TranscriptionResult(
        language=str(info.language),
        language_probability=float(info.language_probability),
        duration_us=_seconds_to_us(info.duration),
        duration_after_vad_us=_seconds_to_us(info.duration_after_vad),
        segments=collected_segments,
        profile=runtime_profile(),
    )


def write_result(path: Path, result: TranscriptionResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial_path = path.with_suffix(f"{path.suffix}.part")
    partial_path.unlink(missing_ok=True)
    try:
        with partial_path.open("x", encoding="utf-8") as output:
            output.write(result.to_json())
            output.flush()
            os.fsync(output.fileno())
        os.replace(partial_path, path)
    finally:
        partial_path.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> None:
    arguments_list = list(sys.argv[1:] if argv is None else argv)
    _ensure_cuda_runtime(arguments_list)
    parser = argparse.ArgumentParser(
        description="Transcreve uma mídia local com timestamps por palavra."
    )
    parser.add_argument("media", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(arguments_list)
    result = transcribe_media(arguments.media)
    write_result(arguments.output, result)


if __name__ == "__main__":
    main()
