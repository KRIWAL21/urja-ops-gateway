"""Unit tests for the HMAC signing logic in portal_client.py"""

from __future__ import annotations

import hashlib
import hmac
import time

from src.portal_client import _sign


def test_sign_produces_hex_string():
    ts, sig = _sign("GET", "/portal/export", "page=1", "my-secret")
    assert len(sig) == 64  # SHA-256 → 32 bytes → 64 hex chars
    assert all(c in "0123456789abcdef" for c in sig)


def test_sign_timestamp_is_recent():
    ts, _ = _sign("GET", "/portal/export", "page=1", "my-secret")
    now = int(time.time())
    assert abs(int(ts) - now) < 5  # within 5 seconds


def test_sign_deterministic_for_same_timestamp():
    """Given the same timestamp, the signature should be deterministic."""
    secret = "test-secret-key"
    method, path, query = "GET", "/portal/export", "page=1"
    timestamp = "1700000000"

    message = "\n".join([method, path, query, timestamp])
    expected = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()

    # Monkey-patch time.time to return a fixed value
    import src.portal_client as pc
    import unittest.mock as mock
    with mock.patch("src.portal_client.time.time", return_value=1700000000.0):
        _, sig = _sign(method, path, query, secret)
    assert sig == expected
