# Writing agents

An agent is a YAML object that becomes a scheduled task. There is no separate
agent runtime: `python -m vigiliae.agents sync` upserts one row per agent into
`tasks` with `kind="agent"`, and the executor sends the prompt to the thinking
kernel.

## File layout

```yaml
team:
  name: "My Cloud Team"
  orchestrator: "briefer"     # free-form; shown in the UI
  report_to: "local"          # free-form

agents:
  - name: "scout"
    role: "Data collection & QA"
    description: "One line for the UI."
    schedule: "cron:0 20 * * *"
    timeout: 1800
    heavy: true
    enabled: true
    boundaries:
      allow: ["...", "..."]
      deny: ["...", "..."]
    prompt: |
      Multi-line prompt goes here.
```

The file is read from `VIGILIAE_AGENTS` (default `./agents.yaml`).

## Field reference

| Field | Required | Default | Meaning |
|---|---|---|---|
| `name` | ✅ | — | Short id. Task id becomes `agent_<name>`. |
| `role` | — | `name` | Human-readable title. |
| `description` | — | empty | Shown by `GET /api/agents` and the chat `agents` command. |
| `schedule` | — | manual | `cron:...`, `every:N`, or empty for manual-only. |
| `timeout` | — | `1800` | Seconds before the kernel call is killed. |
| `heavy` | — | `true` | Defer to off-peak when firing in a peak window. |
| `enabled` | — | `true` | If false, the task is created but paused. |
| `boundaries.allow` | — | `[]` | Injected into the prompt as "allowed". |
| `boundaries.deny` | — | `[]` | Injected into the prompt as "forbidden". |
| `prompt` | ✅ | empty | The actual instruction. Treat it as code. |

## Scheduling syntax

| Syntax | Meaning | Example |
|---|---|---|
| `cron:M H D Mo W` | five-field cron, local time | `cron:0 8 * * *` (daily 08:00) |
| `every:N` | every N seconds | `every:3600` |
| empty | manual only | `""` |

Supported cron features: `*`, `*/N`, lists `1,3,5`, ranges `1-5`. Weekday
`0`/`7` = Sunday (the implementation uses `isoweekday() % 7`).

There is no timezone database: everything uses `VIGILIAE_TZ_OFFSET` (default
UTC+8). Run one Vigiliae per timezone, or adjust the offset.

## Boundaries: prompt vs runtime

The `allow`/`deny` lists are inserted into the prompt, which helps a compliant
model. They are **not** the security boundary. The runtime adds:

- `write_perm=0` on the task row → dangerous shell patterns are blocked;
- `need_approve=1` → the run is parked until approved;
- `timeout` → the subprocess is killed.

If an agent needs to write data, do not give it a shell task that writes
directly. Give it a narrow HTTP endpoint or a Python task that calls a
validated write path. This is the same principle as "least privilege for
service accounts".

## Writing a good prompt

A useful pattern for operations agents:

```
TASK
1. ...
2. ...

BOUNDARIES
- Every claim must have a URL.
- If you cannot verify it, say "not found". Do not guess.
- Never modify data.

REPORT (under N words)
- what changed
- what failed
- what the operator should do next
```

Three rules that matter more than prompt style:

1. **Make "I don't know" an acceptable answer.** Otherwise the model invents.
2. **Require sources for factual claims.** Add a URL field to the report format.
3. **Cap the output.** A 400-word report is read; a 4,000-word report is not.

## Cost control

- Mark data collection / research / regression jobs as `heavy: true` so they
  run off-peak.
- Keep the zero-token rule engine in front of the model. Agents that only
  report status should be rule-based, not LLM-based.
- `DSH_DAILY_LIMIT` is a hard cap per process per day (default 200).
- The executor does not stream; a slow kernel blocks only its own thread.

## Registering and running

```bash
# validate + upsert
python -m vigiliae.agents sync

# list what would be synced
python -m vigiliae.agents list

# run one agent now
curl -X POST http://localhost:8110/api/tasks/agent_scout/run

# see the result
curl 'http://localhost:8110/api/runs?limit=5'
```

In Docker:

```bash
docker compose exec vigiliae python -m vigiliae.agents sync
```

## Three example agents

### Data collector (nightly, heavy)

```yaml
- name: "scout"
  role: "Data collection & QA"
  schedule: "cron:0 20 * * *"
  heavy: true
  boundaries:
    allow: ["fetch public pages", "append records with source_url + confidence"]
    deny: ["delete records", "personal data", "bypass robots.txt"]
  prompt: |
    Collect 100-200 public records. Each needs source_url, confidence A-E,
    as_of. Mark unverifiable records E. Respect robots.txt. Report deltas only.
```

### Policy watcher (nightly, changes only)

```yaml
- name: "policy-watch"
  role: "Policy & competitor monitoring"
  schedule: "cron:30 20 * * *"
  heavy: true
  boundaries:
    allow: ["read official sources", "read competitor sites"]
    deny: ["speculation as fact", "conclusions without a URL"]
  prompt: |
    Report CHANGES only. If nothing changed, say "no material change today".
    Every claim needs a URL. Never modify our data.
```

### Morning briefer (daily, cheap)

```yaml
- name: "briefer"
  role: "Orchestration & daily brief"
  schedule: "cron:0 8 * * *"
  heavy: false
  boundaries:
    allow: ["read agent reports", "write the morning brief"]
    deny: ["decide for the operator", "hide failures"]
  prompt: |
    Merge last night's agent reports into one brief: what each did, new
    findings, what broke, what to read first.
```

## Debugging

| Symptom | Check |
|---|---|
| agent never runs | `GET /api/tasks` → `enabled`, `schedule` |
| run says `deferred` | it fired in a peak window; see `/api/deferred` |
| run says `failed` with exit_code 3 | dangerous pattern blocked by read-only gate |
| run says `failed` with kernel error | `data/logs/<task_id>.log`, `DSH_BIN` path |
| no output | kernel writes to stdout, not stderr; check `DSH_TIMEOUT` |
