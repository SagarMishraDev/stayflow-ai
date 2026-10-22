# Embeddable website chat widget (§11)

A vanilla-JS widget a hotel can place on its own website. Guests chat
with the same StayFlow agent used by every other channel; bookings and
orders keep the deterministic confirmation gate inside the agent tools.

## Embed snippet

```html
<script
  src="https://YOUR_HOSTED_DOMAIN/widget.js"
  data-hotel-id="HOTEL_PUBLIC_ID"
  async
></script>
```

- `src` — where StayFlow is hosted. The FastAPI app serves the loader at
  `/widget.js` (and the widget assets under `/widget/`).
- `data-hotel-id` — the hotel's **public id** (`hotels.public_id`, a
  32-char random hex token). Find it in the staff dashboard under
  **Hotel settings → Integrations**. Never use the internal numeric
  hotel id — the public API does not accept it.
- Optional attributes: `data-api-base="https://api.example.com"` when
  the API is hosted on a different origin than the script, and
  `data-title="Chat with us"` to change the launcher label.

The loader injects a launcher button (bottom-right) and an expandable
panel containing an iframe with the chat UI (`/widget/chat.html`). It is
mobile-friendly, shows loading/typing/error states with retry, displays
the hotel name and check-in/check-out times, and persists the session
(the conversation id) in `localStorage`, scoped per hotel public id.

## Public API used by the widget

All endpoints are under `/api/v1/public/...`, need no staff token, and
resolve the hotel **only** by public id:

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/public/hotels/{public_id}` | Public hotel info: name, city, description, check-in/out times, currency. No internal id, no secrets. |
| `GET /api/v1/public/hotels/{public_id}/widget-config` | The info above plus `welcome_message` and `widget_title` for the chat UI. |
| `POST /api/v1/public/chat` | One chat turn. Body: `{"hotel_public_id", "message", "session_id"?}`. Response: `{"reply", "conversation_id", "session_id", "hotel_id" (public id), "status", "degraded"}`. |

Rules enforced server-side:

- Unknown or inactive public ids → `404`.
- A `session_id` minted for one hotel presented under another hotel's
  public id → `422` (hotel isolation).
- Rate limited per hotel + client IP (`RATE_LIMIT_PUBLIC_CHAT_*`,
  default 20/min) → `429` with a `Retry-After` header.
- The agent runs with `channel="widget"` through the shared runner —
  no duplicated agent logic.

## Run and test locally

```bash
cd backend
uv run uvicorn app.main:app --port 8000
# Demo/test page (stands in for a hotel website):
#   http://localhost:8000/widget/?hotel=<HOTEL_PUBLIC_ID>
# Loader:  http://localhost:8000/widget.js
# Chat UI: http://localhost:8000/widget/chat.html?hotel=<HOTEL_PUBLIC_ID>
```

Get a public id from the dashboard (Hotel settings → Integrations) or
the staff API (`GET /api/v1/hotels` includes `public_id`).

Source files: `frontend/widget/widget.js` (loader), `widget.css`,
`chat.html` (iframe chat page), `index.html` (demo page); backend:
`backend/app/api/public.py`.
