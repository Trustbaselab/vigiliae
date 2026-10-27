# -*- coding: utf-8 -*-
"""Price-slot aware scheduling.

Some LLM providers charge list price during weekday business hours and roughly
half price outside those windows. Heavy, non-urgent jobs (data collection,
regression runs, research) can be deferred automatically, which is where the
~50% saving comes from.

Peak windows (local time): weekdays 09:00-12:00 and 14:00-18:00.
Everything else (lunch break, evenings, nights, weekends, holidays) is off-peak.

This module never guesses a provider's prices. It only implements a
configurable peak/off-peak clock; the windows are constants you can audit.
"""
import json
import os
from datetime import timedelta

from .config import DATA_DIR, HOLIDAYS, now

PEAK_WINDOWS = [(9 * 60, 12 * 60), (14 * 60, 18 * 60)]
DEFERRED_FILE = os.path.join(DATA_DIR, "deferred.json")


def _is_holiday(dt):
    if dt.strftime("%Y-%m-%d") in HOLIDAYS:
        return True
    path = os.path.join(DATA_DIR, "holidays.txt")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                days = {line.strip() for line in fh if line.strip() and not line.startswith("#")}
            return dt.strftime("%Y-%m-%d") in days
        except OSError:
            return False
    return False


def is_peak(dt=None):
    dt = dt or now()
    if dt.weekday() >= 5 or _is_holiday(dt):
        return False
    minute = dt.hour * 60 + dt.minute
    return any(lo <= minute < hi for lo, hi in PEAK_WINDOWS)


def next_offpeak(dt=None):
    dt = dt or now()
    if not is_peak(dt):
        return dt
    minute = dt.hour * 60 + dt.minute
    if minute < 12 * 60:
        return dt.replace(hour=12, minute=0, second=0, microsecond=0)
    return dt.replace(hour=18, minute=0, second=0, microsecond=0)


def price_slot(dt=None):
    """Return (is_peak, human_label, seconds_until_price_changes)."""
    dt = dt or now()
    if is_peak(dt):
        nxt = next_offpeak(dt)
        return True, "peak (list price)", int((nxt - dt).total_seconds())
    minute = dt.hour * 60 + dt.minute
    if dt.weekday() >= 5 or _is_holiday(dt):
        return False, "off-peak (weekend/holiday)", 0
    if minute < 9 * 60:
        nxt = dt.replace(hour=9, minute=0, second=0, microsecond=0)
    elif minute < 14 * 60:
        nxt = dt.replace(hour=14, minute=0, second=0, microsecond=0)
    else:
        nxt = (dt + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    return False, "off-peak (half price)", int((nxt - dt).total_seconds())


def defer_heavy(task_id, run_id, reason):
    """Persist a deferral so the UI / ops can see why a heavy job did not run."""
    try:
        with open(DEFERRED_FILE, encoding="utf-8") as fh:
            items = json.load(fh)
    except (OSError, ValueError):
        items = []
    items.append({
        "task_id": task_id,
        "run_id": run_id,
        "at": now().strftime("%Y-%m-%d %H:%M:%S"),
        "reason": reason,
        "retry_after": next_offpeak().strftime("%Y-%m-%d %H:%M:%S"),
    })
    with open(DEFERRED_FILE, "w", encoding="utf-8") as fh:
        json.dump(items[-200:], fh, ensure_ascii=False, indent=1)
