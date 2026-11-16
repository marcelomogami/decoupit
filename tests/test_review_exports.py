import json

from decoupit.review_exports import render_review_csv, render_review_markers_json
from decoupit.review_intervals import ReviewInterval


def _interval(
    identifier: str,
    start_frame: int,
    end_frame: int,
    classification: str | None,
) -> ReviewInterval:
    return ReviewInterval(
        id=identifier,
        normalized_media_id="normalized-1",
        start_frame=start_frame,
        end_frame=end_frame,
        classification=classification,
        created_at="2026-11-16T00:00:00.000Z",
        updated_at="2026-11-16T00:00:00.000Z",
    )


def test_render_review_csv_preserves_inclusive_frames_and_exact_times() -> None:
    rendered = render_review_csv(
        (
            _interval("first", 3, 8, "primary"),
            _interval("second", 1, 1, None),
        )
    )

    assert rendered == (
        "id_intervalo,quadro_entrada,quadro_saida,inicio_us,fim_exclusivo_us,"
        "duracao_quadros,classificacao\n"
        "first,3,8,100000,300000,6,principal\n"
        "second,1,1,33334,66667,1,sem classificação\n"
    )


def test_render_review_csv_uses_portuguese_classification_labels() -> None:
    rendered = render_review_csv(
        (
            _interval("alternative", 0, 0, "alternative"),
            _interval("blooper", 0, 0, "blooper"),
            _interval("discard", 0, 0, "discard"),
        )
    )

    assert [row.rsplit(",", 1)[-1] for row in rendered.strip().splitlines()[1:]] == [
        "alternativa",
        "blooper",
        "descarte",
    ]


def test_render_review_markers_uses_points_and_inclusive_intervals() -> None:
    rendered = json.loads(
        render_review_markers_json(
            "normalized-1",
            (
                _interval("point", 4, 4, None),
                _interval("interval", 8, 12, "primary"),
            ),
        )
    )

    assert rendered == {
        "format": "decoupit.review-markers/v1",
        "normalized_media_id": "normalized-1",
        "frame_rate": {"numerator": 30, "denominator": 1},
        "markers": [
            {
                "id": "point",
                "kind": "point",
                "frame": 4,
                "classification": None,
            },
            {
                "id": "interval",
                "kind": "interval",
                "start_frame": 8,
                "end_frame": 12,
                "classification": "primary",
            },
        ],
    }
