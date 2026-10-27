# -*- coding: utf-8 -*-
"""Task execution: shell / HTTP / Python / agent."""
import json
import os
import re
import subprocess
import traceback
import urllib.request

from . import config
from .config import now, now_str
from .db import db
from .price_slot import defer_heavy, is_peak, next_offpeak

DANGEROUS_PATTERNS = [
    (r"\brm\s+-rf\s+/", "recursive delete from root"),
    (r"\bmkfs\b", "format filesystem"),
    (r"\bdd\s+if=", "raw write to disk"),
    (r">\s*/dev/[sh]d[a-z]", "write to block device"),
    (r"\bcurl\b.*\|\s*(bash|sh)\b", "pipe remote script to shell"),
    (r"\bwget\b.*\|\s*(bash|sh)\b", "pipe remote script to shell"),
    (r"\bsystemctl\s+(stop|disable)\s+(nginx|openresty|mysql|postgres)", "stop a critical service"),
    (r"\bdocker\s+rm\b", "remove containers"),
    (r"\bDROP\s+TABLE\b", "drop a table"),
    (r"\bDELETE\s+FROM\b(?!.*WHERE)", "DELETE without WHERE"),
]


def check_dangerous(cmd):
    hits = []
    for pattern, desc in DANGEROUS_PATTERNS:
        if re.search(pattern, cmd, re.I):
            hits.append(desc)
    return hits


def exec_shell(payload, timeout=300):
    cmd = payload.get("cmd") or ""
    if not cmd:
        return 1, "", "payload is missing `cmd`"
    cwd = payload.get("cwd") or config.DSH_CWD
    env = os.environ.copy()
    env.update(payload.get("env") or {})
    try:
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                              timeout=timeout, cwd=cwd, env=env)
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "timed out after %ds" % timeout
    except Exception as exc:  # noqa: BLE001
        return 1, "", str(exc)


def exec_http(payload, timeout=60):
    url = payload.get("url") or ""
    method = (payload.get("method") or "GET").upper()
    headers = payload.get("headers") or {}
    body = payload.get("body")
    if isinstance(body, (dict, list)):
        body = json.dumps(body).encode()
        headers.setdefault("Content-Type", "application/json")
    elif isinstance(body, str):
        body = body.encode()
    try:
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 0, resp.read().decode("utf-8", "replace")[:20000], ""
    except Exception as exc:  # noqa: BLE001
        code = getattr(exc, "code", None) or 1
        message = str(exc)
        try:
            message = exc.read().decode("utf-8", "replace")[:1000]
        except Exception:  # noqa: BLE001
            pass
        return code, "", message


def exec_python(payload, timeout=300):
    code = payload.get("code") or ""
    if not code:
        return 1, "", "payload is missing `code`"
    try:
        proc = subprocess.run(["python3", "-c", code], capture_output=True, text=True,
                              timeout=timeout, cwd=payload.get("cwd") or config.DSH_CWD)
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "timed out after %ds" % timeout
    except Exception as exc:  # noqa: BLE001
        return 1, "", str(exc)


def exec_agent(payload, timeout=None):
    """Run a prompt through the configured thinking kernel."""
    from . import bridge

    ok, answer = bridge.ask(payload.get("prompt") or "", timeout=timeout)
    return (0 if ok else 1), answer, ""


EXECUTORS = {
    "shell": exec_shell,
    "http": exec_http,
    "python": exec_python,
    "agent": exec_agent,
}


def _report_task_bus(task, status, detail):
    if not config.TASK_BUS_URL:
        return
    try:
        body = json.dumps({
            "source": "vigiliae",
            "task": task["name"],
            "status": "done" if status == "ok" else "blocked",
            "detail": (detail or "")[:500],
            "artifacts": [],
            "needs_owner": False,
        }).encode()
        req = urllib.request.Request(
            config.TASK_BUS_URL, data=body, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10).read()
    except Exception:  # noqa: BLE001
        pass


