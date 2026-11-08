---
name: agent-fleet-ops
description: 运维一支长期运行的 Agent 舰队的工程方法：识别僵死运行、接上看门狗、修计数器漂移、区分「故障」与「排队」、发现空转 Agent、建活动矩阵与配额守卫。当多 Agent 系统跑了几天后出现「任务卡住」「状态不对」「数字对不上」「有的 Agent 一直说运行中」「配额突然用完」「跑得很勤但没产出」时使用。适用于任何 scheduler + runs 表的 Agent 编排系统。
---

# Agent 舰队运维

## 何时使用

- 多 Agent 系统跑了一段时间后出现状态异常
- 看到「运行中」的任务几天没结束
- 台账数字（run_count / fail_count）与实际不符
- 失败率突然飙高，但不知道原因
- Agent 跑得很勤，但产出是空壳
- 要回答「这套系统到底在不在正常运转」

**不适用**：

- 单次任务调试 → 直接看日志
- 从零搭 Agent 系统 → 先设计再运维

---

## 第一原则：先分清三种「卡住」

**这是最容易被混淆的地方。**

| 类型 | 现象 | 根因 | 处理 |
|---|---|---|---|
| **A. 运行超时** | `status=running` 且 `started_at` 是很久以前 | 进程崩了/被杀了，但状态没回写 | 看门狗标 `timeout` |
| **B. 审批僵死** | `status=pending_approval` 且 `decided_at` 为空 | 审批门开启但没人批，或门禁已关但旧记录没清 | 标 `superseded` |
| **C. 成功无收尾** | `status=ok` 但 `finished_at` 为空 | 写完状态但异常中断 | 补 `finished_at` |

**⭐ 三种必须分别处理。统一标「失败」会丢信息，统一标「成功」会掩盖问题。**

---

## 执行流程（七步）

### ① 先做全量体检，不要逐个查

一条 SQL 扫出所有异常，比人工翻 1 万条记录快 100 倍：

```
A 类：SELECT * FROM runs WHERE status='running'
      AND (now - started_at) > (task.timeout + 120s)

B 类：SELECT * FROM runs WHERE status='pending_approval' AND finished_at IS NULL

C 类：SELECT * FROM runs WHERE status='ok' AND finished_at IS NULL

D 类：SELECT * FROM runs WHERE finished_at < started_at   -- 时间倒挂

E 类：计数器漂移
      SELECT t.id, t.run_count, COUNT(r.run_id)
      FROM tasks t LEFT JOIN runs r ON r.task_id=t.id
      GROUP BY t.id HAVING t.run_count != COUNT(r.run_id)

F 类：失败无原因
      SELECT * FROM runs WHERE status IN ('failed','timeout')
      AND (stderr IS NULL OR stderr='')
```

### ② 关键：先看 stdout，不要只看 stderr

**⭐ 这是最容易踩的坑。**

很多编排系统把「内核输出」写进 `stdout`，只有进程级错误才进 `stderr`。
结果 `stderr` 是空的，但真正的失败原因在 `stdout` 里：

```
常见 stdout 里的失败信号：
  "Daily quota reached (N calls)"      → 配额耗尽，不是故障
  "Thinking kernel timed out after Ns" → 超时
  "Thinking kernel failed (code=1)"    → 真失败
  "MISSING_CREDENTIAL"                 → 缺密钥
  "unauthorized / 401"                 → 鉴权失败
```

**⭐ 排查顺序：先 stdout，再 stderr，最后看 exit_code。**

### ③ 区分「故障」和「排队」——这句最重要

```
配额用完 → 应该记 deferred（排队），不是 failed（故障）
            ⭐ 记成 failed 会让失败率虚高 40%，掩盖真故障
超时     → 应该记 timeout（超时），不是 failed
真崩溃   → 才是 failed
```

**⭐ 判据：能不能通过「等待 / 换时段 / 补额度」自动恢复？**
- 能 → 排队
- 不能 → 故障

### ④ 看门狗必须真的被调用

**⭐ 血泪教训：写好但没接上的看门狗，等于没有看门狗。**

```
检查清单：
□ 有没有 check_stuck_runs() 这类函数？
□ 它只「报告」还是也「修复」？  ⭐ 很多只报告
□ 谁调用它？在哪调用？多久一次？  ⭐ 这里最容易断
```

