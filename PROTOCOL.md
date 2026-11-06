# PROTOCOL.md — How the Urja Meter Ops portal actually works

> This is my reverse-engineering write-up, produced by exploring the portal
> systematically before writing a line of gateway code. Everything here was
> discovered by reading HTTP traffic and decompiling the client-side JavaScript;
> no undocumented tricks or attacks were used.

---

## 1. Tech stack

The portal is a **SvelteKit** single-page application served with SSR
(server-side rendering). The favicon and HTML comments confirm this. All pages
are rendered on the server on first load, then hydrated on the client.

Authentication is handled by the **better-auth** library
(`__Secure-better-auth.session_token` cookie).

---

## 2. Authentication

| Step | Detail |
|------|--------|
| Login page | `GET /login` — returns a plain HTML form (no CSRF token visible in HTML) |
| Login action | `POST /login` with `Content-Type: application/x-www-form-urlencoded`, fields `email` and `password` |
| Success | Server responds with `{"type":"redirect","status":303,"location":"/meters"}` and sets a `__Secure-better-auth.session_token` cookie |
| Failure | Returns `{"type":"error","error":{"message":"..."}}` with status 403 |
| Session validity | The cookie is an opaque signed token; no expiry was observed in the short exploration window, but the gateway re-authenticates on 401/403 |
| Sign-out | `fetch('/api/auth/sign-out')` (found in decompiled JS) |

**Quirk:** The form field is `email`, not `username`. The HTML `input` element
has `autocomplete="username"` but `name="email"` — easy to miss.

---

## 3. Routes (UI pages)

| Route | Purpose |
|-------|---------|
| `/login` | Login form |
| `/meters` | Paginated meter list with inline search |
| `/meters/{id}` | Meter detail: nameplate, hierarchy breadcrumb, location, consumption table |
| `/transformers` | Paginated DT list with bulk export |

Both list pages use client-side pagination (Previous / Next buttons) driven by
JavaScript fetches to the internal `/portal/` endpoints.

---

## 4. Internal portal API endpoints

All endpoints require the `__Secure-better-auth.session_token` cookie.
Unauthenticated requests return 302 → `/login` or 401/403.

### 4.1 Meter search

```
GET /portal/meters/search?q={query}&page={n}
```

- `q`: search string matched against meter ID and serial number (case-insensitive prefix, apparently)
- `page`: 1-based page number
- Returns 20 meters per page

**Response shape:**
```json
{
  "data": [
    {
      "meterId": "J100001",
      "serialNo": "GE84132",
      "make": "L&T",
      "phaseType": "single",
      "installStatus": "Installed",
      "dtCode": "DT-002"
    }
  ],
  "total": 403,
  "page": 1,
  "pageSize": 20
}
```

There are **403 meters** in the dataset.

### 4.2 Meter geo location

```
GET /portal/meters/{meterId}/geo
```

**Response:**
```json
{
  "data": {
    "latitude": "26.938961002479868",
    "longitude": "75.83095696146852"
  }
}
```

Note: latitude and longitude are **strings**, not numbers.

### 4.3 Meter energy / consumption

```
GET /portal/meters/{meterId}/energy
```

Returns 30-minute interval readings. In the dataset observed, each meter has
roughly 337 readings (≈ 7 days of half-hourly data, though the portal UI only
shows the most recent day).

**Response:**
```json
{
  "data": [
    {
      "timestamp": "24/06/2026 00:00",
      "kwh": "48439.16",
      "kvah": "52314.29",
      "voltR": "229"
    }
  ]
}
```

Fields are all strings. `kwh` and `kvah` are **cumulative** register values, not
delta/interval readings. The UI does not display this distinction. `voltR` is the
R-phase voltage.

### 4.4 Distribution Transformers list

```
GET /portal/dts?page={n}
```

20 DTs per page, 40 total (2 pages). Discovered from the Transformers page JS.

**Response:**
```json
{
  "data": [
    {
      "code": "DT-001",
      "name": "Malviya Nagar DT 1",
      "feederCode": "F-001",
      "capacityKva": 100
    }
  ],
  "total": 40,
  "page": 1,
  "pageSize": 20
}
```

### 4.5 Signing key

```
GET /portal/keys
```

