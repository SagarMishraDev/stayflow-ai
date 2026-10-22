# StayFlow AI — Master Build Report (v2)

Date: 2026-10-20 · Repo: `~/workspace/stayflow-ai-work` · ZIP: `~/workspace/your_files/stayflow-ai-master-v2.zip`

This build closes the four confirmed gaps against the 23-section MASTER
PROJECT PROMPT without rewriting working code. Everything below was
implemented and verified in this environment; limitations are stated
honestly at the end.

## Baseline vs. after

| Check | Before | After |
|---|---|---|
| Backend tests (`pytest -q`, SQLite e2e DB, mock LLM, hashed embeddings) | **171 passed, 2 failed, 2 deselected** (175 collected) | **193 passed, 2 failed, 2 deselected** (197 collected = 171 + 22 new passing; the same 2 pre-existing SQLite-environment failures, 0 regressions — see Known limitations) |
| `ruff check .` | clean | clean |
| `ruff format --check .` | clean | clean (157 files) |
| Dashboard `npm run build` (tsc + Vite) | — | **passes** (170 modules) |
| Alembic migration | head `6fac09f32444` | new head `c4d8e2a91b07`, up/down/up verified, `alembic check` clean |

## Gap 1 — §11 Embeddable widget (was missing entirely)

**Model + migration**
- `backend/app/models/hotel.py`: `public_id` (String(64), unique, indexed,
  Python-side default `uuid4().hex` — non-sequential), `check_in_time` /
  `check_out_time` (nullable `HH:MM` strings, §5), plus integration
  credential fields (gap 2).
- `backend/alembic/versions/c4d8e2a91b07_widget_and_integrations.py`
  (revises `6fac09f32444`): batch-mode hotels changes (SQLite + Postgres
  safe), per-row `public_id` backfill, unique index `ix_hotels_public_id`,
  three new integration tables. Verified on a scratch DB: upgrade
  (incl. backfill of a pre-existing row → 32-char public_id), downgrade,
  re-upgrade, and `alembic check` ("No new upgrade operations detected").
- `backend/app/schemas/hotel.py`: responses/creates/updates carry
  `public_id`, `check_in_time`, `check_out_time` (with `HH:MM` validation).

**Public widget API** — `backend/app/api/public.py`, mounted at `/api/v1`:
- `GET /api/v1/public/hotels/{public_id}` and
  `GET /api/v1/public/hotels/{public_id}/widget-config` — dedicated public
  schemas; the internal integer id is never accepted and never returned.
- `POST /api/v1/public/chat` — resolves the hotel by `public_id` only,
  runs the **existing** agent runner (`channel="widget"`, no duplicated
  agent logic; booking/order confirmation gate untouched), rate-limited
  per hotel + IP (new `rate_limit_public_chat` in `app/core/rate_limit.py`,
  built on a reusable `rate_limit_factory`). A session id from another
  hotel is rejected with 422 by the runner's hotel check.

**Widget frontend** — `frontend/widget/` (vanilla JS, no build step):
- `widget.js` — loader: reads `data-hotel-id` (plus optional
  `data-api-base`, `data-title`) from its own script tag, injects the
  stylesheet, a launcher button, and an expandable panel with an iframe.
- `chat.html` — iframe chat UI: hotel branding + check-in/out times from
  widget-config, welcome message, message history, typing indicator,
  error banner with retry, 429 handling, session id persisted in
  `localStorage` (key scoped per public id).
- `widget.css` — `sfw-`-prefixed styles (no host-site collisions),
  mobile layout.
- `index.html` — demo/test page (paste a public id or use `?hotel=`).
- Served by FastAPI: `/widget.js` (canonical loader path), `/widget/*`
  static mount. Verified live: `/chat` and `/docs` unaffected.

Docs: `docs/WIDGET.md` + README section with the real snippet:
`<script src="https://YOUR_HOSTED_DOMAIN/widget.js" data-hotel-id="HOTEL_PUBLIC_ID" async></script>`

## Gap 2 — §12 Existing-chat integration API (was missing as specified)

**New module** `backend/app/api/integrations.py`:
- `POST /api/v1/integrations/chat/message` — server-to-server. Auth:
  per-hotel HMAC-SHA256, headers `X-StayFlow-Timestamp` /
  `X-StayFlow-Signature` (`sha256=<hex>` over `timestamp + "." + raw_body`),
  5-minute timestamp window (`INTEGRATION_TIMESTAMP_WINDOW_SECONDS`),
  constant-time compare (`app/services/integration_security.py`). Request:
  `hotel_public_id`, `message`, optional `conversation_id`/`session_id`,
  `guest_id`, `guest_reference`, `event_id`. Response:
  `{conversation_id, reply, hotel_id (public), status, degraded, guest_reference}`.
  Invokes the same agent runner (`channel="integration"`).
- **Replay protection:** each accepted signature is stored as a one-time
  nonce (`integration_nonces`, unique) and replays are rejected
  (`replay_detected`). Requests **with** an idempotency key skip the nonce
  check — their duplicates are handled by the idempotency store (a
  byte-identical retry returns the stored response).
- **Idempotency:** `Idempotency-Key` header (or body `event_id`).
  `integration_idempotency_keys` (hotel-scoped unique constraint) stores
  the first response; duplicates return it without re-running the agent
  or duplicating messages (tested, incl. per-hotel scoping and a
  concurrent-race fallback).
- **Secrets:** per-hotel secret in a dedicated model field (required in
  raw form to verify HMAC), generated via
  `POST /api/v1/integrations/secret/rotate` (staff JWT) and returned
  **exactly once**; only a SHA-256 fingerprint is kept for display. Never
  logged, never in any other response. Optional global fallback
  `INTEGRATION_FALLBACK_SECRET`. Staff endpoints:
  `GET /api/v1/integrations/settings`, `POST .../secret/rotate`,
  `POST .../webhook-secret/rotate`, `PATCH /api/v1/integrations/webhook`.
