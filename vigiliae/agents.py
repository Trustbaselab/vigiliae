# -*- coding: utf-8 -*-
"""Load `agents.yaml` and turn agent definitions into scheduled tasks.

An agent is just a prompt + a schedule + a boundary list. `sync` upserts one
row per agent into the tasks table with kind="agent"; the executor then routes
the prompt to the thinking kernel.

Usage:
    python -m vigiliae.agents list
    python -m vigiliae.agents sync [path/to/agents.yaml]
"""
import sys

import yaml

from . import config
from .config import now_str
from .db import db, init_db


def load_agents(path=None):
    path = path or config.AGENTS_FILE
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data.get("team") or {}, data.get("agents") or []


def sync(path=None):
    init_db()
    team, agents = load_agents(path)
    created = 0
    with db() as conn:
        for agent in agents:
            name = (agent.get("name") or "").strip()
            if not name:
                continue
            task_id = "agent_" + name
            payload = {"prompt": agent.get("prompt") or ""}
            conn.execute(
                """INSERT INTO tasks
                   (id,name,desc,kind,payload,schedule,enabled,write_perm,need_approve,
                    heavy,exec_pref,timeout,retries,created_at,updated_at,run_count,fail_count)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,0)
                   ON CONFLICT(id) DO UPDATE SET
                     name=excluded.name, desc=excluded.desc, payload=excluded.payload,
                     schedule=excluded.schedule, heavy=excluded.heavy,
                     timeout=excluded.timeout, updated_at=excluded.updated_at""",
                (task_id, agent.get("role") or name, agent.get("description") or "",
                 "agent", _dumps(payload), agent.get("schedule") or "",
                 1 if agent.get("enabled", True) else 0,
                 0, 0,
                 1 if agent.get("heavy", True) else 0,
                 "cloud", int(agent.get("timeout") or 1800), 2,
                 now_str(), now_str()))
            created += 1
    return created, team


def _dumps(value):
    import json
    return json.dumps(value, ensure_ascii=False)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    command = argv[0] if argv else "list"
    path = argv[1] if len(argv) > 1 else None

    if command == "sync":
        count, team = sync(path)
        print("Synced %d agent(s) from %s%s" % (
            count, path or config.AGENTS_FILE,
            (" (team: %s)" % team.get("name")) if team.get("name") else ""))
        return 0

    if command == "list":
        team, agents = load_agents(path)
        print("Team: %s" % (team.get("name") or "-"))
        for agent in agents:
            print("- %-16s %-28s %s" % (
                agent.get("name"), agent.get("role") or "",
                agent.get("schedule") or "manual"))
        return 0

    print("Usage: python -m vigiliae.agents [list|sync] [path/to/agents.yaml]")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
