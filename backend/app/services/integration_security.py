"""HMAC-SHA256 signing for the server-to-server integration API (§12).

Protocol (documented in docs/INTEGRATIONS.md):

- The client sends two headers on every request:
  - ``X-StayFlow-Timestamp``: Unix seconds when the request was signed.
  - ``X-StayFlow-Signature``: ``sha256=<hex>`` where ``<hex>`` is
    HMAC-SHA256(secret, ``f"{timestamp}." + raw_body``) using the hotel's
    integration secret as the key and the *exact raw request body bytes*.
- The server rejects timestamps further than the configured window
  (default 5 minutes) from server time, compares signatures in constant
  time, and records each accepted signature as a one-time nonce so a
  captured request cannot be replayed inside the window.

The secret itself is never logged and never appears in any response after
the one-time generation call.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets as _secrets

SIGNATURE_HEADER = "X-StayFlow-Signature"
TIMESTAMP_HEADER = "X-StayFlow-Timestamp"
IDEMPOTENCY_HEADER = "Idempotency-Key"
SIGNATURE_PREFIX = "sha256="


def generate_secret() -> str:
    """Generate a new per-hotel integration secret (URL-safe, 256-bit)."""
    return _secrets.token_urlsafe(32)


def secret_fingerprint(secret: str) -> str:
    """Short non-reversible fingerprint for identifying a secret in UIs/logs."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()[:12]


def compute_signature(secret: str, timestamp: str, raw_body: bytes) -> str:
    """Return the ``sha256=<hex>`` signature for a request."""
    signed_payload = f"{timestamp}.".encode() + raw_body
    digest = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return f"{SIGNATURE_PREFIX}{digest}"


def normalize_signature(signature: str) -> str:
    """Accept the signature with or without the ``sha256=`` prefix."""
    value = signature.strip()
    if value.lower().startswith(SIGNATURE_PREFIX):
        value = value[len(SIGNATURE_PREFIX) :]
    return value.lower()


def verify_signature(secret: str, timestamp: str, raw_body: bytes, provided_signature: str) -> bool:
    """Constant-time verification of a provided signature."""
    expected = compute_signature(secret, timestamp, raw_body)
    return hmac.compare_digest(
        normalize_signature(expected), normalize_signature(provided_signature)
    )