**最小可行实现：**

```python
# 在 scheduler 主循环里，每 60 秒调一次
if time.time() - self._last_wd >= 60:
    self._last_wd = time.time()
    watchdog.reap()      # ⭐ reap = 真的修，不只是查
```

**`reap()` 要做三件事：**
```
① 把超时 run 标 timeout，补 finished_at 和 duration
② 修复 tasks.last_status（与最新 run 对齐）
③ 打印修了几条（不打印等于没发生）
```

### ⑤ 修计数器漂移

```
症状：台账写「失败 9 次」，实际查 runs 表是 169 次
原因：手动触发的运行没走计数逻辑，或历史清理后没重算

修法：定期从 runs 表反推重算
  run_count  = COUNT(*) WHERE task_id = ?
  fail_count = COUNT(*) WHERE task_id = ? AND status IN ('failed','timeout')
```

### ⑥ 找「空转 Agent」——这是最隐蔽的问题

**⭐⭐ 定义：跑得很勤，但每次产出是同一个空壳。**

排查方法：把每个 Agent 最近一条产出拉出来对比。

```
❌ 空转特征：
  · 输出永远是 {"count":0,"items":[]}
  · 输出永远是 {"local_online":false}
  · 输出永远是 "status written" / "appended N"
  · 输出永远是 "anchored 0"（说明路径找错了）

✅ 有价值特征：
  · 输出里含真实测量值（8/8 页面、166/200 配额、5 个锚定）
  · 输出每次可能不同（随真实状态变化）
  · 输出能被下游消费（不是自说自话）
```

**⭐ 空转为啥会发生：**
```
不是 Agent 写错了，是「被监控的对象本身不存在」
· 没有本地实例 → local_online 永远 false
· 没有延迟任务 → count 永远 0
· 路径写错 → anchored 永远 0

⭐ 修法：把传感器对准「真的有东西」的地方
```

### ⑦ 建两个运维视图

**① 活动矩阵（12 Agent × 60 秒）**
```
每一格 = 那一秒这个 Agent 有没有跑
⭐⭐ 这是唯一能「一眼看出系统在不在跳」的视图
```

**② 配额守卫**
```
每 N 分钟统计：今日已用 / 上限 / 剩余 / 百分比
⭐ 剩余低于 20% 预警，低于 5% 严重
⭐ 这个指标能提前一天发现「配额不够」
```

---

## 频率设计原则

**⭐ 高频不等于有效。先算配额，再定频率。**

```
例：某 Agent 每 5 分钟跑一次 = 288 次/天
    但云推理配额只有 200 次/天
    → 每天必然 88 次跑不动 → 88 次假失败

修法：降到每 10 分钟 = 144 次/天，留余量
```

**频率选择表：**

| 任务性质 | 合理频率 | 理由 |
|---|:-:|---|
| 心跳/健康探针 | 5-10 分钟 | 再快没意义 |
| 状态镜像 | 5-10 分钟 | 与上游同步即可 |
| 配额/成本守卫 | 10 分钟 | 变化慢 |
| 内部记账 | 15 分钟 | 批量写更省 |
| 采集/分析 | 每天 1-2 次 | 重任务，放低峰 |
| 总调度 | 10 分钟 | 需要配额，别太密 |

---

## 健康度自检表

一套 Agent 舰队是否健康，看这 7 项：

```
□ running 数量 = 0 或等于「真正在跑的」
□ pending_approval 数量 = 0 或都有明确负责人
□ 今日 failed 里没有「配额耗尽」这类假故障
□ run_count / fail_count 与 runs 表一致
□ 每个 Agent 最新产出里都有真实数值（非空壳）
□ 配额剩余 > 20%
□ 看门狗日志里能看到「本次修了 N 条」
```

---

## 诚实边界

- 本 Skill 是运维方法，不含具体系统实现
- 「空转」判定需要看真实产出，不能只看状态码
- 修复僵死记录是**有损操作**（把 running 改成 timeout），要保留 `finished_at` 和 `duration` 以便追溯
- 清理历史数据前必须备份；生产环境不要在没有备份的情况下批量 UPDATE
- 计数器重算会覆盖历史值，如果历史值有业务含义（如对外披露的 SLA），先确认再改
