"""
Pydantic response models for the gateway API.

All fields use snake_case. Aliases are only used for *parsing* the portal's
camelCase payloads; the serialised JSON this gateway emits uses snake_case.
"""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


# ---------------------------------------------------------------------------
# Shared / nested
# ---------------------------------------------------------------------------


class HierarchyNode(BaseModel):
    name: str
    code: str


class MeterHierarchy(BaseModel):
    zone: Optional[HierarchyNode] = None
    circle: Optional[HierarchyNode] = None
    division: Optional[HierarchyNode] = None
    subdivision: Optional[HierarchyNode] = None
    substation: Optional[HierarchyNode] = None
    feeder: Optional[HierarchyNode] = None
    dt: Optional[HierarchyNode] = None


class GeoLocation(BaseModel):
    lat: float
    lng: float


class Pagination(BaseModel):
    page: int
    page_size: int
    total: int
    total_pages: int


# ---------------------------------------------------------------------------
# Meters
# ---------------------------------------------------------------------------


class MeterSummary(BaseModel):
    """Lightweight meter row returned by list / search."""

    meter_id: str
    serial_no: str
    make: str
    phase_type: str
    install_status: str
    dt_code: str


class MeterDetail(BaseModel):
    """Full meter record as returned by the export / detail endpoints."""

    meter_id: str
    serial_no: str
    make: str
    phase_type: str
    install_status: str
    install_type: str
    build: str
    dt_code: str
    hierarchy: MeterHierarchy
    geo: Optional[GeoLocation] = None


class MeterGeo(BaseModel):
    meter_id: str
    lat: float
    lng: float


class EnergyReading(BaseModel):
    timestamp: str
    kwh: Optional[str] = None
    kvah: Optional[str] = None
    volt_r: Optional[str] = None


class MeterConsumption(BaseModel):
    meter_id: str
    readings: list[EnergyReading]


# ---------------------------------------------------------------------------
# Meters list response
# ---------------------------------------------------------------------------


class MeterListResponse(BaseModel):
    data: list[MeterSummary]
    pagination: Pagination


class MeterDetailResponse(BaseModel):
    data: MeterDetail


class MeterGeoResponse(BaseModel):
    data: MeterGeo


class MeterConsumptionResponse(BaseModel):
    data: MeterConsumption


# ---------------------------------------------------------------------------
# Distribution Transformers
# ---------------------------------------------------------------------------


class DistributionTransformer(BaseModel):
    code: str
    name: str
    feeder_code: str
    capacity_kva: int


class DTListResponse(BaseModel):
    data: list[DistributionTransformer]
    pagination: Pagination


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: str
    portal_authenticated: bool
    version: str = "1.0.0"
