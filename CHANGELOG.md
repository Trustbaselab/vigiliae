# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.0] - 2026-10-27

First public snapshot. This is an extraction of an internal tool that has been
running on a single 4-core VPS, not a rewrite.

### Added
- SQLite-backed task queue with cron / interval schedules and manual runs.
- Executors for `shell`, `http`, `python`, and `agent` (prompt via a CLI).
- Local ↔ cloud handover: heartbeat table, takeover state, `exec_pref` routing.
- Off-peak price-slot guard: heavy jobs are deferred during peak windows.
- Rule engine for zero-token answers (`status`, `tasks`, `runs`, `price`,
  `agents`, `inspect`, `help`).
- `agents.yaml` loader + `python -m vigiliae.agents sync` to register agents
  as scheduled tasks.
- Token login (URL token → HttpOnly cookie) for mobile browsers, including
  WeChat's in-app browser.
- Mobile-first chat UI and JSON API (`/api/messages`, `/api/brief`,
  `/api/whatsnew`, `/api/price_slot`, `/api/deferred`, `/api/handover`).
- Approval gate for tasks marked `need_approve`.
- Optional reporting to an external task bus.
- Dockerfile + docker-compose, systemd and nginx deployment notes.

### Known limitations
- Single-node only (SQLite). No horizontal scaling.
- One maintainer. No formal test suite yet (the original deployment is tested
  by the agents themselves against a regression suite).
- The `agent` executor expects a CLI with the shape
  `dsh --profile headless "<prompt>"`; adapt `vigiliae/bridge.py` for others.
