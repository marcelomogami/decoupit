"""Read-only inspection of source media with ffprobe."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from pathlib import Path
from typing import Any

ProbeRunner = Callable[..., subprocess.CompletedProcess[str]]


class MediaProbeError(ValueError):
    """Raised when a source cannot be safely inspected."""


@dataclass(frozen=True, slots=True)
class SourceInspection:
    path: Path
    device: int
    inode: int
    size_bytes: int
    modified_at_ns: int
    format_name: str
    duration_us: int | None
    video_codec: str
    width: int
    height: int
    nominal_frame_rate: tuple[int, int] | None
    average_frame_rate: tuple[int, int] | None
    frame_rate_mode: str
    audio_codec: str | None
    sample_rate: int | None
    channels: int | None
    probe_json: str


def _rate(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, str):
        return None
    try:
        rate = Fraction(value)
    except (ValueError, ZeroDivisionError):
        return None
    if rate <= 0:
        return None
    return rate.numerator, rate.denominator


def _duration_us(*values: Any) -> int | None:
    for value in values:
        if value in (None, "N/A"):
            continue
        try:
            duration = Decimal(str(value))
        except InvalidOperation:
            continue
        if duration >= 0:
            return int(duration * 1_000_000)
    return None


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def probe_source(
    path: Path,
    *,
    runner: ProbeRunner = subprocess.run,
    timeout_seconds: float = 30,
) -> SourceInspection:
    """Inspect a regular file without copying or opening it for writing."""

    try:
        canonical_path = path.expanduser().resolve(strict=True)
    except FileNotFoundError as error:
        raise MediaProbeError(f"o arquivo não existe: {path}") from error
    except OSError as error:
        raise MediaProbeError(f"não foi possível acessar o arquivo: {path}") from error
    if not canonical_path.is_file():
        raise MediaProbeError(f"o caminho não é um arquivo regular: {canonical_path}")
    before = canonical_path.stat()
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_format",
        "-show_streams",
        "-of",
        "json",
        str(canonical_path),
    ]
    try:
        result = runner(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise MediaProbeError("ffprobe excedeu o limite de tempo") from error
    except OSError as error:
        raise MediaProbeError(f"não foi possível executar ffprobe: {error}") from error
    if result.returncode != 0:
        detail = result.stderr.strip() or "erro sem detalhes"
        raise MediaProbeError(f"ffprobe rejeitou o arquivo: {detail}")
    try:
        probe_data = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise MediaProbeError("ffprobe retornou JSON inválido") from error
    if not isinstance(probe_data, dict):
        raise MediaProbeError("ffprobe retornou uma estrutura inesperada")

    after = canonical_path.stat()
    identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if identity_after != identity_before:
        raise MediaProbeError("o arquivo mudou durante a inspeção")

    streams = probe_data.get("streams", [])
    if not isinstance(streams, list):
        raise MediaProbeError("ffprobe retornou uma lista de streams inválida")
    video = next(
        (stream for stream in streams if stream.get("codec_type") == "video"), None
    )
    if video is None:
        raise MediaProbeError("o arquivo não contém stream de vídeo")
    audio = next(
        (stream for stream in streams if stream.get("codec_type") == "audio"), None
    )
    format_data = probe_data.get("format", {})
    if not isinstance(format_data, dict):
        format_data = {}
    width = _optional_int(video.get("width"))
    height = _optional_int(video.get("height"))
    if width is None or height is None or width <= 0 or height <= 0:
        raise MediaProbeError("o stream de vídeo não possui dimensões válidas")
    nominal_rate = _rate(video.get("r_frame_rate"))
    average_rate = _rate(video.get("avg_frame_rate"))
    if nominal_rate is None or average_rate is None:
        frame_rate_mode = "unknown"
    elif nominal_rate == average_rate:
        frame_rate_mode = "constant"
    else:
        frame_rate_mode = "variable"

    return SourceInspection(
        path=canonical_path,
        device=before.st_dev,
        inode=before.st_ino,
        size_bytes=before.st_size,
        modified_at_ns=before.st_mtime_ns,
        format_name=str(format_data.get("format_name", "unknown")),
        duration_us=_duration_us(video.get("duration"), format_data.get("duration")),
        video_codec=str(video.get("codec_name", "unknown")),
        width=width,
        height=height,
        nominal_frame_rate=nominal_rate,
        average_frame_rate=average_rate,
        frame_rate_mode=frame_rate_mode,
        audio_codec=None if audio is None else audio.get("codec_name"),
        sample_rate=None if audio is None else _optional_int(audio.get("sample_rate")),
        channels=None if audio is None else _optional_int(audio.get("channels")),
        probe_json=json.dumps(
            probe_data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ),
    )
