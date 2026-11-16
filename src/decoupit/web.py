"""Local HTTP application for DecoupIt."""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from html import escape
from importlib.metadata import version
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.base import RequestResponseEndpoint
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import Response
from starlette.staticfiles import StaticFiles

from decoupit.database import connect_database, initialize_database
from decoupit.job_store import (
    Job,
    enqueue_job,
    find_active_source_job,
    get_job,
    recover_incomplete_jobs,
)
from decoupit.jobs import JobState
from decoupit.media import MediaProbeError, SourceInspection, probe_source
from decoupit.normalization import (
    NormalizedMedia,
    get_normalized_media,
    get_normalized_media_by_id,
)
from decoupit.paths import AppPaths, resolve_app_paths
from decoupit.projects import Project, create_project, get_project, list_projects
from decoupit.review_intervals import (
    ReviewInterval,
    ReviewIntervalError,
    create_review_interval,
    delete_review_interval,
    list_review_intervals,
    update_review_interval,
)
from decoupit.sources import (
    SourceMedia,
    create_source,
    get_source,
    list_sources,
)
from decoupit.subtitles import render_srt
from decoupit.transcripts import (
    TranscriptDocument,
    TranscriptionRun,
    current_profile_hash,
    get_transcript_document,
    get_transcription_run,
    get_transcription_run_by_id,
)
from decoupit.waveform import (
    Waveform,
    get_waveform,
    get_waveform_by_id,
)


class ProjectInput(BaseModel):
    name: Annotated[str, Field(max_length=200)]


class ProjectOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    status: str
    created_at: str
    updated_at: str


class SourceInput(BaseModel):
    path: Path


class SourceOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    path: Path
    size_bytes: int
    duration_us: int | None
    video_codec: str
    width: int
    height: int
    frame_rate_mode: str
    audio_codec: str | None
    sample_rate: int | None
    channels: int | None
    created_at: str


class JobOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: str
    state: JobState
    attempt: int
    error_message: str | None


class NormalizedMediaOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_id: str
    path: Path
    size_bytes: int
    duration_us: int
    frame_count: int | None
    video_codec: str
    created_at: str


class WaveformOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    normalized_media_id: str
    size_bytes: int
    point_count: int
    sample_rate: int
    samples_per_point: int
    format_version: int
    created_at: str


class TranscriptionOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    normalized_media_id: str
    language: str
    language_probability: float
    duration_us: int
    duration_after_vad_us: int
    segment_count: int
    word_count: int
    created_at: str


class TranscriptWordOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    start_us: int
    end_us: int
    text: str
    probability: float


class TranscriptSegmentOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    segment_index: int
    start_us: int
    end_us: int
    text: str
    words: tuple[TranscriptWordOutput, ...]


class TranscriptDocumentOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    transcription_run_id: str
    language: str
    segments: tuple[TranscriptSegmentOutput, ...]


class ReviewIntervalInput(BaseModel):
    start_frame: Annotated[int, Field(strict=True, ge=0)]
    end_frame: Annotated[int, Field(strict=True, ge=0)]
    classification: Literal["primary", "alternative", "blooper", "discard"] | None = (
        None
    )


class ReviewIntervalOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    normalized_media_id: str
    start_frame: int
    end_frame: int
    classification: Literal["primary", "alternative", "blooper", "discard"] | None
    created_at: str
    updated_at: str


