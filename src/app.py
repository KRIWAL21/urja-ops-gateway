"""
Application factory for the Urja Ops Gateway.

Wires together:
  - FastAPI app with OpenAPI metadata
  - Lifespan context that creates / tears down the portal client
  - API router mounted at /v1
  - Scalar UI served at /docs (interactive OpenAPI explorer)
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .portal_client import PortalClient
from .routes import router

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the portal client on startup; shut it down on shutdown."""
    client = PortalClient()
    app.state.portal_client = client
    await client.start()
    logger.info("Gateway ready on port %d", settings.port)
    yield
    await client.stop()
    logger.info("Gateway shut down")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Urja Ops Gateway",
        summary="A clean REST API over the Urja Meter Ops portal.",
        description=(
            "Exposes meter data, distribution-transformer information, GPS locations, "
            "and 30-minute consumption readings — all sourced from the Urja Meter Ops "
            "web portal via authenticated scraping. "
            "See **PROTOCOL.md** in the repository for a full description of how the "
            "portal works under the hood."
        ),
        version="1.0.0",
        contact={"name": "Flock Energy Assignment", "url": "https://flockenergy.tech"},
        license_info={"name": "Private"},
        lifespan=lifespan,
        docs_url=None,       # We serve Scalar below
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # Allow any origin for local/dev use; tighten in production.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    app.include_router(router, prefix="/v1")

    # Scalar interactive docs at /docs
    @app.get("/docs", include_in_schema=False)
    async def scalar_ui():
        from fastapi.responses import HTMLResponse
        return HTMLResponse(
            """<!doctype html>
<html>
<head>
  <title>Urja Ops Gateway — API Docs</title>
  <meta charset="utf-8"/>
</head>
<body>
  <script
    id="api-reference"
    data-url="/openapi.json"
    src="https://cdn.jsdelivr.net/npm/@scalar/api-reference"></script>
</body>
</html>"""
        )

    return app


app = create_app()
