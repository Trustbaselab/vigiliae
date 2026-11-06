#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""更柝 Vigiliae · 数据采集技能（collect skill）

学自：
  · dsh-skill-manager / lib/scan.js、lib/parse.js（MIT）
    学的是「先解析、再校验、重复项只提示/跳过，不把脏数据塞进结果」；
    不照抄它的技能包扫描代码。
  · data-expander 的手工流程：_SEEN_URLS.txt 先读后写，见过的 URL 不再采。
  · 更柝数据资产规则：每条必须有 source_url + quote；空值跳过。

输入：topic + sources（URL 列表/JSON 文件）+ seen_urls_file
输出：{"records": [...], "stats": {...}}

支持两类来源：
  · JSON：{"records": [{name, source_url, quote, ...}]} 或直接数组
  · HTML：抓 title + 首个段落，生成一条候选记录

用法：
  python collect.py --topic "rCB 欧盟法规" \
      --source https://example.com/data.json \
      --seen _SEEN_URLS.txt --output records.json
  python collect.py --test
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser

UA = "VigiliaeCollect/1.0 (+https://trustbaselab.com)"
MAX_BYTES = 2_000_000
DEFAULT_SEEN = "_SEEN_URLS.txt"


class _PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title, self.desc, self.paras = "", "", []
        self._in_title = False
        self._in_para = False
        self._buf = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("script", "style", "noscript"):
            self._skip += 1
        elif tag == "title":
            self._in_title = True
            self._buf = []
        elif tag == "meta" and attrs.get("name", "").lower() in ("description", "og:description"):
            self.desc = (attrs.get("content") or "").strip()
        elif tag in ("p", "li"):
            self._in_para = True
            self._buf = []

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self._skip:
            self._skip -= 1
        elif tag == "title":
            self.title = " ".join("".join(self._buf).split())
            self._in_title = False
        elif tag in ("p", "li") and self._in_para:
            text = " ".join("".join(self._buf).split())
            if len(text) >= 20:
                self.paras.append(text)
            self._in_para = False

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_title or self._in_para:
            self._buf.append(data)


def _normalize(text):
    return re.sub(r"\s+", " ", (text or "")).strip()


