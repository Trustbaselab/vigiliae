# -*- coding: utf-8 -*-
"""Flask application and HTTP API."""
import json
import os
import threading
import traceback

from flask import Flask, jsonify, make_response, redirect, request

from . import auth, bridge, config
from .agents import load_agents
from .config import now, now_str
from .db import db, init_db
from .engine import quick_reply
from .executor import run_task
from .handover import local_online, record_heartbeat
from .price_slot import next_offpeak, price_slot as current_price_slot
from .scheduler import Scheduler

app = Flask(__name__)
init_db()

_UI_CACHE = {"html": None}


def _ui_html():
    if _UI_CACHE["html"] is None:
        path = os.path.join(config.TEMPLATES_DIR, "ui.html")
        with open(path, encoding="utf-8") as fh:
            _UI_CACHE["html"] = fh.read()
    return _UI_CACHE["html"]


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
@app.before_request
def _check_auth():
    path = request.path
    if path in auth.PUBLIC_PATHS:
        return None
    if not auth.get_bot_token():
        return None  # dev mode: BOT_TOKEN not configured
    if auth.token_ok(request.cookies.get(config.COOKIE_NAME)):
        return None

    query_token = request.args.get("k")
    if query_token and auth.token_ok(query_token):
        args = {k: v for k, v in request.args.items() if k != "k"}
        qs = "&".join("%s=%s" % (k, v) for k, v in args.items())
        target = path + ("?" + qs if qs else "")
        resp = make_response(redirect(target or "/"))
        resp.set_cookie(config.COOKIE_NAME, auth.get_bot_token(),
                        max_age=config.COOKIE_MAX_AGE, httponly=True,
                        samesite="Lax", path="/")
        return resp

    if path.startswith("/api/"):
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    return auth.LOGIN_PAGE, 401, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/login")
def login():
    token = request.args.get("k") or ""
    if auth.token_ok(token):
        resp = make_response(redirect("/"))
        resp.set_cookie(config.COOKIE_NAME, auth.get_bot_token(),
                        max_age=config.COOKIE_MAX_AGE, httponly=True,
                        samesite="Lax", path="/")
        return resp
    return redirect("/?bad=1")


@app.route("/logout")
def logout():
    resp = make_response(redirect("/"))
    resp.set_cookie(config.COOKIE_NAME, "", max_age=0, path="/")
    return resp


# ---------------------------------------------------------------------------
# Status / tasks / runs
# ---------------------------------------------------------------------------
@app.route("/api/health")
def api_health():
    return jsonify({"ok": True, "service": "vigiliae", "time": now_str()})


@app.route("/api/status")
def api_status():
    online, age = local_online()
    with db() as conn:
        tasks_total = conn.execute("SELECT COUNT(*) c FROM tasks").fetchone()["c"]
        tasks_enabled = conn.execute("SELECT COUNT(*) c FROM tasks WHERE enabled=1").fetchone()["c"]
        runs_total = conn.execute("SELECT COUNT(*) c FROM runs").fetchone()["c"]
        runs_failed = conn.execute("SELECT COUNT(*) c FROM runs WHERE status='failed'").fetchone()["c"]
        approvals = conn.execute(
            "SELECT COUNT(*) c FROM approvals WHERE status='pending'").fetchone()["c"]
    peak, label, secs = current_price_slot()
    return jsonify({
        "ok": True,
        "server_time": now_str(),
        "local_online": online,
        "local_heartbeat_ago_sec": age,
        "role": "local_primary" if online else "cloud_takeover",
        "tasks": {"total": tasks_total, "enabled": tasks_enabled},
        "runs": {"total": runs_total, "failed": runs_failed},
        "pending_approvals": approvals,
        "pricing": {"is_peak": peak, "label": label, "seconds_until_change": secs},
        "thinking_kernel": {"configured": bridge.available()},
        "dev_mode": not bool(auth.get_bot_token()),
    })