def run_task(task_id, trigger="scheduled"):
    """Execute one task and return a small result dict."""
    with db() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not row:
        return {"error": "task not found"}

    task = dict(row)

    # Heavy jobs are deferred during peak-price windows.
    if task.get("heavy") and is_peak():
        with db() as conn:
            run_id = conn.execute(
                "INSERT INTO runs (task_id, started_at, status, trigger) VALUES (?,?,?,?)",
                (task_id, now_str(), "deferred", trigger)).lastrowid
            conn.execute(
                "UPDATE runs SET stderr=? WHERE run_id=?",
                ("peak window: deferred to %s" % next_offpeak().strftime("%H:%M"), run_id))
        defer_heavy(task_id, run_id, "peak_hour")
        return {"run_id": run_id, "status": "deferred", "reason": "peak_hour",
                "retry_after": next_offpeak().strftime("%H:%M")}

    # Manual approval gate.
    if task["need_approve"]:
        with db() as conn:
            conn.execute(
                "INSERT INTO approvals (task_id, requested_at, status) VALUES (?,?,?)",
                (task_id, now_str(), "pending"))
            run_id = conn.execute(
                "INSERT INTO runs (task_id, started_at, status, trigger) VALUES (?,?,?,?)",
                (task_id, now_str(), "pending_approval", trigger)).lastrowid
        return {"run_id": run_id, "status": "pending_approval"}

    started = now()
    with db() as conn:
        run_id = conn.execute(
            "INSERT INTO runs (task_id, started_at, status, trigger) VALUES (?,?,?,?)",
            (task_id, started.strftime("%Y-%m-%d %H:%M:%S"), "running", trigger)).lastrowid

    payload = json.loads(task["payload"] or "{}")
    fn = EXECUTORS.get(task["kind"])
    if not fn:
        code, out, err = 1, "", "unknown executor: %s" % task["kind"]
    else:
        try:
            code, out, err = fn(payload, timeout=task["timeout"] or 300)
        except Exception:  # noqa: BLE001
            code, out, err = 1, "", traceback.format_exc()[:4000]

    # Read-only tasks may not run dangerous shell commands.
    if not task["write_perm"] and task["kind"] == "shell":
        hits = check_dangerous(payload.get("cmd") or "")
        if hits:
            code, err = 3, "read-only task blocked: " + ", ".join(hits)

    finished = now()
    duration_ms = int((finished - started).total_seconds() * 1000)
    status = "ok" if code == 0 else "failed"

    with db() as conn:
        conn.execute(
            "UPDATE runs SET finished_at=?, status=?, exit_code=?, stdout=?, stderr=?, duration_ms=? "
            "WHERE run_id=?",
            (finished.strftime("%Y-%m-%d %H:%M:%S"), status, code,
             (out or "")[:50000], (err or "")[:20000], duration_ms, run_id))
        conn.execute(
            "UPDATE tasks SET last_run_at=?, last_status=?, run_count=run_count+1, "
            "fail_count=fail_count+? WHERE id=?",
            (finished.strftime("%Y-%m-%d %H:%M:%S"), status,
             0 if status == "ok" else 1, task_id))

    try:
        log_file = os.path.join(config.LOG_DIR, task_id + ".log")
        with open(log_file, "a", encoding="utf-8") as fh:
            fh.write("\n=== %s [%s] %s (code=%s, %dms) ===\n" %
                     (finished.strftime("%Y-%m-%d %H:%M:%S"), trigger, status, code, duration_ms))
            fh.write((out or "")[-4000:])
            if err:
                fh.write("\n[STDERR]\n" + err[-2000:])
    except OSError:
        pass

    _report_task_bus(task, status, out or err)

    return {"run_id": run_id, "status": status, "exit_code": code,
            "duration_ms": duration_ms, "stdout": (out or "")[:500],
            "stderr": (err or "")[:500]}
