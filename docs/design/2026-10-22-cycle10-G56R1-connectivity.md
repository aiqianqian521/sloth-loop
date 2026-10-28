# cycle-10 场景 C 增量复评 · G-5/G-6/R1 接线闭合后的 19 维覆盖矩阵（2026-10-22）

> 评估口径：architect-skills 真包（**B 增量 cycle-10 后**：`architect-agent` 17 条检查点含新增 AGE-19、核心原则 18 条；
> `architect-cost` 8 条含 COS-08 补强；`node scripts/validate-contracts.mjs` → 19 atom / 0 错误 / 0 警告；
> `node tests/run-l1-tests.mjs` → 32 passed）
> 被评对象：sloth-loop（`<WORKSPACE_ROOT>\loop-dev-next`，`dev`，代码 head `cd54ef3`；基线 **1392 passed / 1 xfailed / 74.42%**，
> fail_under=70）+ 蜂群（subagent/swarm 编排）
> 风险分级口径：`architect-skills/reference/risk-grading-scheme.md`
> 定位：**本轮是"接线轮"** —— 不新增矩阵行，只重判 cycle-9 登记的两处"机制已落、接线未闭"缺口，及其下游 partial 维度。
> 承上：`docs/design/2026-10-22-cycle9-C-16dim-coverage.md`（该文件为 cycle-9 快照，数字刻意不回填）。

## ① 矩阵变化（相对 cycle-9）

| # | 维度（atom） | cycle-9 | cycle-10 | 变化依据（判据） |
|---|---|---|---|---|
| 5 | workflow（③⑥） | partial | **covered** | 步骤级异常策略已接真实单步调用点：`adapters/task_runner.py:271`、`tool_pipeline.py:193` |
| 6 | agent（⑥） | partial | **covered** | G-5 闭合（AGE-18 复检钩子闭环）；三态策略在 Act 点可选启用 |
| 13 | cost（⑩） | partial→partial+ | partial（不变） | 接线已通（`quota_probe` → 停止判定），但**仍无真实额度源**（N-3） |
| 2 | review（横切 12 层） | partial | partial（不变） | 12 层审计台账仍未成体系（low） |
| 9 | net（④） | partial | partial（不变） | 出站超时/幂等策略未成文（low） |
| 11 | ops（⑩） | partial | partial（不变） | 无容器/编排清单（low，非目标场景） |
| 14 | compliance（⑩） | partial | partial（不变） | 合规检查点未纳入（low） |
| 17 | 性能（⑥主+⑩） | N/A | N/A（不变） | 无 load-test/benchmark 目录（复检触发：出现 benchmark 目录再评） |

其余 11 行（design / data / test / git / docs / security / observability / frontend / plugin / context / rag）保持 covered。

**计数**：**covered 12 → 14 / partial 6 → 4 / N/A 1**（矩阵 19 行不变）。

## ② 本轮闭合三项（含可复跑判据）

- **G-5（medium → closed）**：`sloth_engine/step_exception_policy.py` 从"机制"变"控制面"。
  接入点 = `sloth_engine/adapters/task_runner.py:271`（`BacktestRunner.run`，orchestrator / ooda_pipeline 的 Act 点）
  + `sloth_engine/tool_pipeline.py:193`（14 步管线 step 10）。
  不变量：默认 `ExceptionPolicy()` = 单次尝试 + 原样上抛（**默认档逐字节等价**）；仅真重试才写 `provenance.step_attempts`；
  兜底三态盖 `isSuccess` 但输出保持 `not_verified` / `not_evaluated`（**执行完成 ≠ 业务成功**）。
  判据：`git grep -n "apply_policy\|ExceptionPolicy" -- sloth_engine/*.py sloth_engine/adapters/*.py`
  → 命中 `task_runner.py:271` / `tool_pipeline.py:193`（cycle-9 时仅命中模块自身）。
- **G-6（medium → closed；残余 N-3）**：`Orchestrator.quota_probe / quota_provider / quota_cache`
  + `sloth_engine/run_loop.py` `_quota_snapshot()` / `_quota_stop_reason()`，在 `run()`（行 204）与 `iter_loop()`（行 581）每轮前判定。
  不变量：`exhausted` → 干净停机（status=ok，`total_rounds` 不计）；探针抛错 / 无可用窗口 → 降级 + 上次已知快照兜底，
  **绝不停机**；无探针 = 行为不变。
- **R1（cycle-9 残余 → closed）**：`sloth_engine/cli_router.py` `_run_once` 与长跑共用 `<runtime.root>/.loop.lock`
  （冲突退 2 且不动原锁；`finally` 释放）。与 `sloth_engine/run_lock.py` 的 pid 判活（`_pid_alive` / `_parse_lock_pid`）联动。

## ③ 仍未做（如实登记，未绕过 §0.1#6）

- **N-1（新，medium）**：把"机制已落、接线未闭"判据**门禁化** —— 脚本化检测 `sloth_engine/` 内无调用方的机制模块，
  防 G-5 式回归（当前靠人工 `git grep`）。
- **N-2（承 cycle-9）**：coze I-1..I-4 候选逐条评估（loop 节点图语义 / batch 并发闸门 / 嵌套迭代续跑 / Redis 中断事件队列）。
- **N-3（承 cycle-9）**：G-6 残余（真实额度源）+ R3（真实模型调用 / 24h soak）—— 需 LLM 挂载主机，本机无凭证。
- **R2（每项目文件沙箱）**：用户明确裁定**不做**。
- **WebUI / `guardian/risk_assessor.py::llm_review()`**：用户裁定**不动**（已文档化为设计缺口）。

## ④ 复检命令（GREEN-first）

```powershell
.\.venv\Scripts\python.exe -m pytest tests sloth_engine/tests -q    # 权威门禁：1392 passed / 1 xfailed / 74.42%
.\.venv\Scripts\python.exe scripts\docs_baseline.py               # 文档口径守护
.\.venv\Scripts\python.exe scripts\run_gate.py --all              # 全量门禁（pytest + docs_baseline）
```