#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""更柝 Vigiliae · 数据核验技能（verify skill）

学自：
  · dsh-mcp-manager / lib/probe.js、lib/health.js（MIT）
    学的是「探测要分阶段、要有超时、状态是某一刻的证据，不是永久标签」；
    不照抄它的 MCP 握手代码，只把同样的纪律用于 HTTP 来源核验。
  · 更柝自己的数据资产规则：source_url + quote + confidence + as_of。

本技能只做四件事：
  ① 请求 source_url，记录 HTTP 状态、最终 URL、内容类型、耗时；
  ② 把页面正文归一化，检查 quote 是否为页面原文子串；
  ③ 按域名权威性给出 A/B/C 基础等级（.gov/.gov.cn/.eu/.int 等 → A；
     明确行业组织 → B；其他 → C）；
  ④ HTTP 失败或 quote 不一致时降级，并给出可读 reasons。

不是法律意见，也不是“永久可信”的盖章：它只证明「此刻这个 URL 的页面里
确实出现了这段原文」，以及「域名属于哪一档」。

用法：
  python verify.py --url https://example.com/page --quote "原文" --name "记录名"
  python verify.py --input items.json --output result.json
  python verify.py --test
"""
import argparse
import html
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser

UA = "VigiliaeVerify/1.0 (+https://trustbaselab.com)"
MAX_BYTES = 2_000_000
DEFAULT_TIMEOUT = 20

# 政府 / 国际组织 / 国家标准机构：A
A_DOMAINS = {
    "europa.eu", "ec.europa.eu", "eur-lex.europa.eu", "eurostat.ec.europa.eu",
    "un.org", "unep.org", "unfccc.int", "ipcc.ch", "wmo.int", "who.int",
    "fao.org", "ilo.org", "worldbank.org", "imf.org", "oecd.org",
    "iea.org", "iso.org", "iec.ch", "itu.int", "bipm.org",
    "nist.gov", "energy.gov", "epa.gov", "nasa.gov", "noaa.gov",
    "ustr.gov", "trade.gov", "state.gov", "eia.gov",
}
# 明确行业组织 / 行业协会：B（不是所有 .org 都自动算 B）
B_DOMAINS = {
    "worldsteel.org", "cement.org", "theicct.org", "api.org",
    "sae.org", "astm.org", "cfa.org", "cablel.org",
}
A_SUFFIXES = (".gov", ".gov.cn", ".gov.uk", ".gov.au", ".mil", ".int", ".eu")
DEGRADE = {"A": "B", "B": "C", "C": "C"}
VALID_CONF = ("A", "B", "C")


class _TextExtractor(HTMLParser):
    """提取可读正文；跳过 script/style/noscript。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.parts.append(data)


def _normalize(text):
    text = html.unescape(text or "")
    text = re.sub(r"\s+", " ", text)
    return text.strip().casefold()


def _page_text(body, content_type):
    text = body or ""
    if "html" in (content_type or "").lower() or "<html" in text[:500].lower():
        parser = _TextExtractor()
        try:
            parser.feed(text)
            text = " ".join(parser.parts)
        except Exception:  # noqa: BLE001
            text = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", text)
            text = re.sub(r"(?s)<[^>]+>", " ", text)
    return _normalize(text)


def _decode(body, headers):
    charset = None
    try:
        charset = headers.get_content_charset()
    except Exception:  # noqa: BLE001
        charset = None
    if not charset:
        head = body[:2048].decode("ascii", "ignore")
        m = re.search(r"(?i)charset\s*=\s*['\"]?([a-z0-9_-]+)", head)
        if m:
            charset = m.group(1)
    for enc in (charset, "utf-8", "gb18030", "latin-1"):
        if not enc:
            continue
        try:
            return body.decode(enc, "replace")
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", "replace")


