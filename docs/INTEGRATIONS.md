# Existing-chat integration API (§12)

Connect a hotel's existing website chat (or any partner backend) to
StayFlow AI without replacing its frontend:

```
Existing website chat → partner backend → POST /api/v1/integrations/chat/message
                                        → StayFlow agent (same runner as all channels)
                                        → structured JSON response → existing chat
```

## Endpoint

`POST /api/v1/integrations/chat/message` (server-to-server only; a staff
JWT does **not** authenticate this route).

### Request

Headers:

| Header | Required | Meaning |
|---|---|---|
| `Content-Type: application/json` | yes | |
| `X-StayFlow-Timestamp` | yes | Unix seconds when the request was signed |
| `X-StayFlow-Signature` | yes | `sha256=<hex>` — see signing below |
| `Idempotency-Key` | recommended | Any unique-per-event string (≤255 chars). Duplicate deliveries return the original response. The body's `event_id` is accepted as a fallback. |

Body:

```json
{
  "hotel_public_id": "290434ea78354dc2931beea84f1be4b7",
  "message": "Is the Deluxe room available this weekend?",
  "session_id": null,
  "guest_reference": "partner-user-8812"
}
```

| Field | Required | Notes |
|---|---|---|
| `hotel_public_id` | yes | The hotel's public id (dashboard → Hotel settings → Integrations). Internal numeric ids are not accepted. |
| `message` | yes | Guest message, 1–4000 chars. |
| `conversation_id` | no | Continue a conversation by its id (from a previous response). |
| `session_id` | no | Same, as a string (e.g. the previous `conversation_id`). Unknown values start a fresh conversation. |
| `guest_id` | no | A StayFlow guest id belonging to this hotel. |
| `guest_reference` | no | Your own opaque reference for the guest; echoed in the response, never used as an identity. |
| `event_id` | no | Fallback idempotency key when the header is absent. |

### Response (200)

```json
{
  "conversation_id": 1234,
  "reply": "Yes — the Deluxe room is available …",
  "hotel_id": "290434ea78354dc2931beea84f1be4b7",
  "status": "ok",
  "degraded": false,
  "guest_reference": "partner-user-8812"
}
```

`hotel_id` in the response is always the **public** id. Persist
`conversation_id` and send it back (as `conversation_id` or `session_id`)
to continue the conversation. `degraded: true` means the LLM provider
failed and the reply is a graceful fallback message.

### Errors

Errors are structured and never leak secrets or internals:

```json
{ "detail": { "error": { "code": "invalid_signature", "message": "Request authentication failed" } } }
```

| HTTP | `code` | Meaning |
|---|---|---|
| 401 | `missing_signature_headers` | Timestamp/signature header absent |
| 401 | `invalid_timestamp` | Timestamp is not Unix seconds |
| 401 | `timestamp_expired` | Timestamp outside the ±5 min window |
| 401 | `integration_not_configured` | Hotel has no secret and no fallback is configured |
| 401 | `invalid_signature` | HMAC mismatch (wrong secret or altered body) |
| 401 | `replay_detected` | Identical signed request already processed (requests without an idempotency key) |
| 404 | `hotel_not_found` | Unknown/inactive public id |
| 422 | `invalid_json` / `validation_error` / `agent_validation_error` | Malformed body, failed validation, or the conversation/guest does not belong to this hotel |
| 429 | — | Rate limited (per hotel + IP, default 60/min); honour `Retry-After` |
| 500 | `agent_error` | Agent failure; safe to retry with the same idempotency key |

## Signing (HMAC-SHA256)

The signature is computed over the **exact raw request body bytes**:

```
signature = "sha256=" + hex( HMAC_SHA256(secret, timestamp + "." + raw_body) )
```

- `secret` — the hotel's integration secret. Generate/rotate it in the
  dashboard (Hotel settings → Integrations) or via
  `POST /api/v1/integrations/secret/rotate` (staff JWT). It is returned
  **exactly once**; only a short fingerprint is kept for identification.
  A global fallback (`INTEGRATION_FALLBACK_SECRET`) can serve hotels
  without their own secret; per-hotel secrets take precedence.
- `timestamp` — the same value sent in `X-StayFlow-Timestamp`.
- Verification is constant-time; timestamps must be within
  `INTEGRATION_TIMESTAMP_WINDOW_SECONDS` (default 300) of server time.

Python example:

```python
import hashlib, hmac, json, time
import httpx

secret = "<the hotel integration secret>"
body = {"hotel_public_id": "<public id>", "message": "Hello!"}
raw = json.dumps(body).encode()
ts = str(int(time.time()))
signature = "sha256=" + hmac.new(
    secret.encode(), f"{ts}.".encode() + raw, hashlib.sha256
).hexdigest()

resp = httpx.post(
    "https://YOUR_HOSTED_DOMAIN/api/v1/integrations/chat/message",
    content=raw,
    headers={
        "Content-Type": "application/json",
        "X-StayFlow-Timestamp": ts,
        "X-StayFlow-Signature": signature,
        "Idempotency-Key": "evt-2026-000123",
    },
    timeout=30,
)
print(resp.json())
```

## Idempotency & retries

- Always send an `Idempotency-Key` per guest message event. A duplicate
  delivery (same key, same hotel) returns the **original** response —
  the agent is not re-run and no messages are duplicated. Keys are
  hotel-scoped and persisted (`integration_idempotency_keys`).
- Retry policy for callers: retry on network errors, `429` (after
  `Retry-After`), and `5xx`, with exponential backoff (e.g. 1s, 2s, 4s;
  max ~3 attempts) and the **same** idempotency key. Do not retry other
  `4xx` responses. Use a client timeout of ~30s (the agent may run
  several tool steps).
- Requests without an idempotency key are replay-protected instead: a
  byte-identical re-send is rejected with `replay_detected`. Re-sign
  retries with a fresh timestamp.

## Outbound webhook (async responses)

If the hotel configures an outbound webhook URL and signing secret
(dashboard → Integrations, or `PATCH /api/v1/integrations/webhook` +
`POST /api/v1/integrations/webhook-secret/rotate`), every chat response
is also POSTed to that URL as JSON, signed with the **same** scheme
(`X-StayFlow-Timestamp` / `X-StayFlow-Signature` headers over
`timestamp + "." + raw_body`, keyed by the webhook signing secret), so
receivers can verify deliveries and apply the same replay window.

Delivery is best-effort and bounded: per-attempt timeout
`INTEGRATION_HTTP_TIMEOUT_SECONDS` (default 5s), up to
`INTEGRATION_MAX_RETRIES` attempts (default 3) with backoff, retrying
only network errors and `5xx` (`4xx` is permanent). The synchronous API
response remains authoritative — a failed webhook never fails the chat
request. The outcome is recorded on the integration request log
(`webhook_delivered`). Implementation: `app/services/webhook_delivery.py`.

## Staff configuration endpoints (staff JWT, hotel-scoped)

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/integrations/settings` | Status: public id, secret configured?, fingerprint, webhook URL/secret status. Never returns a secret. |
| `POST /api/v1/integrations/secret/rotate` | Generate a new integration secret — returned once. The old secret stops working immediately. |
| `POST /api/v1/integrations/webhook-secret/rotate` | Generate a new webhook signing secret — returned once. |
| `PATCH /api/v1/integrations/webhook` | Set/clear the outbound webhook URL (`{"webhook_url": "https://…"}` or `null`). |

A minimal request log (`integration_request_logs`: hotel, outcome,
conversation/idempotency ids, webhook outcome) is kept for operations —
it contains no secrets, signatures, or message text.