- **Errors:** structured `{"detail": {"error": {"code", "message"}}}`,
  no secret/infra leakage. **Request log:** `integration_request_logs`
  (hotel, status, ids, webhook outcome — no secrets, no message text).
- **Outbound webhook:** `app/services/webhook_delivery.py` — signed
  delivery helper (same HMAC scheme) with bounded retries (default 3
  attempts, 5s timeout, backoff; retries network/5xx only). Wired into
  the chat endpoint: when a hotel has a webhook URL + signing secret,
  each response is delivered best-effort and the outcome logged; a failed
  delivery never fails the chat request. Covered by signer/retry/
  end-to-end tests with mocked HTTP (no live delivery claimed).

Docs: `docs/INTEGRATIONS.md` — sample request/response, Python signing
example, error-code table, retry/timeout guidance.

## Gap 3 — §14 Dashboard Food Orders page (was missing)

- `frontend/dashboard/src/pages/Orders.tsx` — table of orders with
  status-filter chips (backend `ORDER_STATUSES`: PENDING, CONFIRMED,
  PREPARING, READY, DELIVERED, CANCELLED), search by guest/order/type,
  per-order status select + quick-move buttons (`PATCH /orders/{id}`),
  expandable line items (`GET /order-items?order_id=` with menu names),
  server totals displayed as returned, loading/empty/error states via
  the shared `ListState`/`PageHeader` patterns (modelled on
  ServiceRequests/Bookings).
- Wiring: route `/orders` in `App.tsx`, "Food orders" nav entry in
  `Layout.tsx`; `Order`/`OrderItem` types, `useOrders`/`useOrderItems`
  hooks + query keys, `orderUpdateSchema`, StatusBadge styles for
  PREPARING/READY/DELIVERED.
- `Settings.tsx`: new **Integrations** tab — hotel `public_id` with copy
  button, ready-to-paste widget embed snippet (built from
  `WIDGET_BASE_URL` or the current origin), widget demo link, integration
  secret status + fingerprint with one-time-display rotate flow, and
  outbound webhook URL + signing-secret management. Profile tab gained
  check-in/check-out time fields. `Hotel` type + `hotelSchema` updated.

## Gap 4 — §18 Config

- `backend/.env.example` extended (placeholders only, real `.env` never
  touched — none exists in the repo): `WIDGET_BASE_URL`,
  `RATE_LIMIT_PUBLIC_CHAT_*`, `RATE_LIMIT_INTEGRATION_*`,
  `INTEGRATION_TIMESTAMP_WINDOW_SECONDS`, `INTEGRATION_FALLBACK_SECRET`,
  `INTEGRATION_HTTP_TIMEOUT_SECONDS`, `INTEGRATION_MAX_RETRIES`, with a
  per-hotel-secret note. Matching settings added in `app/core/config.py`.
- `.gitignore` verified: `.env` and `.env.*` ignored, `!.env.example`
  excepted; `node_modules/`, `*.db` also ignored.

## Tests added (22) — `backend/tests/test_widget_integrations.py`

Hotel public_id generation/uniqueness + check-in/out via staff API
(incl. invalid time → 422); public info by public_id only (internal id
→ 404, never exposed); public chat isolation (cross-hotel session → 422,
per-hotel conversations, `channel="widget"`); public chat rate limit
(429 + `Retry-After`); widget assets served (`/widget.js`, chat page,
demo, legacy `/chat` intact); integration signature valid / invalid /
missing headers / expired timestamp / replay; unknown hotel 404;
unconfigured secret 401; fallback secret; idempotency duplicate returns
the original response with no new messages; idempotency key scoped per
hotel; settings require staff JWT (401); secret rotation flow (old
secret rejected, new accepted, secret never re-returned); webhook
signer matches the documented HMAC algorithm; delivery retries then
succeeds; bounded retries + permanent 4xx; signed webhook delivered
end-to-end on integration chat (mocked HTTP).

## How to run widget + integration locally

```bash
cd backend
uv run alembic upgrade head            # applies c4d8e2a91b07 on Postgres
uv run uvicorn app.main:app --port 8000
# Widget demo: http://localhost:8000/widget/?hotel=<PUBLIC_ID>
#   (public id: dashboard → Hotel settings → Integrations)
# Integration: see docs/INTEGRATIONS.md for the signing example.
```

Verified additionally with a live uvicorn smoke test against the SQLite
e2e DB: health, `/widget.js`, demo page, public hotel info, public chat
(real policy answer from the agent), `/docs`, and a structured 401 for an
unsigned integration call.

## Known limitations (honest)

- **Two pre-existing tests fail on SQLite (pass on PostgreSQL):**
  `test_pms_comprehensive.py::test_hotel_crud_and_validation` expects
  deleting a hotel with dependent staff records to return 409 via a
  foreign-key IntegrityError, but this app's SQLite engine runs with
  `PRAGMA foreign_keys = 0` (verified), so the delete succeeds (204);
  `test_rag.py::test_ingest_document_creates_chunks_and_embeddings`
  asserts `created_at.tzinfo is not None`, but SQLite read-back returns
  naive datetimes (Postgres `timestamptz` preserves tz). Both failures
  reproduce identically on a fresh scratch SQLite DB, in code paths this
  build did not modify, and were present in the pre-change baseline run
  (171 passed / 2 failed). The suite's documented home is PostgreSQL
  (README + CI), where FK enforcement and tz-aware timestamps hold.
- **Test DB in this sandbox is SQLite** (`backend/stayflow_e2e.db`,
  create_all-managed with an empty `alembic_version` — pre-existing). It
  was synced to the new schema with the migration's exact operations and
  stamped at head `c4d8e2a91b07`. The full pre-existing migration chain
  does not run on SQLite (an older migration uses non-batch constraint
  ALTERs — pre-existing); on PostgreSQL (CI/production) the chain,
  including the new migration, applies via `alembic upgrade head`. The
  new migration itself was verified up/down/up + `alembic check` on a
  scratch SQLite DB.
