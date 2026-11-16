from decoupit.review_exports import render_review_csv
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