def create_app(
    paths: AppPaths | None = None,
    media_probe: Callable[[Path], SourceInspection] = probe_source,
) -> FastAPI:
    """Build the application without starting a server."""

    app_paths = resolve_app_paths() if paths is None else paths
    package_version = version("decoupit")

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        app_paths.create_directories()
        initialize_database(app_paths.database)
        with connect_database(app_paths.database) as connection:
            recover_incomplete_jobs(connection)
        yield

    app = FastAPI(
        title="DecoupIt",
        version=package_version,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )
    app.state.paths = app_paths
    app.mount(
        "/static",
        StaticFiles(directory=Path(__file__).with_name("static")),
        name="static",
    )
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["127.0.0.1", "localhost", "testserver"],
    )

    def review_media(
        connection: sqlite3.Connection, project_id: str, source_id: str
    ) -> tuple[NormalizedMedia, int]:
        try:
            source = get_source(connection, source_id)
        except KeyError as error:
            raise HTTPException(
                status_code=404, detail="mídia de origem não encontrada"
            ) from error
        if source.project_id != project_id:
            raise HTTPException(
                status_code=404, detail="mídia de origem não encontrada"
            )
        normalized = get_normalized_media(connection, source_id)
        if normalized is None:
            raise HTTPException(
                status_code=409, detail="a normalização precisa terminar primeiro"
            )
        frame_count = normalized.frame_count or max(
            1, (normalized.duration_us * 30 + 999_999) // 1_000_000
        )
        return normalized, frame_count

    @app.middleware("http")
    async def validate_origin(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            expected_origin = (
                f"{request.url.scheme}://{request.headers.get('host', '')}"
            )
            if origin is not None and origin != expected_origin:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "origem não autorizada"},
                )
        return await call_next(request)

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def status_page() -> str:
        safe_version = escape(package_version)
        return f"""<!doctype html>
<html lang="pt-BR">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>DecoupIt</title>
  </head>
  <body>
    <main>
      <h1>DecoupIt</h1>
      <p>Aplicação local pronta.</p>
      <p>Versão {safe_version}</p>
    </main>
  </body>
</html>"""

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ready", "version": package_version}

    @app.get("/api/projects", response_model=list[ProjectOutput])
    def projects_index() -> list[Project]:
        with connect_database(app_paths.database) as connection:
            return list_projects(connection)

    @app.post("/api/projects", response_model=ProjectOutput, status_code=201)
    def projects_create(project_input: ProjectInput) -> Project:
        try:
            with connect_database(app_paths.database) as connection:
                return create_project(connection, name=project_input.name)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/api/projects/{project_id}/sources", response_model=list[SourceOutput])
    def sources_index(project_id: str) -> list[SourceMedia]:
        with connect_database(app_paths.database) as connection:
            try:
                get_project(connection, project_id)
            except KeyError as error:
                raise HTTPException(
                    status_code=404, detail="projeto não encontrado"
                ) from error
            return list_sources(connection, project_id)

    @app.post(
        "/api/projects/{project_id}/sources",
        response_model=SourceOutput,
        status_code=201,
    )
    def sources_create(project_id: str, source_input: SourceInput) -> SourceMedia:
        if not source_input.path.is_absolute():
            raise HTTPException(status_code=422, detail="o caminho deve ser absoluto")
        with connect_database(app_paths.database) as connection:
            try:
                get_project(connection, project_id)
            except KeyError as error:
                raise HTTPException(
                    status_code=404, detail="projeto não encontrado"
                ) from error
        try:
            inspection = media_probe(source_input.path)
        except MediaProbeError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        try:
            with connect_database(app_paths.database) as connection:
                return create_source(connection, project_id, inspection)
        except sqlite3.IntegrityError as error:
            raise HTTPException(
                status_code=409,
                detail="a mídia já está cadastrada neste projeto",
            ) from error

    @app.post(
        "/api/projects/{project_id}/sources/{source_id}/normalization",
        response_model=JobOutput,
        status_code=202,
    )
    def normalization_create(project_id: str, source_id: str) -> Job:
        with connect_database(app_paths.database) as connection:
            try:
                source = get_source(connection, source_id)
            except KeyError as error:
                raise HTTPException(
                    status_code=404, detail="mídia de origem não encontrada"
                ) from error
            if source.project_id != project_id:
                raise HTTPException(
                    status_code=404, detail="mídia de origem não encontrada"
                )
            if get_normalized_media(connection, source_id) is not None:
                raise HTTPException(
                    status_code=409, detail="a mídia já possui versão normalizada"
                )
            active_job = find_active_source_job(
                connection, "media.normalize_cfr30", source_id
            )
            if active_job is not None:
                return active_job
            try:
                job_id = enqueue_job(
                    connection,
                    kind="media.normalize_cfr30",
                    payload={"source_id": source_id},
                    project_id=project_id,
                )
            except sqlite3.IntegrityError:
                active_job = find_active_source_job(
                    connection, "media.normalize_cfr30", source_id
                )
                if active_job is None:
                    raise
                return active_job
            return get_job(connection, job_id)

    @app.get("/api/jobs/{job_id}", response_model=JobOutput)
    def jobs_show(job_id: str) -> Job:
        with connect_database(app_paths.database) as connection:
            try:
                return get_job(connection, job_id)
            except KeyError as error:
                raise HTTPException(
                    status_code=404, detail="job não encontrado"
                ) from error

    @app.get(
        "/api/projects/{project_id}/sources/{source_id}/normalization",
        response_model=NormalizedMediaOutput,
    )
    def normalization_show(project_id: str, source_id: str) -> NormalizedMedia:
        with connect_database(app_paths.database) as connection:
            try:
                source = get_source(connection, source_id)
            except KeyError as error:
                raise HTTPException(
                    status_code=404, detail="mídia de origem não encontrada"
                ) from error
            if source.project_id != project_id:
                raise HTTPException(
                    status_code=404, detail="mídia de origem não encontrada"
                )
            normalized = get_normalized_media(connection, source_id)
            if normalized is None:
                raise HTTPException(
                    status_code=404, detail="mídia normalizada ainda não disponível"
                )
            return normalized

    @app.get(
        "/api/normalized-media/{normalized_media_id}/content",
        response_class=FileResponse,
    )
    def normalized_media_content(normalized_media_id: str) -> FileResponse:
        with connect_database(app_paths.database) as connection:
            try:
                normalized = get_normalized_media_by_id(connection, normalized_media_id)
            except KeyError as error:
                raise HTTPException(
                    status_code=404, detail="mídia normalizada não encontrada"
                ) from error
        if not normalized.path.is_file():
            raise HTTPException(
                status_code=404, detail="mídia normalizada não encontrada"
            )
        if normalized.path.stat().st_size != normalized.size_bytes:
            raise HTTPException(
                status_code=409, detail="a mídia normalizada mudou no disco"
            )
        return FileResponse(
            normalized.path,
            media_type="video/mp4",
            headers={"Cache-Control": "no-store"},
        )

    @app.get(
        "/projects/{project_id}/sources/{source_id}/review",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def source_review(project_id: str, source_id: str) -> str:
        with connect_database(app_paths.database) as connection:
            try:
                project = get_project(connection, project_id)
                source = get_source(connection, source_id)
            except KeyError as error:
                raise HTTPException(
                    status_code=404, detail="projeto ou mídia não encontrado"
                ) from error
            if source.project_id != project.id:
                raise HTTPException(
                    status_code=404, detail="projeto ou mídia não encontrado"
                )
            normalized = get_normalized_media(connection, source_id)
            if normalized is None:
                raise HTTPException(
                    status_code=409, detail="a normalização precisa terminar primeiro"
                )
            waveform = get_waveform(connection, normalized.id)
            transcription = get_transcription_run(connection, normalized.id)
        safe_project_name = escape(project.name)
        safe_source_name = escape(source.path.name)
        media_url = f"/api/normalized-media/{normalized.id}/content"
        waveform_url = (
            f"/api/waveforms/{waveform.id}/data"
            if waveform is not None and waveform.path.is_file()
            else ""
        )
        transcript_url = (
            f"/api/transcriptions/{transcription.id}/content"
            if transcription is not None and transcription.raw_output_path.is_file()
            else ""
        )
        review_intervals_url = (
            f"/api/projects/{project.id}/sources/{source.id}/review-intervals"
        )
        subtitle_link = (
            f'<a class="transcript-download" '
            f'href="/api/transcriptions/{transcription.id}/subtitles.srt" '
            f'download="transcript.srt">Baixar SRT</a>'
            if transcript_url
            else ""
        )
        duration = normalized.duration_us / 1_000_000
        size_megabytes = normalized.size_bytes / 1_000_000
        frame_count = normalized.frame_count or max(
            1, (normalized.duration_us * 30 + 999_999) // 1_000_000
        )
        return f"""<!doctype html>
<html lang="pt-BR">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Revisão · {safe_project_name} · DecoupIt</title>
    <link rel="stylesheet" href="/static/review.css">
    <script src="/static/review.js" defer></script>
  </head>
  <body data-fps="30" data-frame-count="{frame_count}"
        data-waveform-url="{waveform_url}"
        data-transcript-url="{transcript_url}"
        data-review-intervals-url="{review_intervals_url}">
    <main>
      <h1>{safe_project_name}</h1>
      <p class="meta">
        {safe_source_name} · {duration:.3f} s · {size_megabytes:.1f} MB
      </p>
      <div class="review-grid">
        <div class="media-column">
          <video id="player" controls playsinline preload="metadata"
                 src="{media_url}"></video>
        </div>
        <aside class="transcript-panel" aria-label="Transcrição">
          <div class="transcript-heading">
            <h2>Transcrição</h2>
            <div class="transcript-actions">
              <span id="transcript-language"></span>
              {subtitle_link}
            </div>
          </div>
          <form id="transcript-search" role="search">
            <label class="visually-hidden" for="transcript-query">
              Buscar na transcrição
            </label>
            <input id="transcript-query" type="search"
                   placeholder="Buscar na transcrição" autocomplete="off">
            <button id="previous-match" type="button" disabled
                    aria-label="Resultado anterior">↑</button>
            <button id="next-match" type="submit" disabled
                    aria-label="Próximo resultado">↓</button>
            <output id="match-count" for="transcript-query"></output>
          </form>
          <div id="transcript" aria-live="off">
            <p id="transcript-message">Carregando transcrição...</p>
          </div>
        </aside>
      </div>
      <div class="position" aria-live="polite">
        <span id="frame-position">Quadro 0 de {frame_count - 1}</span>
        <span id="time-position">00:00:00.000</span>
      </div>
      <div class="waveform-shell">
        <canvas id="waveform" hidden tabindex="0" role="slider"
                aria-label="Posição no áudio" aria-valuemin="0"
                aria-valuemax="{frame_count - 1}" aria-valuenow="0"></canvas>
        <p id="waveform-message">Carregando waveform...</p>
      </div>
      <section class="review-intervals" aria-labelledby="review-intervals-title">
        <div class="review-intervals-heading">
          <h2 id="review-intervals-title">Intervalos manuais</h2>
          <div class="interval-controls">
            <button id="mark-interval-start" type="button">Marcar entrada</button>
            <button id="create-review-interval" type="button" disabled>
              Criar até o quadro atual
            </button>
          </div>
        </div>
        <output id="interval-pending">Nenhuma entrada marcada.</output>
        <p id="interval-message" role="status"></p>
        <ol id="review-interval-list"></ol>
      </section>
      <p id="status">Carregando metadados do vídeo...</p>
    </main>
  </body>
</html>"""

    @app.post(
        "/api/projects/{project_id}/sources/{source_id}/waveform",
        response_model=JobOutput,
        status_code=202,
    )
    def waveform_create(project_id: str, source_id: str) -> Job:
        with connect_database(app_paths.database) as connection:
            try:
                source = get_source(connection, source_id)
            except KeyError as error:
                raise HTTPException(
                    status_code=404, detail="mídia de origem não encontrada"
                ) from error
            if source.project_id != project_id:
                raise HTTPException(
                    status_code=404, detail="mídia de origem não encontrada"
                )
            normalized = get_normalized_media(connection, source_id)
            if normalized is None:
                raise HTTPException(
                    status_code=409, detail="a normalização precisa terminar primeiro"
                )
            existing = get_waveform(connection, normalized.id)
            if existing is not None and existing.path.is_file():
                raise HTTPException(
                    status_code=409, detail="a mídia já possui waveform"
                )
            active_job = find_active_source_job(
                connection, "media.generate_waveform", source_id
            )
            if active_job is not None:
                return active_job
            try:
                job_id = enqueue_job(
                    connection,
                    kind="media.generate_waveform",
                    payload={"source_id": source_id},
                    project_id=project_id,
                )
            except sqlite3.IntegrityError:
                active_job = find_active_source_job(
                    connection, "media.generate_waveform", source_id
                )
                if active_job is None:
                    raise
                return active_job
            return get_job(connection, job_id)

    @app.get(
        "/api/projects/{project_id}/sources/{source_id}/waveform",
        response_model=WaveformOutput,
    )
    def waveform_show(project_id: str, source_id: str) -> Waveform:
        with connect_database(app_paths.database) as connection:
            try:
                source = get_source(connection, source_id)
            except KeyError as error:
                raise HTTPException(
                    status_code=404, detail="mídia de origem não encontrada"
                ) from error
            if source.project_id != project_id:
                raise HTTPException(
                    status_code=404, detail="mídia de origem não encontrada"
                )
            normalized = get_normalized_media(connection, source_id)
            waveform = (
                None if normalized is None else get_waveform(connection, normalized.id)
            )
            if waveform is None or not waveform.path.is_file():
                raise HTTPException(
                    status_code=404, detail="waveform ainda não disponível"
                )
            return waveform

    @app.get("/api/waveforms/{waveform_id}/data", response_class=FileResponse)
    def waveform_data(waveform_id: str) -> FileResponse:
        with connect_database(app_paths.database) as connection:
            try:
                waveform = get_waveform_by_id(connection, waveform_id)
            except KeyError as error:
                raise HTTPException(
                    status_code=404, detail="waveform não encontrado"
                ) from error
        if not waveform.path.is_file():
            raise HTTPException(status_code=404, detail="waveform não encontrado")
        return FileResponse(waveform.path, media_type="application/json")

    @app.post(
        "/api/projects/{project_id}/sources/{source_id}/transcription",
        response_model=JobOutput,
        status_code=202,
    )
    def transcription_create(project_id: str, source_id: str) -> Job:
        with connect_database(app_paths.database) as connection:
            try:
                source = get_source(connection, source_id)
            except KeyError as error:
                raise HTTPException(
                    status_code=404, detail="mídia de origem não encontrada"
                ) from error
            if source.project_id != project_id:
                raise HTTPException(
                    status_code=404, detail="mídia de origem não encontrada"
                )
            normalized = get_normalized_media(connection, source_id)
            if normalized is None:
                raise HTTPException(
                    status_code=409, detail="a normalização precisa terminar primeiro"
                )
            existing = get_transcription_run(
                connection, normalized.id, current_profile_hash()
            )
            if existing is not None:
                raise HTTPException(
                    status_code=409, detail="a mídia já possui esta transcrição"
                )
            active_job = find_active_source_job(
                connection, "media.transcribe_words", source_id
            )
            if active_job is not None:
                return active_job
            try:
                job_id = enqueue_job(
                    connection,
                    kind="media.transcribe_words",
                    payload={"source_id": source_id},
                    project_id=project_id,
                )
            except sqlite3.IntegrityError:
                active_job = find_active_source_job(
                    connection, "media.transcribe_words", source_id
                )
                if active_job is None:
                    raise
                return active_job
            return get_job(connection, job_id)

    @app.get(
        "/api/projects/{project_id}/sources/{source_id}/transcription",
        response_model=TranscriptionOutput,
    )
    def transcription_show(project_id: str, source_id: str) -> TranscriptionRun:
        with connect_database(app_paths.database) as connection:
            try:
                source = get_source(connection, source_id)
            except KeyError as error:
                raise HTTPException(
                    status_code=404, detail="mídia de origem não encontrada"
                ) from error
            if source.project_id != project_id:
                raise HTTPException(
                    status_code=404, detail="mídia de origem não encontrada"
                )
            normalized = get_normalized_media(connection, source_id)
            transcription = (
                None
                if normalized is None
                else get_transcription_run(connection, normalized.id)
            )
            if transcription is None:
                raise HTTPException(
                    status_code=404, detail="transcrição ainda não disponível"
                )
            if not transcription.raw_output_path.is_file():
                raise HTTPException(
                    status_code=409, detail="o JSON bruto da transcrição está ausente"
                )
            return transcription

    @app.get(
        "/api/transcriptions/{transcription_run_id}/content",
        response_model=TranscriptDocumentOutput,
    )
    def transcription_content(transcription_run_id: str) -> TranscriptDocument:
        with connect_database(app_paths.database) as connection:
            try:
                run = get_transcription_run_by_id(connection, transcription_run_id)
                document = get_transcript_document(connection, transcription_run_id)
            except KeyError as error:
                raise HTTPException(
                    status_code=404, detail="transcrição não encontrada"
                ) from error
        if not run.raw_output_path.is_file():
            raise HTTPException(
                status_code=409, detail="o JSON bruto da transcrição está ausente"
            )
        return document

    @app.get("/api/transcriptions/{transcription_run_id}/subtitles.srt")
    def transcription_subtitles(transcription_run_id: str) -> Response:
        with connect_database(app_paths.database) as connection:
            try:
                run = get_transcription_run_by_id(connection, transcription_run_id)
                document = get_transcript_document(connection, transcription_run_id)
            except KeyError as error:
                raise HTTPException(
                    status_code=404, detail="transcrição não encontrada"
                ) from error
        if not run.raw_output_path.is_file():
            raise HTTPException(
                status_code=409, detail="o JSON bruto da transcrição está ausente"
            )
        return Response(
            render_srt(document),
            media_type="application/x-subrip; charset=utf-8",
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": 'attachment; filename="transcript.srt"',
            },
        )

    @app.get(
        "/api/projects/{project_id}/sources/{source_id}/review-intervals",
        response_model=list[ReviewIntervalOutput],
    )
    def review_interval_list(project_id: str, source_id: str) -> list[ReviewInterval]:
        with connect_database(app_paths.database) as connection:
            normalized, _ = review_media(connection, project_id, source_id)
            return list_review_intervals(connection, normalized.id)

    @app.post(
        "/api/projects/{project_id}/sources/{source_id}/review-intervals",
        response_model=ReviewIntervalOutput,
        status_code=201,
    )
    def review_interval_create(
        project_id: str,
        source_id: str,
        interval: ReviewIntervalInput,
    ) -> ReviewInterval:
        with connect_database(app_paths.database) as connection:
            normalized, frame_count = review_media(connection, project_id, source_id)
            try:
                return create_review_interval(
                    connection,
                    normalized.id,
                    start_frame=interval.start_frame,
                    end_frame=interval.end_frame,
                    frame_count=frame_count,
                    classification=interval.classification,
                )
            except ReviewIntervalError as error:
                raise HTTPException(status_code=422, detail=str(error)) from error

    @app.patch(
        "/api/projects/{project_id}/sources/{source_id}/review-intervals/{interval_id}",
        response_model=ReviewIntervalOutput,
    )
    def review_interval_update(
        project_id: str,
        source_id: str,
        interval_id: str,
        interval: ReviewIntervalInput,
    ) -> ReviewInterval:
        with connect_database(app_paths.database) as connection:
            normalized, frame_count = review_media(connection, project_id, source_id)
            try:
                return update_review_interval(
                    connection,
                    normalized.id,
                    interval_id,
                    start_frame=interval.start_frame,
                    end_frame=interval.end_frame,
                    frame_count=frame_count,
                    classification=interval.classification,
                )
            except KeyError as error:
                raise HTTPException(
                    status_code=404, detail="intervalo não encontrado"
                ) from error
            except ReviewIntervalError as error:
                raise HTTPException(status_code=422, detail=str(error)) from error

    @app.delete(
        "/api/projects/{project_id}/sources/{source_id}/review-intervals/{interval_id}",
        status_code=204,
    )
    def review_interval_delete(
        project_id: str, source_id: str, interval_id: str
    ) -> Response:
        with connect_database(app_paths.database) as connection:
            normalized, _ = review_media(connection, project_id, source_id)
            if not delete_review_interval(connection, normalized.id, interval_id):
                raise HTTPException(status_code=404, detail="intervalo não encontrado")
        return Response(status_code=204)

    return app
