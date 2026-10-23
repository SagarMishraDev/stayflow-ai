# Render keep-alive (health pings)

StayFlow's demo runs on Render's **free tier**, which spins the web
service down after roughly **15 minutes without inbound traffic**. The
next visitor then waits through a cold start (commonly 30–60s+). A
small periodic request to the health endpoint keeps the service warm.

## Health endpoint

Already implemented — no new endpoint was added:

```
GET /api/v1/health
→ 200 {"status": "ok", "service": "StayFlow AI", "version": "0.1.0"}
```

The handler (`app/api/router.py`) returns static application metadata
only: it runs **no database query**, modifies nothing, and exposes no
secrets or environment details. A separate authenticated `GET
/api/v1/db-check` exists for database readiness and is deliberately
NOT used for keep-alive (it needs a JWT and touches the DB).

Verify it any time:

```bash
curl -i https://<your-service>.onrender.com/api/v1/health
```

## The keep-alive script

`backend/scripts/keep_render_awake.py` — standard library only.

| Env var | Required | Meaning |
| --- | --- | --- |
| `KEEP_ALIVE_URL` | yes | Full public health URL, e.g. `https://<your-service>.onrender.com/api/v1/health`. The script exits with an error when unset — no URL is hardcoded. |
| `KEEP_ALIVE_INTERVAL_MINUTES` | no | Ping interval; default **12**, clamped to 5–30. |

Run it locally (or on any always-on machine):

```bash
cd backend
KEEP_ALIVE_URL=https://<your-service>.onrender.com/api/v1/health \
  .venv/bin/python scripts/keep_render_awake.py
# one-shot (for cron): add --once
```

Each cycle makes exactly **one** request (30s timeout, no retry
storm) and logs one line — timestamp, status, latency — e.g.:

```
[2026-10-23T05:00:01+00:00] GET https://…/api/v1/health -> 200 in 212 ms
```

Stop with Ctrl+C or SIGTERM; the loop exits cleanly.

## The honest limitation

**A script running inside the Render service cannot keep that service
awake.** When the free-tier service spins down, every process in it —
including any in-app loop or background thread — is frozen with it.
That is why this project deliberately does **not** add a keep-alive
loop to the web server startup, a background worker, or the Docker
image. The pinger must live **outside** the service.

## External scheduler options (pick one)

1. **Muse cron pinger (already set up for this project)** — a
   scheduled job in the owner's Muse setup requests the health URL on
   the configured interval. Nothing to install; disable by pausing or
   deleting that job.
2. **cron-job.org** (free) — create a job hitting
   `https://<your-service>.onrender.com/api/v1/health` every 10–14
   minutes.
3. **UptimeRobot** (free tier) — an HTTP(s) monitor on the same URL
   with a 5-minute interval doubles as uptime alerting.
4. **Your own always-on machine / VPS cron**:

   ```cron
   */12 * * * * KEEP_ALIVE_URL=https://<your-service>.onrender.com/api/v1/health /path/to/backend/.venv/bin/python /path/to/backend/scripts/keep_render_awake.py --once >> /var/log/stayflow-keepalive.log 2>&1
   ```

## Verifying it works

- `curl` the health URL: a warm service answers in well under a
  second; a cold one takes noticeably longer on the first hit.
- Watch the pinger's log lines — every cycle should show `-> 200`.
- In the Render dashboard, the service's **Logs**/**Metrics** show the
  regular inbound `GET /api/v1/health` requests and no spin-down gaps.

## Disabling

Stop the external scheduler (pause/delete the cron job or monitor).
Nothing inside the application needs to change — the health endpoint
is a normal, harmless route used by Render's own health checks too.

## Alternatives

The only way to remove spin-down entirely is a paid Render plan
(always-on instance). That is a billing decision for the service
owner; this setup changes no plan, adds no paid service, and does not
promise to bypass Render's platform limits — it simply keeps a free
service warm with regular, permitted health pings.
