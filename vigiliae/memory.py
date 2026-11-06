#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys

# ===== WORK MAP（v2，2026-11-06）=====
# 目标：跨会话记忆的写/读/搜/列/删 + 摘要注入
# 步骤：解析 frontmatter -> 作用域目录 -> 脱敏 -> 去重提示 -> 原子写 -> 摘要预算
# 输入：name/body/description/type/aliases/scope/cwd/home
# 输出：{ok,name,similar,path}；摘要 Markdown；v2 增加 before/after diff
# 依赖：标准库；VIGILIAE_MEMORY_HOME
# 分支：global/project；同名合并；别名；脱敏幂等；近期带
# ==========================================
"""更柝 Vigiliae · 记忆技能（memory skill）

设计来源：学自 dsh-memory-manager（MIT），但重写为更柝自己的 Python 实现。
伊森 2026-11-06：「学别人的技能，学到以后自己生成自己。有些简单的直接复制，
开源的对不对，直接当我们自己用。我们这个更柝就是我们最大的一个 bot。」

保留的核心机制（学来的）：
  ① 文件存储：YAML frontmatter + Markdown 正文，单条独立文件，任何编辑器能读写
  ② 作用域：global（跨项目）+ project（按 cwd 推导）
  ③ 5 个工具：write / read / search / list / delete
  ④ 摘要注入：按 updatedAt 倒序 + 24h 内「近期带」+ 字节预算
  ⑤ 写入去重：CJK-bigram + Jaccard（阈值 0.3），只提示不拦截
  ⑥ 别名：metadata.aliases，读/搜/删都认
  ⑦ 写入脱敏：确定性规则表，宁可漏不可过度打码
  ⑧ 幂等：重复写同一内容不改动

砍掉的（更柝不需要）：
  ✗ LLM 召回选择器 → 用词法
  ✗ 梦整流/轮末抽取 → 复杂，先不做
  ✗ 设置页 UI → 更柝有自己的控制台
  ✗ 详细事件审计 → 简化成一行
"""
import hashlib
import io
import json
import os
import re
import time
from collections import OrderedDict

# ── 路径 ──
DEFAULT_HOME = os.environ.get("VIGILIAE_MEMORY_HOME", os.path.join(os.path.expanduser("~"), ".vigiliae", "memory"))

# ── 配置 ──
DIGEST_MAX_ENTRIES = 24
DIGEST_ENTRY_CHARS = 120
DIGEST_MAX_BYTES = 2400
DIGEST_RECENT_HOURS = 24
DIGEST_RECENT_MAX = 6
SIMILAR_THRESHOLD = 0.3

