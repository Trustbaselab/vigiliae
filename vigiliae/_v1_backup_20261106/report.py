#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""更柝 Vigiliae · 统一汇报技能（report skill）

学自：
  · dsh-skill-manager / docs/verification.md（MIT）
    学的是「事实、检查项、结论分开写，问题必须可定位」；
  · dsh-mcp-manager / lib/health.js 的诊断字段（level/what/detail）
    学的是「问题分级 + snapshot，而不是一句“都正常”」。
  不照抄它们的代码；只保留更柝需要的三种对外格式。

三种格式：
  · daily  日报：今天做了什么 / 新变化 / 待决策 / 阻塞
  · patrol 巡检报告：健康度 + 问题 + snapshot
  · audit  审计报告：数据质量指标 + 异常

输入是 JSON；输出是 Markdown（可直接贴给人/公众号/群）。
用法：
  python report.py --type daily  --input daily.json  --output daily.md
  python report.py --type patrol --input patrol.json --output patrol.md
  python report.py --type audit  --input audit.json  --output audit.md
  python report.py --test
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone


def _now():
    return datetime.now(timezone.utc).isoformat()


def _cell(value):
    text = str(value if value is not None else "")
    return text.replace("|", "\\|").replace("\n", " ").strip()


def _bullets(items, empty="（无）"):
    if not items:
        return ["- " + empty]
    out = []
    for item in items:
        if isinstance(item, dict):
            label = item.get("text") or item.get("what") or item.get("name") or item.get("title") or ""
            detail = item.get("detail") or item.get("note") or ""
            out.append("- **%s**%s" % (_cell(label), (" — " + _cell(detail)) if detail else ""))
        else:
            out.append("- " + _cell(item))
    return out


def render_daily(data):
    data = data or {}
    date = data.get("date") or datetime.now().strftime("%Y-%m-%d")
    lines = [
        "# 更柝日报 · %s" % date,
        "",
        "> 生成时间：%s" % (data.get("generated_at") or _now()),
        "",
        "## 今天做了什么",
        "",
    ]
    lines.extend(_bullets(data.get("done")))
    lines += ["", "## 新变化", ""]
    lines.extend(_bullets(data.get("changes")))
    lines += ["", "## 待决策", ""]
    lines.extend(_bullets(data.get("decisions")))
    lines += ["", "## 阻塞 / 风险", ""]
    lines.extend(_bullets(data.get("blocked")))
    if data.get("next"):
        lines += ["", "## 下一步", ""]
        lines.extend(_bullets(data.get("next")))
    lines += ["", "---", "", "*Vigiliae · 更柝 · 日报*", ""]
    return "\n".join(lines)


def render_patrol(data):
    data = data or {}
    snapshot = data.get("snapshot") or {}
    issues = data.get("issues") or []
    ok = data.get("ok")
    if ok is None:
        ok = not any((i or {}).get("level") == "high" for i in issues if isinstance(i, dict))
    lines = [
        "# 更柝巡检报告",
        "",
        "> 生成时间：%s" % (snapshot.get("checked_at") or _now()),
        "",
        "## 结论",
        "",
        ("**健康** ✅" if ok else "**有问题** ❌"),
        "",
        "## 健康度",
        "",
        "| 项目 | 值 |",
        "|---|---|",
    ]
    pages = snapshot.get("pages") or []
    if pages:
        for p in pages:
            lines.append("| page | %s (status=%s, %sms) |" % (
                _cell(p.get("url", "")), p.get("status", ""), p.get("latency_ms", "")))
    service = snapshot.get("service")
    if service:
        lines.append("| service | %s (status=%s, ok=%s) |" % (
            _cell(service.get("url", "")), service.get("status", ""), service.get("ok", "")))
    version = snapshot.get("version") or {}
    if version:
        lines.append("| version | data=%s / site=%s |" % (
            _cell(version.get("data")), _cell(version.get("site"))))
    backup = snapshot.get("backup") or {}
    if backup:
        lines.append("| backup | latest=%s, age=%sh, files=%s |" % (
            _cell(backup.get("latest")), backup.get("age_hours", ""), backup.get("files", "")))
    lines += ["", "## 问题", ""]
    if not issues:
        lines.append("（无）")
    else:
        lines += ["| 级别 | 项目 | 详情 |", "|---|---|---|"]
        for i in issues:
            lines.append("| %s | %s | %s |" % (
                _cell(i.get("level", "")), _cell(i.get("what", "")), _cell(i.get("detail", ""))))
    lines += ["", "---", "", "*Vigiliae · 更柝 · 巡检*", ""]
    return "\n".join(lines)


