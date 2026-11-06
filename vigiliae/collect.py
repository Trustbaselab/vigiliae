#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ===== WORK MAP（v2，2026-11-06）=====
# 目标：按 topic 从 sources 采集候选，不重复采，拒绝要留原因
# 步骤：读 seen -> fetch/重试 -> 内容质量门 -> quote 单句化 -> accepted/rejected
# 输入：topic/sources/seen_file/limit/timeout
# 输出：{records[],stats{rejected}}；v2 增加 accepted/rejected 证据清单
# 依赖：标准库 urllib/html.parser；目标站点；_SEEN_URLS.txt
# 分支：非法 URL；seen；抓取失败；登录墙；正文短/占比低；去重
# ==========================================
"""更柝 Vigiliae · 数据采集技能（collect skill）

学自：
  · dsh-skill-manager / lib/scan.js、lib/parse.js（MIT）
  · data-expander 的手工流程：_SEEN_URLS.txt 先读后写，见过的 URL 不再采。
  · 更柝数据资产规则：每条必须有 source_url + quote；空值跳过。

v2 改进（2026-11-06）：
  P0 内容质量门：正文长度、登录墙/反爬特征、正文占比、正文容器优先
  P1 quote 单句化 + ≤320 字；优先含数字句
  P1 to_production_record() 补齐 category/region/issuer/effective_date/confidence_self
  P2 默认 write_seen=False；CLI 需显式 --write-seen
  P2 失败重试 1 次（间隔 2 秒）；默认超时 10 秒；记录失败/过滤原因

用法：
  python collect.py --topic "rCB 欧盟法规" \
      --source https://example.com/page --seen _SEEN_URLS.txt --output records.json
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
DEFAULT_TIMEOUT = 10          # P2：默认超时 10 秒
MAX_QUOTE = 320               # P1：quote 上限
MIN_BODY = 200                # P0：正文长度门
MIN_RATIO = 0.10              # P0：正文/全文占比门

LOGIN_PATTERNS = [
    "您无权阅读", "无权阅读", "请先登录", "登录后查看", "请登录后", "您需要登录", "您还未登录",
    "会员可见", "付费阅读",
    "访问验证", "环境异常", "完成验证", "安全验证", "滑动验证",
    "Just a moment", "Checking your browser", "Access Denied", "403 Forbidden",
    "Enable JavaScript", "Please enable cookies",
]
ANTIBOT_TITLE = re.compile(
    r"(验证|异常|Error|Access Denied|Forbidden|Just a moment|Checking your browser|404|403)",
    re.I,
)
NAV_TAGS = {"aside", "nav", "footer", "header", "form", "iframe"}
SCRIPT_TAGS = {"script", "style", "noscript", "svg"}
MAIN_RE = re.compile(r"(article|content|main|post|detail|text|body|entry|story|news)", re.I)
NUM_RE = re.compile(r"\d")
TOPIC_RE = re.compile(r"(碳|排放|能源|电力|发电|煤炭|石油|天然气|新能源|可再生|工业|制造|环境|气候|生态|节能|能耗|橡胶|轮胎|炭黑|价格|产量|增长|投资|消费|标准|政策)", re.I)


def _normalize(text):
    return re.sub(r"\s+", " ", (text or "")).strip()


class _PageParser(HTMLParser):
    """提取 title/description/段落；区分正文容器与导航/侧栏/页脚。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.desc = ""
        self.paras = []          # [{"text","in_main","tag"}]
        self.total_chars = 0
        self.main_chars = 0
        self._skip = 0           # 脚本/样式
        self._nav = 0            # 导航/侧栏/页脚
        self._main = 0           # 正文容器深度
        self._in_title = False
        self._in_para = None     # tag name
        self._buf = []
        self._stack = []

    def handle_starttag(self, tag, attrs):
        tag = (tag or "").lower()
        attrs = dict(attrs)
        cls = (attrs.get("class") or "") + " " + (attrs.get("id") or "")
        was_skip = tag in SCRIPT_TAGS
        was_nav = tag in NAV_TAGS
        was_main = tag in ("article", "main") or (tag == "div" and bool(MAIN_RE.search(cls)))
        if was_skip:
            self._skip += 1
        if was_nav:
            self._nav += 1
        if was_main:
            self._main += 1
        if tag == "title":
            self._in_title = True
            self._buf = []
        elif tag == "meta" and (attrs.get("name") or "").lower() in ("description", "og:description"):
            self.desc = (attrs.get("content") or "").strip()
        elif tag in ("p", "li"):
            self._in_para = tag
            self._buf = []
        self._stack.append((tag, was_skip, was_nav, was_main))

    def handle_endtag(self, tag):
        tag = (tag or "").lower()
        if self._stack:
            etag, was_skip, was_nav, was_main = self._stack.pop()
            if was_skip and self._skip:
                self._skip -= 1
            if was_nav and self._nav:
                self._nav -= 1
            if was_main and self._main:
                self._main -= 1
        if tag == "title" and self._in_title:
            self.title = " ".join("".join(self._buf).split())
            self._in_title = False
        elif tag in ("p", "li") and self._in_para:
            text = " ".join("".join(self._buf).split())
            if len(text) >= 20 and self._nav == 0:
                self.paras.append({"text": text, "in_main": self._main > 0, "tag": tag})
            self._in_para = None

    def handle_data(self, data):
        if self._skip:
            return
        self.total_chars += len(data)
        if self._main:
            self.main_chars += len(data)
        if self._in_title or self._in_para:
            self._buf.append(data)