- **No live external delivery was performed**: outbound webhook delivery
  is verified against mocked HTTP only; no real partner endpoint exists
  in this environment. Mercury 2.5 remains not live-tested (no API key
  here) — all agent tests use the mock provider, as before.
- Rate limiting stays in-memory/per-process (existing design); the new
  public/integration limiters share that property.
- Widget chat does not render the structured tool-trace cards that the
  full-page `/chat` UI shows; it displays the agent's text replies
  (which include booking/order summaries from the deterministic tools).

---

# Addendum — Hotel Landing Page (v3, 2026-10-21)

A public hotel landing page at the site root with role-based staff
login, built on top of the v2 delivery without modifying the dashboard
SPA or any staff auth boundary.

## What was built

**Public landing API** — `backend/app/api/public.py` (extended):
- `GET /api/v1/public/hotels/{public_id}/landing` — one aggregate,
  public-safe payload: hotel (name, description, city, address, phone,
  email, currency, check-in/out times, `public_id` — dedicated schemas
  with **no `id` / `hotel_id` field anywhere**), rooms (type, capacity,
  description, amenities text, nightly rate = earliest upcoming real
  `Rate` row, or `null` when none exists), offers (active **and**
  within their validity window only), services, FAQs, policies
  (incl. cancellation), menu highlights (available items only). Every
  query is hotel-scoped; rate-limited via a new `rate_limit_public_read`
  limiter (path + IP keyed, sharing the public-chat budget settings).
- `GET /api/v1/public/featured-hotel/landing` — same payload for the
  first active hotel; documented single-property/demo convenience.
  Multi-hotel deployments use `?hotel=<public_id>`.

**Landing page** — `frontend/landing/` (`index.html`, `styles.css`,
`app.js`; vanilla, no build step), in the dashboard's pine/parchment/
brass palette with Fraunces brand headings:
- Sticky nav (hotel name, section links, Chat, Staff Login — or Open
  Dashboard + Logout when a session exists), hero (name, city,
  description, check-in/out chips, View Rooms / Chat with Concierge),
  About, Rooms & Rates cards (real prices + currency + capacity),
  Amenities & Services grid, Offers, Dining highlights, FAQ accordion,
  Policies + Contact, footer "Powered by StayFlow AI".
- All sections are populated from the landing API and **hidden when
  their data is empty** — no invented ratings, reviews, prices, or
  amenities. Loading skeletons + a clear error/retry state included.
- Hotel resolution: `?hotel=<public_id>` → localStorage last hotel →
  featured-hotel fallback. The existing widget is embedded per hotel
  (`/widget.js` with `data-hotel-id`), so the chat launcher appears on
  the landing page and the Chat buttons open it.
- **Role-based login:** the login modal posts to the same
  `POST /api/v1/auth/login` the dashboard uses, then fetches the user
  the same way the dashboard does (JWT payload → `GET /hotel-users/{id}`)
  and stores the session under the **same localStorage keys**
  (`stayflow_token`, `stayflow_hotel_id`). The role panel reads:
  SUPER_ADMIN → "Open Admin Dashboard", HOTEL_ADMIN → "Open Hotel
  Dashboard", STAFF → "Open Staff Dashboard", with a 5-second
  auto-redirect that can be cancelled. Guests need no account — an
  "I'm a Guest" path in the modal opens the concierge chat. Login
  errors are generic; credentials are never logged.
- **Dashboard URL resolution:** `window.STAYFLOW_DASHBOARD_URL` →
  localStorage `stayflow_dashboard_url` → `http://localhost:5173/`
  (Vite dev default). Documented in the README landing section.

**Serving** — `backend/app/main.py`: explicit `GET /` route returning
the landing `index.html` + a `/landing` static mount (absolute asset
paths, no catch-all). Verified live that `/`, `/landing/*`, `/api/*`,
`/docs`, `/openapi.json`, `/chat`, `/widget` and `/widget.js` all
respond correctly after the change.

## Verification

| Check | Result |
|---|---|
| Backend tests | **199 passed, 2 failed, 2 deselected** (203 collected) — the 2 failures are the same pre-existing SQLite-environment ones documented in v2 (`test_hotel_crud_and_validation`, `test_ingest_document_creates_chunks_and_embeddings`); baseline was 193 passed, the +6 are the new landing tests in `backend/tests/test_landing.py` (own-content/rates, cross-hotel isolation, unknown/internal id → 404, no internal id anywhere in the payload, featured endpoint, root serving + other surfaces intact) |
| `ruff check .` / `ruff format --check .` | clean (158 files) |
| Preview screenshots (real renders, throwaway `/tmp` `create_all` DB + `seed_demo.py`, mock LLM, Playwright + cached headless_shell) | `07-landing-page.png` (desktop: pine hero, real room cards ₹4,500/₹5,500/₹12,000 per night from seeded rates, widget launcher visible), `08-landing-mobile.png` (390×844, responsive), `09-landing-logged-in.png` (real login as the demo HOTEL_ADMIN through the landing form — role panel shows "Welcome, Demo Admin — you are signed in as Hotel Admin" with the "Open Hotel Dashboard" button; nav switched to Open Dashboard + Logout). All visually inspected — none blank. |
| Dashboard SPA | untouched (not modified, not rebuilt) |

## Limitations (honest)

- The auto-redirect/dashboard buttons point at the configured
  dashboard URL; in the preview environment the Vite dashboard was not
  running on :5173, so the redirect target itself was not screenshot-
  verified from the landing page (the dashboard was verified separately
  in the v2 preview round). The role panel, button labels, session
  storage, and cancel behaviour were verified live.