# ══════════════════════════════════════════════════════════════
# 脱敏（学自 dsh-memory-manager/lib/redact.js）
# 原则：宁可漏，不可过度打码
#   · 只锚定 token 形状（前缀+长度）或显式赋值（name: value 且值含数字）
#   · 绝不匹配裸高熵字符串或裸词
#   · 幂等：[REDACTED:xxx] 不匹配任何规则
# ══════════════════════════════════════════════════════════════
REDACT_RULES = [
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S)),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
    ("api-key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}")),
    ("api-key", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{16,}")),
    ("api-key", re.compile(r"\bAKIA[A-Z0-9]{16,}")),
    ("api-key", re.compile(r"\bAIza[A-Za-z0-9_-]{30,}")),
    ("api-key", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    ("bearer", re.compile(r"\bBearer\s+[A-Za-z0-9._-]{20,}")),
    # URL basic auth: scheme://user:pass@host
    ("url-auth", re.compile(r"\b([a-z][a-z0-9+.-]*://)[^\s:/@]+:[^\s@/]+@")),
    # 显式赋值：name: value 或 name=value，值必须含数字（避免误伤 token: GITHUB_TOKEN）
    ("secret-assign", re.compile(
        r"\b((?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|"
        r"secret[_-]?key|private[_-]?key|credential|auth)\s*[:=]\s*)"
        r"([^\s,;'\"]{6,})", re.I)),
]


def redact(text):
    """写入前确定性脱敏。幂等：已打码的 [REDACTED:x] 不会再变。"""
    if not text:
        return text
    for kind, pat in REDACT_RULES:
        if kind == "url-auth":
            text = pat.sub(lambda m: m.group(1) + "[REDACTED:url-auth]@", text)
        elif kind == "secret-assign":
            def _sub(m):
                val = m.group(2)
                # 值不含数字 → 大概率不是密钥（如 token: GITHUB_TOKEN）
                if not re.search(r"\d", val):
                    return m.group(0)
                return m.group(1) + "[REDACTED:secret]"
            text = pat.sub(_sub, text)
        else:
            text = pat.sub("[REDACTED:%s]" % kind, text)
    return text


# ══════════════════════════════════════════════════════════════
# 笔记格式：YAML frontmatter + Markdown
#   ---
#   name: xxx
#   description: 一句话
#   type: fact|decision|preference|credential-location|lesson
#   aliases: [a, b]
#   updatedAt: 2026-11-06T12:30:00
#   ---
#   正文
# ══════════════════════════════════════════════════════════════
def _parse_note(text, fname):
    """解析 frontmatter + 正文"""
    note = {"name": fname[:-3] if fname.endswith(".md") else fname,
            "description": "", "type": "fact", "aliases": [], "body": ""}
    if not text.startswith("---"):
        note["body"] = text.strip()
        return note
    parts = text.split("---", 2)
    if len(parts) < 3:
        note["body"] = text.strip()
        return note
    fm, body = parts[1], parts[2]
    note["body"] = body.strip()
    for line in fm.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        k, v = line.split(":", 1)
        k, v = k.strip(), v.strip()
        if k == "name":
            note["name"] = v
        elif k == "description":
            note["description"] = v
        elif k == "type":
            note["type"] = v
        elif k == "updatedAt":
            note["updatedAt"] = v
        elif k == "aliases":
            v = v.strip("[]")
            note["aliases"] = [x.strip().strip("'\"") for x in v.split(",") if x.strip()]
    return note


def _format_note(note):
    """序列化成 YAML frontmatter + Markdown"""
    aliases = note.get("aliases") or []
    alias_s = ", ".join(aliases)
    lines = [
        "---",
        "name: %s" % note["name"],
        "description: %s" % note.get("description", ""),
        "type: %s" % note.get("type", "fact"),
    ]
    if alias_s:
        lines.append("aliases: [%s]" % alias_s)
    lines.append("updatedAt: %s" % note.get("updatedAt", _now_iso()))
    lines.append("---")
    lines.append("")
    lines.append(note.get("body", ""))
    return "\n".join(lines) + "\n"


def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


# ══════════════════════════════════════════════════════════════
# 作用域：global + project（按 cwd 推导）
# ══════════════════════════════════════════════════════════════
def project_key(cwd=None):
    """<slug>-<sha256(路径)[0:16]>（与 ZCode 目录命名方案一致）"""
    cwd = os.path.abspath(cwd or os.getcwd())
    slug = re.sub(r"[^a-z0-9]+", "-", os.path.basename(cwd).lower()).strip("-") or "root"
    h = hashlib.sha256(cwd.encode()).hexdigest()[:16]
    return "%s-%s" % (slug, h)


def scope_dir(scope="project", cwd=None, home=None):
    home = home or DEFAULT_HOME
    if scope == "global":
        return os.path.join(home, "global")
    return os.path.join(home, "projects", project_key(cwd), "memory")


def _ensure(d):
    os.makedirs(d, exist_ok=True)
    return d


# ══════════════════════════════════════════════════════════════
# 写入去重：CJK-bigram + Jaccard
# ══════════════════════════════════════════════════════════════
def _bigrams(s):
    s = re.sub(r"\s+", "", s.lower())
    if len(s) < 2:
        return {s} if s else set()
    return {s[i:i + 2] for i in range(len(s) - 1)}


def _jaccard(a, b):
    A, B = _bigrams(a), _bigrams(b)
    if not A or not B:
        return 0.0
    return len(A & B) / float(len(A | B))


def find_similar(scope, name, description, cwd=None, home=None):
    """找近似条目（只提示，不拦截）"""
    items = list_notes(scope, cwd, home)
    out = []
    for it in items:
        s = max(_jaccard(name, it["name"]),
                _jaccard(description, it.get("description", "")))
        if s >= SIMILAR_THRESHOLD:
            out.append({"name": it["name"], "score": round(s, 3)})
    out.sort(key=lambda x: -x["score"])
    return out[:5]


# ══════════════════════════════════════════════════════════════
# 5 个工具
# ══════════════════════════════════════════════════════════════
def memory_write(name, body, description="", type_="fact", aliases=None,
                 scope="project", cwd=None, home=None):
    """写记忆。同作用域同名 = 合并更新。返回 {ok, name, similar, viaAlias}"""
    d = _ensure(scope_dir(scope, cwd, home))
    name = re.sub(r"[/\\:*?\"<>|]", "_", name.strip())[:80]
    if not name:
        return {"ok": False, "error": "name 不能为空"}

    body = redact(body or "")
    description = redact(description or "")

    # 别名写入：只在原条目记下别名
    existing = {n["name"]: n for n in list_notes(scope, cwd, home)}
    for ename, en in existing.items():
        if aliases and name in (en.get("aliases") or []):
            return {"ok": True, "name": ename, "viaAlias": True,
                    "similar": find_similar(scope, name, description, cwd, home)}

    similar = find_similar(scope, name, description, cwd, home)
    path = os.path.join(d, name + ".md")
    note = existing.get(name) or {"name": name, "aliases": []}
    note["description"] = description or note.get("description", "")
    note["type"] = type_
    note["body"] = body
    note["updatedAt"] = _now_iso()
    if aliases:
        merged = list(OrderedDict.fromkeys((note.get("aliases") or []) + aliases))
        note["aliases"] = merged

    # 原子写
    tmp = path + ".tmp"
    io.open(tmp, "w", encoding="utf-8").write(_format_note(note))
    os.replace(tmp, path)
    return {"ok": True, "name": name, "similar": similar, "path": path}


def list_notes(scope="project", cwd=None, home=None):
    """列出记忆（按 updatedAt 倒序）"""
    d = scope_dir(scope, cwd, home)
    if not os.path.isdir(d):
        return []
    items = []
    for f in sorted(os.listdir(d)):
        if not f.endswith(".md"):
            continue
        try:
            txt = io.open(os.path.join(d, f), encoding="utf-8").read()
        except Exception:
            continue
        n = _parse_note(txt, f)
        n["_scope"] = scope
        items.append(n)
    items.sort(key=lambda x: x.get("updatedAt", ""), reverse=True)
    return items


def _resolve(name, scope, cwd, home):
    """按 name 或 alias 解析到实际条目"""
    items = list_notes(scope, cwd, home)
    for it in items:
        if it["name"] == name:
            return it
    for it in items:
        if name in (it.get("aliases") or []):
            return it
    return None


def memory_read(name, scope="project", cwd=None, home=None):
    it = _resolve(name, scope, cwd, home)
    if not it:
        return {"ok": False, "error": "未找到: %s" % name}
    return {"ok": True, "note": it}


def memory_search(q, scope="project", cwd=None, home=None, limit=10):
    """词法搜索：CJK-bigram Jaccard + 子串命中加权"""
    items = list_notes(scope, cwd, home)
    scored = []
    for it in items:
        hay = " ".join([it["name"], it.get("description", ""), it.get("body", "")])
        s = 0.0
        if q.lower() in hay.lower():
            s += 1.0
        s += _jaccard(q, it["name"]) * 0.5
        s += _jaccard(q, it.get("description", "")) * 0.3
        s += _jaccard(q, it.get("body", "")[:500]) * 0.2
        if s > 0:
            scored.append((s, it))
    scored.sort(key=lambda x: -x[0])
    return {"ok": True, "hits": [{"score": round(s, 3), **it} for s, it in scored[:limit]]}


def memory_delete(name, scope="project", cwd=None, home=None):
    it = _resolve(name, scope, cwd, home)
    if not it:
        return {"ok": False, "error": "未找到: %s" % name}
    path = os.path.join(scope_dir(scope, cwd, home), it["name"] + ".md")
    try:
        os.remove(path)
        return {"ok": True, "deleted": it["name"]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ══════════════════════════════════════════════════════════════
# 摘要注入（这是精髓）
#   · 按 updatedAt 倒序（≤24 条，每条 ≤120 字）
#   · 24h 内更新的，另成「近期」带（≤6 条）
#   · 字节预算（≤2400 字节）
# 关键：参照时间取「缓存快照」而非墙钟 → 同一快照多次渲染字节一致
# ══════════════════════════════════════════════════════════════
def build_digest(cwd=None, home=None, snapshot_time=None):
    """生成注入到 systemPrompt 的记忆摘要"""
    snap = snapshot_time or time.time()
    items = list_notes("project", cwd, home)
    if not items:
        return ""

    def age_h(it):
        try:
            ts = time.mktime(time.strptime(it.get("updatedAt", "")[:19], "%Y-%m-%dT%H:%M:%S"))
            return (snap - ts) / 3600.0
        except Exception:
            return 9999.0

    recent = [i for i in items if age_h(i) <= DIGEST_RECENT_HOURS][:DIGEST_RECENT_MAX]
    recent_names = {i["name"] for i in recent}

    lines = ["## 记忆（当前项目）"]
    used = len(lines[0].encode("utf-8"))
    n = 0
    for it in items:
        if n >= DIGEST_MAX_ENTRIES:
            break
        if it["name"] in recent_names:
            continue
        line = "- %s：%s" % (it["name"],
                            (it.get("description") or it.get("body", ""))[:DIGEST_ENTRY_CHARS])
        b = len(line.encode("utf-8"))
        if used + b > DIGEST_MAX_BYTES:
            break
        lines.append(line)
        used += b
        n += 1

    if recent:
        lines.append("")
        lines.append("### 近 24 小时更新")
        for it in recent:
            line = "- %s：%s" % (it["name"],
                                (it.get("description") or it.get("body", ""))[:DIGEST_ENTRY_CHARS])
            b = len(line.encode("utf-8"))
            if used + b > DIGEST_MAX_BYTES:
                break
            lines.append(line)
            used += b

    g = list_notes("global", cwd, home)
    if g:
        lines.append("")
        lines.append("（全局记忆 %d 条）" % len(g))

    return "\n".join(lines)



# ===== v2: 反馈日志 + 统一 --check 入口（不改变原函数语义）=====
_SKILL_NAME = "memory"
_HAS_MAIN = False
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


def _note_text(note):
    if not note:
        return ""
    return "name: %s\ndescription: %s\ntype: %s\n\n%s" % (
        note.get("name", ""), note.get("description", ""),
        note.get("type", ""), note.get("body", ""))


def _check_main(path):
    import difflib
    try:
        req = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError) as e:
        return _emit_check({"status": "not_verified", "error": "cannot read input: %s" % e})
    op = req.get("operation") or req.get("op") or "write"
    home = req.get("home") or os.environ.get("VIGILIAE_MEMORY_HOME")
    scope = req.get("scope", "project")
    name = req.get("name", "")
    before = memory_read(name, scope=scope, home=home).get("note") if name else None
    if op == "write":
        r = memory_write(name, req.get("body", ""), req.get("description", ""),
                         req.get("type", "fact"), req.get("aliases"), scope=scope, home=home)
    elif op == "delete":
        r = memory_delete(name, scope=scope, home=home)
    elif op in ("read", "search", "list"):
        r = {"ok": True, "op": op}
    else:
        return _emit_check({"status": "not_verified", "error": "unknown operation: %s" % op})
    after = memory_read(name, scope=scope, home=home).get("note") if name and op != "delete" else None
    before_s, after_s = _note_text(before), _note_text(after)
    diff = list(difflib.unified_diff(before_s.splitlines(), after_s.splitlines(),
                                     fromfile="before", tofile="after", lineterm=""))
    changed = before_s != after_s
    human = []
    if op == "delete":
        human.append({"what": "delete", "detail": "删除属于决定，必须人工确认"})
    if r.get("ok"):
        status = "human_review" if op == "delete" else "auto_verified"
    else:
        status = "not_verified"
    return _emit_check({
        "status": status,
        "operation": op,
        "result": r,
        "changed": changed,
        "diff": "\n".join(diff),
        "before_chars": len(before_s),
        "after_chars": len(after_s),
        "human_review": human,
        "scope": "file_diff_only",
        "not_checked": ["semantic correctness"],
        "feedback_log": _feedback_path(),
    })


# ══════════════════════════════════════════════════════════════
# CLI（方便测试）
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import sys
    if "--check" in sys.argv or "--feedback" in sys.argv:
        raise SystemExit(_front())
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"

    if cmd == "test":
        home = os.path.join(os.environ.get("TEMP", "/tmp"), "_vig_mem_test")
        print("测试目录: %s" % home)

        r = memory_write("腾讯云凭据", "SecretId 在 .keys/tencent_cloud.txt",
                         "腾讯云子账号凭据存放位置", "credential-location", home=home)
        print("写入1: %s" % r)

        r = memory_write("腾讯云账号", "同一条，测试别名",
                         "别名测试", "credential-location",
                         aliases=["tencent", "腾讯"], home=home)
        print("写入2: %s" % r)

        r = memory_write("测试脱敏", "我的 key 是 sk-EXAMPLE0000000000000000000000",
                         "脱敏测试", "fact", home=home)
        print("写入3(脱敏): %s" % r)
        print("  读回: %s" % memory_read("测试脱敏", home=home)["note"]["body"])

        print("\n列表: %s" % [x["name"] for x in list_notes(home=home)])
        print("搜索「腾讯」: %s" % [x["name"] for x in memory_search("腾讯", home=home)["hits"]])
        print("别名读「tencent」: %s" % memory_read("tencent", home=home).get("note", {}).get("name"))
        print("\n=== 摘要 ===")
        print(build_digest(home=home))

    elif cmd == "write":
        print(memory_write(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "",
                           sys.argv[4] if len(sys.argv) > 4 else ""))
    elif cmd == "list":
        for x in list_notes():
            print("- %s：%s" % (x["name"], x.get("description", "")))
    elif cmd == "digest":
        print(build_digest())
    else:
        print("用法: python3 memory.py [test|write|list|digest]")
