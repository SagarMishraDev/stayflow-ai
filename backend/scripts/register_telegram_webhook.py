#!/usr/bin/env python3
"""Register the Telegram webhook for a hotel (Prompt-1 section 4).

Tells Telegram to POST updates to::

    {PUBLIC_BASE_URL}/api/v1/webhooks/telegram/{HOTEL_ID}

with ``secret_token`` set so the backend can verify
``X-Telegram-Bot-Api-Secret-Token``.

Usage::

    export TELEGRAM_BOT_TOKEN="<token from @BotFather>"
    export TELEGRAM_WEBHOOK_SECRET="<long random string>"
    export PUBLIC_BASE_URL="https://stayflow.example.com"
    python scripts/register_telegram_webhook.py <HOTEL_ID>

Or with explicit flags::

    python scripts/register_telegram_webhook.py 3 \\
        --bot-token <token> --secret <secret> \\
        --base-url https://stayflow.example.com

The secret is also verified with curl::

    curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \\
      -d "url=https://stayflow.example.com/api/v1/webhooks/telegram/3" \\
      -d "secret_token=<SECRET>"

Sandbox quirk: proxy env vars (``NO_PROXY`` containing ``"[::1]"``) break
httpx in some setups, so they are stripped for this call.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request

_PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("hotel_id", type=int, help="Hotel id for the webhook path")
    parser.add_argument("--bot-token", default=os.environ.get("TELEGRAM_BOT_TOKEN"))
    parser.add_argument("--secret", default=os.environ.get("TELEGRAM_WEBHOOK_SECRET"))
    parser.add_argument("--base-url", default=os.environ.get("PUBLIC_BASE_URL"))
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    missing = [
        name
        for name, value in (
            ("bot token (--bot-token / TELEGRAM_BOT_TOKEN)", args.bot_token),
            ("webhook secret (--secret / TELEGRAM_WEBHOOK_SECRET)", args.secret),
            ("public base URL (--base-url / PUBLIC_BASE_URL)", args.base_url),
        )
        if not value
    ]
    if missing:
        print(f"Missing required: {', '.join(missing)}", file=sys.stderr)
        return 2

    webhook_url = f"{args.base_url.rstrip('/')}/api/v1/webhooks/telegram/{args.hotel_id}"
    body = urllib.parse.urlencode({"url": webhook_url, "secret_token": args.secret}).encode()

    for name in _PROXY_VARS:
        os.environ.pop(name, None)
        os.environ.pop(name.lower(), None)

    request = urllib.request.Request(
        f"https://api.telegram.org/bot{args.bot_token}/setWebhook",
        data=body,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310
            payload = json.loads(response.read().decode())
    except Exception as exc:  # noqa: BLE001
        print(f"setWebhook failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(payload, indent=2))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
