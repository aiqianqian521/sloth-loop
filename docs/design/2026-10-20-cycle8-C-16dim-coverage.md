# cycle-8 场景 C 评估 · sloth-loop + 蜂群 16/19 维覆盖矩阵 + 缺口 + 风险分级（2026-10-20）

> 评估口径：architect-skills 真包（**B-round3 2026-10-20 校正后**，含新增 AGE-16/AGE-17）
> 被评对象：sloth-loop（`<WORKSPACE_ROOT>\loop-dev-next`，dev，HEAD `9808f82`；基线 1310 passed / 1 xfailed / 73.23%）+ 蜂群（subagent/swarm 编排）
> 风险分级口径：`architect-skills/reference/risk-grading-scheme.md`（引其触发条件编号）
> 定位：**评而不修**优先；本文件只给矩阵/缺口/风险，采纳项另走 A4 式回填（契约不变 + 跑绿 + gate）。

## ① 覆盖矩阵（architect-skills 19 矩阵行；sloth-loop 侧）

| # | 维度（atom） | loop 状态 | 关键证据（行级） | 缺口 |
|---|---|---|---|---|
| 1 | design（①②③） | covered | `docs/adr/ADR-006/007`（godfile 拆分）；模块边界清晰 | — |
| 2 | review（横切 12 层） | partial | `self_modify_gate.py` / `verifier.py`；无 12 层审计台账 | 12 层审计未成体系（low） |
| 3 | data（⑤） | covered | `memory_store*.py` / `immutable_state.py` / `pattern_store_*.py` | — |
| 4 | test（⑧） | covered | `tests/`(78 文件) + `sloth_engine/tests/`；`run_gate.py`；契约不变量层 | AI 输出评测框架缺失（medium，承 round2） |
| 5 | workflow（③⑥） | covered | `loop_controller.py` / `ooda_pipeline.py` / `run_lock.py` | — |
| 6 | **agent（⑥）** | **covered→partial** | `async_loop.py` / `circuit_breaker.py` / `failure_scope*.py` / `stall_watchdog.py`(cycle-8) | 见 §② G-1（看门狗未接入调用点） |
| 7 | git（⑨） | covered | 本仓 commit 规范 + `run_gate.py` + `docs_baseline.py` | — |
| 8 | docs（⑨） | covered | README/CLAUDE/RUNBOOK/ONBOARDING/AS-BUILT/ROADMAP 齐全且口径受守护 | — |
| 9 | net（④） | partial | 无对外 HTTP 服务；`mcp_client.py` 出站 | 出站超时/幂等策略未成文（low） |
| 10 | security（⑦） | covered | `permission_levels.py` / `self_modify_gate.py` / `exec_gate`（fail-closed） | — |
| 11 | ops（⑩） | partial | 无容器/编排清单；`scripts/` 运维脚本 | 部署编排缺失（low，非目标场景） |
| 12 | observability（⑩） | covered | `telemetry.py` / `event_log.py` / `event_diagnostics.py` | — |
| 13 | cost（⑩） | partial | `config_util.py` 预算项；无计费基线 | 用量计费未成文（low） |
| 14 | compliance（⑩） | partial | 审计日志（`event_log`）；无合规检查点 | 合规未纳入（low） |
| 15 | frontend（⑩） | covered | `sloth_engine/webui.py`（cycle-新）+ FastAPI | — |
| 16 | plugin（③横切） | covered | `plugin_loader.py` / `plugin_bootstrap.py` / `plugin_manifest.py` / `plugin_roster.py` / 11+ DSH 插件 | — |
| 17 | 性能（⑥主+⑩） | N/A | 无 load-test/benchmark 目录 | N/A（附复检触发条件：出现 benchmark 目录再评） |
| 18 | context（上下文预算） | covered | `context_compactor.py` / `context_fragment.py` / `pattern_compactor.py` | — |
| 19 | rag（RAG/记忆检索） | covered | `rag_layers.py` / `bm25_retrieval.py` / `memory_store*.py` | — |

> 蜂群侧：`sub_agent.py`（`AgentRegistry` 有界并发 + `SpawnReservation` + `InputQueue` 邮箱/steer）→ ⑥ 的"并发上限/编排"covered；
> `run_once_pipeline.py:280` 把 `orchestrator.tool_registry` 传入 Act 路径，`ooda_pipeline.py:352` 优先统一调度 → 工具治理 covered。

