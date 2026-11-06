#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""更柝 Vigiliae · 一键安装器（install skill / installer）

学自：
  · dsh-skill-manager 的“扫描 → 校验 → 状态机”安装思路（MIT）；
  · 更柝自己的 docs/DEPLOY.md 手工步骤：环境检查 → 目录 → 代码 → agents
    → systemd/nohup → 健康检查。
  不照抄任何插件的安装代码。

一条命令：
  curl -sSL https://trustbaselab.com/vigiliae-install.sh | bash
  # 或
  pip install vigiliae && vigiliae init

能处理的边界：
  · 没有 systemd（容器）→ nohup 降级
  · 端口被占 → 自动换端口
  · 已有安装 → 升级模式，保留 data/ 和 .env
  · 权限不够 → 明确提示 sudo / 换 --prefix
  · 没网 → 本地源码模式可装；需要 pip 依赖时提示离线

用法：
  python -m vigiliae.install --prefix /opt/vigiliae
  python -m vigiliae.install --test
  python -m vigiliae.init --test   # 兼容入口
"""
import argparse
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

APP_NAME = "vigiliae"
DEFAULT_PORT = 8110
DEFAULT_PREFIX = "/opt/vigiliae" if os.name != "nt" else os.path.join(
    os.path.expanduser("~"), "vigiliae")
MIN_PYTHON = (3, 9)
MIN_NODE = 20
REQUIRED_AGENTS = 12
SKIP_DIRS = {".git", "data", "venv", ".venv", "__pycache__", ".backup-20261105-2253"}
SKIP_NAMES = {".env", "agents.yaml", "*.pyc", "*.pyo"}


class InstallError(RuntimeError):
    pass


def log(msg):
    print("[vigiliae-install] " + msg, flush=True)


def warn(msg):
    print("[vigiliae-install] WARNING: " + msg, flush=True)


def fail(msg):
    raise InstallError(msg)


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_root():
    return hasattr(os, "geteuid") and os.geteuid() == 0


def python_ok():
    return sys.version_info >= MIN_PYTHON


def node_version():
    exe = shutil.which("node")
    if not exe:
        return None
    try:
        out = subprocess.check_output([exe, "--version"], text=True, timeout=5).strip()
        m = re.search(r"v?(\d+)", out)
        return int(m.group(1)) if m else None
    except Exception:  # noqa: BLE001
        return None


def has_systemd():
    return (sys.platform.startswith("linux") and bool(shutil.which("systemctl"))
            and os.path.isdir("/run/systemd/system"))


def port_free(port, host="0.0.0.0"):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((host, int(port)))
        return True
    except OSError:
        return False
    finally:
        s.close()


def choose_port(start, host="0.0.0.0"):
    for p in range(int(start), int(start) + 30):
        if port_free(p, host):
            return p
    return None


def _source_root():
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    parent = os.path.dirname(pkg_dir)
    for c in (parent, pkg_dir, os.getcwd()):
        if os.path.isdir(os.path.join(c, "vigiliae")) and (
                os.path.exists(os.path.join(c, "agents.yaml"))
                or os.path.exists(os.path.join(c, "pyproject.toml"))):
            return c
    # pip-installed package: the only source tree is the package itself.
    return pkg_dir


def _default_agents_path(root):
    for c in (os.path.join(root, "agents.yaml"),
              os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "agents.yaml")):
        if os.path.exists(c):
            return c
    return None


def _ignore(_dir, names):
    return [n for n in names if n in SKIP_DIRS or n.endswith((".pyc", ".pyo"))]


def copy_app(source_root, app_dir, upgrade=False):
    """Copy source/package into <prefix>/app. Existing data is never touched."""
    if not os.path.isdir(app_dir):
        os.makedirs(app_dir, exist_ok=True)
    if os.path.isdir(os.path.join(source_root, "vigiliae")):
        # Source checkout: copy the package + runtime docs, not .git/data/.env.
        for name in os.listdir(source_root):
            if name in SKIP_DIRS or name in (".env", "agents.yaml") or name.startswith(".backup"):
                continue
            src = os.path.join(source_root, name)
            dst = os.path.join(app_dir, name)
            if os.path.isdir(src):
                shutil.copytree(src, dst, dirs_exist_ok=True, ignore=_ignore)
            else:
                shutil.copy2(src, dst)
    else:
        # pip-installed package: copy the package directory itself.
        pkg_src = os.path.dirname(os.path.abspath(__file__))
        shutil.copytree(pkg_src, os.path.join(app_dir, "vigiliae"),
                        dirs_exist_ok=True, ignore=_ignore)
        req = os.path.join(app_dir, "requirements.txt")
        if not os.path.exists(req):
            with open(req, "w", encoding="utf-8") as fh:
                fh.write("Flask>=3.0,<4\nPyYAML>=6.0,<7\n")
    return app_dir


def _read_text(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _write_text(path, text, mode=0o644):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def validate_agents(path):
    """Return (ok, count, error). PyYAML is optional for install validation."""
    try:
        import yaml
        data = yaml.safe_load(_read_text(path)) or {}
        agents = data.get("agents") or []
        return len(agents) == REQUIRED_AGENTS, len(agents), ""
    except ImportError:
        text = _read_text(path)
        count = len(re.findall(r"(?m)^\s*-\s+name:", text))
        return count == REQUIRED_AGENTS, count, ""
    except Exception as e:  # noqa: BLE001
        return False, 0, str(e)[:300]


def install_agents(source_root, app_dir, existing, force=False):
    dst = os.path.join(app_dir, "agents.yaml")
    if existing and os.path.exists(dst) and not force:
        ok, count, err = validate_agents(dst)
        if ok and "skills:" in _read_text(dst):
            return dst, "kept existing agents.yaml"
        if ok:
            warn("existing agents.yaml is valid but has no skills metadata; upgrading to 12-agent skill config")
        else:
            warn("existing agents.yaml has %s agent(s) (%s); replacing with 12" % (count, err))
    src = _default_agents_path(source_root)
    if not src:
        fail("no bundled agents.yaml found; run from the source checkout or pip package with templates/agents.yaml")
    shutil.copy2(src, dst)
    ok, count, err = validate_agents(dst)
    if not ok:
        fail("generated agents.yaml has %s agent(s), expected %d (%s)" % (
            count, REQUIRED_AGENTS, err))
    return dst, "wrote 12 agents"


def build_env(prefix, app_dir, port, token=None, existing_env=None):
    existing = {}
    if existing_env and os.path.exists(existing_env):
        for line in _read_text(existing_env).splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                existing[k.strip()] = v.strip()
    token = token or existing.get("BOT_TOKEN") or ("bot-" + secrets.token_urlsafe(24))
    port = int(port or existing.get("VIGILIAE_PORT") or DEFAULT_PORT)
    host = existing.get("VIGILIAE_HOST") or "0.0.0.0"
    values = {
        "BOT_TOKEN": token,
        "VIGILIAE_HOST": host,
        "VIGILIAE_PORT": str(port),
        "VIGILIAE_DATA_DIR": os.path.join(prefix, "data"),
        "VIGILIAE_AGENTS": os.path.join(app_dir, "agents.yaml"),
        "VIGILIAE_BASE_URL": "http://127.0.0.1:%s" % port,
        "VIGILIAE_TZ_OFFSET": existing.get("VIGILIAE_TZ_OFFSET") or "8",
        "VIGILIAE_HEARTBEAT_TIMEOUT": existing.get("VIGILIAE_HEARTBEAT_TIMEOUT") or "120",
        "DSH_BIN": existing.get("DSH_BIN") or "dsh",
        "DSH_PROFILE": existing.get("DSH_PROFILE") or "headless",
        "DSH_TIMEOUT": existing.get("DSH_TIMEOUT") or "180",
        "DSH_DAILY_LIMIT": existing.get("DSH_DAILY_LIMIT") or "200",
    }
    body = "# Generated by vigiliae-install; keep this file private.\n"
    body += "\n".join("%s=%s" % (k, v) for k, v in values.items()) + "\n"
    env_path = os.path.join(prefix, ".env")
    _write_text(env_path, body, 0o600)
    return env_path, values


def parse_env(path):
    out = {}
    try:
        for line in _read_text(path).splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    except OSError:
        pass
    return out


def ensure_venv(prefix, app_dir, no_venv=False, offline=False):
    if no_venv:
        return sys.executable, "using current interpreter (--no-venv)"
    venv = os.path.join(prefix, "venv")
    py = os.path.join(venv, "bin", "python")
    if os.name == "nt":
        py = os.path.join(venv, "Scripts", "python.exe")
    if not os.path.exists(py):
        log("creating venv: %s" % venv)
        rc = subprocess.call([sys.executable, "-m", "venv", venv])
        if rc != 0:
            # Most clean Debian/Ubuntu images do not ship python3-venv.
            # Falling back to the current interpreter is safer than failing
            # the whole install: Flask/PyYAML are often already available.
            warn("python -m venv failed (rc=%s); falling back to current interpreter. "
                 "Install python3-venv for an isolated venv, or rerun with --no-venv." % rc)
            return sys.executable, "venv creation failed; using current interpreter"
    req = os.path.join(app_dir, "requirements.txt")
    if os.path.exists(req):
        log("installing Python dependencies")
        cmd = [py, "-m", "pip", "install", "-r", req]
        if offline:
            cmd.append("--no-index")
        rc = subprocess.call(cmd)
        if rc != 0:
            warn("pip install in venv failed (rc=%s); falling back to current interpreter. "
                 "If Flask/PyYAML are missing, install them first or use --offline." % rc)
            return sys.executable, "dependency install failed; using current interpreter"
    return py, "venv"


def write_systemd(prefix, app_dir, python_bin):
    unit = """[Unit]
