# cycle-11 N-1/N-2/N-3：无调用方机制门禁 + coze 候选复评 + 配额接口约定（2026-10-22）

> 起点：代码 head `cd54ef3`（基线 1392 passed / 1 xfailed / 74.42%）。本文件记录 step A 三项
> （N-1 门禁化 / N-2 coze I-1..I-4 复评 / N-3 真实额度源接口约定）的判据、真值与结论。
> 代码提交 `81f0b46`；基线刷新为 **1405 / 75.06**。

---

## ① N-1：把「机制已落、接线未闭」判据门禁化（已闭合）

### 缺口与动机
- cycle-9/10 出现两处「机制落了、**没有任何调用方**」的静默回归：G-5（`step_exception_policy`）、
  G-6（`quota_window` 无真实来源）。当轮**只靠人工 `git grep`** 才发现 —— 人工判据不可持续。
- 本轮把它脚本化为门禁：机制必须**可被机器证明有调用方**，否则 `run_gate.py` 直接红。

### 交付一：`scripts/check_orphan_mechanisms.py`
| 环节 | 规则 |
|---|---|
| 候选 | `sloth_engine/*.py` **顶层**模块，且看起来像可复用机制（≥1 顶层 `def`/`async def`/`class`）→ `_strip_bom.py` 这类纯工具脚本被自动排除 |
| 边（调用方） | AST 静态导入（`utf-8-sig`/BOM 容错）+ 字面量 `import_module("x")`/`__import__("x")` + **生产代码中的引号字面量**（配置驱动动态加载兜底） |
| 判定 | `wired`（≥1 非测试引用，OK）/ `test_only`（仅测试引用 → **informational**，允许的参考实现）/ `orphan`（无人引用 → **FAIL**） |
| 白名单 | `EXEMPT` 显式条目，每条附**理由 + 追踪项**；**陈旧豁免**（条目对应模块消失或已接线）同样 **FAIL** —— 白名单不能腐烂 |

- 接入 `scripts/run_gate.py`：与 docs-baseline 并列，fail-closed（导入/执行异常 = 失败）。
- 自带防遮蔽：门禁脚本自身的 `EXEMPT` 字面量会被排除，避免白名单把自己"变成"调用方。

### 交付二：首次运行的真实命中（证明门禁不是空转）
| 模块 | 判定 | 处置 |
|---|---|---|
| `sloth_engine/loop_pipeline.py` | **orphan**（0 调用方，全仓仅其自身出现） | **归档** → `sloth_engine/_archive/loop_pipeline.py`（`git mv`，保留证据）+ 文件头 ARCHIVED 说明。其 `BackpressureQueue` / `CircuitBreaker` / `LoopConfig·State·Deps` 均为 `backpressure.py`（DeferOperation 版）/ `circuit_breaker.py` / `run_state.py` 的**被取代副本** |
| `sloth_engine/tool_concurrency.py` | **orphan**（0 调用方） | **显式豁免**（见下 §② I-2）；追踪项 N-2/I-2 |

- 归档 `loop_pipeline.py` 的**副作用（正向）**：它是 312 行从未被导入的死代码，一直拉低覆盖率分母。
  移除后全量覆盖率 74.42% → **75.06%**（用例数同时 +13）。

### 交付三：附带修正 I-1
- `sloth_engine/rag_layers.py:1` docstring 未用 raw 字符串（内含 `sloth-loop\docs\...` 路径样例 → `\d` 非法转义），
  触发 `DeprecationWarning`。改为 `r"""` 后归零（门禁扫描亦不再产生该告警）。

### 判据闭环（可复现）
```
# 归档前
$ python scripts/check_orphan_mechanisms.py    -> orphan 1 (loop_pipeline) + stale_exempt 1 ... exit 1
# 归档 + 豁免后
$ python scripts/check_orphan_mechanisms.py    -> wired 71 / test_only 15 / exempt 1 / orphan 0 / stale 0 -> exit 0
```
- 契约测试：`tests/test_orphan_mechanisms_gate.py`（**13 例**：orphan 命中 / 生产接线 / 仅测试引用 informational /
  无 def 脚本排除 / BOM 容错 / 动态 `import_module` 字面量 / 活豁免抑制 / 缺席豁免陈旧 / 已接线豁免陈旧 /
  dunder+`_archive` 不在范围 / 真仓零违规 / EXEMPT 必带追踪项 / `run_gate` 接线 tripwire）。

---

## ② N-2：coze I-1..I-4 候选逐条复评（结论：均不采纳，但修正 I-2 口径）

> 真值：`docs/knowledge-distillation/agent-orchestration/2026-10-22-coze-studio-step-exception-policy-three-state-and-success-marker.md`
> 与 `work_ooda/20261022-131900-cycle9-A-coze-lobehub-distill/ISSUES.md`。