## ② 缺口（按风险分级，引 `risk-grading-scheme.md`）

- **G-1（medium）AGE-16 复检钩子未闭合**：`stall_watchdog.py` 只落了**机制**，尚未接入 `sub_agent.py:96 run_subagent(context, executor_fn)` / `async_loop.py` 的真实委派调用点。
  - 判据：`git grep -n 'stall_watchdog' -- sloth_engine/*.py` 目前仅命中自身模块（无调用点）。
  - **已闭合（2026-10-20，cycle-8 A4-cand-A）**：`stall_watchdog` 已接入 `sub_agent.run_subagent(context, executor_fn, stall_ms=0)`（additive/opt-in，句柄暴露为 `context.watchdog`，耗尽态 `status="stalled"`）；commit `3f8b5b6`；`tests/test_subagent_stall.py`(8)；gate PASS 1318/73.27%。
  - 触发条件（scheme §一③类"关键路径缺保护"）：长任务卡死不可见即命中。
- **G-2（medium）AGE-17 上下文域工具收窄缺席**：`ToolRegistry` 是**活路径**（非死分支），但**无按执行上下文（子 agent / 计划态）收窄工具面**的策略门；`permission_levels.py` 只做角色分级，不做上下文域收窄。
  - 判据：`git grep -n 'pre_approval\|context.*allowlist' -- sloth_engine/*.py` = 0 命中。
  - **已闭合（2026-10-21，cycle-8 A4-cand-B）**：新增 `sloth_engine/context_tool_policy.py` + `ToolRegistry.add_context_tool_policy`（复用单调 guard 缝，**结果级**阻断、不抛异常）+ `tests/test_context_tool_policy.py`(20)；commit `f698d49`；gate PASS 1338/73.46%。
- **G-3（low，文档纠正）**：既有记录称"ToolRegistry 现为死分支"——**实测已证伪**（`orchestrator.py:163` 构造 → `run_once_pipeline.py:280` 传入 → `ooda_pipeline.py:352` 优先调度；`tests/test_tool_registry.py` 覆盖）。
- **G-4（medium，承上一轮压测 handoff）**：G0–G8 余项——同项目并发、全量套件、真实模型调用、每项目文件沙箱。

## ③ 采纳判定
- 本轮 **不新增 adopted 代码改动**：G-1/G-2 需改 `AgentContext`（additive 字段）与工具策略门设计，属独立工作单元；遵循"评而不修 + 不为凑数改代码"，登记为**下一轮 A4 候选**（附精确接入点）。
- **后续已回填（2026-10-20/21）**：A4-cand-A 与 A4-cand-B 均已 adopted 落地（见 `2026-09-05-grand-loop-status.md` §13.27 / §13.28），故本文件 §② 的 G-1/G-2 标注为已闭合；G-4 仍开。
- G-3 为纯文档纠正，已在 `2026-09-05-grand-loop-status.md §13.26` 落地。

## ④ 下一步（可执行可验证）
1. ✅ **A4-cand-A（已完成，commit `3f8b5b6`）**：`sub_agent.AgentContext` 增 additive 字段 `watchdog`（默认 None）；`run_subagent` 增可选 `stall_ms`（默认 0=关闭，契约不变）；`stall_ms>0` 时经 `run_stall_resilient` 包 `executor_fn`，失败态映射为 `status="stalled"`。验证：`tests/test_subagent_stall.py`(8) + `run_gate.py --all` PASS（1318/73.27%）。
2. ✅ **A4-cand-B（已完成，commit `f698d49`）**：新增 `sloth_engine/context_tool_policy.py`（AGE-17 真值 1:1 移植）+ `ToolRegistry.add_context_tool_policy`（**复用既有单调 guard 缝**，被拒=结果级 blocked、不抛异常；不改 `dispatch()` 签名）+ `AgentContext` 两个 additive 字段。验证：`tests/test_context_tool_policy.py`(20) + `run_gate.py --all` PASS（1338/73.46%）。
3. 复检命令：`python -m pytest tests sloth_engine/tests -q`（=权威门禁口径）。