Description=Vigiliae / 更柝 — self-hosted AI agent runtime
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=%s
EnvironmentFile=%s/.env
ExecStart=%s -m vigiliae
Restart=always
RestartSec=5
KillSignal=SIGTERM
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
""" % (app_dir, prefix, python_bin)
    path = "/etc/systemd/system/vigiliae.service"
    _write_text(path, unit)
    return path


def stop_existing(prefix):
    pid_file = os.path.join(prefix, "vigiliae.pid")
    if os.path.exists(pid_file):
        try:
            pid = int(_read_text(pid_file).strip())
            os.kill(pid, 15)
            time.sleep(1)
            os.kill(pid, 0)
            os.kill(pid, 9)
        except (OSError, ValueError):
            pass
        try:
            os.remove(pid_file)
        except OSError:
            pass
    if has_systemd() and os.path.exists("/etc/systemd/system/vigiliae.service"):
        subprocess.call(["systemctl", "stop", "vigiliae"], stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL)


def start_nohup(prefix, app_dir, python_bin, env_values):
    log_dir = os.path.join(prefix, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "app.log")
    env = os.environ.copy()
    env.update(env_values)
    env["PYTHONUNBUFFERED"] = "1"
    out = open(log_path, "a", encoding="utf-8")
    proc = subprocess.Popen([python_bin, "-m", "vigiliae"], cwd=app_dir, env=env,
                            stdout=out, stderr=subprocess.STDOUT,
                            start_new_session=True)
    out.close()
    _write_text(os.path.join(prefix, "vigiliae.pid"), str(proc.pid))
    return proc.pid, log_path


def sync_agents(app_dir, python_bin, env_values):
    env = os.environ.copy()
    env.update(env_values)
    cmd = [python_bin, "-m", "vigiliae.agents", "sync", "agents.yaml"]
    log("registering 12 agents")
    rc = subprocess.call(cmd, cwd=app_dir, env=env)
    if rc != 0:
        fail("agent sync failed (rc=%s)" % rc)
    return True


def check_agents_api(port, token="", timeout=10):
    url = "http://127.0.0.1:%s/api/agents" % port
    headers = {}
    if token:
        headers["Cookie"] = "cb_auth=" + token
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        agents = data.get("agents") or []
        return len(agents), ""
    except Exception as e:  # noqa: BLE001
        return 0, str(e)[:300]


def detect_public_ip():
    """Best-effort public IP; empty string when offline or blocked."""
    try:
        with urllib.request.urlopen("https://api.ipify.org", timeout=3) as r:
            ip = r.read(64).decode("ascii", "ignore").strip()
            if re.match(r"^[0-9a-fA-F:.]+$", ip):
                return ip
    except Exception:  # noqa: BLE001
        pass
    return ""


def access_info(port, token, public_ip="", host="127.0.0.1"):
    """Build the exact first-visit URLs.  ?k= is required once to set the cookie."""
    q = urllib.parse.quote(token or "", safe="")
    local = "http://127.0.0.1:%d" % port
    public = "http://%s:%d" % (public_ip or "<公网IP>", port)
    return {
        "local_url": local,
        "public_url": public,
        "login_url": local + "/login?k=" + q,
        "public_login_url": public + "/login?k=" + q,
        "status_url": local + "/api/status?k=" + q,
        "token": token,
    }


def print_access(port, token, public_ip="", started=True):
    info = access_info(port, token, public_ip)
    print("")
    print("[vigiliae-install] ✅ 安装%s" % ("成功" if started else "完成（未启动）"))
    print("")
    print("  控制台：%s" % info["public_login_url"])
    print("  或者：  %s" % info["login_url"])
    print("")
    print("  ⚠️ 第一次访问必须带 ?k=<BOT_TOKEN>，会种 cookie；之后直接访问 http://<IP>:%d/ 即可。" % port)
    print("  ⚠️ 如果云厂商有安全组/防火墙，请放行 TCP %d。" % port)
    print("")
    print("  查看状态：curl -L '%s'" % info["status_url"])
    print("  登录拿 cookie：curl -c /tmp/vig.cookie -L '%s'" % info["login_url"])
    print("  之后带 cookie：curl -b /tmp/vig.cookie '%s/api/tasks'" % info["local_url"])
    print("")
    return info


def health(port, host="127.0.0.1", timeout=30):
    url = "http://%s:%s/api/health" % (host, port)
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return True, url
        except Exception as e:  # noqa: BLE001
            last = str(e)[:200]
        time.sleep(0.5)
    return False, last


def install(args):
    prefix = os.path.abspath(os.path.expanduser(args.prefix or DEFAULT_PREFIX))
    source_root = os.path.abspath(args.source or _source_root())
    app_dir = os.path.join(prefix, "app")
    data_dir = os.path.join(prefix, "data")
    existing = os.path.exists(os.path.join(prefix, "app", "agents.yaml")) or (
        os.path.exists(os.path.join(data_dir, "vigiliae.db"))) or os.path.exists(
        os.path.join(prefix, ".installed"))

    log("source: %s" % source_root)
    log("prefix: %s" % prefix)
    log("mode: %s" % ("upgrade (data preserved)" if existing else "fresh install"))

    if not python_ok():
        fail("Python %d.%d+ required, got %s" % (
            MIN_PYTHON[0], MIN_PYTHON[1], sys.version.split()[0]))
    node = node_version()
    if node is None:
        warn("Node.js not found; DSH headless brain will not start until Node 20+ is installed")
    elif node < MIN_NODE:
        warn("Node.js %s found; DSH needs Node 20+" % node)

    systemd = has_systemd() and not args.no_systemd
    if systemd and not is_root():
        fail("systemd install needs root. Rerun with sudo, or use --no-systemd for nohup")
    if not systemd:
        log("systemd not available/disabled; using nohup fallback")

    parent = os.path.dirname(prefix)
    if not os.access(parent, os.W_OK) and not is_root():
        fail("no write permission to %s. Use sudo, or --prefix $HOME/vigiliae" % parent)

    # Network is not required for a local source install; only warn for venv deps.
    if not args.no_network_check:
        try:
            socket.create_connection(("pypi.org", 443), timeout=3).close()
        except OSError:
            warn("no network to pypi.org; if dependencies are missing use --no-venv/--offline")

    port = args.port or DEFAULT_PORT
    if existing and os.path.exists(os.path.join(prefix, ".env")):
        old = parse_env(os.path.join(prefix, ".env"))
        port = int(old.get("VIGILIAE_PORT") or port)
    if existing and not args.dry_run:
        # Stop the old process first; otherwise the old listener makes the
        # port look occupied and an upgrade would drift to a new port.
        stop_existing(prefix)
    if not port_free(port):
        new_port = choose_port(port + 1)
        if new_port is None:
            fail("no free port in %s..%s" % (port, port + 30))
        warn("port %s is occupied; using %s" % (port, new_port))
        port = new_port

    plan = {
        "prefix": prefix, "app_dir": app_dir, "data_dir": data_dir,
        "port": port, "systemd": systemd, "upgrade": existing,
        "source": source_root,
    }
    public_ip = (args.public_ip or os.environ.get("VIGILIAE_PUBLIC_IP") or "").strip()
    if not public_ip and not args.no_network_check:
        public_ip = detect_public_ip()
    plan["public_ip"] = public_ip or "<公网IP>"
    if args.dry_run:
        print(json.dumps({"dry_run": True, "plan": plan}, ensure_ascii=False, indent=2))
        return 0

    os.makedirs(prefix, exist_ok=True)
    os.makedirs(data_dir, exist_ok=True)
    log("copying app files")
    copy_app(source_root, app_dir, upgrade=existing)

    agents_path, agents_note = install_agents(
        source_root, app_dir, existing, force=args.force_agents)
    log(agents_note + ": " + agents_path)
    env_path, env_values = build_env(prefix, app_dir, port,
                                     existing_env=os.path.join(prefix, ".env"))
    log("wrote env: " + env_path)

    python_bin, py_note = ensure_venv(prefix, app_dir, no_venv=args.no_venv,
                                      offline=args.offline)
    log("python: %s (%s)" % (python_bin, py_note))
    sync_agents(app_dir, python_bin, env_values)

    _write_text(os.path.join(prefix, ".installed"), _now() + "\n")

    if systemd:
        unit = write_systemd(prefix, app_dir, python_bin)
        log("wrote systemd unit: " + unit)
        subprocess.check_call(["systemctl", "daemon-reload"])
        subprocess.check_call(["systemctl", "enable", "--now", "vigiliae"])
    elif not args.no_start:
        pid, log_path = start_nohup(prefix, app_dir, python_bin, env_values)
        log("started pid=%s log=%s" % (pid, log_path))
    else:
        log("--no-start: files installed; run `%s -m vigiliae` in %s" % (python_bin, app_dir))
        pid = None

    if args.no_start:
        info = print_access(port, env_values.get("BOT_TOKEN", ""), public_ip, started=False)
        print(json.dumps({"ok": True, "plan": plan, "started": False,
                          "url": info["public_url"], "login_url": info["public_login_url"],
                          "local_login_url": info["login_url"],
                          "status_url": info["status_url"]},
                         ensure_ascii=False, indent=2))
        return 0

    ok, url_or_err = health(port)
    if not ok:
        tail = ""
        try:
            with open(os.path.join(prefix, "logs", "app.log"), encoding="utf-8") as fh:
                tail = "".join(fh.readlines()[-30:])
        except OSError:
            pass
        fail("service did not become healthy: %s\n%s" % (url_or_err, tail))
    agent_count, agent_err = check_agents_api(port, env_values.get("BOT_TOKEN", ""))
    if agent_count != REQUIRED_AGENTS:
        fail("service is up but /api/agents returned %s agents (%s); expected %d" % (
            agent_count, agent_err or "no error", REQUIRED_AGENTS))
    log("healthy: %s (%d agents)" % (url_or_err, agent_count))
    info = print_access(port, env_values.get("BOT_TOKEN", ""), public_ip, started=True)
    print(json.dumps({
        "ok": True, "url": info["public_url"],
        "login_url": info["public_login_url"],
        "local_login_url": info["login_url"],
        "status_url": info["status_url"],
        "prefix": prefix, "port": port, "systemd": systemd, "upgrade": existing,
        "agents": agents_path, "env": env_path,
    }, ensure_ascii=False, indent=2))
    return 0


# ──────────────────────────────────────────────────────────────
# self-test：不装系统服务、不联网
# ──────────────────────────────────────────────────────────────
def _self_test():
    tmp = tempfile.mkdtemp(prefix="vigil-install-test-")
    source = _source_root()
    checks = []
    try:
        assert python_ok()
        checks.append("python")
        assert port_free(DEFAULT_PORT) or choose_port(DEFAULT_PORT) is not None
        checks.append("port")
        agents_src = _default_agents_path(source)
        assert agents_src, "no agents.yaml source"
        app = os.path.join(tmp, "app")
        copy_app(source, app)
        agents, note = install_agents(source, app, False, force=True)
        ok, count, err = validate_agents(agents)
        assert ok and count == REQUIRED_AGENTS, (ok, count, err)
        checks.append("agents12")
        env_path, vals = build_env(tmp, app, 8910)
        assert vals["VIGILIAE_PORT"] == "8910"
        assert vals["VIGILIAE_AGENTS"] == os.path.join(app, "agents.yaml")
        assert os.path.exists(env_path)
        checks.append("env")
        # upgrade must preserve data and existing env token
        os.makedirs(os.path.join(tmp, "data"), exist_ok=True)
        db = os.path.join(tmp, "data", "vigiliae.db")
        with open(db, "w", encoding="utf-8") as fh:
            fh.write("keep-me")
        token = vals["BOT_TOKEN"]
        env2, vals2 = build_env(tmp, app, 8911, existing_env=env_path)
        assert vals2["BOT_TOKEN"] == token
        assert open(db, encoding="utf-8").read() == "keep-me"
        checks.append("upgrade-preserve")
        # occupied port -> next port
        s = socket.socket(); s.bind(("0.0.0.0", 0)); used = s.getsockname()[1]
        s.listen(1)
        try:
            nxt = choose_port(used + 1)
            assert nxt is not None and nxt != used
        finally:
            s.close()
        checks.append("port-fallback")
        # first-visit URL must include ?k= and the public/local forms
        info = access_info(8910, "bot-test", "203.0.113.7")
        assert info["login_url"].endswith("/login?k=bot-test")
        assert info["public_login_url"].startswith("http://203.0.113.7:8910/")
        assert info["status_url"].endswith("/api/status?k=bot-test")
        checks.append("access-urls")
        # venv creation failure must hard-fallback to current interpreter
        orig_call = subprocess.call
        def _fake_venv_fail(cmd, *a, **kw):
            if isinstance(cmd, (list, tuple)) and len(cmd) >= 3 and cmd[1:3] == ["-m", "venv"]:
                return 1
            return 0
        subprocess.call = _fake_venv_fail
        try:
            fb_python, fb_note = ensure_venv(os.path.join(tmp, "venv-test"), app)
            assert fb_python == sys.executable, (fb_python, fb_note)
            assert "fallback" in fb_note.lower() or "failed" in fb_note.lower()
        finally:
            subprocess.call = orig_call
        checks.append("venv-fallback")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("OK install self-test: %s" % ", ".join(checks))


def main(argv=None):
    # Windows consoles default to GBK; the success output uses ✅ and Chinese.
    # Reconfigure to UTF-8 (with replacement) so install never crashes at the
    # final "how to open" step after the service is already running.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    p = argparse.ArgumentParser(description="Vigiliae one-command installer")
    p.add_argument("--prefix", default=DEFAULT_PREFIX, help="install root (default /opt/vigiliae)")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--host", default="127.0.0.1", help="printed host only")
    p.add_argument("--public-ip", default="", help="public IP shown in access URLs (auto-detected if blank)")
    p.add_argument("--source", help="source checkout (default: auto)")
    p.add_argument("--no-systemd", action="store_true", help="force nohup fallback")
    p.add_argument("--no-venv", action="store_true", help="use current Python")
    p.add_argument("--no-start", action="store_true", help="install only")
    p.add_argument("--no-network-check", action="store_true")
    p.add_argument("--offline", action="store_true", help="pip --no-index")
    p.add_argument("--force-agents", action="store_true", help="overwrite existing agents.yaml")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--test", action="store_true")
    p.add_argument("--json", action="store_true", help="machine-readable result (best effort)")
    args = p.parse_args(argv)

    if args.test:
        try:
            _self_test()
            return 0
        except Exception as e:  # noqa: BLE001
            print("FAIL install self-test: %s" % e, file=sys.stderr)
            return 1
    try:
        return install(args)
    except InstallError as e:
        print("ERROR: %s" % e, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
