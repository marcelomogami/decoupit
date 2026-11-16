"""Audit exports for manual review decisions."""

from __future__ import annotations

import csv
import json
from collections.abc import Sequence
from io import StringIO

from decoupit.review_categories import review_category
from decoupit.review_intervals import ReviewInterval
from decoupit.timing import frame_start_us

_CLASSIFICATION_LABELS = {
    None: "sem classificação",
    "primary": "principal",
    "alternative": "alternativa",
    "blooper": "blooper",
    "discard": "descarte",
}


def render_review_csv(intervals: Sequence[ReviewInterval]) -> str:
    """Render manual review intervals as an auditable UTF-8 CSV document."""

    output = StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        (
            "id_intervalo",
            "quadro_entrada",
            "quadro_saida",
            "inicio_us",
            "fim_exclusivo_us",
            "duracao_quadros",
            "classificacao",
        )
    )
    for interval in intervals:
        writer.writerow(
            (
                interval.id,
                interval.start_frame,
                interval.end_frame,
                frame_start_us(interval.start_frame),
                frame_start_us(interval.end_frame + 1),
                interval.end_frame - interval.start_frame + 1,
                _CLASSIFICATION_LABELS[interval.classification],
            )
        )
    return output.getvalue()


def render_review_markers_json(
    normalized_media_id: str, intervals: Sequence[ReviewInterval]
) -> str:
    """Render manual decisions as frame-accurate, neutral JSON markers."""

    markers: list[dict[str, str | int | None]] = []
    for interval in intervals:
        category = review_category(interval.classification)
        marker: dict[str, str | int | dict[str, str] | None] = {
            "id": interval.id,
            "kind": (
                "point" if interval.start_frame == interval.end_frame else "interval"
            ),
            "classification": interval.classification,
            "category": {
                "key": category.key,
                "label": category.label,
                "color": category.color,
            },
        }
        if interval.start_frame == interval.end_frame:
            marker["frame"] = interval.start_frame
        else:
            marker["start_frame"] = interval.start_frame
            marker["end_frame"] = interval.end_frame
        markers.append(marker)
    document = {
        "format": "decoupit.review-markers/v1",
        "normalized_media_id": normalized_media_id,
        "frame_rate": {"numerator": 30, "denominator": 1},
        "markers": markers,
    }
    return json.dumps(document, ensure_ascii=False, indent=2) + "\n"
