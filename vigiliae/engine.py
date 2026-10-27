# -*- coding: utf-8 -*-
"""Zero-token rule engine.

Simple commands ("status", "tasks", "price", ...) are answered locally without
calling an LLM. Only messages that miss every rule are escalated to the
thinking kernel (or left queued for the local agent).

This is intentionally boring: a list of keywords and functions. It is the
cheapest and most predictable way to handle the 80% of chat traffic that is
just "what is going on?".
"""
from . import config
from .config import now_str
from .db import db
from .executor import run_task
from .handover import local_online
from .price_slot import price_slot


def _status():
    online, age = local_online()
    with db() as conn:
        failed = conn.execute("SELECT COUNT(*) c FROM runs WHERE status='failed'").fetchone()["c"]
        enabled = conn.execute("SELECT COUNT(*) c FROM tasks WHERE enabled=1").fetchone()["c"]
        total_runs = conn.execute("SELECT COUNT(*) c FROM runs").fetchone()["c"]
    if online:
        who = "local agent online"
    elif age is not None:
        who = "local agent offline for %d min" % (age // 60)
    else:
        who = "local agent never seen"
    peak, label, _ = price_slot()
    return ("**%s** · cloud %s\n"
            "tasks %d enabled · %d runs · %d failed\n"
            "pricing: %s\n"
            "time: %s") % (who, "standby" if online else "in takeover",
                           enabled, total_runs, failed, label, now_str())


def _tasks():
    with db() as conn:
        rows = conn.execute(
            "SELECT id,name,schedule,enabled,last_status,last_run_at,heavy "
            "FROM tasks ORDER BY id").fetchall()
    if not rows:
        return "No tasks yet. Add one via POST /api/tasks or `agents.yaml`."
    lines = ["**Tasks** (%d)" % len(rows)]
    for row in rows:
        mark = "ON " if row["enabled"] else "OFF"
        heavy = " heavy" if row["heavy"] else ""
        last = ("last %s %s" % ((row["last_run_at"] or "")[5:16], row["last_status"] or "")
                if row["last_run_at"] else "never")
        lines.append("%s `%s` %s%s · %s · %s" % (
            mark, row["id"], row["name"], heavy, row["schedule"] or "manual", last))
    return "\n".join(lines)


def _runs():
    with db() as conn:
        rows = conn.execute(
            "SELECT run_id,task_id,status,duration_ms,started_at "
            "FROM runs ORDER BY run_id DESC LIMIT 8").fetchall()
    if not rows:
        return "No runs yet."
    lines = ["**Last %d runs**" % len(rows)]
    for row in rows:
        icon = "OK" if row["status"] == "ok" else "!!"
        lines.append("#%d `%s` %s %sms %s" % (
            row["run_id"], row["task_id"], icon,
            row["duration_ms"] or 0, (row["started_at"] or "")[5:16]))
    return "\n".join(lines)


def _price():
    peak, label, secs = price_slot()
    if peak:
        return "**Peak window** (list price). Off-peak in %d min. Heavy jobs are deferred." % (secs // 60)
    return "**Off-peak** (about half price). %s" % label


def _agents():
    from .agents import load_agents
    try:
        team, agents = load_agents()
    except Exception as exc:  # noqa: BLE001
        return "Could not load agents.yaml: %s" % str(exc)[:200]
    if not agents:
        return "No agents defined. Copy `agents.yaml.template` to `agents.yaml`."
    lines = ["**%s**" % (team.get("name") or "Cloud team")]
    for agent in agents:
        lines.append("· `%s` %s — %s" % (
            agent.get("name"), agent.get("role") or "", agent.get("description") or ""))
    return "\n".join(lines)


def _inspect():
    with db() as conn:
        row = conn.execute(
            "SELECT id FROM tasks WHERE id=?", (config.INSPECT_TASK,)).fetchone()
    if not row:
        return _status()
    result = run_task(row["id"], "manual")
    if result.get("status") == "ok":
        return "**Inspection OK** (%d ms)\n```\n%s\n```" % (
            result.get("duration_ms", 0), (result.get("stdout") or "")[:800])
    return "**Inspection failed**: %s" % (
        (result.get("stderr") or result.get("stdout") or "unknown")[:500])


def _help():
    return ("**Instant commands (0 tokens):**\n"
            "`status` — system + handover state\n"
            "`tasks` — task list\n"
            "`runs` — recent executions\n"
            "`price` — peak / off-peak window\n"
            "`agents` — the configured team\n"
            "`inspect` — run the configured inspection task\n"
            "\n**Escalated to the thinking kernel / local agent:**\n"
            "anything else.")


RULES = [
    (["help", "帮助", "能做什么", "how"], _help),
    (["status", "状态", "situation"], _status),
    (["tasks", "任务"], _tasks),
    (["runs", "历史", "执行记录"], _runs),
    (["price", "价格", "时段", "offpeak", "off-peak"], _price),
    (["agents", "团队", "agent list"], _agents),
    (["inspect", "巡检", "检查"], _inspect),
]


def quick_reply(text):
    """Return (matched, reply_text)."""
    text = (text or "").strip().lower()
    if not text:
        return True, _help()

    for keywords, fn in RULES:
        for keyword in keywords:
            if text == keyword or text == keyword + "?" or text == keyword + "？":
                return True, fn()
    for keywords, fn in RULES:
        for keyword in keywords:
            if keyword in text:
                return True, fn()

    return False, ""
