"""
Portal client — authenticates against the Urja Meter Ops SvelteKit portal and
exposes a thin async wrapper around every internal endpoint we discovered.

Authentication:
  POST /login  {email, password}  →  sets __Secure-better-auth.session_token cookie.

Internal endpoints (all require the session cookie):
  GET /portal/meters/search?q=&page=N          → paginated meter list
  GET /portal/meters/{id}/geo                  → GPS location
  GET /portal/meters/{id}/energy               → 30-min consumption readings
  GET /portal/dts?page=N                       → distribution transformers
  GET /portal/keys                             → HMAC signing secret
  GET /portal/export?page=N + x-timestamp/x-signature → full bulk export
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from typing import Any

import httpx

from .config import settings

logger = logging.getLogger(__name__)

PORTAL_BASE = str(settings.portal_url).rstrip("/")


def _sign(method: str, path: str, query: str, secret: str) -> tuple[str, str]:
    """
    Compute the HMAC-SHA256 signature expected by /portal/export.

    The portal (discovered from the decompiled JS) signs:
        f"{method}\n{path}\n{query}\n{timestamp}"
    with the secret obtained from /portal/keys.
    """
    timestamp = str(int(time.time()))
    message = "\n".join([method, path, query, timestamp])
    sig = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    return timestamp, sig


class PortalClient:
    """
    Async HTTP client that holds a single authenticated session with the Urja portal.

    Instantiate once, call ``login()`` before the first request, and reuse.
    The underlying httpx.AsyncClient handles connection pooling automatically.
    """

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._signing_secret: str | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Create the HTTP client and authenticate."""
        self._client = httpx.AsyncClient(
            base_url=PORTAL_BASE,
            headers={"User-Agent": "urja-ops-gateway/1.0"},
            follow_redirects=True,
            timeout=30.0,
        )
        await self._login()
        logger.info("PortalClient authenticated and ready")

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
        logger.info("PortalClient closed")

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    async def _login(self) -> None:
        """POST /login — obtains the session cookie."""
        resp = await self._client.post(
            "/login",
            data={"email": settings.portal_email, "password": settings.portal_password},
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": PORTAL_BASE,
                "Referer": f"{PORTAL_BASE}/login",
            },
        )
        if resp.status_code not in (200, 303):
            raise RuntimeError(
                f"Portal login failed with status {resp.status_code}: {resp.text[:200]}"
            )
        cookie_name = "__Secure-better-auth.session_token"
        if cookie_name not in self._client.cookies:
            raise RuntimeError("Login did not set expected session cookie")
        logger.debug("Portal session cookie acquired")

    async def _ensure_auth(self) -> None:
        """Re-authenticate if the session has expired (401/302 to /login)."""
        await self._login()

    # ------------------------------------------------------------------
    # Raw request helper
    # ------------------------------------------------------------------

    async def _get(self, path: str, **params: Any) -> Any:
        """
        Issue a GET to *path* with query *params*.  
        On session expiry, re-authenticates once and retries.
        """
        resp = await self._client.get(path, params=params or None)
        if resp.status_code in (401, 403) or (
            resp.status_code == 302 and "/login" in resp.headers.get("location", "")
        ):
            logger.warning("Session expired, re-authenticating…")
            await self._ensure_auth()
            resp = await self._client.get(path, params=params or None)
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Portal endpoints
    # ------------------------------------------------------------------

    async def search_meters(self, q: str = "", page: int = 1) -> dict:
        """
        Search meters by meter-ID or serial number prefix.

        Returns:
            {data: [...], total: int, page: int, pageSize: int}
        """
        return await self._get("/portal/meters/search", q=q, page=page)

    async def get_meter_geo(self, meter_id: str) -> dict:
        """
        Return the GPS location of *meter_id*.

        Returns:
            {data: {latitude: str, longitude: str}}
        """
        return await self._get(f"/portal/meters/{meter_id}/geo")

    async def get_meter_energy(self, meter_id: str) -> dict:
        """
        Return 30-minute interval consumption readings for *meter_id*.

        Returns:
            {data: [{timestamp, kwh, kvah, voltR}, ...]}
        """
        return await self._get(f"/portal/meters/{meter_id}/energy")

    async def get_meter_detail(self, meter_id: str) -> dict:
        """
        Return the SSR (server-side-rendered) detail data for *meter_id*.
        This includes nameplate parameters and the full hierarchy string.

        Returns the raw decoded SvelteKit __data.json node.
        """
        return await self._get(f"/meters/{meter_id}/__data.json")

    async def list_dts(self, page: int = 1) -> dict:
        """
        Return a paginated list of distribution transformers.

        Returns:
            {data: [{code, name, feederCode, capacityKva}], total: int, page: int, pageSize: int}
        """
        return await self._get("/portal/dts", page=page)

    async def _get_signing_secret(self) -> str:
        """Fetch and cache the HMAC signing secret from /portal/keys."""
        if self._signing_secret is None:
            data = await self._get("/portal/keys")
            self._signing_secret = data["data"]["signingSecret"]
            logger.debug("Signing secret cached")
        return self._signing_secret

    async def bulk_export(self, page: int = 1) -> dict:
        """
        Fetch the signed bulk export endpoint.

        The portal requires an HMAC-SHA256 signature computed from
        [METHOD, PATH, QUERYSTRING, UNIX_TIMESTAMP] joined by newlines.

        Returns:
            {data: [{meterId, serialNo, make, phaseType, installStatus,
                     installType, build, dtCode, hierarchy: {...}, geo: {...}}],
             total: int}
        """
        secret = await self._get_signing_secret()
        query = f"page={page}"
        path = "/portal/export"
        timestamp, signature = _sign("GET", path, query, secret)

        resp = await self._client.get(
            path,
            params={"page": page},
            headers={"x-timestamp": timestamp, "x-signature": signature},
        )
        if resp.status_code in (401, 403):
            # secret may have rotated — clear cache and retry once
            self._signing_secret = None
            secret = await self._get_signing_secret()
            timestamp, signature = _sign("GET", path, query, secret)
            resp = await self._client.get(
                path,
                params={"page": page},
                headers={"x-timestamp": timestamp, "x-signature": signature},
            )
        resp.raise_for_status()
        return resp.json()

