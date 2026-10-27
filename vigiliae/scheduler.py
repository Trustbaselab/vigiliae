# -*- coding: utf-8 -*-
"""Minimal cron / interval scheduler.

Supported schedule strings:
  ""                     manual only
  "every:3600"           every N seconds
  "cron:0 8 * * *"       five-field cron (minute hour day month weekday)
"""
import threading
import time
import traceback

from .config import now
from .db import db
from .executor import run_task


def parse_schedule(schedule):
    schedule = (schedule or "").strip()
    if not schedule:
        return None, None
    if schedule.startswith("every:"):
        try:
            return "interval", int(schedule.split(":", 1)[1])
        except ValueError:
            return None, None
    if schedule.startswith("cron:"):
        return "cron", schedule.split(":", 1)[1].split()
    return None, None


def cron_match(fields, dt):
    if len(fields) != 5:
        return False

    def match(field, value):
        if field == "*":
            return True
        if field.startswith("*/"):
            try:
                return value % int(field[2:]) == 0
            except ValueError:
                return False
        for part in field.split(","):
            if "-" in part:
                try:
                    lo, hi = part.split("-")
                    if int(lo) <= value <= int(hi):
                        return True
                except ValueError:
                    pass
            else:
                try:
                    if int(part) == value:
                        return True
                except ValueError:
                    pass
        return False

    return (match(fields[0], dt.minute) and match(fields[1], dt.hour)
            and match(fields[2], dt.day) and match(fields[3], dt.month)
            and match(fields[4], dt.isoweekday() % 7))


class Scheduler(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.last_minute = {}
        self.last_interval = {}
        self.stop_flag = False

    def run(self):
        print("  scheduler started", flush=True)
        while not self.stop_flag:
            try:
                self.tick()
            except Exception:  # noqa: BLE001
                traceback.print_exc()
            time.sleep(5)

    def tick(self):
        with db() as conn:
            rows = conn.execute("SELECT id, schedule FROM tasks WHERE enabled=1").fetchall()
        dt = now()
        for row in rows:
            task_id, schedule = row["id"], row["schedule"]
            kind, value = parse_schedule(schedule)
            if not kind:
                continue
            if kind == "interval":
                last = self.last_interval.get(task_id, 0)
                if time.time() - last >= value:
                    self.last_interval[task_id] = time.time()
                    threading.Thread(target=self._safe_run, args=(task_id,),
                                     daemon=True).start()
            elif kind == "cron":
                minute_key = dt.strftime("%Y%m%d%H%M")
                if self.last_minute.get(task_id) != minute_key and cron_match(value, dt):
                    self.last_minute[task_id] = minute_key
                    threading.Thread(target=self._safe_run, args=(task_id,),
                                     daemon=True).start()

    @staticmethod
    def _safe_run(task_id):
        try:
            run_task(task_id, "scheduled")
        except Exception:  # noqa: BLE001
            traceback.print_exc()