def http_get(url, timeout=DEFAULT_TIMEOUT):
    """Return {ok, status, final_url, content_type, text, error, elapsed_ms}."""
    started = time.time()
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "text/html,application/json,text/plain,*/*",
            "Accept-Encoding": "identity",
        },
    )
    context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=context) as r:
            raw = r.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raw = raw[:MAX_BYTES]
            body = _decode(raw, r.headers)
            return {
                "ok": True,
                "status": getattr(r, "status", 200),
                "final_url": r.geturl(),
                "content_type": r.headers.get("Content-Type", ""),
                "text": body,
                "error": "",
                "elapsed_ms": int((time.time() - started) * 1000),
            }
    except urllib.error.HTTPError as e:
        try:
            raw = e.read(MAX_BYTES)
            body = _decode(raw, e.headers)
        except Exception:  # noqa: BLE001
            body, raw = "", b""
        return {
            "ok": False,
            "status": e.code,
            "final_url": e.geturl(),
            "content_type": e.headers.get("Content-Type", "") if e.headers else "",
            "text": body,
            "error": "HTTP %s" % e.code,
            "elapsed_ms": int((time.time() - started) * 1000),
        }
    except Exception as e:  # noqa: BLE001
        return {
            "ok": False,
            "status": 0,
            "final_url": url,
            "content_type": "",
            "text": "",
            "error": str(e)[:500],
            "elapsed_ms": int((time.time() - started) * 1000),
        }


def domain_grade(url):
    """Return (grade, reason). A=政府/国际组织/国家标准；B=明确行业组织；C=其他。"""
    try:
        host = (urllib.parse.urlsplit(url).hostname or "").lower().strip(".")
    except Exception:  # noqa: BLE001
        host = ""
    if not host:
        return "C", "invalid URL host"
    if any(host == d or host.endswith("." + d) for d in A_DOMAINS):
        return "A", "government/international/standard domain: %s" % host
    if host.endswith(A_SUFFIXES):
        return "A", "government/international TLD: %s" % host
    if any(host == d or host.endswith("." + d) for d in B_DOMAINS):
        return "B", "recognized industry association: %s" % host
    if host.endswith(".edu") or host.endswith(".ac.uk"):
        return "B", "academic institution (B, not A): %s" % host
    return "C", "other domain: %s" % host


def assess(domain_grade_value, http_ok, quote_found):
    """Compute actual grade + verified flag. A/B + HTTP 200 + quote = verified."""
    actual = domain_grade_value
    if not http_ok:
        actual = "C"
    elif not quote_found:
        actual = DEGRADE.get(domain_grade_value, "C")
    verified = bool(http_ok and quote_found and actual in ("A", "B"))
    return actual, verified


def verify_source(name, source_url, quote, confidence_self="B", timeout=DEFAULT_TIMEOUT):
    reasons = []
    fetched = http_get(source_url, timeout=timeout)
    grade, grade_reason = domain_grade(source_url)
    page = _page_text(fetched["text"], fetched["content_type"])
    quote_norm = _normalize(quote)
    quote_found = bool(quote_norm) and quote_norm in page
    http_ok = fetched["ok"] and fetched["status"] == 200

    if not source_url.lower().startswith(("http://", "https://")):
        reasons.append("source_url is not http(s)")
        http_ok = False
    if not quote.strip():
        reasons.append("quote is empty")
    if http_ok:
        reasons.append("HTTP 200 (%d ms)" % fetched["elapsed_ms"])
    else:
        reasons.append("HTTP failed: status=%s error=%s" % (
            fetched["status"], fetched["error"] or "n/a"))
    reasons.append(grade_reason)
    if quote_found:
        reasons.append("quote found as substring of page text")
    elif quote_norm:
        reasons.append("quote NOT found in page text (page may be JS-rendered or quote may be edited)")
    if quote_found and grade == "C":
        reasons.append("source is reachable but domain authority is C")

    actual, verified = assess(grade, http_ok, quote_found)
    self_conf = (confidence_self or "B").upper()
    if self_conf not in VALID_CONF:
        reasons.append("confidence_self=%r invalid; treated as B" % confidence_self)
        self_conf = "B"
    if self_conf != actual:
        if VALID_CONF.index(actual) > VALID_CONF.index(self_conf):
            reasons.append("downgraded from self=%s to actual=%s" % (self_conf, actual))
        else:
            reasons.append("actual=%s is better than self=%s; keep actual" % (actual, self_conf))

    return {
        "name": name or "",
        "source_url": source_url,
        "final_url": fetched["final_url"],
        "verified": verified,
        "actual_confidence": actual,
        "confidence_self": self_conf,
        "reasons": reasons,
        "evidence": {
            "http_status": fetched["status"],
            "http_ok": http_ok,
            "quote_found": quote_found,
            "domain": urllib.parse.urlsplit(source_url).hostname or "",
            "domain_grade": grade,
            "content_type": fetched["content_type"],
            "elapsed_ms": fetched["elapsed_ms"],
            "checked_at": datetime.now(timezone.utc).isoformat(),
        },
        "quote_preview": quote.strip()[:200],
    }


