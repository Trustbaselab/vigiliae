# -*- coding: utf-8 -*-
"""Local <-> cloud handover.

The local agent (e.g. DSH on a laptop) POSTs a heartbeat every 30 s.
If the last heartbeat is older than HEARTBEAT_TIMEOUT, the cloud considers the
local machine offline and takes over `exec_pref=cloud|either` tasks. When the
local machine comes back, it resumes `exec_pref=local|either` tasks.

The protocol is deliberately tiny: one table, one timestamp, no consensus.
"""
from datetime import datetime

from .config import HEARTBEAT_TIMEOUT, TZ, now
from .db import db


def local_online():
    """Return (online, seconds_since_last_heartbeat_or_None)."""
    with db() as conn:
        row = conn.execute(
            "SELECT at FROM heartbeats WHERE role='local' ORDER BY at DESC LIMIT 1"
        ).fetchone()
    if not row:
        return False, None
    try:
        last = datetime.strptime(row["at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ)
    except ValueError:
        return False, None
    age = int((now() - last).total_seconds())
    return age < HEARTBEAT_TIMEOUT, age


def record_heartbeat(role="local", meta=None):
    import json

    with db() as conn:
        conn.execute(
            "INSERT INTO heartbeats (role, at, meta) VALUES (?,?,?)",
            (role, now().strftime("%Y-%m-%d %H:%M:%S"),
             json.dumps(meta or {}, ensure_ascii=False)),
        )
