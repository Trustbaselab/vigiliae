# -*- coding: utf-8 -*-
"""Watchdog — look for work that is stuck, looping, or waiting on a human.

The Roman *vigiles* did not only fight fires; they walked their beat and
reported what was wrong. Vigiliae's scheduler decides *when* to run things;
the Watchdog asks a different question: **is anything quietly going wrong?**

It looks for four conditions, in order of how much they cost you:

1. **Stuck** — a run that started and never finished. The task is neither
   running nor done, so nothing will ever retry it.
2. **Looping** — the same task failing over and over. Retries burn tokens and
   attention; after a few identical failures, more retries make it worse.
3. **Waiting on a human** — an approval request nobody answered. The agent is
   behaving correctly by waiting; the silence is the failure.
4. **Dark** — no heartbeat from the local agent for longer than the configured
   timeout, while the cloud is expected to be a backup rather than the primary.

Findings are returned as plain dicts so a caller can log them, POST them to a
task bus, or render them in the UI. The Watchdog never takes corrective
action on its own — deciding to kill, retry or escalate is a human call, and
this module deliberately has no side effects beyond reading the database.
"""

from datetime import datetime, timedelta

from . import config
from .db import db

# How many consecutive identical failures count as "looping".
LOOP_THRESHOLD = 3
# An approval older than this is considered stale.
APPROVAL_STALE_HOURS = 24
# How many recent runs to look at when detecting a loop.
LOOP_LOOKBACK = 10


def _parse(ts):
    """Parse an ISO-ish timestamp from SQLite into a naive UTC datetime."""
    if not ts:
        return None
    ts = str(ts).strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(ts[:len("YYYY-MM-DD HH:MM:SS")], fmt)
        except ValueError:
            continue
    return None


def _now():
    """Wall-clock now in the configured timezone, as a naive datetime."""
    return config.now().replace(tzinfo=None)


def check_stuck_runs():
    """Runs that are still marked running past their task's timeout."""
    findings = []
    now = _now()
    with db() as conn:
        rows = conn.execute(
            """
            SELECT r.run_id, r.task_id, r.started_at, r.trigger,
                   t.name, t.timeout
            FROM runs r
            LEFT JOIN tasks t ON t.id = r.task_id
            WHERE r.status = 'running'
            """
        ).fetchall()

    for row in rows:
        started = _parse(row["started_at"])
        if not started:
            continue
        timeout = row["timeout"] or 300
        # A run is stuck once it has been running longer than its own timeout,
        # plus a grace period so slow-but-healthy runs do not flap.
        deadline = started + timedelta(seconds=timeout + 120)
        if now > deadline:
            over = int((now - started).total_seconds())
            findings.append({
                "kind": "stuck",
                "severity": "high",
                "task_id": row["task_id"],
                "task_name": row["name"] or row["task_id"],
                "run_id": row["run_id"],
                "started_at": row["started_at"],
                "detail": "running for %ds (timeout %ds)" % (over, timeout),
            })
    return findings