| 候选 | coze 语义（真值 file:行段） | loop 现状（本轮实核） | 结论 |
|---|---|---|---|
| **I-1** loop 节点图语义 | `domain/workflow/internal/nodes/loop/loop.go`：ByArray/ByIteration/Infinite + `break/continue` 经中间变量存储 | loop 是**固定 OODA 四段 + `max_rounds`** 的线性循环模型，无任意节点图抽象（`ooda_pipeline.py` 无 graph/node 调度器） | **candidate-pending**（不同构，移植价值低；不新增抽象层） |
| **I-2** batch 并发闸门 | `nodes/batch/batch.go:340-360`：`minLen < concurrency` 扇出 vs worker pool | **旧口径错误**：cycle-9 记「与 `tool_concurrency` 重叠、不采」，但本轮 N-1 门禁证明 **`tool_concurrency` 自身即为未接线机制（0 调用方）** → 前提不成立。真实现状：OODA `Act` 每轮只 `registry.dispatch(exec_type, ...)` **一个**工具，没有任何批量生产者 | **不采纳**（当前模型无批量调用点）；`tool_concurrency` 作为 opt-in 参考机制**显式豁免**并追踪 |
| **I-3** 嵌套迭代断点续跑 | `Index2Done`/`Index2InterruptInfo`/`resumed` 清理 + 「无新中断但历史残留→主动再抛中断」 | loop 已有 step 级 checkpoint + 幂等键 + `resume_guard`（语义重叠）；唯一差异 = 「残留中断主动重抛」，需真实**人工闸门**场景才成立 | **candidate-pending**（等真实人工闸门用例再评） |
| **I-4** Redis 中断事件队列 | `repo/interrupt_event_store.go`：peek→update→pop + 24h TTL + 优先级回插 | loop **无 Redis 依赖**；已用 SQLite 事务 + 幂等键达成等效 | **candidate-pending**（不引入 Redis 依赖） |

- 本轮**无新采纳**（真正的产出是 I-2 的**口径纠错**：把「与既有机制重叠」这一结论建立在"N-1 门禁证伪"之上）。
- 全量登记见 `work_ooda/20261022-190000-cycle11-A-orphan-gate/ISSUES.md`。

---

## ③ N-3：G-6 残余（真实额度源）+ R3（真实模型调用 / 24h soak）—— **blocked**（附接口约定）

### 状态：blocked（本机不可达）
- 本机**无 LLM client、无供应商凭证**；R3（真实模型调用 / 24h soak）需要 LLM 挂载主机与费用额度 → 非本环境可行。
- 按纪律**登记为 blocked，不绕过**（§0.1#6）；解封条件：出现一台能读供应商配额的挂载主机。

### 接口约定（主机侧只需实现一个零参可调用对象）
G-6 的接线已就位，主机侧**只差一个真实 `quota_probe`**：

```python
# 宿主注入（Orchestrator 属性；默认 None = 行为完全不变）
orch.quota_probe    = callable          # 零参；返回 raw 字典 或 QuotaSnapshot；抛异常/返回 None 都安全
orch.quota_provider = "openai"          # 快照里的 provider 标签（默认 "loop"）
orch.quota_cache    = None              # 上次已知快照；由 run_loop 自动回写，用于降级兜底
```

`quota_probe()` 的 raw 返回（`quota_window.from_raw` 约定）：

```json
{
  "primary":   {"usedPercent": 12.5, "resetsAt": 1761200000000, "windowDurationMins": 300},
  "secondary": {"usedPercent": 91.0, "resetsAt": 1761600000000, "windowDurationMins": 10080}
}
```
- 字段名兼容两套口径：`usedPercent`/`used_percent`、`resetsAt`/`resets_at`、`windowDurationMins`/`window_duration_minutes`。
- `usedPercent` 夹取到 [0,100]；非法/缺失的窗被丢弃；两窗皆不可用 → `None`；`resetsAt` 支持 epoch ms 或可解析时间。
- **fail-soft 契约**（已有实现保证）：探针抛错或返回不可用 → 降级为 error snapshot / 上次已知快照（`degraded=True`），
  **绝不停机**；只有 `exhausted`（任一窗 `used_percent >= 100`）才干净停机，停机原因含 `provider=` 与 `next_reset_at=`。

### 建议的下一刀（候选，未做）
- **文件型探针**：让宿主/包装器把上述 JSON 写到 `LOOP_QUOTA_FILE`，loop 侧加一个只读该文件的 `quota_probe`
  （opt-in、默认关闭）。它不需要任何厂商 SDK，可离线测试 —— 是当前 blocked 状态下**最省**的解封路径。

## ④ 本轮基线
- 1392 passed / 1 xfailed / 74.42% → **1405 passed / 1 xfailed / 75.06%**（+13 用例；`loop_pipeline.py` 归档离场）。
- `run_gate.py --all` PASS；`scripts/docs_baseline.py` OK；`python scripts/check_orphan_mechanisms.py` OK。