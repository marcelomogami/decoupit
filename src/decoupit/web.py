"""Local HTTP application for DecoupIt."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from html import escape
from importlib.metadata import version

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from decoupit.database import connect_database, initialize_database
from decoupit.job_store import recover_incomplete_jobs
from decoupit.paths import AppPaths, resolve_app_paths


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

    return app