- SUPER_ADMIN and STAFF role panels use the same code path as the
  verified HOTEL_ADMIN login (label/button map); only HOTEL_ADMIN was
  exercised end-to-end because the demo seed creates exactly that role.
- The seeded demo hotel has no check-in/check-out times, address, or
  amenities text on its rooms, so those elements correctly do not
  appear in the preview screenshots — they render when the data exists
  (covered by the API tests, which create a fully populated hotel).
- The landing page loads Google Fonts when online and falls back to
  Georgia/system fonts offline; no other external assets.

---

# Addendum — Landing redesign, Nest reference (v4, 2026-10-22)

The public landing page (`frontend/landing/` only — no backend, dashboard,
`/chat`, or widget code touched; backend `.py` tree verified byte-identical
via md5 before/after) was restyled to recreate the visual design of the
reference site **Nest Hostel Lisbon**
(https://nest-hostel-lisbon-228988.hostingersite.com/, home + /rooms
inspected). Nest branding, copy, testimonials, and images were NOT copied —
only its design language, applied to StayFlow's own hotel data.

## Changed files

- `frontend/landing/index.html` — restructured: sticky header with logo
  mark + hamburger, hero with media figure, feature-chips strip, About,
  Rooms (mist band), Experience/services, Offers, Dining (mist band),
  Location & Contact + policies, FAQ, sun final-CTA band, ink footer.
  All element IDs/hooks used by `app.js` preserved.
- `frontend/landing/styles.css` — full rewrite on reference tokens.
- `frontend/landing/app.js` — additive only: image pools + gradient
  fallback helper, hero photo, feature chips from service names, room /
  service card photos, "Ask to book" chat CTA per room (delegated
  `[data-chat-open]` handling), menu price pills, hamburger open/close.
  Auth, hotel resolution, widget embed, and role-panel logic unchanged.

## Design tokens applied

`--paper #FFFFFF`, `--ink #2B2B2B`, `--sun #FFD23F`, `--coral #FF6B6B`,
`--teal #1BA39C`, `--deep-teal #08756F`, `--mist #EFF8F6`,
`--line hsl(0 0% 86%)`, `--radius 1rem` / `--radius-lg 1.5rem`, soft card
shadows. Type: **Barlow Condensed** 500–800 (uppercase display, hero at
`clamp(64px, 7.4vw, 112px)`) + **Nunito Sans** 400–900 body, via Google
Fonts. Caps eyebrows (0.22em tracking) above giant condensed H2s, pill
buttons (sun primary, ink / deep-teal secondary), hover lift on cards,
FAQ accordion with rotating +/× sun badge, focus-visible outlines.

## Images (replacements — verified HTTP 200, image/jpeg, 2026-10-22)

Found via image search; none are the reference site's assets.
- Hero (resort infinity pool at sunset): make-my-trip.fr upload,
  `serene-sunset-at-luxury-infinity-pool-resort.jpg` (source page:
  make-my-trip.fr "plus beaux hôtels 6 étoiles").
- Rooms ×3 (Pexels CDN): photos/20666872 (w=1200), 14025032 (w=1200),
  29702286 (w=940).
- Experience/services ×3 (Pexels CDN): photos/6187269 (spa), 6758532
  (hotel lamps/lobby), 28999499 (restaurant, w=1600).
Any image that fails to load is replaced at runtime by a token-coloured
gradient block — never a broken `<img>`.

## Verification

| Check | Result |
|---|---|
| `node --check frontend/landing/app.js` | OK |
| Backend suite (SQLite e2e DB) | **199 passed, 2 failed, 2 deselected** — identical to the v3 baseline; the 2 failures are the same pre-existing SQLite-environment ones (`test_hotel_crud_and_validation`, `test_ingest_document_creates_chunks_and_embeddings`). Suite run twice (relative and absolute SQLite URLs) with identical results; backend tree is byte-identical, so no regression is attributable to this frontend-only change. |
| Live preview (throwaway create_all DB + seed_demo, mock LLM, Playwright + headless_shell, egress proxy for fonts) | `10-landing-nest-desktop.png` (hero + feature chips + rooms below fold in full-page capture), `11-landing-nest-mobile.png` (390×844, compact header, menu closed), `12-landing-nest-login.png` (real HOTEL_ADMIN login through the landing form — role panel "Open Hotel Dashboard", nav switched to Open Dashboard + Logout). Programmatic checks: 3 room cards, 3 service cards, 3 feature chips, 4 FAQ items, FAQ expands (`aria-expanded=true`), widget launcher present, hamburger toggles `sf-nav-open` + `aria-expanded`, zero page errors. All shots visually inspected. |
| Reference comparison | Reference homepage re-screenshotted at 1440px + 390px into /tmp — the sandbox Chromium renders it blank (its egress proxy refuses the host: `ERR_TUNNEL_CONNECTION_FAILED`; the same block hits every external image host). Comparison was therefore done against the reference's extracted live CSS/HTML spec + full page text (browser fetch), and the design was iterated once against it (compact mobile header; image-fallback pass). |

## Deliberate differences / remaining gaps

- **No testimonials/reviews section** and **no weekly events programme
  with day tabs**: StayFlow has no data source for either, and neither
  was fabricated (the reference itself labels its stories as samples).
- **No cart/checkout, no per-room sub-pages**: booking stays in the
  concierge chat with the existing deterministic confirmation gate;
  room cards carry an "Ask to book" chat CTA instead.
- **No embedded map**: the location section is a styled ink contact card
  (address/phone/email from the API) + policy cards — no fake map pin
  for a hotel whose address may be unset.
