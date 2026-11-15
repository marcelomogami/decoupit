"""Local HTTP application for DecoupIt."""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from html import escape
from importlib.metadata import version
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.base import RequestResponseEndpoint
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import Response

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
from decoupit.normalization import NormalizedMedia, get_normalized_media
from decoupit.paths import AppPaths, resolve_app_paths
from decoupit.projects import Project, create_project, get_project, list_projects
from decoupit.sources import (
    SourceMedia,
    create_source,
    get_source,
    list_sources,
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
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["127.0.0.1", "localhost", "testserver"],
    )

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

    return app