def check_looping_tasks():
    """Tasks whose last N runs all failed."""
    findings = []
    with db() as conn:
        task_ids = [
            r["task_id"]
            for r in conn.execute(
                "SELECT DISTINCT task_id FROM runs WHERE status = 'failed'"
            ).fetchall()
        ]
        for task_id in task_ids:
            recent = conn.execute(
                """
                SELECT status, started_at, stderr
                FROM runs
                WHERE task_id = ?
                ORDER BY run_id DESC
                LIMIT ?
                """,
                (task_id, LOOP_THRESHOLD),
            ).fetchall()

            if len(recent) < LOOP_THRESHOLD:
                continue
            if not all((r["status"] or "") == "failed" for r in recent):
                continue

            info = conn.execute(
                "SELECT name, fail_count FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            last_err = (recent[0]["stderr"] or "").strip().splitlines()
            tail = last_err[-1][:160] if last_err else ""

            findings.append({
                "kind": "looping",
                "severity": "high",
                "task_id": task_id,
                "task_name": (info["name"] if info else None) or task_id,
                "detail": "%d consecutive failures; last error: %s"
                          % (LOOP_THRESHOLD, tail or "(none captured)"),
            })
    return findings


def check_stale_approvals():
    """Approval requests that have been pending for too long."""
    findings = []
    now = _now()
    cutoff = now - timedelta(hours=APPROVAL_STALE_HOURS)
    with db() as conn:
        rows = conn.execute(
            """
            SELECT a.id, a.task_id, a.requested_at, t.name
            FROM approvals a
            LEFT JOIN tasks t ON t.id = a.task_id
            WHERE a.status = 'pending'
            """
        ).fetchall()

    for row in rows:
        requested = _parse(row["requested_at"])
        if not requested:
            continue
        if requested < cutoff:
            hours = int((now - requested).total_seconds() // 3600)
            findings.append({
                "kind": "stale_approval",
                "severity": "medium",
                "task_id": row["task_id"],
                "task_name": (row["name"] if row["name"] else None) or row["task_id"],
                "approval_id": row["id"],
                "requested_at": row["requested_at"],
                "detail": "waiting %dh for a decision (threshold %dh)"
                          % (hours, APPROVAL_STALE_HOURS),
            })
    return findings


def check_heartbeat():
    """Whether the local agent has gone quiet."""
    findings = []
    now = _now()
    with db() as conn:
        row = conn.execute(
            "SELECT role, at FROM heartbeats ORDER BY id DESC LIMIT 1"
        ).fetchone()

    if not row:
        # No heartbeat at all is only a problem if one is expected. A fresh
        # install has none; treat it as informational rather than an alarm.
        findings.append({
            "kind": "no_heartbeat",
            "severity": "low",
            "detail": "no heartbeat recorded yet (expected on a fresh install)",
        })
        return findings

    last = _parse(row["at"])
    if not last:
        return findings

    age = int((now - last).total_seconds())
    timeout = config.HEARTBEAT_TIMEOUT
    if age > timeout:
        findings.append({
            "kind": "dark",
            "severity": "medium",
            "role": row["role"],
            "last_heartbeat": row["at"],
            "detail": "no heartbeat for %ds (timeout %ds); cloud is covering"
                      % (age, timeout),
        })
    return findings


def check_all():
    """Run every check and return a summary.

    Returns a dict with a flat list of findings plus a cheap boolean so the
    caller can log one line when everything is fine:

        {"healthy": True, "count": 0, "findings": []}
    """
    # A fresh install may have no database yet. Creating the schema is
    # idempotent, so call it here rather than making every caller remember.
    try:
        from .db import init_db
        init_db()
    except Exception:
        pass

    findings = []
    for fn in (
        check_stuck_runs,
        check_looping_tasks,
        check_stale_approvals,
        check_heartbeat,
    ):
        try:
            findings.extend(fn())
        except Exception as exc:  # a broken check must not take down the rest
            findings.append({
                "kind": "watchdog_error",
                "severity": "low",
                "detail": "%s failed: %s" % (fn.__name__, exc),
            })

    # Anything above "low" means a human should probably look.
    actionable = [f for f in findings if f.get("severity") != "low"]
    return {
        "at": config.now_str(),
        "healthy": not actionable,
        "count": len(actionable),
        "findings": findings,
    }


def format_line(summary):
    """One line suitable for a log file."""
    if summary["healthy"]:
        return "WATCHDOG_OK at %s" % summary["at"]
    parts = ["%s:%s" % (f["kind"], f.get("task_id") or f.get("role") or "-")
             for f in summary["findings"] if f.get("severity") != "low"]
    return "WATCHDOG_ALERT %d issue(s) at %s — %s" % (
        summary["count"], summary["at"], ", ".join(parts))


if __name__ == "__main__":
    import json
    import sys

    summary = check_all()
    if "--json" in sys.argv:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(format_line(summary))
        for f in summary["findings"]:
            print("  [%s] %s — %s" % (
                f["severity"], f.get("task_name") or f.get("role") or "-",
                f["detail"]))
    sys.exit(0 if summary["healthy"] else 1)