- **Sandbox image rendering**: this environment's Chromium egress proxy
  blocks all external image hosts (Pexels, Marriott, Wikimedia, the
  reference's own Hostinger CDN — all ERR), so the preview screenshots
  show the designed gradient fallbacks. The image URLs themselves were
  verified live (HTTP 200, image/jpeg, incl. a cross-origin Referer
  preflight) and load in a normal browser; Google Fonts (allowlisted)
  does render in the shots.
- Section order follows the reference (hero → chips → rooms →
  experience → offers → location → FAQ → CTA band) with Dining kept as
  its own mist band from the existing menu data, and About retained
  from v3 directly after the chips strip.

# Addendum — Landing images localized (v5, 2026-10-22)

Follow-up to v4: the landing page's replacement photography is no longer
hotlinked. All 7 images were downloaded (shell egress; each verified
HTTP 200, real JPEG via `file`, 36 KB–315 KB) into
`frontend/landing/assets/` and `frontend/landing/app.js` now references
them as absolute `/landing/assets/*` paths — served by the existing
`/landing` static mount, so they resolve identically at `/` and at
`/landing/index.html` (both verified live). The gradient `onerror`
fallback is unchanged. No other file changed (backend untouched;
`node --check app.js` OK). Original sources remain as credited in the
v4 section — none are the reference site's assets.

| Local file | Content | Size |
|---|---|---|
| assets/hero.jpg | Resort infinity pool at sunset (make-my-trip.fr upload) | 322,429 B |
| assets/room-1.jpg | Hotel room (Pexels 20666872) | 98,436 B |
| assets/room-2.jpg | Hotel room (Pexels 14025032) | 111,076 B |
| assets/room-3.jpg | Hotel room (Pexels 29702286) | 73,080 B |
| assets/exp-1.jpg | Spa (Pexels 6187269) | 173,322 B |
| assets/exp-2.jpg | Hotel lobby/lamps (Pexels 6758532) | 36,165 B |
| assets/exp-3.jpg | Restaurant (Pexels 28999499) | 245,491 B |

Preview re-taken with the established recipe (throwaway create_all DB +
seed_demo, mock LLM, Playwright + headless_shell) — this time the photos
actually render, because they are same-origin: all 7 `<img>` reported
complete with full natural dimensions and zero page errors.
`~/workspace/your_files/stayflow-preview/13-landing-nest-photos-desktop.png`
(full page: hero pool photo, 3 room photos, experience photos),
`14-landing-nest-photos-mobile.png` (390×844, hero photo visible),
`15-landing-nest-photos-login.png` (HOTEL_ADMIN role panel, hero photo
behind the modal). Delivery ZIP: `stayflow-ai-master-v5.zip` (landing
assets included).

---

# Addendum — Single-service demo deployment prep (v6, 2026-10-22)

Goal: a public demo link. This round is **prep + local verification only —
nothing was committed, pushed, or deployed.** The remaining steps need
Sagar's GitHub/Render login and are listed at the end.

## What was built

- **Dashboard subpath support** (`frontend/dashboard/`): `vite.config.ts`
  reads the base from `VITE_BASE` (default `/`); `App.tsx` passes
  `basename={import.meta.env.BASE_URL…}` to React Router; new script
  `build:demo` → `dist-demo/`. Axios API base stays absolute `/api/v1`.
  Demo build: `VITE_BASE=/dashboard/ npm run build:demo`. The normal
  build (base `/`) is unchanged and re-verified.
- **Demo wrapper** `backend/app/demo_main.py`: imports the real
  `app.main` app unchanged, then (a) replaces only the `GET /` route so
  the landing HTML is served with
  `window.STAYFLOW_DASHBOARD_URL = "/dashboard/"` injected (in-memory;
  committed landing files untouched), (b) serves the dashboard
  `dist-demo` at `/dashboard/` with SPA fallback, (c) with `DEMO_SEED=1`,
  creates tables (`create_all` — demo shortcut; production uses Alembic)
  and seeds via `scripts/seed_demo.py` when the hotels table is empty.
  Seeded demo admin: `admin@stayflowgrand.example` / `Preview@123`
  (**demo-only**, via `SEED_ADMIN_PASSWORD`).
- **`Dockerfile.demo`** (repo root): multi-stage — Node 20 stage builds
  the dashboard inside the image (`VITE_BASE=/dashboard/ npm run
  build:demo`), uv stage installs locked backend deps, slim runtime
  serves `app.demo_main` on `${PORT:-8000}`. Production
  `backend/Dockerfile` and `docker-compose.yml` untouched.
- **`render.yaml`**: free web service, Docker runtime, health check
  `/api/v1/health`, env: `DEMO_SEED=1`, mock providers, hashed
  embeddings, `JWT_SECRET_KEY` generated, SQLite demo DB.
  **`ENVIRONMENT=demo`, deliberately not `production`**: the config
  validator (correctly) refuses production boot with SQLite and without
  Telegram/Twilio production secrets; a throwaway mock demo must not
  pretend to be production. `.env.demo.example` + `docs/DEMO_DEPLOY.md`
  document the whole flow.

## Local verification (demo wrapper on :9000, throwaway SQLite, DEMO_SEED=1)

| Check | Result |
|---|---|
| `GET /` | 200, HTML contains `STAYFLOW_DASHBOARD_URL = "/dashboard/"` |
| `GET /api/v1/health` | 200 `{"status":"ok",…}` |
| `GET /landing/assets/hero.jpg` | 200 |
| `GET /dashboard/` + its JS asset | 200 / 200 (assets under `/dashboard/assets/`) |
| `GET /dashboard/login`, `/dashboard/orders` | 200, SPA index fallback |
| `GET /chat/` · `/widget.js` · `/docs` | 200 · 200 · 200 (original handlers win) |
| `GET /api/v1/public/featured-hotel/landing` | 200, seeded hotel (auto-seeded on boot) |
| Login API + same-origin dashboard login (Playwright) | token issued; UI login reached the overview — screenshot `17-deploy-demo-dashboard.png` shows "StayFlow Grand Hotel — today", Demo Admin (hotel_admin) signed in |
| Screenshots | `16-deploy-demo-landing.png`, `17-deploy-demo-dashboard.png` in `stayflow-preview/` |
| Backend suite | **199 passed, 2 failed, 2 deselected** — the 2 failures are the same pre-existing SQLite-environment ones; zero regressions. `ruff check` + format clean for the new module; `node --check` landing `app.js` OK; **both** dashboard builds (`build`, `build:demo`) compile |

## Remaining steps (need Sagar)

1. Commit + push the repo to GitHub (agent made **no** commit/push).
2. render.com → New → Blueprint → connect the repo → deploy (free plan:
   sleeps when idle; SQLite re-seeds on fresh boots — fine for a demo).
3. Open the Render URL, log in with the demo admin, share the link.

`frontend/dashboard/dist-demo` is a build artifact and is **excluded**
from the delivery ZIP — `Dockerfile.demo` rebuilds it in its Node stage,
so source-only deploys work.

---

# Bugfix — chat display + mock booking flow (2026-10-22)

Two bugs reported from the live demo (dashboard screenshots):

1. **Staff transcript leaked raw tool JSON.** The agent runner persists
   its tool traces as `TOOL_CALL` / `TOOL_RESULT` message rows (they are
   the agent's own history). The staff endpoint
   `GET /conversations/{id}/messages` returned every row, so the
   dashboard rendered `{"tool": "search_faq", ...}` as chat bubbles.
   **Fix:** the endpoint now returns only `message_type == "TEXT"` rows
   (guest, agent, and staff replies are all TEXT; the staff POST already
   writes TEXT). The runner's history path (`conversation_store
   .get_history`, used by `_history_messages`) is deliberately NOT
   filtered — the agent still sees its tool rows. Dashboard
   defense-in-depth: `ConversationDetail` also drops TOOL_CALL /
   TOOL_RESULT rows client-side before rendering.
2. **Mock AI lost the booking conversation.** A bare date reply
   (`23/11/2026`) after "ok book it" fell into the FAQ no-answer
   fallback ("I don't have an answer for that yet… front desk?").
   **Fix (mock provider only):**
   - `_extract_dates` now parses day-first numeric dates
     (23/11/2026, 23-11-2026, 23.11.2026 — Indian locale), month names
     (23 Nov 2026 / Nov 23, 2026), "today", plus the existing ISO and
     "tomorrow"; invalid dates (31/02/2026) are skipped.
   - Slot carryover: `_gather_booking_slots` collects room / dates /
     guest count from all guest messages in the conversation.
   - Pending-booking guard (router step 2b): when a booking is in
     progress (list_rooms shown, or the agent asked for details /
     identity, and nothing previewed yet) and the reply carries slot
     info, the agent completes the slots via the shared
     `_continue_booking` (preview → guest lookup → identity ask) or asks
     ONLY for the missing pieces (e.g. "I've noted check-in:
     2026-11-23. I still need: room type, check-out date."). It never
     routes such a reply to `search_faq`. The deterministic
     preview → confirm → create_booking gate is unchanged.

**Tests:** new `backend/tests/test_chat_bugfixes.py` (4 tests — date
formats, staff filter vs. agent history, carryover-to-preview flow with
confirmation gate, pending-guard missing-pieces flow). Suite:
**203 passed / 2 failed / 2 deselected** (baseline 199/2/2; the 2
failures are the same pre-existing SQLite-environment ones —
`test_hotel_crud_and_validation`, `test_ingest_document_creates_chunks
_and_embeddings`). `ruff check` + `ruff format --check` clean; dashboard
`npm run build` and `npm run build:demo` both pass.

**Live smoke** (public chat API, mock provider, demo seed): "i want an
room" → room list; "ok book it" → asks room type + dates; "23/11/2026"
→ "I've noted check-in: 2026-11-23. I still need: room type, check-out
date."; "Deluxe King Room, check-out 25/11/2026" → identity ask (slots
completed across turns).

Note: the fixes take effect on the live Render demo only after the
parent pushes this commit and Render redeploys.

# Real AI + Neon switch — prepared 2026-10-22

Status: **prepared locally, NOT pushed.** The live demo still runs
mock + ephemeral SQLite until the parent pushes this change and Sagar
pastes the two dashboard secrets (below); live verification is pending
that push.

What changed:

- **render.yaml:** `LLM_PROVIDER`/`AGENT_PROVIDER` flipped from `mock`
  to `inception` (real Mercury). `INCEPTION_API_KEY` and `DATABASE_URL`
  are now declared with `sync: false` (values live only in the Render
  dashboard — the SQLite literal is gone). `ENVIRONMENT=demo`,
  `DEMO_SEED=1`, `JWT_SECRET_KEY generateValue`,
  `EMBEDDING_PROVIDER=hashed`, `SEED_ADMIN_PASSWORD`, free plan and the
  `Dockerfile.demo` path are unchanged. `.env.demo.example` mirrors the
  new variable set with placeholders and Neon/Inception notes.
- **app/demo_bootstrap.py (new):** the `DEMO_SEED=1` bootstrap moved out
  of `app/demo_main.py` into small testable functions. On PostgreSQL it
  runs the Alembic migrations to head **in-process** (bare
  `alembic.config.Config` + explicit `script_location`; the URL comes
  from settings — `alembic/env.py` re-derives the same normalized
  `sqlalchemy.url` from `get_settings()`, one source of truth), then
  seeds only if the hotels table is empty. Migration failure raises —
  startup fails loudly rather than serving a half-migrated database.
  On SQLite the original `create_all` + seed-if-empty shortcut is
  unchanged. Re-running against a migrated, seeded Neon database is a
  no-op, and data now persists across restarts/redeploys.
- **DATABASE_URL normalization:** Neon hands out bare
  `postgresql://…?sslmode=require` URLs, but the project ships psycopg
  v3 only. `normalize_database_url` in `app/core/config.py` rewrites
  `postgres://` / bare `postgresql://` to `postgresql+psycopg://`
  (query string intact; already-qualified and SQLite URLs untouched),
  applied by a `Settings` field validator — the single point the app
  engine, the Alembic env and the demo bootstrap all read.
- **Docs:** `docs/DEMO_DEPLOY.md` rewritten for the Neon + Mercury flow
  (Neon project → copy the **direct** connection string with pooling
  off → paste `DATABASE_URL` + `INCEPTION_API_KEY` into Render → first
  boot migrates + seeds; persistence and free-tier spin-down notes).
  Stale header comments in `Dockerfile.demo` updated to match.

Tests: new `backend/tests/test_demo_bootstrap.py` (15 tests — normalizer
parametrized cases incl. pass-through and idempotency, Settings-level
application, and the branch with faked migrate/create_all/count/seed
steps: Postgres migrates + never create_alls, SQLite create_alls +
never migrates, seed skipped when hotels exist, migration failure
propagates and the seed never runs). Full suite on the sandbox's
SQLite: **217 passed / 3 failed / 2 deselected** (baseline measured
before this change: 203/2/2). The 15 new tests all pass and no test
that passed in the baseline broke for a code reason; the third failure
is `test_concurrent_bookings_cannot_oversell_last_room`, a two-thread
race test that is timing-marginal on SQLite (no row locking — the
loser's oversell window is pure thread interleaving). During
verification it flipped both ways across full-suite runs and was shown
to flip even when the ONLY change was adding a content-free dummy test
file (15 trivial asserts, no app imports), i.e. any suite-composition
perturbation moves it; it passes in isolation, and on PostgreSQL (CI)
`SELECT … FOR UPDATE` makes it deterministic. Live smokes in the
sandbox: the rewired `DEMO_SEED=1` SQLite boot ran create_all + the
real seed end-to-end (1 hotel; second boot logged "already present,
skipping seed"), and the PostgreSQL branch entered `run_migrations`
and raised `sqlalchemy.exc.OperationalError` loudly against an
unreachable server — never a silent fallback. (No live Neon run is
possible from the sandbox; first real boot happens on Render after the
push + secret paste.) `ruff check` and `ruff format --check` clean.

Pending (parent + Sagar): push; Sagar creates the Neon project and
pastes `DATABASE_URL` + `INCEPTION_API_KEY` into the Render dashboard;
then verify live (health, Mercury chat reply, data surviving a
redeploy).

# Enhancement pack 2026-10-22

Five items on top of the live Mercury + Neon build (218 passed baseline).
All local; push/deploy is the parent's step.

## 1. Real-LLM answer quality (`backend/app/agent/prompts.py`)

The live Mercury agent answered a pool question with "I don't have
access to specific hotel details… could you please provide your hotel
ID?" — the system prompt now forbids exactly that. `build_system_prompt`
gained two blocks ahead of the existing rules (booking gate, tool
registry, mock provider untouched):

- **Identity**: the agent is the concierge for THIS already-identified
  hotel; it must NEVER ask for a hotel ID/name or claim it lacks access
  to the hotel's details — facts come from its tools.
- **Tools first, always**: any hotel-specific question (amenities,
  timings, policies, services, menu, offers, rooms, prices) must call
  the matching real tool before answering — `search_faq`,
  `get_hotel_policy`, `get_services`, `get_offers`, `get_menu`,
  `list_rooms`/`get_room_details`, `search_hotel_knowledge`. The front
  desk may be offered only when tools genuinely return nothing.
- **Language**: the existing "answer in the guest's language" rule now
  names Hindi/Hinglish explicitly.
- Also fixed a stale tool name in the price rule (`room_rate` →
  `get_room_rate`, the registered name).

Test: `test_system_prompt_grounds_agent_in_the_identified_hotel`
(tests/test_prompt_injection.py) asserts the directives and tool names.

## 2. Landing services photos matched by service, not position

`frontend/landing/app.js` no longer cycles `exp-1/2/3` by card index
(which put the spa photo on the Airport Shuttle card). A
`SERVICE_IMAGE_RULES` keyword table over name+category+description maps:
spa/wellness/massage → exp-1 (spa), restaurant/dining/food → exp-3
(restaurant), shuttle/transfer/airport/taxi → **exp-transport.jpg**
(new: white minivan at an airport terminal, Pexels 39075475, verified
HTTP 200, JPEG 1200×800, 93,796 B), pool/swim → hero.jpg (pool),
lobby/reception → exp-2 (lobby). No match (e.g. Laundry) → the same
gradient fallback figure the error path uses; layout unchanged.
Verified with `node --check` + a node harness running the seeded
services through the extracted rules: Airport Shuttle →
exp-transport.jpg, Spa Session → exp-1.jpg, Laundry → fallback.

## 3. Demo seed: complete hotel details (`backend/scripts/seed_demo.py`)

The seeded hotel now carries address (12, Pearl Tower, C-Scheme,
Jaipur, Rajasthan 302001), phone (+91 141 400 2233), email
(reservations@stayflowgrand.example), check_in_time 14:00,
check_out_time 11:00 — fresh installs render the landing's contact and
policies sections instead of hiding them. Creation defaults only (the
seed's natural-key idempotency is unchanged); verified by running the
seed against a throwaway DB and reading the row back.

## 4. Telegram bot: paste-only activation

The webhook route (`POST /api/v1/webhooks/telegram/{hotel_id}`,
`X-Telegram-Bot-Api-Secret-Token` verified) already existed; activation
is now three dashboard pastes:

- `render.yaml`: `APP_PUBLIC_BASE_URL` (value: the demo URL — public),
  `TELEGRAM_BOT_TOKEN` and `TELEGRAM_WEBHOOK_SECRET`, both
  `sync: false`. `.env.demo.example` mirrors them (commented).
- `app/bots/telegram.py`: new `set_webhook()` — same never-raises
  contract as `send_message`, passes `secret_token` through.
- `app/main.py` lifespan: `_register_telegram_webhook()` — acts only
  when token + secret + base URL are ALL set (no token → returns before
  any network/DB work, so local runs and tests are unaffected);
  registers `{APP_PUBLIC_BASE_URL}/api/v1/webhooks/telegram/{lowest
  hotel id}` (one bot token owns one webhook URL; a warning is logged
  when several hotels share the deployment); idempotent; every failure
  is a logged warning, never a boot crash. Config validators verified:
  the production secret rules fire only for ENVIRONMENT=production, so
  `demo` + a Telegram token boots clean.
- Docs: `docs/DEMO_DEPLOY.md` gained the BotFather walkthrough
  (create bot → token → generate secret → paste both in Render →
  automatic registration on boot; test by messaging the bot).
- Tests: `tests/test_telegram_activation.py` (6) — registration with
  the exact URL + secret when configured (httpx faked), no call without
  a token, boot survives a Telegram outage, `set_webhook` unit
  behaviour, demo-env config validation.

## 5. Semantic embeddings — resilient, but NOT flipped on the free tier

`app/knowledge/embeddings.py`: new `ResilientEmbeddingProvider` —
wraps the semantic provider; the first load/encode failure is logged
once and *cached*, and the process serves hashed embeddings from then
on (no retry-storm). `default_embedding_provider()` now returns
`SentenceTransformerEmbedding` inside this wrapper for
`EMBEDDING_PROVIDER=sentence-transformer`; `hashed` stays the code
default and the demo's setting. One existing assertion
(`test_default_embedding_provider_selection`) was updated to the new
wrapper type; new `tests/test_embeddings_fallback.py` (3 tests) covers
fallback engagement, failure caching, dimension fallback and clean
pass-through.

Local verification (backend venv, real model, this sandbox): the model
loads lazily (construct peak RSS 52 MB), embeds correctly (384-dim;
"Do you have a swimming pool?" → pool text at cosine 0.517, far above
the runner-up 0.169), single embeds after load are ~0.01 s — but the
**embedding process alone peaks at 501 MB RSS (current 499 MB)** after
the first `embed_many` (~35 s incl. the one-time ~90 MB download).
That leaves no headroom for uvicorn + FastAPI + SQLAlchemy on a
512 MB instance. **Decision: do NOT flip** — `render.yaml` keeps
`EMBEDDING_PROVIDER=hashed`. On a larger instance the flip is a one-line
env change, and the new fallback guarantees a failed model load degrades
to hashed instead of bricking the site. (Known pre-existing caveat,
unchanged: corpora are dimension-bound — re-ingest after any provider
switch.)

## Tests

Full suite, mandated recipe (`DATABASE_URL=sqlite:///./stayflow_e2e.db`):
baseline **218 passed / 2 failed / 2 deselected** → after the pack
**228 passed / 2 failed / 2 deselected**. The 2 failures are the same
pre-existing SQLite-env ones (`test_hotel_crud_and_validation`,
`test_ingest_document_creates_chunks_and_embeddings`); zero
regressions; +10 new tests (1 prompt, 6 telegram, 3 embeddings).
`ruff check` + `ruff format --check` clean. Dashboard untouched (no
rebuild needed); landing change is JS-only plus one new asset.

---

## Addendum — DB request hangs on Render + Neon (2026-10-23)

**Symptom (live):** DB-backed requests (login, chat) hung forever on the
Render + Neon deployment while non-DB routes (health, static) answered
instantly. Render logs showed the hung requests producing **zero
errors** — they never failed, they just never returned. When Neon
force-terminated one connection (`psycopg AdminShutdown`), that request
500'd and subsequent requests on fresh connections worked again —
pointing at dead pooled connections, not app logic. Ruled out by the
logs/timing: the in-memory rate limiter (instant), argon2 hashing, and
the LLM call.

**Root cause:** `backend/app/database.py` created the engine bare —
`create_engine(settings.database_url)` with no `pool_pre_ping`, no
`pool_recycle`, no timeouts anywhere. Neon is serverless: its compute
suspends after ~5 idle minutes and kills/recycles open connections,
while the app process stays awake (health checks do not touch the DB),
so the pool filled with dead psycopg sockets. The next DB request
checked out a dead connection, sent its query into the void, and waited
forever.

**Fix (`backend/app/database.py` only):** a small `_engine_options(url)`
helper applies hardening for PostgreSQL URLs only (SQLite/test behaviour
byte-identical): `pool_pre_ping=True` (dead pooled connections are
detected and replaced before use), `pool_recycle=180` (recycle every
3 min, inside Neon's idle window), and psycopg v3 `connect_args` —
`connect_timeout=10`, TCP keepalives (`keepalives=1`,
`keepalives_idle=60`, `keepalives_interval=10`, `keepalives_count=5`),
and `options="-c statement_timeout=60000"` so a stuck query fails
server-side in 60 s instead of hanging forever. `app/database.py` is the
single engine creation point (`app/db/session.py` imports this engine);
Alembic's `env.py` one-shot engine is intentionally untouched (it opens
a fresh connection per migration run, so pooling hazards do not apply).
`test_connection()` unchanged and working.

**Tests:** 5 new tests in `backend/tests/test_database.py` — SQLite URLs
get no options; PostgreSQL options carry the exact pre-ping/recycle/
timeout/keepalive values; a lazily-created PostgreSQL engine's pool
introspects as `_pre_ping=True`, `_recycle=180` (no live connection);
the app's SQLite engine still executes against the e2e DB. Full suite,
mandated recipe: **233 passed / 2 failed / 2 deselected** vs baseline
228/2/2 — the 2 failures are the same pre-existing SQLite-env ones,
zero regressions. Ruff check + format clean. Not yet pushed/deployed —
first live boot on Render + Neon is the final verification (watch the
first DB request after a >5 min idle gap).
