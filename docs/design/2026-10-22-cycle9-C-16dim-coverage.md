# cycle-9 场景 C 评估 · sloth-loop + 蜂群 19 维覆盖矩阵 + 缺口 + 风险分级（2026-10-22）

> 评估口径：architect-skills 真包（**B 增量 2026-10-22 后**：`architect-agent` 18 条检查点含新增 AGE-18、
> `architect-cost` 8 条含新增 COS-08；验证器 `node scripts/validate-contracts.mjs` → 19 atom / 0 错误 / 0 警告）
> 被评对象：sloth-loop（`<WORKSPACE_ROOT>\loop-dev-next`，`dev`，HEAD `561727b`；代码 head `2a1a180`；
> 基线 **1368 passed / 1 xfailed / 73.79%**，fail_under=70）+ 蜂群（subagent/swarm 编排）
> 风险分级口径：`architect-skills/reference/risk-grading-scheme.md`（引其触发条件编号）
> 定位：**评而不修**优先；本文件只给矩阵/缺口/风险，采纳项另走 A4 式回填（契约不变 + 跑绿 + gate）。

## ① 覆盖矩阵（19 矩阵行；sloth-loop 侧）

| # | 维度（atom） | loop 状态 | 关键证据（行级/模块级） | 缺口 |
|---|---|---|---|---|
| 1 | design（①②③） | covered | `docs/adr/ADR-006/007`（godfile 拆分）；模块边界清晰 | — |
| 2 | review（横切 12 层） | partial | `self_modify_gate.py` / `verifier.py`；无 12 层审计台账 | 12 层审计未成体系（low） |
| 3 | data（⑤） | covered | `memory_store*.py` / `immutable_state.py` / `pattern_store_*.py` | — |
| 4 | test（⑧） | covered | `tests/` 84 + `sloth_engine/tests/` 2 = **86 个测试文件**；`run_gate.py`；**1368 passed / 73.79%** | AI 输出评测框架缺失（medium，承 round2） |
| 5 | workflow（③⑥） | covered | `loop_controller.py` / `ooda_pipeline.py` / `run_lock.py` / `step_exception_policy.py`(cycle-9) | 步骤异常策略**尚无调用点**（见 §② G-5） |
| 6 | **agent（⑥）** | **partial** | `async_loop.py` / `circuit_breaker.py` / `failure_scope*.py` / `stall_watchdog.py`（已接线 `3f8b5b6`） | G-5（新机制未接线，medium） |
| 7 | git（⑨） | covered | 本仓 commit 规范 + `run_gate.py` + `docs_baseline.py` | — |
| 8 | docs（⑨） | covered | README/CLAUDE/RUNBOOK/ONBOARDING/AS-BUILT/ROADMAP 齐全且口径受守护（`docs_baseline` OK） | — |
| 9 | net（④） | partial | 无对外 HTTP 服务；`mcp_client.py` 出站 | 出站超时/幂等策略未成文（low） |
| 10 | security（⑦） | covered | `permission_levels.py` / `self_modify_gate.py` / `exec_gate`（fail-closed） | — |
| 11 | ops（⑩） | partial | 无容器/编排清单；`scripts/` 运维脚本 | 部署编排缺失（low，非目标场景） |
| 12 | observability（⑩） | covered | `telemetry.py` / `event_log.py` / `event_diagnostics.py` | — |
| 13 | cost（⑩） | **partial→partial+** | `config_util.py` 预算项；**`quota_window.py`**（cycle-9：双窗快照 + 降级 + 幂等消费） | G-6（无真实额度源，medium） |
| 14 | compliance（⑩） | partial | 审计日志（`event_log`）；无合规检查点 | 合规未纳入（low） |
| 15 | frontend（⑩） | covered | `sloth_engine/webui.py`（+ FastAPI） | 用户裁定本轮不动 |
| 16 | plugin（③横切） | covered | `plugin_loader.py` / `plugin_bootstrap.py` / `plugin_manifest.py` / `plugin_roster.py` / 11+ DSH 插件 | — |
| 17 | 性能（⑥主+⑩） | N/A | 无 load-test/benchmark 目录 | N/A（复检触发：出现 benchmark 目录再评） |
| 18 | context（上下文预算） | covered | `context_compactor.py` / `context_fragment.py` / `pattern_compactor.py` | — |
| 19 | rag（RAG/记忆检索） | covered | `rag_layers.py` / `bm25_retrieval.py` / `memory_store*.py` | — |