Returns a secret used to sign the export request. No expiry observed.

**Response:**
```json
{
  "data": {
    "signingSecret": "I3dZPPf5CgTp7JyGNMI8i6z8LFR7TmSR"
  }
}
```

### 4.6 Bulk export (signed)

```
GET /portal/export?page={n}
Headers: x-timestamp: {unix_epoch_seconds}
         x-signature: {hmac_sha256_hex}
```

This is the richest endpoint — it returns all meter fields including the full
network hierarchy and GPS coordinates. 403 meters fit on a single page (the
portal's page-size for export appears to be much larger than the search
endpoint's 20).

**Signature algorithm** (extracted from decompiled JS `4.2Bgc2kUI.js`):

```javascript
const message = [method, path, queryString, timestamp].join("\n");
const signature = hmac_sha256(secret, message);
```

Concretely, for `GET /portal/export?page=1`:
```
message = "GET\n/portal/export\npage=1\n{timestamp}"
x-signature = hex(HMAC-SHA256(signingSecret, message))
x-timestamp = timestamp  // Unix seconds as a string
```

**Response** (one item shown):
```json
{
  "data": [
    {
      "meterId": "J100000",
      "serialNo": "SE33962",
      "make": "HPL",
      "phaseType": "single",
      "installStatus": "Decommissioned",
      "installType": "Whole Current",
      "build": "legacy",
      "dtCode": "DT-001",
      "hierarchy": {
        "zone":        {"name": "Jaipur Zone 1",       "code": "Z-01"},
        "circle":      {"name": "Circle 1",             "code": "C-01"},
        "division":    {"name": "Division 1",           "code": "D-01"},
        "subdivision": {"name": "Subdivision 1",        "code": "SD-01"},
        "substation":  {"name": "Substation 1",         "code": "SS-01"},
        "feeder":      {"name": "Feeder 1",             "code": "F-001"},
        "dt":          {"name": "Malviya Nagar DT 1",   "code": "DT-001"}
      },
      "geo": {
        "lat": 26.938961002479868,
        "lng": 75.83095696146852
      }
    }
  ],
  "total": 403
}
```

---

## 5. Network hierarchy

The portal organises meters into a 7-level hierarchy:

```
Zone → Circle → Division → Subdivision → Substation → Feeder → DT → Meter
```

This is a Jaipur (Rajasthan) electricity distribution network. The data has:
- **5 Zones** (Z-01 … Z-05)
- **40 DTs** (DT-001 … DT-040)
- **403 Meters**

The DT-to-feeder mapping has an inconsistency: DT-029 (`Sikar Road DT 29`) has
`feederCode: "F-001"` despite being DT-029. This is likely a data quality issue
in the portal itself.

---

## 6. SvelteKit SSR data

Every page exposes its server-side-rendered payload at `{path}/__data.json`.
For example:

```
GET /meters/J100001/__data.json
```

Returns a compact, shared-reference-encoded JSON object from which the meter's
nameplate data and hierarchy can be extracted. This is a SvelteKit internal
format and is more brittle to parse than the `/portal/` API endpoints, so the
gateway uses the `/portal/` endpoints instead.

---

## 7. Quirks and surprises

1. **No CSRF protection on login** — The form POST succeeds with no CSRF token.
   This is consistent with the `better-auth` library's default configuration for
   cookie-based sessions.

2. **Signed export is easy to replay** — The signing secret is served over the
   same authenticated session it protects. Any authenticated user can read the
   key and forge export requests. The signing appears to be an audit/integrity
   mechanism rather than a security boundary.

3. **`voltR` only** — The energy readings only include the R-phase voltage. Y and
   B phases are not surfaced, even though the meter type (`phaseType: "three"`)
   implies they exist.

4. **Cumulative kWh/kVAh** — The register values are totals from the meter's
   epoch, not interval deltas. Computing actual consumption requires differencing
   adjacent readings.

5. **All 403 meters fit in one export page** — The export endpoint doesn't
   paginate in practice (or its page size is very large). `page=1` returns all
   403 meters.

6. **Meter IDs are sequential but not contiguous** — IDs run from J100000 to
   J100402, but the mapping to DTs is not sequential; meters are spread across
   DTs in the data.