def _sentences(text):
    parts = re.split(r"(?<=[。！？!?；;])\s*|(?<=[.!?])\s+", text or "")
    return [p.strip() for p in parts if p.strip()]


def _pick_sentence(text, topic=""):
    """P1：单句 + ≤320 字，优先含数字、含主题词。"""
    best, best_score = "", -1
    for s in _sentences(text):
        if len(s) < 40 or len(s) > MAX_QUOTE:
            continue
        score = 0
        if NUM_RE.search(s):
            score += 3
        if TOPIC_RE.search(s):
            score += 2
        if topic and topic.lower() in s.lower():
            score += 1
        score += min(len(s), MAX_QUOTE) / 100.0
        if score > best_score:
            best, best_score = s, score
    return best


def _body_gate(parser):
    """P0：内容质量门；返回 (ok, reason, body_text)。"""
    title = parser.title or ""
    if ANTIBOT_TITLE.search(title):
        return False, "反爬标题:%s" % title[:60], ""
    paras = [p for p in parser.paras if p["in_main"]] or [p for p in parser.paras if not p["in_main"]]
    body = " ".join(p["text"] for p in paras)
    blob = title + " " + body + " " + (parser.desc or "")
    for pat in LOGIN_PATTERNS:
        if pat.lower() in blob.lower():
            return False, "登录墙/反爬:%s" % pat, body
    if not body:
        return False, "无正文段落", ""
    if len(body) < MIN_BODY:
        return False, "正文过短:%d字" % len(body), body
    ratio = len(body) / max(parser.total_chars, 1)
    if ratio < MIN_RATIO:
        return False, "正文占比过低:%.1f%%" % (ratio * 100), body
    return True, "", body


def _get(url, timeout=DEFAULT_TIMEOUT):
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


# P1：schema adapter -------------------------------------------------------
OFFICIAL_DOMAINS = (
    "gov.cn", "europa.eu", "eea.europa.eu", "eia.gov", "epa.gov", "nist.gov",
    "iea.org", "irena.org", "iso.org", "iec.ch", "unfccc.int",
    "worldbank.org", "imf.org", "oecd.org",
)


def _region_of(url, quote=""):
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    if "gov.cn" in host or "nea.gov.cn" in host or "mee.gov.cn" in host:
        return "中国"
    if "europa.eu" in host:
        return "欧盟"
    if host.endswith("eia.gov") or host.endswith("epa.gov") or host.endswith("nist.gov"):
        return "美国"
    return "国际"


def _issuer_of(url):
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    table = [
        ("nea.gov.cn", "国家能源局"), ("mee.gov.cn", "生态环境部"),
        ("stats.gov.cn", "国家统计局"), ("cria.org.cn", "中国橡胶工业协会"),
        ("europa.eu", "欧洲委员会"), ("eea.europa.eu", "欧洲环境署"),
        ("eia.gov", "美国能源信息署（EIA）"), ("epa.gov", "美国环保署（EPA）"),
        ("ghgprotocol.org", "GHG Protocol"), ("worldbank.org", "世界银行"),
        ("unfccc.int", "UNFCCC"), ("iea.org", "IEA"), ("irena.org", "IRENA"),
    ]
    for key, name in table:
        if key in host:
            return name
    return host or "未知来源"


def _category_of(text):
    if re.search(r"(标准|规范|指南|核算|方法学|计量)", text):
        return "核算标准"
    if re.search(r"(通知|方案|意见|规划|条例|办法|公告|目录|规定)", text):
        return "政策文件"
    if re.search(r"(市场|交易|价格|数据|增长|产量|投资|消费|统计|同比|装机)", text):
        return "市场统计"
    if re.search(r"(项目|并网|工程|基地|电站|园区|平台)", text):
        return "基础设施"
    return "政策文件"


