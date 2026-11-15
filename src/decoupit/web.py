"""Local HTTP application for DecoupIt."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from html import escape
from importlib.metadata import version
from typing import Annotated

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.base import RequestResponseEndpoint
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import Response

from decoupit.database import connect_database, initialize_database
from decoupit.job_store import recover_incomplete_jobs
from decoupit.paths import AppPaths, resolve_app_paths
from decoupit.projects import Project, create_project, list_projects


class ProjectInput(BaseModel):
    name: Annotated[str, Field(max_length=200)]


class ProjectOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    status: str
    created_at: str
    updated_at: str


def create_app(paths: AppPaths | None = None) -> FastAPI:
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

    return app