def render_audit(data):
    data = data or {}
    metrics = data.get("metrics") or {}
    exceptions = data.get("exceptions") or []
    lines = [
        "# 更柝审计报告",
        "",
        "> 生成时间：%s" % (data.get("generated_at") or _now()),
        "",
        "## 数据质量",
        "",
        "| 指标 | 值 | 说明 |",
        "|---|---|---|",
    ]
    if not metrics:
        lines.append("| （无） | - | - |")
    else:
        for key, value in metrics.items():
            if isinstance(value, dict):
                lines.append("| %s | %s | %s |" % (
                    _cell(key), _cell(value.get("value", "")), _cell(value.get("note", ""))))
            else:
                lines.append("| %s | %s | - |" % (_cell(key), _cell(value)))
    lines += ["", "## 异常", ""]
    if not exceptions:
        lines.append("（无）")
    else:
        for item in exceptions:
            if isinstance(item, dict):
                lines.append("- **%s** — %s" % (
                    _cell(item.get("name") or item.get("what") or "异常"),
                    _cell(item.get("detail") or item.get("note") or "")))
            else:
                lines.append("- " + _cell(item))
    lines += ["", "---", "", "*Vigiliae · 更柝 · 审计*", ""]
    return "\n".join(lines)


def render(kind, data):
    kind = (kind or "").lower()
    if kind == "daily":
        return render_daily(data)
    if kind == "patrol":
        return render_patrol(data)
    if kind == "audit":
        return render_audit(data)
    raise ValueError("unknown report type: %s" % kind)


def _self_test():
    checks = []
    daily = {
        "date": "2026-11-06",
        "done": ["写了 verify/patrol/collect/report 四个技能"],
        "changes": [{"text": "memory.py", "detail": "5 个工具"}],
        "decisions": ["是否把 verify 接入 Libra"],
        "blocked": [],
        "next": ["跑 12 Agent 验收"],
    }
    md = render_daily(daily)
    assert "# 更柝日报 · 2026-11-06" in md
    assert "## 待决策" in md and "Libra" in md
    assert "（无）" in md
    checks.append("daily")

    patrol = {
        "ok": True,
        "issues": [],
        "snapshot": {
            "checked_at": "2026-11-06T12:00:00+00:00",
            "pages": [{"url": "https://example.com", "status": 200, "latency_ms": 123}],
            "service": {"url": "http://127.0.0.1:8912/api/health", "status": 200, "ok": True},
            "version": {"data": "1.2.3", "site": "1.2.3"},
            "backup": {"latest": "vigiliae.db", "age_hours": 1.2, "files": 3},
        },
    }
    md = render_patrol(patrol)
    assert "**健康**" in md and "| page |" in md and "### " not in md
    checks.append("patrol")

    audit = {
        "metrics": {"total": 100, "A": {"value": 80, "note": "80%"}},
        "exceptions": [{"name": "missing_source", "detail": "3 条"}],
    }
    md = render_audit(audit)
    assert "# 更柝审计报告" in md and "missing_source" in md
    checks.append("audit")

    # empty inputs must not crash
    assert "# 更柝日报" in render("daily", {})
    assert "# 更柝巡检报告" in render("patrol", {})
    assert "# 更柝审计报告" in render("audit", {})
    checks.append("empty")
    print("OK report self-test: %s" % ", ".join(checks))


def main(argv=None):
    p = argparse.ArgumentParser(description="Vigiliae Markdown report renderer")
    p.add_argument("--test", action="store_true")
    p.add_argument("--type", choices=["daily", "patrol", "audit"])
    p.add_argument("--input", help="JSON input; '-' reads stdin")
    p.add_argument("--output", help="write Markdown here")
    args = p.parse_args(argv)

    if args.test:
        try:
            _self_test()
            return 0
        except Exception as e:  # noqa: BLE001
            print("FAIL report self-test: %s" % e, file=sys.stderr)
            return 1

    if not args.type:
        p.print_help()
        return 2
    data = {}
    if args.input:
        if args.input == "-":
            data = json.load(sys.stdin)
        else:
            with open(args.input, encoding="utf-8") as fh:
                data = json.load(fh)
    text = render(args.type, data)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text)
        print("wrote %s (%d chars)" % (args.output, len(text)))
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
