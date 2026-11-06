# Vigiliae · 更柝

**一个跑在你自己服务器上的 AI 团队 —— 12 个守夜人，你关机它继续工作，数据永远不出你的机器。**

[English README](README.md) · 中文说明（本页）

---
**一个跑在你自己服务器上的 AI 团队 —— 12 个守夜人，你关机它继续工作，数据永远不出你的机器。**

[![tests](https://github.com/Trustbaselab/vigiliae/actions/workflows/tests.yml/badge.svg)](https://github.com/Trustbaselab/vigiliae/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![Status: early stage](https://img.shields.io/badge/status-early%20stage-orange.svg)](#honest-limitations)

---

## 30 秒看懂

```
你付：一台云服务器（约 200-500 元/月）
你得到：
  · 12 个各有名字的 AI 员工，24 小时值班
  · 你关机，服务器继续干活
  · 数据 100% 在你自己的服务器
  · 技能可组合、可扩展
  · 大模型可选（DeepSeek / Qwen / 本地部署）

⭐ Grok Bot（xAI）和 Meta Muse 国内用不了 —— 这是你自己搭的那一个
```

---

## Quick start

```bash
# 1. 装
pip install vigiliae

# 2. 初始化（生成 12 个 Agent 的默认配置）
vigiliae init

# 3. 起（默认 8110 端口）
vigiliae serve

# 4. 打开
open http://localhost:8110
```

**或者用 Docker：**

```bash
git clone https://github.com/Trustbaselab/vigiliae
cd vigiliae
cp .env.example .env        # 至少填 BOT_TOKEN
docker compose up -d
```

**接上思考内核（可选，但推荐）：**

```bash
# 更柝用 DSH（DeepSeek Harness）作为「大脑」
# 加上这个，4 个 LLM 型 Agent 才能跑
export DEEPSEEK_API_KEY=sk-xxxxxxxx
```

**⭐ 装完就能用。12 个 Agent 会自己开始跑（HTTP/Python 型的先跑起来，LLM 型的等你配 key）。**

---

## Authentication (important)

If `BOT_TOKEN` is set, every page/API except `/api/health` and `/api/heartbeat` is protected.
The first browser visit must carry the token as `?k=`; the server returns a `302` and sets the
`cb_auth` cookie. After that, visit `/` normally.

```bash
# 1) token from .env
TOKEN=$(grep '^BOT_TOKEN=' .env | cut -d= -f2-)

# 2) browser: open this once, then use the normal URL
echo "http://<SERVER-IP>:8110/login?k=$TOKEN"

# 3) curl: follow the 302 and save the cookie
curl -c /tmp/vig.cookie -L "http://127.0.0.1:8110/login?k=$TOKEN"
curl -b /tmp/vig.cookie "http://127.0.0.1:8110/api/tasks"

# 4) or one-shot with ?k= (API returns 200 directly; -L is future-proof)
curl -L "http://127.0.0.1:8110/api/tasks?k=$TOKEN"
```

- Browser: `http://<SERVER-IP>:8110/login?k=<TOKEN>` first, then `http://<SERVER-IP>:8110/`.
- `?k=` on an **API** request returns the data and `Set-Cookie` in one 200 response
  (no redirect); `-L` is harmless and keeps the command future-proof.
- `?k=` only seeds the cookie; API calls after that can use `-b`.
- If `BOT_TOKEN` is empty, the app runs in open dev mode (do **not** expose it publicly).
- The token is in the URL during first login, so use HTTPS in production and avoid sharing logs.

---

## 它到底能干什么

**一句话：你有 12 个各有专长的 AI 员工，各管一摊。**

| 守夜人 | 职责 | 你能用它做什么 |
|---|---|---|
| **更柝 Vigiliae** | 总调度 | 决定谁在值班、下一步干什么 |
| **长庚 Hesperus** | 双态交接 | 本机离线时云端自动接管 |
| **代明 Sol et Luna** | 班次与价格钟 | 重活只在便宜时段跑 |
| **夜分 Nox media** | 成本窗口 | 守住 API 花销 |
| **春秋 Annales** | 编年 | 每次运行都归档，可追溯 |
| **权衡 Libra** | 核验 | 验证数据来源，防幻觉 |
| **行人 Nuntius** | 传令 | 把结果传出去（消息/简报） |
| **阊阖 Porta** | 门禁 | 审批，没批准的写操作一律拦截 |
| **庭燎 Taeda** | 灯火 | 生成报告与可视化 |
| **织女 Arachne** | 织图 | 把散落的数据织成关系图 |
| **后稷 Sator** | 采集 | 按缺口采数据 |
| **疆埸 Terminus** | 锚定 | 哈希、存证、不可篡改 |

**⭐ 每个名字都有中西古典出处 —— 详见 [NAMING.md](NAMING.md)。**

---

## 五个技能（内置，不依赖任何插件）

```bash
python -m vigiliae.memory  --help    # 记忆：跨会话记住事情
python -m vigiliae.verify  --help    # 核验：验证数据来源
python -m vigiliae.patrol  --help    # 巡检：检查系统健康
python -m vigiliae.collect --help    # 采集：按缺口找数据
python -m vigiliae.report  --help    # 汇报：统一输出格式
```

**每个技能都能单独用，也能被任何 Agent 调用。**

**⭐ 技能是学了业界最好的机制后自己实现的 —— 见 [SKILLS.md](SKILLS.md)。**

---

## 为什么是它，而不是别的

### ① 本地 ↔ 云端交接

本机在线时本机干活；本机离线，云端自动接管。**心跳检测 + 接管协议**，不丢任务、不重跑已完成的部分。

```
[你的笔记本]  ──心跳──▶  [你的 VPS]
     │                      │
  关机/断网                  │
     ✗                      ▼
                       自动接管，继续干
```

### ② 价格感知调度

基于 API 时段定价编排任务。**重活自动挪入半价窗口**，同一批工作成本减半。

### ③ Agent 边界写在 YAML 里

每个 Agent 能写什么、要不要审批、只能读还是能执行 —— 在 `agents.yaml` 里声明，**运行时强制执行**，不是写在提示词里求模型自觉。

### ④ 规则引擎 + LLM，两层

确定性指令走规则引擎，只把需要推理的交给 LLM。**省钱、可复现、可审计。**

### ⑤ Bring your own thinking kernel

不绑定任何模型。DSH / 任何能输出文本的 CLI 都行。也可以完全不用 LLM，只跑规则引擎。

---

## Comparison

| | Grok Bot | Meta Muse | SaaS 助手 | **Vigiliae** |
|---|:-:|:-:|:-:|:-:|
| 国内可用 | ❌ | ❌ | ✅ | ✅ |
| 数据在自己手里 | ❌ | ❌ | ❌ | **✅** |
| 24h 不间断 | ✅ | ✅ | ✅ | ✅ |
| 关机后继续 | 不适用 | 不适用 | ✅ | **✅** |
| 多 Agent 团队 | 部分 | ✅ | 部分 | **✅ 12 个** |
| 可私有化 | ❌ | ❌ | 少数 | **✅** |
| 可定制技能 | ❌ | 部分 | ❌ | **✅** |
| 成本 | 高（$） | 高（$） | 中 | **低（服务器成本）** |

---

## Architecture

```
┌─────────────────────────────────────────────┐
│              Vigiliae (更柝)                  │
├─────────────────────────────────────────────┤
│  编排层：12 个 Agent（各有 YAML 配置）        │
│    · write_perm / need_approve / exec_pref   │
│    · reports_to / depends_on                 │
├─────────────────────────────────────────────┤
│  技能层：memory / verify / patrol /          │
│          collect / report                    │
├─────────────────────────────────────────────┤
│  内核：规则引擎 + 价格调度 + 交接协议         │
├─────────────────────────────────────────────┤
│  存储：SQLite（任务/运行/审批/心跳）           │
├─────────────────────────────────────────────┤
│  大脑：DSH headless（可换任何 CLI）           │
└─────────────────────────────────────────────┘
```

**详细的运行机制、数据流、状态机见 [ARCHITECTURE.md](ARCHITECTURE.md)。**

---

## Write your first agent

```yaml
# agents.yaml
agents:
  - id: agent_myscraper
    name: 我的采集器
    desc: 每天早上 8 点采一次行业新闻
    kind: python              # python | http | agent
    schedule: "cron:0 8 * * *"
    exec_pref: cloud          # local | cloud | either
    write_perm: 0             # 只读
    need_approve: 0           # 不需要审批
    payload:
      script: scripts/scrape.py
```

```bash
vigiliae agents sync agents.yaml   # 同步进数据库
vigiliae agents run agent_myscraper # 立即跑一次
```

**完整参考见 [agents.yaml](agents.yaml)（12 个 Agent 的示例配置）。**

---

## API

```bash
# 任务列表
curl http://localhost:8110/api/tasks

# 运行状态
curl http://localhost:8110/api/status

# 手动触发
curl -X POST http://localhost:8110/api/tasks/agent_vigiliae/run

# 审批
curl http://localhost:8110/api/approvals
curl -X POST http://localhost:8110/api/approvals/1/decide -d '{"decision":"approve"}'

# 交接
curl http://localhost:8110/api/handover
```

**完整 OpenAPI 见 [docs/api.md](docs/api.md)。**

---

## Configuration

```bash
# .env
VIGILIAE_PORT=8110
VIGILIAE_DATA_DIR=./data
BOT_TOKEN=your_token              # 可选，用于消息推送
DSH_BIN=dsh                       # 思考内核的路径
DSH_PROFILE=headless              # 用哪个 profile
DEEPSEEK_API_KEY=sk-xxxx          # LLM Agent 需要
```

**所有配置项见 [docs/configuration.md](docs/configuration.md)。**

---

## Operating modes

| 模式 | 说明 | 什么时候用 |
|---|---|---|
| `local` | 只在本机跑 | 开发/测试 |
| `cloud` | 只在服务器跑 | 生产 |
| `either` | 谁在线谁跑 | 默认（配合交接协议） |
| `local_first` | 本机优先，离线时云端接管 | 有笔记本 + VPS 的场景 |

---

## Honest limitations

**我们不想吹，以下是现在真的做不到的：**

```
✗ 一键安装 —— 现在要 3 步（pip install / init / serve），还不是 curl | bash
✗ 多租户 —— 单机单用户，没有租户隔离
✗ 企业级审计 —— 只有基础运行日志，没有合规级审计
✗ 云端电脑 —— Agent 不能操作 GUI / 点网页（Grok Bot 有，我们没有）
✗ 行业技能包 —— 现在 5 个通用技能，没有行业包
✗ 本地大模型 —— 现在通过 API 调 DeepSeek，还没接 Ollama
✗ 真实用户 —— 除了我们自己，还没有外部用户
```

**⭐ 这些都在 [Roadmap](#roadmap) 里，按优先级排着。**

---

## Roadmap

```
2026 Q4
  ✅ 12 个 Agent 编排
  ✅ 本地↔云端交接
  ✅ 价格感知调度
  ✅ 5 个内置技能
  ⏳ 一键安装（curl | bash）
  ⏳ 首屏可视化（5 分钟看懂）
  ⏳ README / 文档对外可读

2027 Q1
  ⏳ 行业技能包（碳数据 / 电商 / 法务）
  ⏳ 浏览器自动化（Playwright）
  ⏳ 多租户
  ⏳ 企业级审计

2027 Q2+
  ⏳ 本地大模型（Ollama）
  ⏳ 市场 / Agent 商店
```

---

## 名字的故事

名字不是随便起的 —— **Vigiliae** 是罗马的「夜分四班」，**更柝** 是中国的「一夜五更」，两个文明独立发明了同一种制度：**把夜晚切成段，一段交一班人，班班相接**。

**完整考据见 [NAMING.md](NAMING.md) —— 包含《学说汇纂》《易经》《木兰辞》《周礼》《唐六典》的原文出处。**

---

## Contributing

见 [CONTRIBUTING.md](CONTRIBUTING.md)。我们特别欢迎：

```
· 行业技能包（你所在的行业，你知道缺什么）
· 部署案例（你在什么环境装过，踩了什么坑）
· Bug（尤其是跨平台/容器环境）
```

**安全问题见 [SECURITY.md](SECURITY.md)。**

---

## License

MIT —— 见 [LICENSE](LICENSE)。

**⭐ 开源版是免费的、完整的、可商用的。企业版（多租户/审计/SSO）单独授权。**

---

## Acknowledgements

```
· DeepSeek Harness (DSH) —— 思考内核
· 12 个 Agent 的命名考据 —— 荷马、赫西俄德、维吉尔、李维、
  《学说汇纂》、《易经》、《诗经》、《楚辞》、《礼记》、《左传》、《唐六典》、《山海经》
· 技能机制参考了 DSH 社区的开源插件（MIT）：
  dsh-memory-manager / dsh-mcp-manager / dsh-skill-manager
  我们学了它们的机制，用 Python 重写在 vigiliae 里 —— 不依赖任何插件
```

---

**Built by [Trustbase Lab](https://trustbaselab.com)**

*一夜五更，班班相接。*
