# Urja Ops Gateway

A clean, documented REST API service over the **Urja Meter Ops** web portal — a legacy internal tool used by electricity distribution utility staff to look up smart-meter information.

> **Assignment context:** Flock Energy Engineering Take-Home. The portal has no native API; this gateway reverse-engineers it and exposes a sensible, well-structured JSON API that any engineer or program can consume without touching the original portal.

---

## What was built

| File | Purpose |
|------|---------|
| `src/portal_client.py` | Async HTTP client that authenticates against the portal and wraps every internal endpoint |
| `src/routes.py` | FastAPI route handlers — the clean API surface |
| `src/transforms.py` | Maps the portal's camelCase payloads to snake_case gateway models |
| `src/models.py` | Pydantic response models (the contract we expose) |
| `src/app.py` | App factory + lifespan wiring |
| `src/config.py` | Settings from env vars / `.env` file |
| `PROTOCOL.md` | Full write-up of how the portal works under the hood |
| `openapi.json` | OpenAPI 3.x description of the gateway's API |
| `tests/` | 12 offline unit tests (no network required) |

---

## How to install and run

### Prerequisites

- Python 3.11+ (tested on 3.13)
- pip

### Install

```bash
git clone https://github.com/KRIWAL21/urja-ops-gateway.git
cd urja-ops-gateway
pip install -r requirements.txt
```

### Configure (optional)

The gateway ships with the portal credentials pre-set as defaults.  
To override, create a `.env` file:

```env
PORTAL_URL=https://urja-ops.flockenergy.tech
PORTAL_EMAIL=operator@urja.local
PORTAL_PASSWORD=urja-ops-2026
PORT=8000
LOG_LEVEL=INFO
```

### Run

```bash
python -m src
```

The server starts at `http://localhost:8000`.

---

## API overview

