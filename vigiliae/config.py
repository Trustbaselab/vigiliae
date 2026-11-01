# -*- coding: utf-8 -*-
"""Runtime configuration.

Everything is environment-driven. There are no hardcoded hosts, tokens or
paths inside the package, so the same image can run on a laptop or a VPS.
"""
import os
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_dotenv(path):
    """Minimal .env loader — no dependency on python-dotenv.

    Reads KEY=VALUE lines, ignores blanks and # comments, strips surrounding
    quotes. Existing environment variables win, so `export KEY=x` still works.
    """
    if not os.path.isfile(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip()
                # strip matching quotes
                if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
                    val = val[1:-1]
                # real env wins
                if key and key not in os.environ:
                    os.environ[key] = val
    except OSError:
        pass


# Load .env from the repository root (next to README/LICENSE), then from the
# current working directory. Root wins so `cd sub && vigiliae` still works.
_load_dotenv(os.path.join(ROOT, ".env"))
_load_dotenv(os.path.join(os.getcwd(), ".env"))

DATA_DIR = os.environ.get("VIGILIAE_DATA_DIR") or os.path.join(ROOT, "data")
LOG_DIR = os.path.join(DATA_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

DB_PATH = os.environ.get("VIGILIAE_DB") or os.path.join(DATA_DIR, "vigiliae.db")
AGENTS_FILE = os.environ.get("VIGILIAE_AGENTS") or os.path.join(ROOT, "agents.yaml")
TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")

# The scheduler reasons in local wall-clock time. Default is UTC+8 because the
# price windows this project was built around are defined in China time.
TZ_OFFSET = float(os.environ.get("VIGILIAE_TZ_OFFSET", "8"))
TZ = timezone(timedelta(hours=TZ_OFFSET))

HOST = os.environ.get("VIGILIAE_HOST", "127.0.0.1")
PORT = int(os.environ.get("VIGILIAE_PORT", "8110"))

# If the local agent has not sent a heartbeat for this long, the cloud takes over.
HEARTBEAT_TIMEOUT = int(os.environ.get("VIGILIAE_HEARTBEAT_TIMEOUT", "120"))

# Optional: POST results to an external task bus (leave empty to disable).
TASK_BUS_URL = os.environ.get("VIGILIAE_TASK_BUS_URL", "").strip()

# --- auth -------------------------------------------------------------------
# If BOT_TOKEN is empty the app runs in "open dev mode" and logs a warning.
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
COOKIE_NAME = "cb_auth"
COOKIE_MAX_AGE = 30 * 86400

# --- thinking kernel (optional) ---------------------------------------------
# Vigiliae does not ship an LLM runtime. It shells out to any CLI that takes a
# prompt and prints an answer. DSH (DeepSeek Harness) is the default.
DSH_BIN = os.environ.get("DSH_BIN", "dsh")
DSH_PROFILE = os.environ.get("DSH_PROFILE", "headless")
DSH_HOME = os.environ.get("DSH_HOME", "")
DSH_TIMEOUT = int(os.environ.get("DSH_TIMEOUT", "180"))
DSH_DAILY_LIMIT = int(os.environ.get("DSH_DAILY_LIMIT", "200"))
DSH_CWD = os.environ.get("DSH_CWD", ROOT)

# --- off-peak pricing -------------------------------------------------------
# Comma-separated ISO dates, e.g. "2026-01-01,2026-02-17".
HOLIDAYS = {d.strip() for d in os.environ.get("VIGILIAE_HOLIDAYS", "").split(",") if d.strip()}

# Task id used by the chat command `inspect`. Set to your heartbeat task.
INSPECT_TASK = os.environ.get("VIGILIAE_INSPECT_TASK", "inspect")


def now():
    return datetime.now(TZ)


def now_str():
    return now().strftime("%Y-%m-%d %H:%M:%S")