@app.route("/api/tasks", methods=["GET", "POST"])
def api_tasks():
    if request.method == "POST":
        data = request.get_json(force=True, silent=True) or {}
        task_id = data.get("id") or ("t_" + str(int(now().timestamp() * 1000))[-10:])
        with db() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO tasks
                   (id,name,desc,kind,payload,schedule,enabled,write_perm,need_approve,
                    heavy,exec_pref,timeout,retries,created_at,updated_at,run_count,fail_count)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,0)""",
                (task_id, data.get("name") or task_id, data.get("desc") or "",
                 data.get("kind") or "shell",
                 json.dumps(data.get("payload") or {}, ensure_ascii=False),
                 data.get("schedule") or "",
                 1 if data.get("enabled", True) else 0,
                 1 if data.get("write_perm") else 0,
                 1 if data.get("need_approve") else 0,
                 1 if data.get("heavy") else 0,
                 data.get("exec_pref") or "cloud",
                 int(data.get("timeout") or 300),
                 int(data.get("retries") or 2),
                 now_str(), now_str()))
        return jsonify({"ok": True, "id": task_id})

    with db() as conn:
        rows = conn.execute("SELECT * FROM tasks ORDER BY created_at DESC").fetchall()
    online, _ = local_online()
    tasks = []
    for row in rows:
        task = dict(row)
        task["payload"] = json.loads(task["payload"] or "{}")
        task["effective_runner"] = (
            "local" if (online and task["exec_pref"] == "local") else "cloud")
        tasks.append(task)
    return jsonify({"ok": True, "tasks": tasks, "local_online": online})


@app.route("/api/tasks/<task_id>/run", methods=["POST"])
def api_run(task_id):
    return jsonify({"ok": True, "result": run_task(task_id, "manual")})


@app.route("/api/tasks/<task_id>/toggle", methods=["POST"])
def api_toggle(task_id):
    with db() as conn:
        conn.execute("UPDATE tasks SET enabled=1-enabled, updated_at=? WHERE id=?",
                     (now_str(), task_id))
        row = conn.execute("SELECT enabled FROM tasks WHERE id=?", (task_id,)).fetchone()
    return jsonify({"ok": True, "enabled": bool(row["enabled"]) if row else None})


@app.route("/api/runs")
def api_runs():
    limit = int(request.args.get("limit") or 50)
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM runs ORDER BY run_id DESC LIMIT ?", (limit,)).fetchall()
    return jsonify({"ok": True, "runs": [dict(r) for r in rows]})


# ---------------------------------------------------------------------------
# Handover / approvals
# ---------------------------------------------------------------------------
@app.route("/api/heartbeat", methods=["POST"])
def api_heartbeat():
    data = request.get_json(force=True, silent=True) or {}
    record_heartbeat(data.get("role") or "local", data.get("meta") or {})
    online, _ = local_online()
    return jsonify({"ok": True, "local_online": online})


@app.route("/api/handover")
def api_handover():
    online, age = local_online()
    return jsonify({"local_online": online, "last_heartbeat_ago_sec": age,
                    "takeover": not online})


@app.route("/api/approvals")
def api_approvals():
    with db() as conn:
        rows = conn.execute("SELECT * FROM approvals ORDER BY id DESC LIMIT 50").fetchall()
    return jsonify({"ok": True, "approvals": [dict(r) for r in rows]})


@app.route("/api/approvals/<int:approval_id>", methods=["POST"])
def api_approval_decision(approval_id):
    data = request.get_json(force=True, silent=True) or {}
    decision = "approved" if data.get("approve") else "rejected"
    with db() as conn:
        conn.execute("UPDATE approvals SET status=?, decided_at=?, note=? WHERE id=?",
                     (decision, now_str(), data.get("note") or "", approval_id))
    return jsonify({"ok": True, "status": decision})


# ---------------------------------------------------------------------------
# Messages (the chat queue)
# ---------------------------------------------------------------------------
@app.route("/api/messages", methods=["GET", "POST"])
def api_messages():
    if request.method == "POST":
        data = request.get_json(force=True, silent=True) or {}
        body = (data.get("body") or "").strip()
        if not body:
            return jsonify({"ok": False, "error": "empty body"}), 400
        sender = data.get("sender") or "you"
        with db() as conn:
            message_id = conn.execute(
                "INSERT INTO messages (sender, body, created_at, reply_to, meta) "
                "VALUES (?,?,?,?,?)",
                (sender, body[:8000], now_str(), data.get("reply_to"),
                 json.dumps(data.get("meta") or {}, ensure_ascii=False))).lastrowid

        auto_reply = None
        cloud_thinking = False
        if sender == "you":
            try:
                matched, reply = quick_reply(body)
                if matched and reply:
                    with db() as conn:
                        auto_reply = conn.execute(
                            "INSERT INTO messages (sender, body, created_at, reply_to, meta) "
                            "VALUES ('dsh', ?, ?, ?, ?)",
                            (reply[:8000], now_str(), message_id,
                             json.dumps({"auto": True}, ensure_ascii=False))).lastrowid
                elif bridge.available():
                    threading.Thread(target=bridge.reply_async,
                                     args=(message_id, body), daemon=True).start()
                    cloud_thinking = True
            except Exception:  # noqa: BLE001
                traceback.print_exc()

        return jsonify({"ok": True, "id": message_id, "auto_reply_id": auto_reply,
                        "cloud_thinking": cloud_thinking})

    since = request.args.get("since")
    unread = request.args.get("unread")
    with db() as conn:
        if unread:
            rows = conn.execute(
                "SELECT * FROM messages WHERE sender='you' AND read_at IS NULL "
                "ORDER BY id ASC").fetchall()
        elif since:
            rows = conn.execute(
                "SELECT * FROM messages WHERE id > ? ORDER BY id ASC",
                (int(since),)).fetchall()
        else:
            rows = list(reversed(conn.execute(
                "SELECT * FROM messages ORDER BY id DESC LIMIT 100").fetchall()))
    return jsonify({"ok": True, "messages": [dict(r) for r in rows]})


@app.route("/api/messages/read", methods=["POST"])
def api_messages_read():
    data = request.get_json(force=True, silent=True) or {}
    ids = data.get("ids") or []
    with db() as conn:
        for message_id in ids:
            conn.execute("UPDATE messages SET read_at=? WHERE id=? AND read_at IS NULL",
                         (now_str(), message_id))
    return jsonify({"ok": True, "marked": len(ids)})


@app.route("/api/messages/unread_count")
def api_unread_count():
    with db() as conn:
        count = conn.execute(
            "SELECT COUNT(*) c FROM messages WHERE sender='you' AND read_at IS NULL"
        ).fetchone()["c"]
    return jsonify({"ok": True, "unread": count})


# ---------------------------------------------------------------------------
# Briefing / what's new / pricing / agents
# ---------------------------------------------------------------------------
@app.route("/api/brief")
def api_brief():
    mark = request.args.get("mark_read")
    with db() as conn:
        unread = [dict(r) for r in conn.execute(
            "SELECT id, body, created_at FROM messages "
            "WHERE sender='you' AND read_at IS NULL ORDER BY id ASC").fetchall()]
        failures = [dict(r) for r in conn.execute(
            "SELECT run_id, task_id, started_at, stderr FROM runs "
            "WHERE status='failed' ORDER BY run_id DESC LIMIT 5").fetchall()]
        approvals = [dict(r) for r in conn.execute(
            "SELECT id, task_id, requested_at FROM approvals "
            "WHERE status='pending' ORDER BY id DESC").fetchall()]
        tasks_total = conn.execute("SELECT COUNT(*) c FROM tasks").fetchone()["c"]
        tasks_enabled = conn.execute("SELECT COUNT(*) c FROM tasks WHERE enabled=1").fetchone()["c"]
        runs_total = conn.execute("SELECT COUNT(*) c FROM runs").fetchone()["c"]
        runs_failed = conn.execute("SELECT COUNT(*) c FROM runs WHERE status='failed'").fetchone()["c"]

    online, age = local_online()
    if mark and unread:
        with db() as conn:
            for message in unread:
                conn.execute("UPDATE messages SET read_at=? WHERE id=? AND read_at IS NULL",
                             (now_str(), message["id"]))

    return jsonify({
        "ok": True,
        "server_time": now_str(),
        "local_online": online,
        "local_heartbeat_ago_sec": age,
        "unread_count": len(unread),
        "unread_messages": unread[-20:],
        "recent_failures": failures,
        "pending_approvals": approvals,
        "tasks": {"total": tasks_total, "enabled": tasks_enabled},
        "runs": {"total": runs_total, "failed": runs_failed},
    })


@app.route("/api/whatsnew")
def api_whatsnew():
    since = request.args.get("since") or ""
    if not since:
        since = (now() - __import__("datetime").timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S")
    with db() as conn:
        messages = [dict(r) for r in conn.execute(
            "SELECT id, sender, body, created_at FROM messages "
            "WHERE created_at >= ? ORDER BY id ASC LIMIT 200", (since,)).fetchall()]
        runs = [dict(r) for r in conn.execute(
            "SELECT run_id, task_id, status, duration_ms, started_at FROM runs "
            "WHERE started_at >= ? ORDER BY run_id DESC LIMIT 100", (since,)).fetchall()]

    from collections import Counter
    by_status = Counter(r["status"] for r in runs)
    by_task = Counter(r["task_id"] for r in runs)
    return jsonify({
        "ok": True, "since": since, "server_time": now_str(),
        "messages": messages, "runs": runs[:50],
        "summary": {"messages": len(messages), "runs": len(runs),
                    "by_status": dict(by_status), "by_task": dict(by_task)},
    })


@app.route("/api/price_slot")
def api_price_slot():
    peak, label, seconds = current_price_slot()
    return jsonify({
        "ok": True,
        "server_time": now_str(),
        "is_peak": peak,
        "label": label,
        "price_ratio": 1.0 if peak else 0.5,
        "seconds_until_change": seconds,
        "next_offpeak": next_offpeak().strftime("%Y-%m-%d %H:%M:%S"),
        "rule": "peak = weekdays 09:00-12:00 and 14:00-18:00; everything else is off-peak",
    })


@app.route("/api/deferred")
def api_deferred():
    path = os.path.join(config.DATA_DIR, "deferred.json")
    try:
        with open(path, encoding="utf-8") as fh:
            items = json.load(fh)
    except (OSError, ValueError):
        items = []
    return jsonify({"ok": True, "count": len(items), "items": items[-50:]})


@app.route("/api/agents")
def api_agents():
    try:
        team, agents = load_agents()
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)[:300]}), 500
    return jsonify({"ok": True, "team": team, "agents": agents})


@app.route("/")
def index():
    return _ui_html()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    if not auth.get_bot_token():
        print("  WARNING: BOT_TOKEN is not set - the app is running in open dev mode.",
              flush=True)
    print("  data dir: %s" % config.DATA_DIR, flush=True)
    if not bridge.available():
        print("  thinking kernel not found (set DSH_BIN); chat will queue for the local agent.",
              flush=True)
    Scheduler().start()
    print("  Vigiliae listening on http://%s:%d" % (config.HOST, config.PORT), flush=True)
    app.run(host=config.HOST, port=config.PORT, threaded=True, debug=False)


if __name__ == "__main__":
    main()