def _get(url, timeout=20):
    started = time.time()
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/json,text/html,text/plain,*/*",
        "Accept-Encoding": "identity",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(MAX_BYTES)
            text = raw.decode(r.headers.get_content_charset() or "utf-8", "replace")
            return {"ok": True, "status": getattr(r, "status", 200),
                    "content_type": r.headers.get("Content-Type", ""),
                    "text": text, "error": "",
                    "elapsed_ms": int((time.time() - started) * 1000)}
    except urllib.error.HTTPError as e:
        return {"ok": False, "status": e.code, "content_type": "", "text": "",
                "error": "HTTP %s" % e.code,
                "elapsed_ms": int((time.time() - started) * 1000)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "status": 0, "content_type": "", "text": "",
                "error": str(e)[:400], "elapsed_ms": int((time.time() - started) * 1000)}


def _http_url(url):
    return str(url or "").strip().lower().startswith(("http://", "https://"))


def _seen_key(url):
    return str(url or "").strip().rstrip("/")


def load_seen(path):
    if not path or not os.path.exists(path):
        return set()
    out = set()
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#"):
                    out.add(_seen_key(line))
    except OSError:
        pass
    return out


def append_seen(path, urls):
    if not path or not urls:
        return 0
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    existing = load_seen(path)
    new = [_seen_key(u) for u in urls if _seen_key(u) not in existing]
    if not new:
        return 0
    with open(path, "a", encoding="utf-8") as fh:
        for u in new:
            fh.write(u + "\n")
    return len(new)


def extract_json_records(data, source_url, topic):
    items = data.get("records") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []
    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = _normalize(item.get("name") or item.get("title") or item.get("headline") or "")
        src = _normalize(item.get("source_url") or item.get("url") or source_url)
        quote = _normalize(item.get("quote") or item.get("summary")
                           or item.get("description") or item.get("snippet") or "")
        if not name or not src or not quote or not _http_url(src):
            continue
        out.append({
            "name": name, "source_url": src, "quote": quote, "topic": topic,
            "source_page": source_url,
            "source_kind": "json",
            "collected_at": datetime.now(timezone.utc).isoformat(),
        })
    return out


def extract_html_record(text, source_url, topic):
    parser = _PageParser()
    try:
        parser.feed(text or "")
    except Exception:  # noqa: BLE001
        return []
    quote = ""
    if parser.paras:
        quote = max(parser.paras, key=len)
    elif parser.desc:
        quote = parser.desc
    name = parser.title or urllib.parse.urlsplit(source_url).hostname or source_url
    if not _normalize(quote) or not _http_url(source_url):
        return []
    return [{
        "name": _normalize(name),
        "source_url": _normalize(source_url),
        "quote": _normalize(quote),
        "topic": topic,
        "source_page": source_url,
        "source_kind": "html",
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }]


def collect(topic, sources, seen_file=DEFAULT_SEEN, limit=100, timeout=20,
            write_seen=True):
    seen = load_seen(seen_file)
    records, new_seen = [], []
    stats = {"sources": 0, "fetched": 0, "fetch_failed": 0, "skipped_seen": 0,
             "empty_or_invalid": 0, "duplicates": 0, "records": 0,
             "seen_written": 0}
    dedupe = set()
    for source_url in sources:
        source_url = str(source_url or "").strip()
        stats["sources"] += 1
        key = _seen_key(source_url)
        if not _http_url(source_url):
            stats["empty_or_invalid"] += 1
            continue
        if key in seen:
            stats["skipped_seen"] += 1
            continue
        fetched = _get(source_url, timeout)
        if not fetched["ok"] or fetched["status"] != 200:
            stats["fetch_failed"] += 1
            continue
        stats["fetched"] += 1
        text = fetched["text"]
        ctype = (fetched["content_type"] or "").lower()
        parsed = None
        if "json" in ctype or text.lstrip().startswith(("{", "[")):
            try:
                parsed = extract_json_records(json.loads(text), source_url, topic)
            except ValueError:
                parsed = None
        if parsed is None:
            parsed = extract_html_record(text, source_url, topic)
        if not parsed:
            stats["empty_or_invalid"] += 1
        for rec in parsed:
            if len(records) >= limit:
                break
            sig = (rec["source_url"], re.sub(r"\s+", "", rec["quote"]).casefold()[:160])
            if sig in dedupe:
                stats["duplicates"] += 1
                continue
            dedupe.add(sig)
            records.append(rec)
        new_seen.append(source_url)
    if write_seen and new_seen:
        stats["seen_written"] = append_seen(seen_file, new_seen)
    stats["records"] = len(records)
    return {"records": records, "stats": stats}


def _self_test():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import tempfile
    import threading

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == "/data.json":
                body = json.dumps({"records": [
                    {"name": "Alpha", "source_url": "https://example.com/a", "quote": "Alpha quote"},
                    {"name": "Beta", "source_url": "https://example.com/b", "quote": "Beta quote"},
                    {"name": "MissingQuote", "source_url": "https://example.com/c"},
                    {"name": "", "source_url": "https://example.com/d", "quote": "no name"},
                ]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/page":
                body = ("<html><head><title>Gamma page</title>"
                        "<meta name='description' content='Gamma desc'></head>"
                        "<body><p>Gamma paragraph is long enough to become the quote.</p></body></html>").encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    tmp = tempfile.mkdtemp(prefix="vigil-collect-")
    seen = os.path.join(tmp, "_SEEN_URLS.txt")
    checks = []
    try:
        result = collect("test", [base + "/data.json", base + "/page"], seen)
        assert result["stats"]["records"] == 3, result["stats"]
        names = {r["name"] for r in result["records"]}
        assert {"Alpha", "Beta", "Gamma page"} <= names, names
        assert all(r["source_url"] and r["quote"] for r in result["records"])
        assert result["stats"]["seen_written"] == 2
        checks.append("first_run")

        result2 = collect("test", [base + "/data.json", base + "/page"], seen)
        assert result2["stats"]["skipped_seen"] == 2
        assert result2["stats"]["records"] == 0
        checks.append("seen_skip")

        assert os.path.exists(seen)
        assert len(load_seen(seen)) == 2
        checks.append("seen_file")
    finally:
        srv.shutdown()
        srv.server_close()
    print("OK collect self-test: %s" % ", ".join(checks))


def main(argv=None):
    p = argparse.ArgumentParser(description="Vigiliae gap-driven collector")
    p.add_argument("--test", action="store_true")
    p.add_argument("--topic", default="")
    p.add_argument("--source", action="append", default=[], help="source URL (repeatable)")
    p.add_argument("--source-file", help="JSON array of URLs or config with sources")
    p.add_argument("--seen", default=DEFAULT_SEEN)
    p.add_argument("--no-write-seen", action="store_true")
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--timeout", type=int, default=20)
    p.add_argument("--output", help="write JSON here")
    args = p.parse_args(argv)

    if args.test:
        try:
            _self_test()
            return 0
        except Exception as e:  # noqa: BLE001
            print("FAIL collect self-test: %s" % e, file=sys.stderr)
            return 1

    sources = list(args.source)
    if args.source_file:
        with open(args.source_file, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            sources.extend(data.get("sources") or [])
        elif isinstance(data, list):
            sources.extend(data)
    if not args.topic or not sources:
        p.print_help()
        return 2
    result = collect(args.topic, sources, args.seen, args.limit, args.timeout,
                     write_seen=not args.no_write_seen)
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(payload)
        print("wrote %s (%d records)" % (args.output, len(result["records"])))
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
