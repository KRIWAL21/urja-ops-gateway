"""
Data transformation helpers.

These functions translate the portal's raw camelCase response shapes into the
clean snake_case gateway models we expose to API consumers.
"""

from __future__ import annotations

import math
from typing import Any

from .models import (
    DistributionTransformer,
    DTListResponse,
    EnergyReading,
    GeoLocation,
    HierarchyNode,
    MeterConsumption,
    MeterConsumptionResponse,
    MeterDetail,
    MeterDetailResponse,
    MeterGeo,
    MeterGeoResponse,
    MeterHierarchy,
    MeterListResponse,
    MeterSummary,
    Pagination,
)


def _pagination(total: int, page: int, page_size: int = 20) -> Pagination:
    return Pagination(
        page=page,
        page_size=page_size,
        total=total,
        total_pages=max(1, math.ceil(total / page_size)),
    )


# ---------------------------------------------------------------------------
# Meters
# ---------------------------------------------------------------------------


def _meter_summary(m: dict) -> MeterSummary:
    return MeterSummary(
        meter_id=m.get("meterId", ""),
        serial_no=m.get("serialNo", ""),
        make=m.get("make", ""),
        phase_type=m.get("phaseType", ""),
        install_status=m.get("installStatus", ""),
        dt_code=m.get("dtCode", ""),
    )


def transform_meter_list(raw: dict, page: int) -> MeterListResponse:
    """Transform /portal/meters/search response."""
    meters = [_meter_summary(m) for m in raw.get("data", [])]
    total = raw.get("total", len(meters))
    page_size = raw.get("pageSize", 20)
    return MeterListResponse(
        data=meters,
        pagination=_pagination(total, page, page_size),
    )


def transform_meter_detail_from_export(raw_meter: dict) -> MeterDetail:
    """
    Transform a single entry from /portal/export into a MeterDetail.

    The export provides the richest data: all nameplate fields, full hierarchy,
    and GPS coordinates.
    """
    h = raw_meter.get("hierarchy", {})

    def _node(d: dict | None) -> HierarchyNode | None:
        if not d:
            return None
        return HierarchyNode(name=d.get("name", ""), code=d.get("code", ""))

    hierarchy = MeterHierarchy(
        zone=_node(h.get("zone")),
        circle=_node(h.get("circle")),
        division=_node(h.get("division")),
        subdivision=_node(h.get("subdivision")),
        substation=_node(h.get("substation")),
        feeder=_node(h.get("feeder")),
        dt=_node(h.get("dt")),
    )

    geo_raw = raw_meter.get("geo")
    geo = (
        GeoLocation(lat=float(geo_raw["lat"]), lng=float(geo_raw["lng"]))
        if geo_raw
        else None
    )

    return MeterDetail(
        meter_id=raw_meter["meterId"],
        serial_no=raw_meter.get("serialNo", ""),
        make=raw_meter.get("make", ""),
        phase_type=raw_meter.get("phaseType", ""),
        install_status=raw_meter.get("installStatus", ""),
        install_type=raw_meter.get("installType", ""),
        build=raw_meter.get("build", ""),
        dt_code=raw_meter.get("dtCode", ""),
        hierarchy=hierarchy,
        geo=geo,
    )


def transform_meter_geo(meter_id: str, raw: dict) -> MeterGeoResponse:
    """Transform /portal/meters/{id}/geo response."""
    d = raw.get("data", {})
    return MeterGeoResponse(
        data=MeterGeo(
            meter_id=meter_id,
            lat=float(d.get("latitude", 0)),
            lng=float(d.get("longitude", 0)),
        )
    )


def transform_meter_consumption(meter_id: str, raw: dict) -> MeterConsumptionResponse:
    """Transform /portal/meters/{id}/energy response."""
    readings = [
        EnergyReading(
            timestamp=r.get("timestamp", ""),
            kwh=r.get("kwh"),
            kvah=r.get("kvah"),
            volt_r=r.get("voltR"),  # portal sends voltR → we expose volt_r
        )
        for r in raw.get("data", [])
    ]
    return MeterConsumptionResponse(
        data=MeterConsumption(meter_id=meter_id, readings=readings)
    )


# ---------------------------------------------------------------------------
# Distribution Transformers
# ---------------------------------------------------------------------------


def transform_dt_list(raw: dict, page: int) -> DTListResponse:
    """Transform /portal/dts response."""
    dts = [
        DistributionTransformer(
            code=d.get("code", ""),
            name=d.get("name", ""),
            feeder_code=d.get("feederCode", ""),
            capacity_kva=d.get("capacityKva", 0),
        )
        for d in raw.get("data", [])
    ]
    total = raw.get("total", len(dts))
    page_size = raw.get("pageSize", 20)
    return DTListResponse(
        data=dts,
        pagination=_pagination(total, page, page_size),
    )
