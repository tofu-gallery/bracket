# Modified by Tofu on 2026-10-25 (https://github.com/tofu-gallery/bracket): logos are also kept in the database,
# the demo-account cleanup runs only while demo accounts can be made, and the API docs link this copy's source.
# Modified by Tofu on 2026-10-26: the start's schema work runs once, under one lock, with row-level security on every
# table. See TOFU.md.
import glob
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from starlette.exceptions import HTTPException
from starlette.middleware.base import RequestResponseEndpoint
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse, Response
from starlette.staticfiles import StaticFiles

from bracket.config import Environment, config, environment, init_sentry
from bracket.cronjobs.scheduling import start_cronjobs
from bracket.database import database
from bracket.models.metrics import RequestDefinition, get_request_metrics
from bracket.routes import (
    auth,
    clubs,
    courts,
    internals,
    matches,
    players,
    rankings,
    rounds,
    stage_item_inputs,
    stage_items,
    stages,
    teams,
    tournaments,
    users,
)
from bracket.utils.asyncio import AsyncioTasksManager
from bracket.utils.logging import logger
from bracket.utils.tofu_logos import delete_unused_logos, serve_logo
from bracket.utils.tofu_schema import prepare_schema

init_sentry()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await database.connect()

    # Tofu (2026-10-26): upstream's init_db_when_empty() and alembic_run_migrations(), and Tofu's logo table, run in
    # one transaction under one lock, so that several starts at once do the work once, followed by row-level security
    # on every table (bracket/utils/tofu_schema.py).
    prepare_schema()

    # Tofu (2026-10-25): logos no team or tournament names (bracket/utils/tofu_logos.py).
    await delete_unused_logos()

    # Tofu (2026-10-25): the only cron job deletes expired demo accounts, so it runs only while they can be made.
    if environment is Environment.PRODUCTION and config.allow_demo_user_registration:
        start_cronjobs()

    if environment is Environment.PRODUCTION and not config.is_cors_enabled():
        logger.warning("It's advised to set the `CORS_ORIGINS` environment variable in production")

    yield

    if environment is not Environment.CI:
        await database.disconnect()

    await AsyncioTasksManager.gather()


routers = {
    "Auth": auth.router,
    "Clubs": clubs.router,
    "Courts": courts.router,
    "Internals": internals.router,
    "Matches": matches.router,
    "Players": players.router,
    "Rankings": rankings.router,
    "Rounds": rounds.router,
    "Stage Items": stage_items.router,
    "Stage Item Inputs": stage_item_inputs.router,
    "Stages": stages.router,
    "Teams": teams.router,
    "Tournaments": tournaments.router,
    "Users": users.router,
}

table_of_contents = "\n\n".join(
    [f"- [{tag}](#tag/{tag.replace(' ', '-')})" for tag in routers.keys()]
)


description = f"""
### Description
This API allows you to do everything the frontend of [Bracket](https://github.com/evroon/bracket)
allows you to do (the frontend uses this API as well).

Fore more information, see the [documentation](https://docs.bracketapp.nl).

### Table of Contents
*(links only work for [ReDoc](https://api.bracketapp.nl/redoc), not for Swagger UI)*

{table_of_contents}

### Links
Source code of this copy: <{config.source_url}>

Upstream project: <https://github.com/evroon/bracket>

Docs: <https://docs.bracketapp.nl>

Demo: <https://www.bracketapp.nl/demo>

API docs (Redoc): <https://api.bracketapp.nl/redoc>

API docs (Swagger UI): <https://api.bracketapp.nl/docs>
"""

app = FastAPI(
    title="Bracket API",
    docs_url="/docs",
    version="1.0.0",
    lifespan=lifespan,
    summary="API for Bracket, an open source tournament system.",
    description=description,
    license_info={
        "name": "AGPL-3.0",
        "url": "https://www.gnu.org/licenses/agpl-3.0.en.html",
    },
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins,
    allow_origin_regex=config.cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_process_time_header(request: Request, call_next: RequestResponseEndpoint) -> Response:
    start_time = time.time()
    request_metrics = get_request_metrics()
    request_metrics.request_count[RequestDefinition.from_request(request)] += 1
    response = await call_next(request)
    process_time = time.time() - start_time
    request_metrics.response_time[RequestDefinition.from_request(request)] = process_time
    return response


@app.exception_handler(HTTPException)
async def validation_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse({"detail": "Internal server error"}, status_code=500)




# Tofu (2026-10-25): logos come from this server's disk when it has them, else from the database. Registered before
# the static mount so that it answers first.
@app.get(f"{config.api_prefix}/static/{{folder}}/{{filename}}", include_in_schema=False)
async def logo(folder: str, filename: str) -> Response:
    return await serve_logo(folder, filename)


app.mount(f"{config.api_prefix}/static", StaticFiles(directory="static"), name="static")

for tag, router in routers.items():
    assert router.prefix == config.api_prefix, f"Prefix not set on router with tag `{tag}`"
    app.include_router(router, tags=[tag])

if config.serve_frontend:
    msg = "API_PREFIX env var must be set (e.g. `/api`) when serving the frontend"
    assert config.api_prefix.startswith("/"), msg

    frontend_root = Path("frontend-dist")
    allowed_paths = list(glob.iglob("frontend-dist/**/*", recursive=True))

    @app.get("/{full_path:path}")
    async def frontend(full_path: str) -> FileResponse:
        path = frontend_root / Path(full_path)

        # Checking `str(path) in allowed_paths` should be enough here but we check for more cases
        # to be sure and avoid AI tools raising false positives.
        if (
            path.exists()
            and path.is_file()
            and str(path) in allowed_paths
            and frontend_root in path.parents
        ):
            return FileResponse(path)

        return FileResponse(frontend_root / Path("index.html"))
