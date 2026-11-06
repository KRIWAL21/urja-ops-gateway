"""
Unit tests for the gateway.

Uses FastAPI's TestClient with a no-op lifespan so the real PortalClient never
starts and no network calls are made.  A mock client is injected via app.state.
"""

from __future__ import annotations

import pytest
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock

import src.app as app_module
from src.routes import router


# ---------------------------------------------------------------------------
# Mock data
# ---------------------------------------------------------------------------

MOCK_SEARCH_RESPONSE = {
    "data": [
        {
            "meterId": "J100001",
            "serialNo": "GE84132",
            "make": "L&T",
            "phaseType": "single",
            "installStatus": "Installed",
            "dtCode": "DT-002",
        }
    ],
    "total": 1,
    "page": 1,
    "pageSize": 20,
}

MOCK_EXPORT_RESPONSE = {
    "data": [
        {
            "meterId": "J100001",
            "serialNo": "GE84132",
            "make": "L&T",
            "phaseType": "single",
            "installStatus": "Installed",
            "installType": "CT Operated",
            "build": "legacy",
            "dtCode": "DT-002",
            "hierarchy": {
                "zone": {"name": "Jaipur Zone 2", "code": "Z-02"},
                "circle": {"name": "Circle 2", "code": "C-02"},
                "division": {"name": "Division 2", "code": "D-02"},
                "subdivision": {"name": "Subdivision 2", "code": "SD-02"},
                "substation": {"name": "Substation 2", "code": "SS-02"},
                "feeder": {"name": "Feeder 2", "code": "F-002"},
                "dt": {"name": "Mansarovar DT 2", "code": "DT-002"},
            },
            "geo": {"lat": 26.822, "lng": 75.907},
        }
    ],
    "total": 1,
}

MOCK_GEO_RESPONSE = {
    "data": {"latitude": "26.822136543835608", "longitude": "75.90718190602279"}
}

MOCK_ENERGY_RESPONSE = {
    "data": [
        {"timestamp": "24/06/2026 00:00", "kwh": "48439.16", "kvah": "52314.29", "voltR": "229"},
        {"timestamp": "24/06/2026 00:30", "kwh": "48439.58", "kvah": "52314.75", "voltR": "220"},
    ]
}

MOCK_DT_RESPONSE = {
    "data": [
        {"code": "DT-001", "name": "Malviya Nagar DT 1", "feederCode": "F-001", "capacityKva": 100},
    ],
    "total": 1,
    "page": 1,
    "pageSize": 20,
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_client():
    client = MagicMock()
    client._client = MagicMock()  # truthy → "authenticated"
    client.search_meters = AsyncMock(return_value=MOCK_SEARCH_RESPONSE)
    client.bulk_export = AsyncMock(return_value=MOCK_EXPORT_RESPONSE)
    client.get_meter_geo = AsyncMock(return_value=MOCK_GEO_RESPONSE)
    client.get_meter_energy = AsyncMock(return_value=MOCK_ENERGY_RESPONSE)
    client.list_dts = AsyncMock(return_value=MOCK_DT_RESPONSE)
    return client


@pytest.fixture
def test_client(mock_client):
    """
    Build a minimal test app with a no-op lifespan so we never touch the portal.
    The mock client is set on app.state inside the lifespan before yield.
    """

    @asynccontextmanager
    async def noop_lifespan(app):
        app.state.portal_client = mock_client
        yield

    app = FastAPI(title="Test", lifespan=noop_lifespan)
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"]
    )
    app.include_router(router, prefix="/v1")

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


def test_health(test_client):
    r = test_client.get("/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["portal_authenticated"] is True


# ---------------------------------------------------------------------------
# Meters list
# ---------------------------------------------------------------------------


def test_list_meters_default(test_client, mock_client):
    r = test_client.get("/v1/meters")
    assert r.status_code == 200
    mock_client.search_meters.assert_called_once_with(q="", page=1)
    body = r.json()
    assert len(body["data"]) == 1
    assert body["data"][0]["meter_id"] == "J100001"
    assert body["pagination"]["total"] == 1


def test_list_meters_with_search(test_client, mock_client):
    r = test_client.get("/v1/meters?q=J100&page=2")
    assert r.status_code == 200
    mock_client.search_meters.assert_called_once_with(q="J100", page=2)


# ---------------------------------------------------------------------------
# Meter detail
# ---------------------------------------------------------------------------


def test_get_meter_detail(test_client):
    r = test_client.get("/v1/meters/J100001")
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["meter_id"] == "J100001"
    assert body["data"]["hierarchy"]["zone"]["code"] == "Z-02"
    assert abs(body["data"]["geo"]["lat"] - 26.822) < 0.01


def test_get_meter_detail_not_found(test_client, mock_client):
    mock_client.bulk_export = AsyncMock(return_value={"data": [], "total": 0})
    r = test_client.get("/v1/meters/MISSING")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Meter geo
# ---------------------------------------------------------------------------


def test_get_meter_geo(test_client):
    r = test_client.get("/v1/meters/J100001/geo")
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["meter_id"] == "J100001"
    assert abs(body["data"]["lat"] - 26.822) < 0.01


# ---------------------------------------------------------------------------
# Meter consumption
# ---------------------------------------------------------------------------


def test_get_meter_consumption(test_client):
    r = test_client.get("/v1/meters/J100001/consumption")
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["meter_id"] == "J100001"
    readings = body["data"]["readings"]
    assert len(readings) == 2
    assert readings[0]["kwh"] == "48439.16"
    assert readings[0]["volt_r"] == "229"


# ---------------------------------------------------------------------------
# Transformers
# ---------------------------------------------------------------------------


def test_list_transformers(test_client, mock_client):
    r = test_client.get("/v1/transformers")
    assert r.status_code == 200
    mock_client.list_dts.assert_called_once_with(page=1)
    body = r.json()
    assert body["data"][0]["code"] == "DT-001"
    assert body["data"][0]["capacity_kva"] == 100


# ---------------------------------------------------------------------------
# Export pass-through
# ---------------------------------------------------------------------------


def test_bulk_export(test_client):
    r = test_client.get("/v1/export")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["data"][0]["meterId"] == "J100001"
