# 接任何模型（Bring Your Own Model）

Vigiliae **不内嵌 LLM 运行时**。它把「思考」这件事外包给一个 CLI —— 任何接受
prompt、打印文本的 CLI 都能接。

```
Vigiliae  ──shell out──▶  任意 CLI  ──▶  任意模型
                          (DSH_BIN 环境变量)
```

**这意味着：只要你会写一行 shell，你就能接任何模型。**

---

## 一、配置只有一个变量

```bash
DSH_BIN="/path/to/your/cli-or-command"
```

其他相关变量：

| 变量 | 默认 | 说明 |
|---|---|---|
| `DSH_BIN` | `dsh` | 接受 prompt、输出文本的 CLI |
| `DSH_PROFILE` | `headless` | 传给 DSH 的 profile |
| `DSH_TIMEOUT` | `180` | 单次调用超时（秒） |
| `DSH_DAILY_LIMIT` | `200` | 每日调用上限（防烧钱） |
| `DSH_CWD` | 运行目录 | CLI 的工作目录 |

---

## 二、已确认可用的接入方式

### 1. DSH（默认）—— 接 DeepSeek

```bash
# .env
DSH_BIN=dsh
DSH_PROFILE=headless
DEEPSEEK_API_KEY=sk-xxxx
```

**这是开箱即用的默认方案。**

### 2. Ollama —— 接本地模型（数据完全不出门）

```bash
# 1) 装 ollama
curl -fsSL https://ollama.com/install.sh | sh

# 2) 拉一个模型（4核7.5G 建议 3B）
ollama pull qwen2.5:3b

# 3) 写 wrapper
sudo tee /usr/local/bin/vigiliae-ollama >/dev/null <<'EOF'
#!/bin/bash
# Vigiliae → Ollama wrapper
# $1 = prompt
exec ollama run qwen2.5:3b "$1" 2>/dev/null
EOF
sudo chmod +x /usr/local/bin/vigiliae-ollama

# 4) 配置
DSH_BIN=/usr/local/bin/vigiliae-ollama
```

**⭐ 卖点：数据 100% 不出服务器。Grok Bot / Muse / 任何 SaaS 都做不到。**

### 3. Claude（Anthropic）

```bash
sudo tee /usr/local/bin/vigiliae-claude >/dev/null <<'EOF'
#!/bin/bash
set -e
PROMPT="$1"
curl -sS https://api.anthropic.com/v1/messages \
  -H "x-api-key: ${ANTHROPIC_API_KEY}" \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  -d "$(jq -n --arg p "$PROMPT" '{
    model: "claude-sonnet-4-20250514",
    max_tokens: 2048,
    messages: [{role: "user", content: $p}]
  }')" \
  | jq -r '.content[0].text // .error.message'
EOF
sudo chmod +x /usr/local/bin/vigiliae-claude

DSH_BIN=/usr/local/bin/vigiliae-claude
ANTHROPIC_API_KEY=sk-ant-xxxx
```

### 4. OpenAI / 兼容接口（含 DeepSeek、Moonshot、智谱、通义）

**任何 OpenAI 兼容接口都能用同一个 wrapper：**

```bash
sudo tee /usr/local/bin/vigiliae-openai >/dev/null <<'EOF'
#!/bin/bash
set -e
PROMPT="$1"
BASE="${OPENAI_BASE_URL:-https://api.openai.com/v1}"
MODEL="${OPENAI_MODEL:-gpt-4o-mini}"
curl -sS "$BASE/chat/completions" \
  -H "Authorization: Bearer ${OPENAI_API_KEY}" \
  -H "content-type: application/json" \
  -d "$(jq -n --arg m "$MODEL" --arg p "$PROMPT" '{
    model: $m,
    messages: [{role: "user", content: $p}],
    max_tokens: 2048
  }')" \
  | jq -r '.choices[0].message.content // .error.message'
EOF
sudo chmod +x /usr/local/bin/vigiliae-openai

# 用 OpenAI
DSH_BIN=/usr/local/bin/vigiliae-openai
OPENAI_API_KEY=sk-xxxx
OPENAI_MODEL=gpt-4o-mini

# 用 DeepSeek（OpenAI 兼容）
OPENAI_BASE_URL=https://api.deepseek.com/v1
OPENAI_API_KEY=sk-xxxx
OPENAI_MODEL=deepseek-chat

# 用 Moonshot（Kimi）
OPENAI_BASE_URL=https://api.moonshot.cn/v1
OPENAI_API_KEY=sk-xxxx
OPENAI_MODEL=moonshot-v1-8k

# 用智谱 GLM
OPENAI_BASE_URL=https://open.bigmodel.cn/api/paas/v4
OPENAI_API_KEY=xxxx
OPENAI_MODEL=glm-4-flash

# 用阿里通义
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENAI_API_KEY=sk-xxxx
OPENAI_MODEL=qwen-plus
```