> 蜂群侧：`sub_agent.py`（`AgentRegistry` 有界并发 + `SpawnReservation` + `InputQueue` 邮箱/steer + `stall_ms` 看门狗）→ ⑥ 的
> "并发上限/编排/活性"covered；`run_once_pipeline.py:280` → `ooda_pipeline.py:352` 统一工具调度 → 工具治理 covered
> （`context_tool_policy.py` 结果级阻断，`f698d49`）。

## ② 缺口（按风险分级，引 `risk-grading-scheme.md`）

- **G-5（medium，新）AGE-18 复检钩子未闭合**：`sloth_engine/step_exception_policy.py` 只落了**机制**，
  尚无调用点（`git grep -n "apply_policy\|ExceptionPolicy" -- sloth_engine/*.py` 仅命中本模块自身 + 其测试）。
  - 判据同 cycle-8 G-1（"关键路径缺保护"）：步骤失败策略不统一即命中。
  - 闭合路径（下一轮 A4 候选）：在 `tool_pipeline` 或 `adapters/task_runner` 的单步调用点接入 `apply_policy`
    （additive/opt-in，默认策略 = 现状单次、抛错，契约不变）。
  - **已登记为候选，不在本轮改**（避免为凑数动主链路）。
- **G-6（medium，新）COS-08 无真实额度源**：`sloth_engine/quota_window.py` 是纯快照/账本**机制**，
  没有真实 `fetch` 来源（无 rate-limit 头、无供应商用量接口）→ `resolve_snapshot` 只能降级到错误快照。
  - 触发条件（scheme §一③类"关键路径缺保护"）：额度不可见 → 预算熔断只能靠 `config_util` 的静态预算项。
  - 闭合路径：待 LLM 挂载点（能读到供应商配额）后接 `resolve_snapshot(fetch=...)`，并把 `exhausted` 接入循环停止判定。
- **G-1（已闭合，cycle-8）**：`stall_watchdog` 接入 `sub_agent.run_subagent(..., stall_ms=0)`（`3f8b5b6`）。
- **G-2（已闭合，cycle-8）**：`context_tool_policy.py` + `ToolRegistry.add_context_tool_policy`（`f698d49`）。
- **G-3（已闭合，cycle-8）**：文档纠正（`ToolRegistry` 非死分支）。
- **G-4（已闭合，cycle-9）**：同项目并发探针 + D-F9-1 修复（`b20590f`）。残余 R1（`--once` 无锁 + `io/_data` 共享）、
  R2（每项目沙箱，用户裁定不做）、R3（真实模型/24h soak，需 LLM 主机）仍如实登记、未绕过（§0.1#6）。

## ③ 采纳判定
- 本轮 **不新增 adopted 代码改动**（A 阶段已落地 2 条；C 阶段评而不修，避免"为凑数改代码"）。
- G-5 / G-6 登记为**下一轮 A4 候选**，各自附精确接入点与"契约不变"约束。
- 结论强度（口径 = 矩阵最后状态）：**covered 12 / partial 6 / N/A 1**，**与 cycle-8 同数**。本轮的变化是 partial 的**质量**
  而非数量：#13 cost 从"仅静态预算项"升级为"有双窗快照机制、仍缺真实额度源"；#5 workflow 增补步骤级异常策略模块、
  仍缺调用点；G-1/G-2/G-4 的闭合落在同一批 partial 的子项上，故维度计数不变。G-5/G-6 即上述两处"机制已落、接线未闭"的新增登记。

## ④ 下一步（可执行可验证）
1. **G-5（A4-cand）**：在 `tool_pipeline` 单步调用点接入 `step_exception_policy.apply_policy`
   （默认 `ExceptionPolicy()` = 单次+抛错，行为不变）；验证：新增契约测试 + `run_gate.py --all` PASS。
2. **G-6（A4-cand）**：为 `quota_window.resolve_snapshot` 提供可注入的 `fetch`（先接 mock/接口桩）；
   验证：`exhausted → 停止判定` 的契约测试 + gate PASS。
3. **R1（承 cycle-8）**：把 `run_lock` 扩到 `_run_once`，或给每次 run 独立 io 目录（消除 `io/_data` 串台）。
4. 复检命令：`python -m pytest tests sloth_engine/tests -q`（权威门禁口径）+ `python scripts/docs_baseline.py`。