# ──────────────────────────────────────────────────────────────
# self-test：本地 HTTP，不访问外网
# ──────────────────────────────────────────────────────────────
def _self_test():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == "/ok":
                body = ("<html><body><h1>Test</h1>"
                        "<p>Carbon black N550 &amp; ASTM D1765.</p></body></html>").encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/json":
                body = b'{"ok": true, "value": "N550"}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    checks = []
    try:
        assert domain_grade("https://www.miit.gov.cn/x")[0] == "A"
        assert domain_grade("https://ec.europa.eu/x")[0] == "A"
        assert domain_grade("https://example.com/x")[0] == "C"
        assert domain_grade("https://www.worldsteel.org/x")[0] == "B"
        checks.append("domain_grade")

        assert assess("A", True, True) == ("A", True)
        assert assess("A", True, False) == ("B", False)
        assert assess("B", True, True) == ("B", True)
        assert assess("C", True, True) == ("C", False)
        checks.append("assess")

        ok = verify_source("ok", base + "/ok", "Carbon black N550 & ASTM D1765")
        assert ok["evidence"]["http_status"] == 200
        assert ok["evidence"]["quote_found"] is True
        assert ok["actual_confidence"] == "C"  # localhost is C
        assert ok["verified"] is False
        checks.append("http_quote")

        bad = verify_source("bad", base + "/missing", "anything")
        assert bad["verified"] is False and bad["evidence"]["http_status"] == 404
        checks.append("http_404")

        miss = verify_source("miss", base + "/ok", "this text is not on the page")
        assert miss["verified"] is False and miss["evidence"]["quote_found"] is False
        checks.append("quote_mismatch")

        js = verify_source("json", base + "/json", '"N550"', confidence_self="A")
        assert js["evidence"]["quote_found"] is True
        assert "downgraded" in " ".join(js["reasons"]).lower() or js["actual_confidence"] == "C"
        checks.append("json_source")
    finally:
        srv.shutdown()
        srv.server_close()
    print("OK verify self-test: %s" % ", ".join(checks))


def main(argv=None):
    p = argparse.ArgumentParser(description="Vigiliae data source verifier")
    p.add_argument("--test", action="store_true", help="run offline self-test")
    p.add_argument("--name", default="", help="record name")
    p.add_argument("--url", help="source URL")
    p.add_argument("--quote", help="quote expected on page")
    p.add_argument("--confidence-self", default="B", choices=list(VALID_CONF),
                   help="self-assessed confidence before verification")
    p.add_argument("--input", help="JSON object/array with name, source_url, quote, confidence_self")
    p.add_argument("--output", help="write JSON here instead of stdout")
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    args = p.parse_args(argv)

    if args.test:
        try:
            _self_test()
            return 0
        except Exception as e:  # noqa: BLE001
            print("FAIL verify self-test: %s" % e, file=sys.stderr)
            return 1

    items = []
    if args.input:
        with open(args.input, encoding="utf-8") as fh:
            data = json.load(fh)
        items = data if isinstance(data, list) else [data]
    elif args.url:
        items = [{"name": args.name, "source_url": args.url,
                  "quote": args.quote or "",
                  "confidence_self": args.confidence_self}]
    else:
        p.print_help()
        return 2

    results = []
    for it in items:
        results.append(verify_source(
            it.get("name", ""), it.get("source_url", ""), it.get("quote", ""),
            it.get("confidence_self", args.confidence_self), timeout=args.timeout))
    out = results[0] if len(results) == 1 else results
    payload = json.dumps(out, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(payload)
        print("wrote %s (%d record(s))" % (args.output, len(results)))
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