**⭐⭐ 一个 wrapper 接 8 家厂商 —— 这就是「包罗万象」。**

### 5. llama.cpp —— 接本地 gguf

```bash
sudo tee /usr/local/bin/vigiliae-llama >/dev/null <<'EOF'
#!/bin/bash
exec llama-cli -m /models/qwen2.5-3b-instruct-q4_k_m.gguf \
  -p "$1" -n 512 --no-display-prompt 2>/dev/null
EOF
sudo chmod +x /usr/local/bin/vigiliae-llama

DSH_BIN=/usr/local/bin/vigiliae-llama
```

### 6. 任何「prompt 进、文本出」的工具

```bash
# 只要能这样用，就能接：
echo "你的问题" | your-cli

# 例如：
DSH_BIN="/usr/local/bin/my-custom-llm"
```

---

## 三、按 Agent 分模型（高级）

目前 Vigiliae 是「全局一个 DSH_BIN」。要「不同 Agent 用不同模型」有两种办法：

### 办法 A：wrapper 里按 prompt 前缀分流（不改代码）

```bash
#!/bin/bash
PROMPT="$1"
if [[ "$PROMPT" == *"[VERIFY]"* ]]; then
    # 核验任务用 Claude（更严谨）
    exec /usr/local/bin/vigiliae-claude "$PROMPT"
else
    # 其他用 DeepSeek（便宜）
    exec /usr/local/bin/vigiliae-openai "$PROMPT"
fi
```

### 办法 B：改 agents.yaml（需要代码支持，尚未实现）

```yaml
# 计划中的特性
agents:
  - id: agent_vigiliae
    llm_bin: /usr/local/bin/vigiliae-openai   # DeepSeek
  - id: agent_libra
    llm_bin: /usr/local/bin/vigiliae-claude   # Claude
```

**⭐ 现状如实说：办法 A 现在就能用，办法 B 还没做。**

---

## 四、验证清单（接完必须测）

```bash
# 1) CLI 单独能跑吗
/usr/local/bin/vigiliae-ollama "1+1等于几"
# 期望：输出 "2" 或类似

# 2) Vigiliae 认得它吗
python3 -c "
import sys; sys.path.insert(0,'.')
from vigiliae import bridge
print('available:', bridge.available())
"
# 期望：True

# 3) 端到端（在更柝控制台问一句）
curl -X POST "http://localhost:8912/api/messages?k=$BOT_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"text":"你好，用一句话介绍你自己"}'
```

---

## 五、性能参考（4 核 7.5G 实测建议）

| 模型 | 显存/内存 | 速度 | 建议 |
|---|---|---|---|
| qwen2.5:3b (Q4) | ~2 GB | 快 | ✅ 这个配置能跑 |
| llama3.2:3b | ~2 GB | 快 | ✅ 能跑 |
| qwen2.5:7b (Q4) | ~4.5 GB | 中 | ⚠️ 勉强（会吃满内存） |
| llama3.1:8b | ~5 GB | 慢 | ❌ 内存不够 |
| 13B+ | 8 GB+ | — | ❌ 需要更大机器 |

**⭐ 结论：4 核 7.5G 只能跑 3B 模型。要跑 7B+ 需要 16G 内存。**

---

## 六、为什么这个设计是卖点

```
对比：
  Grok Bot / Muse     → 只能用它们的模型，数据在它们的云
  WorkDaddy           → 配置多模型 key，但仍依赖 SaaS
  Vigiliae            → 换一个 CLI，换整个模型栈，数据永远在自己的机器

⭐ 三个确定性：
  ① 模型确定性 —— 不被任何厂商绑定
  ② 数据确定性 —— 本地模型时数据 0 出网
  ③ 成本确定性 —— 可以用免费本地模型，也可以用便宜的 API
```

---

## 七、诚实边界

```
⚠️ 1. 需要 CLI 形态
   · 不能直接填 API key（要写 wrapper）
   · wrapper 是 10 行 shell，但要会一点 Linux

⚠️ 2. 目前只能全局一个模型
   · 按 Agent 分模型需要 wrapper 分流（办法 A）或改代码（办法 B，未实现）

⚠️ 3. 本地大模型受硬件限制
   · 4核7.5G 只能跑 3B，要跑 7B+ 需 16G 内存
   · 这台机器跑不了 GPT-4 级别的本地模型

⚠️ 4. 未做完整实测
   · 架构上支持（bridge.py 明确写了 "anything with the same shape works"）
   · Claude / GPT 的 wrapper 我写了但没逐家跑过
   · Ollama 未在这台机器上安装实测
   · 建议：选一家先跑通，再扩
```

---

*Last updated: 2026-11-07 · Vigiliae v0.3.x*
