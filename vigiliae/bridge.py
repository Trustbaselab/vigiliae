# -*- coding: utf-8 -*-
"""Bridge to a headless "thinking kernel" CLI.

Vigiliae does not embed an LLM runtime. When the rule engine cannot answer a
message, we shell out to a CLI that accepts a prompt and prints an answer.
The reference implementation is DSH (`dsh --profile headless "<prompt>"`), but
anything with the same shape works: a local model runner, an OpenAI-compatible
CLI, etc.

Two guardrails:
  * a hard daily call limit (default 200) so a runaway loop cannot burn budget;
  * a timeout, with the answer written back asynchronously so the HTTP request
    never blocks behind a slow model.
"""
import os
import subprocess
import threading
import traceback

from . import config
from .db import db

_call_count = {"date": "", "n": 0}


def _quota_ok():
    today = config.now().strftime("%Y-%m-%d")
    if _call_count["date"] != today:
        _call_count["date"] = today
        _call_count["n"] = 0
    return _call_count["n"] < config.DSH_DAILY_LIMIT


def _inc():
    _call_count["n"] += 1


def available():
    """True if a thinking-kernel binary is configured and on PATH."""
    if os.path.sep in config.DSH_BIN:
        return os.path.exists(config.DSH_BIN)
    return any(
        os.access(os.path.join(p, config.DSH_BIN), os.X_OK)
        for p in os.environ.get("PATH", "").split(os.pathsep)
        if p
    )


def _prompt(question):
    return (
        "You are a concise operations assistant. Answer in under 400 words. "
        "If a fact cannot be verified, say so instead of guessing. "
        "Never invent numbers.\n\n"
        "Question: " + question[:2000]
    )


def ask(question, timeout=None):
    """Call the thinking kernel. Returns (ok, answer)."""
    timeout = timeout or config.DSH_TIMEOUT
    if not _quota_ok():
        return False, "Daily cloud-thinking quota reached (%d calls). Queued for the local agent." % config.DSH_DAILY_LIMIT
    if not available():
        return False, ("No thinking kernel configured. Set DSH_BIN (or leave the message "
                       "queued for your local agent).")

    env = os.environ.copy()
    if config.DSH_HOME:
        env["DSH_HOME"] = config.DSH_HOME

    try:
        proc = subprocess.run(
            [config.DSH_BIN, "--profile", config.DSH_PROFILE, _prompt(question)],
            capture_output=True, text=True, timeout=timeout,
            cwd=config.DSH_CWD, env=env,
        )
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        _inc()
        if proc.returncode == 0 and out:
            return True, out[-6000:]
        return False, "Thinking kernel failed (code=%d)\n%s" % (
            proc.returncode, (err or out)[:500])
    except subprocess.TimeoutExpired:
        _inc()
        return False, "Thinking kernel timed out after %ds. The question may be too broad." % timeout
    except Exception as exc:  # noqa: BLE001
        return False, "Thinking kernel error: %s" % str(exc)[:300]


def reply_async(message_id, question):
    """Background worker: write the answer back into the messages table."""
    try:
        ok, answer = ask(question)
        with db() as conn:
            conn.execute(
                "INSERT INTO messages (sender, body, created_at, reply_to, meta) "
                "VALUES ('dsh', ?, ?, ?, ?)",
                (answer[:8000], config.now_str(), message_id,
                 '{"cloud": true, "ok": %s}' % ("true" if ok else "false")),
            )
    except Exception:  # noqa: BLE001
        traceback.print_exc()
