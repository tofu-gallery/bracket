# Modified by Tofu on 2026-10-25 (https://github.com/tofu-gallery/bracket): adds GET <API_PREFIX>/source, which
# redirects to this copy's source code. See TOFU.md.
from fastapi import APIRouter
from fastapi.responses import PlainTextResponse, RedirectResponse

from bracket.config import config
from bracket.models.metrics import get_request_metrics

router = APIRouter(prefix=config.api_prefix)


@router.get("/metrics", response_class=PlainTextResponse)
async def get_metrics() -> PlainTextResponse:
    return PlainTextResponse(get_request_metrics().to_prometheus())


@router.get("/ping", summary="Healthcheck ping")
async def ping() -> str:
    return "ping"


@router.get("/source", summary="Source code of this copy", response_class=RedirectResponse)
async def source() -> RedirectResponse:
    # Tofu (2026-10-25): the "Source code" links in the frontend open this address, which redirects to SOURCE_URL,
    # so that everyone who uses the app can get its source code (AGPL-3.0 section 13).
    return RedirectResponse(config.source_url, status_code=302)
