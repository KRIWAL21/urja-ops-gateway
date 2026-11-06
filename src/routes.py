"""
FastAPI route definitions for the Urja Ops Gateway.

All routes are mounted under /v1 by the main app.
"""

from __future__ import annotations

import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.responses import JSONResponse

from .models import (
    DTListResponse,
    HealthResponse,
    MeterConsumptionResponse,
    MeterDetailResponse,
    MeterGeoResponse,
    MeterListResponse,
)
from .transforms import (
    transform_dt_list,
    transform_meter_consumption,
    transform_meter_detail_from_export,
    transform_meter_geo,
    transform_meter_list,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Dependency: portal client from app state
# ---------------------------------------------------------------------------


def get_client(request: Request):
    return request.app.state.portal_client


ClientDep = Annotated[object, Depends(get_client)]


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    tags=["meta"],
)
async def health(client: ClientDep) -> HealthResponse:
    """Returns the gateway health and whether the portal session is active."""
    authenticated = client._client is not None
    return HealthResponse(
        status="ok" if authenticated else "degraded",
        portal_authenticated=authenticated,
    )


# ---------------------------------------------------------------------------
# Meters
# ---------------------------------------------------------------------------


@router.get(
    "/meters",
    response_model=MeterListResponse,
    summary="List / search meters",
    tags=["meters"],
)
async def list_meters(
    client: ClientDep,
    q: str = Query("", description="Search term — matches meter ID or serial number prefix"),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
) -> MeterListResponse:
    """
    Returns a paginated list of meters, optionally filtered by a search term.

    The search matches against meter ID and serial number.  
    Leave `q` blank to list all meters (20 per page).
    """
    try:
        raw = await client.search_meters(q=q, page=page)
    except Exception as exc:
        logger.error("Error fetching meters: %s", exc)
        raise HTTPException(status_code=502, detail="Portal request failed") from exc
    return transform_meter_list(raw, page)


@router.get(
    "/meters/{meter_id}",
    response_model=MeterDetailResponse,
    summary="Get meter detail",
    tags=["meters"],
)
async def get_meter(
    client: ClientDep,
    meter_id: str = Path(description="Meter ID, e.g. J100000"),
) -> MeterDetailResponse:
    """
    Returns the full nameplate, hierarchy, and geo location for a single meter.

    Uses the bulk-export endpoint (filtered client-side) which provides the
    richest data for a single meter in one request.

    **Design note:** The export endpoint is signed and returns all 403 meters
    at once, so this call is O(1) in portal round-trips when the cache is warm.
    For a production system with many concurrent callers you would add a local
    index built from the bulk export; see PROTOCOL.md for details.
    """
    # Strategy: use the signed export to get rich data for this meter.
    # We scan the export (all meters fit in one page) rather than making three
    # separate calls (search + geo + energy).
    try:
        export = await client.bulk_export(page=1)
    except Exception as exc:
        logger.error("Error fetching export for meter %s: %s", meter_id, exc)
        raise HTTPException(status_code=502, detail="Portal request failed") from exc

    meter_raw = next(
        (m for m in export.get("data", []) if m["meterId"] == meter_id), None
    )
    if meter_raw is None:
        raise HTTPException(status_code=404, detail=f"Meter {meter_id} not found")

    detail = transform_meter_detail_from_export(meter_raw)
    return MeterDetailResponse(data=detail)


@router.get(
    "/meters/{meter_id}/geo",
    response_model=MeterGeoResponse,
    summary="Get meter GPS location",
    tags=["meters"],
)
async def get_meter_geo(
    client: ClientDep,
    meter_id: str = Path(description="Meter ID, e.g. J100000"),
) -> MeterGeoResponse:
    """Returns the latitude and longitude of the meter's installation point."""
    try:
        raw = await client.get_meter_geo(meter_id)
    except Exception as exc:
        logger.error("Error fetching geo for %s: %s", meter_id, exc)
        raise HTTPException(status_code=502, detail="Portal request failed") from exc
    if "data" not in raw or not raw["data"]:
        raise HTTPException(status_code=404, detail=f"Geo data not found for {meter_id}")
    return transform_meter_geo(meter_id, raw)


@router.get(
    "/meters/{meter_id}/consumption",
    response_model=MeterConsumptionResponse,
    summary="Get meter consumption readings",
    tags=["meters"],
)
async def get_meter_consumption(
    client: ClientDep,
    meter_id: str = Path(description="Meter ID, e.g. J100000"),
) -> MeterConsumptionResponse:
    """
    Returns 30-minute interval energy readings for the meter.

    Fields per reading:
    - **timestamp** — local date/time string as returned by the portal
    - **kwh** — cumulative active energy (kWh)
    - **kvah** — cumulative apparent energy (kVAh)
    - **volt_r** — R-phase voltage (V)

    The portal returns readings for the last ~24 hours by default.  
    The number of readings and the time window are determined by the portal and
    cannot currently be changed via this gateway.
    """
    try:
        raw = await client.get_meter_energy(meter_id)
    except Exception as exc:
        logger.error("Error fetching energy for %s: %s", meter_id, exc)
        raise HTTPException(status_code=502, detail="Portal request failed") from exc
    return transform_meter_consumption(meter_id, raw)


# ---------------------------------------------------------------------------
# Distribution Transformers
# ---------------------------------------------------------------------------


@router.get(
    "/transformers",
    response_model=DTListResponse,
    summary="List distribution transformers",
    tags=["transformers"],
)
async def list_transformers(
    client: ClientDep,
    page: int = Query(1, ge=1, description="Page number (1-based)"),
) -> DTListResponse:
    """
    Returns a paginated list of distribution transformers (DTs).

    Each DT has a code, name, feeder code, and rated capacity in kVA.
    """
    try:
        raw = await client.list_dts(page=page)
    except Exception as exc:
        logger.error("Error fetching DTs: %s", exc)
        raise HTTPException(status_code=502, detail="Portal request failed") from exc
    return transform_dt_list(raw, page)


# ---------------------------------------------------------------------------
# Bulk export (pass-through, adds auth transparently)
# ---------------------------------------------------------------------------


@router.get(
    "/export",
    summary="Full meter export",
    tags=["meters"],
    responses={
        200: {
            "description": "All meters with full hierarchy and geo coordinates",
            "content": {"application/json": {}},
        }
    },
)
async def bulk_export(
    client: ClientDep,
    page: int = Query(1, ge=1, description="Page number (1-based, 20 meters per page)"),
):
    """
    Returns all meters for the requested page, including complete hierarchy
    (zone → circle → division → subdivision → substation → feeder → DT)
    and GPS coordinates.

    This endpoint transparently handles HMAC signing of the portal's export
    endpoint — callers need no knowledge of the signing protocol.
    """
    try:
        raw = await client.bulk_export(page=page)
    except Exception as exc:
        logger.error("Error fetching bulk export: %s", exc)
        raise HTTPException(status_code=502, detail="Portal request failed") from exc
    return raw

