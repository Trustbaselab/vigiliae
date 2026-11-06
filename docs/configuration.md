# Configuration

Vigiliae reads environment variables from the process environment and from a
`.env` file in the working directory.

**Precedence:** real env vars override `.env` values.

---

## Minimal config

```bash
# .env — the absolute minimum to boot
BOT_TOKEN=change_me_to_a_random_string
```

That is enough to start the runtime and the 7 non-LLM agents.

---

## Full reference

### Runtime

| Variable | Default | Description |
|---|---|---|
| `VIGILIAE_PORT` | `8110` | HTTP listen port. If busy, the installer auto-picks `8111`, `8112`… |
| `VIGILIAE_HOST` | `127.0.0.1` | Bind address. Set `0.0.0.0` to expose on the network (put a proxy in front). |
| `VIGILIAE_DATA_DIR` | `./data` | Where the SQLite DB, run logs, agent reports and memory live. |
| `VIGILIAE_LOG_LEVEL` | `info` | `debug` · `info` · `warn` · `error` |

### Authentication

| Variable | Default | Description |
|---|---|---|
| `BOT_TOKEN` | *(none)* | Shared secret. First request must carry `?k=<BOT_TOKEN>`. **Required if the runtime is reachable from anywhere except localhost.** |
| `BOT_TOKEN_FILE` | *(none)* | Alternative: read the token from a file (one line). Keeps it out of env dumps. |

### Thinking kernel (LLM)

The kernel is the "brain" the LLM-backed agents call. It is a CLI that takes a
prompt on stdin and returns text on stdout.

| Variable | Default | Description |
|---|---|---|
| `DSH_BIN` | `dsh` | Path to the kernel binary. |
| `DSH_PROFILE` | `headless` | Which profile to boot. |
| `DEEPSEEK_API_KEY` | *(none)* | Required for LLM agents to run. PHP-style rules reject a missing key rather than silently degrade. |
| `LLM_TIMEOUT_SEC` | `120` | Per-call timeout. |
| `LLM_MAX_TOKENS` | `4096` | Per-call output cap. |

**If `DEEPSEEK_API_KEY` is missing**, the 4 LLM agents report `failed` with
"thinking kernel not configured" and the 8 rule agents continue normally. This is
deliberate — the runtime never pretends an agent succeeded when the brain is absent.

### Handoff

| Variable | Default | Description |
|---|---|---|
| `HEARTBEAT_TIMEOUT_SEC` | `300` | How long without a local heartbeat before the cloud instance declares takeover. |
| `HEARTBEAT_INTERVAL_SEC` | `60` | How often the local agent writes a heartbeat. |

### Pricing windows

The scheduler moves heavy runs into the off-peak window automatically.

| Variable | Default | Description |
|---|---|---|
| `PRICE_PEAK_START` | `08:30` | Peak window start (local time). |
| `PRICE_PEAK_END` | `22:30` | Peak window end. |
| `PRICE_RATIO_PEAK` | `1.0` | Relative cost during peak. |
| `PRICE_RATIO_OFFPEAK` | `0.5` | Relative cost off-peak. |

### Subprocess safety

| Variable | Default | Description |
|---|---|---|
| `RUN_TIMEOUT_SEC` | `300` | Hard kill for a single agent run. |
| `MAX_CONCURRENT_RUNS` | `4` | Parallel run cap. |
| `SANDBOX_CWD` | `$VIGILIAE_DATA_DIR/work` | Working directory given to agent subprocesses. |

### Notifications (optional)

Push results out via a bot channel. Wire your own endpoint in `nuntius.py`; the
two env vars below are what the built-in messenger reads.

| Variable | Default | Description |
|---|---|---|
| `NOTIFY_URL` | *(none)* | POST endpoint. |
| `NOTIFY_TOKEN` | *(none)* | Bearer token for that endpoint. |

---

## `.env.example`

The repo ships a working `.env.example`. Copy it:

```bash
cp .env.example .env
$EDITOR .env                     # at minimum: set BOT_TOKEN
```

---

## Docker

`docker-compose.yml` binds `.env` into the container; all variables above work the
same way. The data directory is a named volume — do not delete it, that is your
whole database.

```bash
cp .env.example .env
docker compose up -d
docker compose logs -f
```

---

## Security checklist (read before exposing to the internet)

- [ ] `BOT_TOKEN` set to a long random string (`openssl rand -hex 32`)
- [ ] `VIGILIAE_HOST=127.0.0.1` **or** a reverse proxy with TLS + auth in front
- [ ] `VIGILIAE_DATA_DIR` not world-readable (`chmod 700`)
- [ ] `.env` not committed to git (already in `.gitignore`)
- [ ] `DEEPSEEK_API_KEY` has a spending cap on the provider side
- [ ] Agent `write_perm` reviewed — every agent that can write files should have `need_approve: 1` unless you know exactly what it does

---

## Diagnostics

```bash
# Which variables did the process actually pick up?  (values redacted)
python -m vigiliae.report --config

# Is the kernel reachable?
$DSH_BIN --version

# Which port did it really bind to?
curl -s "http://localhost:${VIGILIAE_PORT:-8110}/api/status"
```

---

*Last updated: 2026-11-06 · matches Vigiliae v0.3.x*
