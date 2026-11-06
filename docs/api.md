# API Reference

All endpoints are served by the Vigiliae runtime (default `http://localhost:8110`).
Responses are JSON unless noted otherwise.

**Authentication:** the first request must carry `?k=<BOT_TOKEN>`. The app then sets
an `HttpOnly` cookie and subsequent requests need no token. API calls with a valid
`?k=` return `200` directly; browser UI redirects so the cookie can be set.

---

## Base

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Web console (HTML) |
| GET | `/api/health` | Liveness probe |

---

## Tasks

### `GET /api/tasks`

List all registered agents and their last run state.

```json
{
  "ok": true,
  "local_online": false,
  "tasks": [
    {
      "id": "agent_taeda",
      "name": "Taeda",
      "kind": "python",
      "enabled": 1,
      "last_status": "ok",
      "last_run_at": "2026-11-06 23:11:43",
      "fail_count": 0
    }
  ]
}
```

**Fields**

| Field | Type | Meaning |
|---|---|---|
| `id` | string | `agent_<slug>` |
| `name` | string | Display name |
| `kind` | string | `python` · `http` · `agent` |
| `enabled` | int | `1` = active, `0` = paused |
| `last_status` | string | `ok` · `failed` · `running` · `null` |
| `last_run_at` | string | Server-local timestamp |
| `fail_count` | int | Consecutive failures |

### `POST /api/tasks/<agent_id>/run`

Trigger one run of the agent immediately.

```json
{
  "ok": true,
  "result": {
    "run_id": 6142,
    "status": "ok",
    "duration_ms": 79,
    "exit_code": 0,
    "stdout": "taeda: status written\n",
    "stderr": "",
    "report": "/opt/.../data/team/taeda/latest.json"
  }
}
```

**Errors:** `404` unknown agent · `409` agent already running · `403` disabled.

---

## Status

### `GET /api/status`

Overall runtime status — the cheapest "is it alive" endpoint.

```json
{
  "ok": true,
  "dev_mode": true,
  "role": "cloud_takeover",
  "local_online": false,
  "local_heartbeat_ago_sec": null,
  "server_time": "2026-11-06 23:12:06",
  "tasks": { "enabled": 12, "total": 12 },
  "runs": { "total": 6178, "failed": 152 },
  "pending_approvals": 2,
  "pricing": {
    "is_peak": false,
    "label": "off-peak (half price)",
    "seconds_until_change": 35273
  },
  "thinking_kernel": { "configured": true }
}
```

---

## Runs

### `GET /api/runs`

Recent run log (default last 50).

```json
{
  "ok": true,
  "runs": [
    {
      "run_id": 6178,
      "task_id": "agent_hesperus",
      "status": "ok",
      "trigger": "scheduled",
      "started_at": "2026-11-06 23:11:43",
      "finished_at": "2026-11-06 23:11:43",
      "duration_ms": 7,
      "exit_code": 0,
      "stdout": "...",
      "stderr": ""
    }
  ]
}
```

**Query params:** `?limit=N` (max 500) · `?task_id=agent_xxx` · `?status=failed`

---

## Approvals

Approvals are the human-in-the-loop gate. Agents with `need_approve: 1` cannot
perform a write action until a pending approval is decided.

### `GET /api/approvals`

```json
{
  "ok": true,
  "approvals": [
    {
      "id": 2,
      "task_id": "agent_sator",
      "status": "pending",
      "requested_at": "2026-11-06 20:30:00",
      "decided_at": null,
      "note": null
    }
  ]
}
```

**Fields**

| Field | Meaning |
|---|---|
| `status` | `pending` · `approved` · `rejected` |
| `requested_at` | When the agent asked |
| `decided_at` | When a human decided (`null` while pending) |
| `note` | Human-supplied reason |

### `POST /api/approvals/<id>/decide`

```bash
curl -X POST "http://localhost:8110/api/approvals/2/decide?k=$BOT_TOKEN" \
     -H 'Content-Type: application/json' \
     -d '{"decision":"approve","note":"ok to write"}'
```

`decision` must be `approve` or `reject`. Returns `409` if already decided.

---

## Handoff

### `GET /api/handover`

Local↔cloud handoff state.

```json
{
  "local_online": false,
  "last_heartbeat_ago_sec": null,
  "takeover": true
}
```

`takeover: true` means the cloud instance has taken over because no local
heartbeat arrived within the timeout window.

---

## Pricing

### `GET /api/price_slot`

Current API price window and when it flips.

```json
{
  "ok": true,
  "is_peak": false,
  "label": "off-peak (half price)",
  "price_ratio": 0.5,
  "seconds_until_change": 35273,
  "next_offpeak": null,
  "rule": "22:30-08:30 off-peak",
  "server_time": "2026-11-06 23:12:06"
}
```

---

## Deferred queue

### `GET /api/deferred`

Runs postponed because they were outside their allowed window.

```json
{ "ok": true, "count": 0, "items": [] }
```

---

## Error format

Every error returns the same shape:

```json
{ "ok": false, "error": "human readable reason", "code": "SOME_CODE" }
```

| HTTP | When |
|---|---|
| 400 | Malformed input |
| 401 | Missing/invalid token |
| 403 | Agent disabled or read-only |
| 404 | Unknown agent / approval / run |
| 409 | Conflict (already running / already decided) |
| 500 | Internal error (see server log) |

---

## Rate limits

None built in. If you expose the runtime to the internet, put it behind a
reverse proxy with basic auth and rate limiting.

---

*Last updated: 2026-11-06 · matches Vigiliae v0.3.x*