All routes are under `/v1`. Interactive docs at **`http://localhost:8000/docs`** (Scalar UI).  
OpenAPI spec at **`http://localhost:8000/openapi.json`** or see [`openapi.json`](./openapi.json).  
ReDoc at **`http://localhost:8000/redoc`**.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/health` | Gateway health & session status |
| `GET` | `/v1/meters` | Paginated list / search meters |
| `GET` | `/v1/meters/{id}` | Full meter detail (nameplate, hierarchy, geo) |
| `GET` | `/v1/meters/{id}/geo` | GPS coordinates only |
| `GET` | `/v1/meters/{id}/consumption` | 30-min interval energy readings |
| `GET` | `/v1/transformers` | Paginated DT list |
| `GET` | `/v1/export` | Full bulk export — all 403 meters with hierarchy + geo |

---

## Sample requests

### List meters

```bash
curl http://localhost:8000/v1/meters
```

```json
{
  "data": [
    {
      "meter_id": "J100000",
      "serial_no": "SE33962",
      "make": "HPL",
      "phase_type": "single",
      "install_status": "Decommissioned",
      "dt_code": "DT-001"
    }
  ],
  "pagination": { "page": 1, "page_size": 20, "total": 403, "total_pages": 21 }
}
```

### Search meters

```bash
curl "http://localhost:8000/v1/meters?q=AL2&page=1"
```

### Meter detail

```bash
curl http://localhost:8000/v1/meters/J100001
```

```json
{
  "data": {
    "meter_id": "J100001",
    "serial_no": "GE84132",
    "make": "L&T",
    "phase_type": "single",
    "install_status": "Installed",
    "install_type": "CT Operated",
    "build": "legacy",
    "dt_code": "DT-002",
    "hierarchy": {
      "zone":        { "name": "Jaipur Zone 2",     "code": "Z-02" },
      "circle":      { "name": "Circle 2",           "code": "C-02" },
      "division":    { "name": "Division 2",         "code": "D-02" },
      "subdivision": { "name": "Subdivision 2",      "code": "SD-02" },
      "substation":  { "name": "Substation 2",       "code": "SS-02" },
      "feeder":      { "name": "Feeder 2",           "code": "F-002" },
      "dt":          { "name": "Mansarovar DT 2",    "code": "DT-002" }
    },
    "geo": { "lat": 26.822136543835608, "lng": 75.90718190602279 }
  }
}
```

### Consumption readings

```bash
curl http://localhost:8000/v1/meters/J100001/consumption
```

```json
{
  "data": {
    "meter_id": "J100001",
    "readings": [
      { "timestamp": "24/06/2026 00:00", "kwh": "48439.16", "kvah": "52314.29", "volt_r": "229" },
      { "timestamp": "24/06/2026 00:30", "kwh": "48439.58", "kvah": "52314.75", "volt_r": "220" }
    ]
  }
}
```

---

## Run tests

```bash
pip install -r requirements-dev.txt
pytest -v
```

All 12 tests run offline — no network required.

```
12 passed in 3.84s
```

---

## Assumptions

1. **Read-only** — I treated the portal as read-only as instructed; no mutation endpoints were attempted.
2. **Single account** — The portal appears to be a single-user system (one operator account); no multi-tenancy logic was needed.
3. **Export is bulk** — The `/portal/export` endpoint returns all 403 meters in one page. I relied on this rather than paginating it.
4. **Signing secret is stable** — The secret from `/portal/keys` is cached for the session lifetime. The gateway invalidates the cache and retries once on a 401/403.
5. **Snake_case API** — The gateway exposes `snake_case` field names (e.g. `meter_id`, `install_status`) regardless of the portal's camelCase. This is a deliberate design decision for a Pythonic REST API.
6. **kWh/kVAh are cumulative** — The portal displays raw register values (not deltas). I preserve this exactly and document it rather than silently computing deltas, which could mislead consumers.

---

## Design decisions & trade-offs

### Why FastAPI?

FastAPI gives automatic OpenAPI generation, Pydantic validation, and async I/O for free — a good fit when the bottleneck is network I/O to the upstream portal.

### Why a single `PortalClient` shared across requests?

One authenticated session is cheaper than logging in per request. The lifespan context manager creates it once and tears it down on shutdown. In a multi-process deployment you'd want a Redis-backed session store; for a single process this is fine and far simpler.

### Why use the export endpoint for single-meter detail?

The portal's `/portal/meters/{id}` detail endpoint (SSR `__data.json`) is a SvelteKit internal format with shared-reference encoding — fragile to parse. The export endpoint gives the same data in a clean JSON shape. For 403 meters, one export fetch (≈250 KB) beats three round-trips (search + geo + energy) for the detail view. With a local index this would be O(1) with no portal round-trip at all.

### What I skipped

- **Caching / local index** — Adding an in-memory index (e.g. built from the bulk export at startup) would make meter lookups sub-millisecond and reduce portal load. The structure is there (`PortalClient.bulk_export`) but I chose not to add cache invalidation complexity in the time budget.
- **Auth to the gateway itself** — The gateway has no authentication; anyone who can reach port 8000 can use it. In production, an API key or OAuth2 layer would sit in front.
- **Rate limiting** — No throttling of outbound portal requests. With high concurrency the portal session could be hammered.
- **Delta energy computation** — The API exposes cumulative kWh/kVAh. Computing `delta = readings[i].kwh - readings[i-1].kwh` would be more useful but changes the semantics in a way I'd want to validate first.
- **WebSocket / streaming** — Not relevant given the portal's polling model.

---

## What I'd improve with more time

1. **Local index** — Build an in-memory SQLite index from the bulk export at startup. Refresh hourly (or on demand). Makes all meter queries sub-millisecond and removes the portal as a hot path.
2. **Pagination on export** — Properly handle the case where the portal's export grows beyond one page.
3. **Delta readings** — Add an optional `?format=delta` query param to the consumption endpoint that returns interval kWh/kVAh instead of cumulative register values.
4. **Gateway auth** — Add API key authentication (FastAPI `Security` dependency + env-var key list).
5. **Docker** — A `Dockerfile` + `docker-compose.yml` for reproducible deployment.
6. **Structured logging / tracing** — Replace `logging` with `structlog` for JSON log output; add request-ID propagation.

---

## Where to find things

| Artifact | Location |
|----------|----------|
| Source code | `src/` |
| Tests | `tests/` |
| Portal reverse-engineering write-up | [`PROTOCOL.md`](./PROTOCOL.md) |
| OpenAPI spec | [`openapi.json`](./openapi.json) |
| Interactive docs (running server) | `http://localhost:8000/docs` |
| Reflection | [`REFLECTION.md`](./REFLECTION.md) |

---

## Reflection

See [`REFLECTION.md`](./REFLECTION.md).