def _effective_of(text, url):
    m = re.search(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})", text or "")
    if m:
        return "%s-%02d-%02d" % (m.group(1), int(m.group(2)), int(m.group(3)))
    m = re.search(r"(20\d{2})[-/.年](\d{1,2})", text or "")
    if m:
        return "%s-%02d" % (m.group(1), int(m.group(2)))
    m = re.search(r"(20\d{2})(\d{2})(\d{2})", url or "")
    if m:
        return "%s-%s-%s" % (m.group(1), m.group(2), m.group(3))
    return "未注明"


def to_production_record(name, source_url, quote, topic, extra=None):
    """P1：把采集结果映射到生产 schema（24 字段的子集）。"""
    rec = {
        "name": _normalize(name)[:120],
        "source_url": _normalize(source_url),
        "quote": _normalize(quote)[:MAX_QUOTE],
        "topic": topic,
        "category": _category_of((name or "") + " " + (quote or "")),
        "region": _region_of(source_url, quote),
        "issuer": _issuer_of(source_url),
        "effective_date": _effective_of((name or "") + " " + (quote or ""), source_url),
        "summary": _normalize(name)[:120],
        "source": _issuer_of(source_url),
        "doc_number": "",
        "confidence_self": "A" if any(d in (urllib.parse.urlsplit(source_url).hostname or "").lower()
                                      for d in OFFICIAL_DOMAINS) else "B",
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        rec.update(extra)
    return rec


# 采集器 -------------------------------------------------------------------
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
        # P1：JSON 里超长 quote 也按单句截断；仍须保留原文前缀
        if len(quote) > MAX_QUOTE:
            q2 = _pick_sentence(quote, topic) or quote[:MAX_QUOTE]
            quote = q2
        extra = {k: item[k] for k in ("category", "region", "issuer", "effective_date",
                                      "summary", "confidence_self", "source", "doc_number")
                 if k in item}
        rec = to_production_record(name, src, quote, topic, extra)
        rec["source_page"] = source_url
        rec["source_kind"] = "json"
        out.append(rec)
    return out


def _extract_html(text, source_url, topic):
    parser = _PageParser()
    try:
        parser.feed(text or "")
    except Exception:  # noqa: BLE001
        return [], "解析失败"
    ok, reason, body = _body_gate(parser)
    if not ok:
        return [], reason
    quote = _pick_sentence(body, topic)
    if not quote:
        return [], "无合格单句(40-320字)"
    name = parser.title or urllib.parse.urlsplit(source_url).hostname or source_url
    rec = to_production_record(name, source_url, quote, topic)
    rec["source_page"] = source_url
    rec["source_kind"] = "html"
    return [rec], ""


def extract_html_record(text, source_url, topic):
    records, _reason = _extract_html(text, source_url, topic)
    return records


def collect(topic, sources, seen_file=DEFAULT_SEEN, limit=100, timeout=DEFAULT_TIMEOUT,
            write_seen=False):
    seen = load_seen(seen_file)
    records, new_seen = [], []
    stats = {"sources": 0, "fetched": 0, "fetch_failed": 0, "skipped_seen": 0,
             "empty_or_invalid": 0, "duplicates": 0, "records": 0,
             "seen_written": 0, "retries": 0}
    rejected = []
    dedupe = set()
    for source_url in sources:
        source_url = str(source_url or "").strip()
        stats["sources"] += 1
        key = _seen_key(source_url)
        if not _http_url(source_url):
            stats["empty_or_invalid"] += 1
            rejected.append({"url": source_url, "reason": "非法URL"})
            continue
        if key in seen:
            stats["skipped_seen"] += 1
            continue
        fetched = _get(source_url, timeout)
        if not fetched["ok"] or fetched["status"] != 200:
            # P2：失败重试 1 次，间隔 2 秒
            time.sleep(2)
            stats["retries"] += 1
            fetched = _get(source_url, timeout)
        if not fetched["ok"] or fetched["status"] != 200:
            stats["fetch_failed"] += 1
            rejected.append({"url": source_url, "reason": "抓取失败:%s" % fetched["error"]})
            continue
        stats["fetched"] += 1
        text = fetched["text"]
        ctype = (fetched["content_type"] or "").lower()
        parsed, reason = None, ""
        if "json" in ctype or text.lstrip().startswith(("{", "[")):
            try:
                parsed = extract_json_records(json.loads(text), source_url, topic)
            except ValueError:
                parsed = None
                reason = "JSON解析失败"
        if parsed is None:
            parsed, reason = _extract_html(text, source_url, topic)
        if not parsed:
            stats["empty_or_invalid"] += 1
            rejected.append({"url": source_url, "reason": reason or "无有效记录"})
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
    stats["rejected"] = rejected[:50]
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
                long_para = ("Gamma paragraph is long enough to become the quote. " * 5).strip()
                body = ("<html><head><title>Gamma page</title>"
                        "<meta name='description' content='Gamma desc'></head>"
                        "<body><article><p>%s</p></article></body></html>" % long_para).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/wall":
                body = ("<html><head><title>Login</title></head><body>"
                        "<article><p>您无权阅读本文，请登录或更改用户；这是一段足够长的正文文本，"
                        "用于测试登录墙检测是否生效。该页面不应该产出任何记录。</p></article></body></html>").encode()
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
        result = collect("test", [base + "/data.json", base + "/page", base + "/wall"],
                         seen, write_seen=True)
        assert result["stats"]["records"] == 3, (result["stats"], [r["name"] for r in result["records"]])
        names = {r["name"] for r in result["records"]}
        assert {"Alpha", "Beta", "Gamma page"} <= names, (names, result["stats"])
        assert all(r["source_url"] and r["quote"] for r in result["records"])
        assert all(r.get("category") and r.get("region") and r.get("issuer")
                   and r.get("confidence_self") for r in result["records"])
        assert result["stats"]["seen_written"] == 3, result["stats"]
        assert any("登录墙" in x.get("reason", "") for x in result["stats"]["rejected"]), result["stats"]["rejected"]
        checks.append("first_run")

        result2 = collect("test", [base + "/data.json", base + "/page", base + "/wall"], seen)
        assert result2["stats"]["skipped_seen"] == 3
        assert result2["stats"]["records"] == 0
        checks.append("seen_skip")

        assert os.path.exists(seen)
        assert len(load_seen(seen)) == 3
        checks.append("seen_file")
    finally:
        srv.shutdown()
        srv.server_close()
    print("OK collect self-test: %s" % ", ".join(checks))



# ===== v2: 反馈日志 + 统一 --check 入口（不改变原函数语义）=====
_SKILL_NAME = "collect"
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
        data = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError) as e:
        return _emit_check({"status": "not_verified", "error": "cannot read input: %s" % e})
    topic = data.get("topic", "") if isinstance(data, dict) else ""
    sources = data.get("sources", []) if isinstance(data, dict) else data
    seen = data.get("seen", "") if isinstance(data, dict) else ""
    result = collect(topic, sources or [], seen_file=seen,
                     write_seen=False)
    accepted = []
    missing = []
    for r in result.get("records", []):
        item = {"name": r.get("name"), "source_url": r.get("source_url"),
                "quote": r.get("quote"), "source_kind": r.get("source_kind")}
        if not item["source_url"] or not item["quote"]:
            missing.append(item)
        else:
            accepted.append(item)
    rejected = (result.get("stats") or {}).get("rejected", [])
    status = "auto_verified" if (accepted and not missing and not rejected) else "not_verified"
    return _emit_check({
        "status": status,
        "accepted": accepted,
        "rejected": rejected,
        "missing_source_or_quote": missing,
        "stats": result.get("stats", {}),
        "human_review": [{"reason": x.get("reason"), "url": x.get("url")} for x in rejected],
        "scope": "record_structure_only",
        "source_verified": False,
        "next": "run verify on accepted records",
        "feedback_log": _feedback_path(),
    })


def main(argv=None):
    p = argparse.ArgumentParser(description="Vigiliae gap-driven collector")
    p.add_argument("--test", action="store_true")
    p.add_argument("--topic", default="")
    p.add_argument("--source", action="append", default=[], help="source URL (repeatable)")
    p.add_argument("--source-file", help="JSON array of URLs or config with sources")
    p.add_argument("--seen", default=DEFAULT_SEEN)
    p.add_argument("--write-seen", action="store_true", help="显式允许写 seen 文件")
    p.add_argument("--no-write-seen", action="store_true", help=argparse.SUPPRESS)  # 兼容旧参数
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
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
                     write_seen=bool(args.write_seen))
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(payload)
        print("wrote %s (%d records, %d rejected)" % (
            args.output, len(result["records"]), len(result["stats"].get("rejected") or [])))
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(_front())

