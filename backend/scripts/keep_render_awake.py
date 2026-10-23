#!/usr/bin/env python3
"""Periodically ping the deployed app's health endpoint (keep-alive).

Render's free tier spins a web service down after ~15 minutes without
inbound traffic; the next visitor then pays a long cold start. This
script sends one lightweight ``GET`` to the configured public health
URL every ``KEEP_ALIVE_INTERVAL_MINUTES`` minutes to keep the service
warm.

IMPORTANT: this script only helps when it runs OUTSIDE the sleeping
service (a cron job, another machine, an external scheduler). A
process inside the Render service cannot ping anything while the
service itself is asleep. See docs/KEEP_ALIVE.md for scheduler
options and the honest platform limitations.

Configuration (environment variables only — no hardcoded URL):

- ``KEEP_ALIVE_URL`` — full public health URL, e.g.
  ``https://your-service.onrender.com/api/v1/health`` (REQUIRED).
- ``KEEP_ALIVE_INTERVAL_MINUTES`` — ping interval, default 12,
  clamped to 5–30.

Behaviour: one attempt per cycle (no retry storm), 30s timeout, logs
timestamp + HTTP status + latency (or the failure) to stdout, stops
cleanly on Ctrl+C / SIGTERM. Standard library only.

Usage::

    KEEP_ALIVE_URL=https://your-service.onrender.com/api/v1/health \
        python scripts/keep_render_awake.py
    python scripts/keep_render_awake.py --once   # single ping (for cron)
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime

DEFAULT_INTERVAL_MINUTES = 12
MIN_INTERVAL_MINUTES = 5
MAX_INTERVAL_MINUTES = 30
TIMEOUT_SECONDS = 30

_stop = False


def _handle_signal(signum: int, _frame) -> None:
    global _stop
    _stop = True
    print(f"[{_now()}] received signal {signum}, stopping after current cycle", flush=True)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _interval_minutes() -> float:
    raw = os.environ.get("KEEP_ALIVE_INTERVAL_MINUTES", "")
    try:
        value = float(raw) if raw else float(DEFAULT_INTERVAL_MINUTES)
    except ValueError:
        value = float(DEFAULT_INTERVAL_MINUTES)
    return max(float(MIN_INTERVAL_MINUTES), min(float(MAX_INTERVAL_MINUTES), value))


def ping(url: str) -> tuple[int | None, float, str | None]:
    """One GET attempt. Returns (status, latency_ms, error)."""
    request = urllib.request.Request(url, headers={"User-Agent": "stayflow-keep-alive/1.0"})
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            response.read(512)
            latency = (time.monotonic() - started) * 1000
            return response.status, latency, None
    except urllib.error.HTTPError as exc:  # server answered, but not 2xx
        latency = (time.monotonic() - started) * 1000
        return exc.code, latency, f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001 - log and continue; never crash the loop
        latency = (time.monotonic() - started) * 1000
        return None, latency, f"{type(exc).__name__}: {exc}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Keep a Render service awake via its health URL.")
    parser.add_argument("--once", action="store_true", help="ping once and exit (for cron jobs)")
    args = parser.parse_args()

    url = os.environ.get("KEEP_ALIVE_URL", "").strip()
    if not url:
        print(
            "error: KEEP_ALIVE_URL is not set — set it to the deployed health URL, "
            "e.g. https://your-service.onrender.com/api/v1/health",
            file=sys.stderr,
        )
        return 2
    if not url.startswith(("https://", "http://")):
        print(f"error: KEEP_ALIVE_URL must be an http(s) URL, got: {url!r}", file=sys.stderr)
        return 2

    interval = _interval_minutes()
    signal.signal(signal.SIGINT, _handle_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_signal)

    print(
        f"[{_now()}] keep-alive started: url={url} interval={interval:g} min "
        f"timeout={TIMEOUT_SECONDS}s",
        flush=True,
    )
    while True:
        status, latency, error = ping(url)
        if error is None:
            print(f"[{_now()}] GET {url} -> {status} in {latency:.0f} ms", flush=True)
        else:
            print(f"[{_now()}] GET {url} -> FAILED ({error}) after {latency:.0f} ms", flush=True)
        if args.once or _stop:
            break
        # Sleep in short slices so SIGINT/SIGTERM stop the loop promptly.
        deadline = time.monotonic() + interval * 60
        while not _stop and time.monotonic() < deadline:
            time.sleep(min(1.0, deadline - time.monotonic()))
        if _stop:
            break
    print(f"[{_now()}] keep-alive stopped", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
