#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ===== WORK MAP（v2，2026-11-06）=====
# 目标：页面/服务/版本/备份四类巡检，输出检查项 -> 证据 -> 结论
# 步骤：配置 -> 页面 GET -> 服务 health -> 版本 -> 备份年龄 -> issues
# 输入：config/pages/service/data_version_file/site_version_url/backup_dir
# 输出：{ok,issues[],snapshot}；v2 增加 checks[] 与 issue evidence
# 依赖：标准库 urllib；文件系统；目标站点
# 分支：非 200；服务 ok=false；版本缺失；备份缺失/过旧
# ==========================================
"""更柝 Vigiliae · 系统巡检技能（patrol skill）

学自：
  · dsh-mcp-manager / lib/health.js、lib/probe.js（MIT）
    学的是「健康不是一个布尔值，而是多个检查项的 snapshot + 分级 issues」；
    不照抄 MCP 协议，只把同样的诊断结构用于更柝自己的页面/版本/备份/服务。
  · dsh-skill-manager / docs/verification.md
    学的是「先列检查项，再逐项给证据，最后给结论」的验收格式。

检查四类：
  ① 页面 200（可配置多个 URL）
  ② 数据版本 vs 站点显示版本
  ③ 备份是否最新（目录里最新文件的时间）
  ④ 服务是否活着（/api/health，默认 127.0.0.1:8912）

输出：
  {"ok": bool, "issues": [{"level": "high|medium|low", "what": ..., "detail": ...}],
   "snapshot": {...}}

用法：
  python patrol.py --config patrol.json
  python patrol.py --page https://trustbaselab.com/vigiliae-demo/ \
                   --service http://127.0.0.1:8912/api/health \
                   --backup-dir ~/.vigiliae/data/backups
  python patrol.py --test
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

UA = "VigiliaePatrol/1.0 (+https://trustbaselab.com)"
DEFAULT_SERVICE = os.environ.get("VIGILIAE_HEALTH_URL", "http://127.0.0.1:8912/api/health")
DEFAULT_BACKUP_DIR = os.environ.get("VIGILIAE_BACKUP_DIR", "data/backups")
DEFAULT_VERSION_FILE = os.environ.get("VIGILIAE_VERSION_FILE", "data/version.json")
BACKUP_EXTS = (".db", ".sqlite", ".sqlite3", ".gz", ".zip", ".tar", ".tar.gz", ".bak")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _get(url, timeout=15):
    """Small stdlib HTTP probe; never raises. Returns status/latency/text/json."""
    started = time.time()
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/json,text/plain,*/*",
        "Accept-Encoding": "identity",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(2_000_000)
            text = raw.decode(r.headers.get_content_charset() or "utf-8", "replace")
            payload = None
            if "json" in (r.headers.get("Content-Type") or "").lower():
                try:
                    payload = json.loads(text)
                except ValueError:
                    payload = None
            return {
                "url": url, "final_url": r.geturl(), "status": getattr(r, "status", 200),
                "ok": True, "latency_ms": int((time.time() - started) * 1000),
                "text": text, "json": payload, "error": "",
            }
    except urllib.error.HTTPError as e:
        return {"url": url, "final_url": e.geturl(), "status": e.code, "ok": False,
                "latency_ms": int((time.time() - started) * 1000),
                "text": "", "json": None, "error": "HTTP %s" % e.code}
    except Exception as e:  # noqa: BLE001
        return {"url": url, "final_url": url, "status": 0, "ok": False,
                "latency_ms": int((time.time() - started) * 1000),
                "text": "", "json": None, "error": str(e)[:400]}


def check_page(url, timeout=15):
    r = _get(url, timeout)
    return {
        "url": url, "final_url": r["final_url"], "status": r["status"],
        "ok": r["ok"] and r["status"] == 200,
        "latency_ms": r["latency_ms"], "error": r["error"],
    }


def check_service(url, timeout=15):
    r = _get(url, timeout)
    ok = r["ok"] and r["status"] == 200
    health_ok = ok
    if isinstance(r["json"], dict) and "ok" in r["json"]:
        health_ok = bool(r["json"].get("ok"))
    return {
        "url": url, "status": r["status"], "ok": ok and health_ok,
        "latency_ms": r["latency_ms"], "json": r["json"] if isinstance(r["json"], dict) else None,
        "error": r["error"],
    }


def _norm_version(v):
    v = str(v or "").strip().lower()
    return v[1:] if v.startswith("v") else v


def extract_version(text):
    """Extract a numeric version from a page; returns str or ''."""
    patterns = [
        r"(?i)(?:data[-_ ]?version|数据版本|数据集版本|version)\s*[:=：]?\s*v?([0-9]+(?:\.[0-9]+){1,3})",
        r"(?i)\bv([0-9]+(?:\.[0-9]+){1,2})\b",
    ]
    for pat in patterns:
        m = re.search(pat, text or "")
        if m:
            return m.group(1)
    return ""


def compare_version(data_version, site_version):
    """Return issue dict or None. Missing values produce low/medium, not crash."""
    dv, sv = _norm_version(data_version), _norm_version(site_version)
    if not dv and not sv:
        return {"level": "low", "what": "version", "detail": "no data or site version available"}
    if not dv:
        return {"level": "medium", "what": "version", "detail": "data version missing; site=%s" % sv}
    if not sv:
        return {"level": "medium", "what": "version", "detail": "site version not found; data=%s" % dv}
    if dv != sv:
        return {"level": "high", "what": "version",
                "detail": "data=%s != site=%s" % (dv, sv)}
    return None


def read_data_version(path):
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def check_backup(backup_dir, max_age_hours=26):
    if not backup_dir or not os.path.isdir(backup_dir):
        return {"dir": backup_dir, "exists": False, "latest": None,
                "age_hours": None, "files": 0}, {
            "level": "high", "what": "backup",
            "detail": "backup directory missing: %s" % backup_dir}
    latest, latest_path = None, None
    count = 0
    for root, _dirs, names in os.walk(backup_dir):
        for name in names:
            if not name.lower().endswith(BACKUP_EXTS):
                continue
            path = os.path.join(root, name)
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            count += 1
            if latest is None or mtime > latest:
                latest, latest_path = mtime, path
    if latest is None:
        return {"dir": backup_dir, "exists": True, "latest": None,
                "age_hours": None, "files": 0}, {
            "level": "high", "what": "backup", "detail": "no backup files in %s" % backup_dir}
    age_hours = (time.time() - latest) / 3600.0
    snap = {"dir": backup_dir, "exists": True,
            "latest": os.path.basename(latest_path),
            "latest_at": datetime.fromtimestamp(latest, timezone.utc).isoformat(),
            "age_hours": round(age_hours, 2), "files": count}
    if age_hours > max_age_hours:
        return snap, {"level": "high", "what": "backup",
                      "detail": "latest %s is %.1fh old (max %sh)" % (
                          os.path.basename(latest_path), age_hours, max_age_hours)}
    return snap, None


def run_patrol(config):
    timeout = int(config.get("timeout") or 15)
    issues = []
    pages = []
    for url in config.get("pages") or []:
        r = check_page(url, timeout)
        pages.append(r)
        if not r["ok"]:
            issues.append({"level": "high", "what": "page",
                           "detail": "%s -> status=%s error=%s" % (url, r["status"], r["error"])})
        elif r["latency_ms"] > 5000:
            issues.append({"level": "low", "what": "page",
                           "detail": "%s slow: %dms" % (url, r["latency_ms"])})

    service = None
    if config.get("service"):
        service = check_service(config["service"], timeout)
        if not service["ok"]:
            issues.append({"level": "high", "what": "service",
                           "detail": "%s -> status=%s error=%s" % (
                               config["service"], service["status"], service["error"])})

    version = {"data": None, "site": None}
    data_file = config.get("data_version_file")
    data_meta = read_data_version(data_file) if data_file else {}
    data_ver = config.get("data_version") or data_meta.get("version")
    site_ver = config.get("site_version") or ""
    site_url = config.get("site_version_url")
    if site_url:
        site = _get(site_url, timeout)
        if site["ok"]:
            site_ver = extract_version(site["text"])
        else:
            issues.append({"level": "high", "what": "version",
                           "detail": "version page %s failed: %s" % (site_url, site["error"])})
    version["data"] = data_ver
    version["site"] = site_ver
    v_issue = compare_version(data_ver, site_ver)
    if v_issue:
        issues.append(v_issue)

    backup_dir = config.get("backup_dir") or DEFAULT_BACKUP_DIR
    backup, b_issue = check_backup(backup_dir, int(config.get("max_backup_age_hours") or 26))
    if b_issue:
        issues.append(b_issue)

    snapshot = {
        "checked_at": _now(),
        "pages": pages,
        "service": service,
        "version": version,
        "backup": backup,
        "counts": {
            "high": sum(1 for i in issues if i["level"] == "high"),
            "medium": sum(1 for i in issues if i["level"] == "medium"),
            "low": sum(1 for i in issues if i["level"] == "low"),
        },
    }
    return {"ok": not any(i["level"] == "high" for i in issues),
            "issues": issues, "snapshot": snapshot}


def _self_test():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import tempfile
    import threading

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == "/":
                body = b"<html><body>Vigiliae <span>data-version: 1.2.3</span></body></html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/api/health":
                body = b'{"ok": true, "service": "vigiliae"}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    tmp = tempfile.mkdtemp(prefix="vigil-patrol-")
    backup = os.path.join(tmp, "backups")
    os.makedirs(backup)
    fresh = os.path.join(backup, "vigiliae.db")
    with open(fresh, "wb") as fh:
        fh.write(b"backup")
    vfile = os.path.join(tmp, "version.json")
    with open(vfile, "w", encoding="utf-8") as fh:
        json.dump({"version": "1.2.3", "records": 10}, fh)
    checks = []
    try:
        assert extract_version("data-version: 1.2.3") == "1.2.3"
        assert compare_version("1.2.3", "1.2.3") is None
        assert compare_version("1.2.3", "1.2.4")["level"] == "high"
        checks.append("version")

        cfg = {
            "pages": [base + "/"], "service": base + "/api/health",
            "data_version_file": vfile, "site_version_url": base + "/",
            "backup_dir": backup, "max_backup_age_hours": 26, "timeout": 5,
        }
        result = run_patrol(cfg)
        assert result["ok"] is True, result["issues"]
        assert result["snapshot"]["version"]["data"] == "1.2.3"
        assert result["snapshot"]["version"]["site"] == "1.2.3"
        checks.append("healthy")

        # stale backup + 404 page -> high issues
        old = time.time() - 48 * 3600
        os.utime(fresh, (old, old))
        cfg2 = dict(cfg, pages=[base + "/missing"])
        result2 = run_patrol(cfg2)
        assert result2["ok"] is False
        levels = {i["what"] for i in result2["issues"]}
        assert "page" in levels and "backup" in levels, result2["issues"]
        checks.append("issues")
    finally:
        srv.shutdown()
        srv.server_close()
    print("OK patrol self-test: %s" % ", ".join(checks))



# ===== v2: 反馈日志 + 统一 --check 入口（不改变原函数语义）=====
_SKILL_NAME = "patrol"
_HAS_MAIN = True
_STATUS_LEGEND = {
    "auto_verified": "自动验证通过（有证据链）",
    "ai_evaluated": "AI 评估通过（本轮未做）",
    "human_confirmed": "人工确认通过（本轮未做）",
    "not_verified": "尚未验证/证据不足",
}


def _feedback_path():
    data_dir = os.environ.get("VIGILIAE_DATA_DIR", "data")
    return os.path.join(data_dir, "team", _SKILL_NAME, "feedback.jsonl")


def record_feedback(issue, fix, prevention, evidence=None):
    """把用户反馈写成可追踪的一行：issue -> fix -> prevention。"""
    import time as _time
    path = _feedback_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rec = {
        "at": _time.strftime("%Y-%m-%dT%H:%M:%S"),
        "skill": _SKILL_NAME,
        "issue": issue or "",
        "fix": fix or "",
        "prevention": prevention or "",
        "evidence": evidence or {},
    }
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return path


def _arg_value(args, key, default=""):
    if key in args:
        i = args.index(key)
        if i + 1 < len(args):
            return args[i + 1]
    return default


def _front(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if "--check" in args:
        i = args.index("--check")
        if i + 1 >= len(args):
            print(json.dumps({"ok": False, "error": "--check needs an input JSON path"},
                             ensure_ascii=False))
            return 2
        return _check_main(args[i + 1])
    if "--feedback" in args:
        issue = _arg_value(args, "--feedback")
        if not issue:
            print(json.dumps({"ok": False, "error": "--feedback needs an issue string"},
                             ensure_ascii=False))
            return 2
        path = record_feedback(
            issue, _arg_value(args, "--fix"), _arg_value(args, "--prevention"),
            {"note": _arg_value(args, "--evidence")})
        print(json.dumps({"ok": True, "feedback_log": path}, ensure_ascii=False))
        return 0
    if _HAS_MAIN:
        return main(args)
    print("用法: --check <input.json> | --feedback <issue> [--fix .. --prevention ..]")
    return 2

def _emit_check(payload):
    payload.setdefault("skill", _SKILL_NAME)
    payload["status_legend"] = _STATUS_LEGEND
    payload.setdefault("ai_evaluation", {"status": "not_run"})
    payload.setdefault("human_confirmation", {"status": "not_run"})
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("status") == "auto_verified" else 2


def _check_main(path):
    try:
        cfg = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError) as e:
        return _emit_check({"status": "not_verified", "error": "cannot read config: %s" % e})
    res = run_patrol(cfg)
    snap = res.get("snapshot") or {}
    checks = [
        {"name": "pages", "status": "pass" if all(p.get("ok") for p in snap.get("pages", []))
         else "fail", "evidence": snap.get("pages", [])},
        {"name": "service", "status": "pass" if (not snap.get("service") or snap["service"].get("ok"))
         else "fail", "evidence": snap.get("service")},
        {"name": "version", "status": "pass" if (
            (snap.get("version") or {}).get("data")
            and (snap.get("version") or {}).get("site")
            and (snap.get("version") or {}).get("data") == (snap.get("version") or {}).get("site")
         ) else "fail", "evidence": snap.get("version")},
        {"name": "backup", "status": "pass" if not any(
            i.get("what") == "backup" for i in res.get("issues", [])) else "fail",
         "evidence": snap.get("backup")},
    ]
    human = [i for i in res.get("issues", []) if i.get("level") in ("high", "medium")]
    all_pass = bool(checks) and all(c.get("status") == "pass" for c in checks)
    return _emit_check({
        "status": "auto_verified" if (res.get("ok") and all_pass) else "not_verified",
        "ok": res.get("ok"),
        "checks": checks,
        "issues": res.get("issues", []),
        "snapshot": snap,
        "human_review": human,
        "scope": "ops_health_only",
        "not_checked": ["content correctness", "backup restore"],
        "feedback_log": _feedback_path(),
    })


def main(argv=None):
    p = argparse.ArgumentParser(description="Vigiliae page/version/backup/service patrol")
    p.add_argument("--test", action="store_true")
    p.add_argument("--config", help="JSON config")
    p.add_argument("--page", action="append", default=[], help="page URL (repeatable)")
    p.add_argument("--service", help="health endpoint")
    p.add_argument("--data-version-file", default=DEFAULT_VERSION_FILE)
    p.add_argument("--site-version", default="")
    p.add_argument("--site-version-url", default="")
    p.add_argument("--backup-dir", default=DEFAULT_BACKUP_DIR)
    p.add_argument("--max-backup-age-hours", type=int, default=26)
    p.add_argument("--timeout", type=int, default=15)
    p.add_argument("--output", help="write JSON here")
    args = p.parse_args(argv)

    if args.test:
        try:
            _self_test()
            return 0
        except Exception as e:  # noqa: BLE001
            print("FAIL patrol self-test: %s" % e, file=sys.stderr)
            return 1

    cfg = {}
    if args.config:
        with open(args.config, encoding="utf-8") as fh:
            cfg = json.load(fh)
    cfg = dict(cfg)
    if args.page:
        cfg["pages"] = args.page
    if args.service:
        cfg["service"] = args.service
    if args.data_version_file:
        cfg["data_version_file"] = args.data_version_file
    if args.site_version:
        cfg["site_version"] = args.site_version
    if args.site_version_url:
        cfg["site_version_url"] = args.site_version_url
    if args.backup_dir:
        cfg["backup_dir"] = args.backup_dir
    if args.max_backup_age_hours:
        cfg["max_backup_age_hours"] = args.max_backup_age_hours
    cfg.setdefault("timeout", args.timeout)
    if not cfg.get("pages") and not cfg.get("service"):
        cfg["service"] = DEFAULT_SERVICE

    result = run_patrol(cfg)
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(payload)
        print("wrote %s (ok=%s, issues=%d)" % (args.output, result["ok"], len(result["issues"])))
    else:
        print(payload)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(_front())
