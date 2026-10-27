# -*- coding: utf-8 -*-
"""SQLite persistence: tasks, runs, heartbeats, approvals, messages."""
import sqlite3
from contextlib import contextmanager

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    desc         TEXT,
    kind         TEXT NOT NULL,          -- shell | http | python | agent
    payload      TEXT NOT NULL,          -- JSON: execution parameters
    schedule     TEXT,                   -- cron expression, "every:300", or empty
    enabled      INTEGER DEFAULT 1,
    write_perm   INTEGER DEFAULT 0,      -- 1 = writes are allowed
    need_approve INTEGER DEFAULT 0,      -- 1 = require manual approval
    heavy        INTEGER DEFAULT 0,      -- 1 = may be deferred to off-peak
    exec_pref    TEXT DEFAULT 'cloud',   -- cloud | local | either
    timeout      INTEGER DEFAULT 300,
    retries      INTEGER DEFAULT 2,
    created_at   TEXT,
    updated_at   TEXT,
    last_run_at  TEXT,
    last_status  TEXT,
    run_count    INTEGER DEFAULT 0,
    fail_count   INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS runs (
    run_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT NOT NULL,
    started_at  TEXT,
    finished_at TEXT,
    status      TEXT,                   -- running | ok | failed | deferred | pending_approval
    exit_code   INTEGER,
    stdout      TEXT,
    stderr      TEXT,
    duration_ms INTEGER,
    trigger     TEXT,                   -- scheduled | manual | retry
    FOREIGN KEY (task_id) REFERENCES tasks(id)
);

CREATE TABLE IF NOT EXISTS heartbeats (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT,
    at   TEXT,
    meta TEXT
);

CREATE TABLE IF NOT EXISTS approvals (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id      TEXT,
    requested_at TEXT,
    status       TEXT DEFAULT 'pending',  -- pending | approved | rejected
    decided_at   TEXT,
    note         TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    sender     TEXT NOT NULL,            -- you | dsh
    body       TEXT NOT NULL,
    created_at TEXT,
    read_at    TEXT,
    reply_to   INTEGER,
    meta       TEXT
);

CREATE INDEX IF NOT EXISTS idx_runs_task ON runs(task_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_heartbeats ON heartbeats(at DESC);
CREATE INDEX IF NOT EXISTS idx_msgs ON messages(created_at DESC);
"""


@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with db() as conn:
        conn.executescript(SCHEMA)
    return DB_PATH
