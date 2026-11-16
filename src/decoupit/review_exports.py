"""Audit exports for manual review decisions."""

from __future__ import annotations

import csv
from collections.abc import Sequence
from io import StringIO

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
