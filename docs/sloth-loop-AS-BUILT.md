# sloth-loop AS-BUILT 架构基线（建成现状 · 单一参考基线）

> 版本：v1 · 建立于 2026-09-03 · 代码基线 **git HEAD 5238c1d**（docs: 完整架构扫描+根因分析）
> 测试基线：**1760 passed / 0 xfailed / coverage 79.49%**（fail_under=70，pyproject.toml）
> **基线刷新 2026-10-17**（HEAD `751d7f2`）：原 755 passed / 71.91% / fail_under=64 为 2026-09-03 初建快照；经 L1 批二 + 批三（P0 传播、D9/D8/D4/D7、P2-1/P1-3/D5/P1-6/P1-4）后实测为 1282 passed / 1 xfailed / coverage 72.91%，fail_under 由 64 提至 70。**后续刷新 2026-10-27**（HEAD `fc492f0`）：当前基线 **1760 passed / 0 xfailed / coverage 79.49%**。下文带日期的历史数字（如 cycle-2 780 passed）保留为证据，不再代表当前基线。
> 数据源种子：`ai-skill-output-template/output/sloth-loop/2026-09-02/report.md`（L2 架构报告），按 architect-skills Router「全面项目分析」框架重排刷新。
> 用途：这是 sloth-loop 的**唯一 as-built 架构参考**。以后任何扫描/审查/验收，一律先对照本基线 diff 代码，禁止凭经验从零人肉重扫。

---

## ① 项目架构地图（Intake 建图，每目录一句话职责）

| 目录/入口 | 职责一句话 | 关键文件(行级证据) |
|----------|-----------|-------------------|
| sloth_engine/orchestrator.py | CLI 组合根：加载配置 + 编排 OODA + schema 强校验 | ~680 行（godfile 拆分后） |
| sloth_engine/ooda_pipeline.py | OODA 7 步编排 + U&Q 条件触发 + exec 调度 | L390-392 script 分支（F1 旁路风险点） |
| sloth_engine/run_once_pipeline.py | 单轮 execute→Verify→Learn 管线 | L304 读 success_criteria 默认 |
| sloth_engine/verifier.py | 逐条对照 success_criteria 判定 PASS/FAIL | L24/L49-52（F6 unknown 风险点） |
| sloth_engine/config_util.py | 默认配置 / 解析 | L158 backtest.script（A1 逃库风险点） |
| sloth_engine/runtime_exec.py | ExecGate：去 shell + 解释器白名单 + 资源上限 | 114 行，spawn 唯一受控出口 |
| sloth_engine/runtime_paths.py | fail-closed 路径隔离（断言在 runtime.root 内） | assert_under_root |
| sloth_engine/event_log.py | JSONL 事件日志（只追加事实源） | L473-484 _write_event（C-1 已修P1: RLock 串行 + replay 完整性暴露, inv-4c/4d） |
| sloth_engine/memory_store.py | SQLite 模式库 v001-v006（失败/成功经验） | 541 行 |
| sloth_engine/circuit_breaker.py | 熔断半开多探针恢复 | 107 行 HALF_OPEN |
| sloth_engine/orchestrator.py + run_loop.py | 停止条件（token_budget/max_rounds/no_progress） | run_loop.py L244（A2 死条件风险点） |
| sloth_engine/self_modify_gate.py | 自改码沙箱 pytest 门禁原语（第2档） | 默认关/搁置 |
| sloth_engine/evolution_bridge.py | 信号池→遗传演化→候选（第1档） | 默认关/搁置 |
| sloth_engine/adapters/backtest_adapter.py | Loop 与回测代码唯一耦合点 | L191 configure + io_dir |
| sloth_engine/adapters/task_runner.py | TaskRunner ABC + BacktestRunner | L305 metrics |
| backtest/ | 回测脚本契约（mock_backtest / runtime_resolver，历史 lh_runtime 已并入） | mock_backtest.py 契约 docstring |
| scripts/ | 门禁 + 脚手架（run_gate/make_pilot/make_pm_task_config） | run_gate.py |
| projects/<domain>/<task>/ | 业务场景接入根（config+signals+wrapper+candidates/reports） | projects/pm/_template |
| docs/ | 手册/版本/路线/PM 接入规范/架构扫描/根因 | docs/sloth-loop-QUICKSTART.md |
| _data/ | 子进程 I/O 契约落点（loop_backtest_input/output.json） | backtest_adapter 契约 |

**模块清点**：sloth_engine 核心 45 + adapters 2 + corrections 1 + migrations 7 = 55 引擎模块；scripts 4 + 仓库根 1 = 5 脚本；测试 51 文件。合计 59 源码 + 51 测试。

---

## ② 维度覆盖矩阵（architect-skills 15 维 · covered/partial/N-A + 证据 + 风险分级）

> 定级口径引 router 骨架：`critical`=阻塞/安全可利用/不可逆数据风险；`high`=显著伤质量；`medium`=小瑕疵；`low`=打磨。
> 所有 `covered` 均指到已实读证据；无证据只标 partial/N-A（防逃维）。

| 维度 | 状态 | 主 skill | 证据 | 风险 |
|------|------|---------|------|------|
| ① 上下文与约束 | covered | architect-agent | orchestrator 组合根 + OODA 7 步 + 四层约束 Budget/Stop/Scope/Zone | low |
| ② 需求与领域 | covered | architect-workflow | signal_schema 强校验 + success_criteria 两级定义 + verifier | low |
| ③ 系统结构 | covered | architect-design | 模块地图 + ADR-006/007（godfile 拆分） | low |
| ④ 接口与通信 | partial | architect-net | 子进程 --input/--output 契约（_data） | medium（无 REST/服务间） |
| ⑤ 数据与状态 | covered | architect-data | memory_store SQLite v001-v006 + event_log JSONL + provenance SHA | low（C-1 已修 P1: RLock + replay 完整性暴露） |
| ⑥ Agent/异步流程 | covered | architect-agent | OODA 状态机 + resume_guard 幂等 + circuit_breaker | high（A2 token_budget 死条件） |
| ⑦ 安全与信任边界 | covered | architect-security | ExecGate 白名单 + runtime_paths fail-closed + env scrub | high（F1 ExecGate 旁路） |
| ⑧ 测试与质量门禁 | covered | architect-test | 64+ 测试文件 1760 passed / 0 xfailed / 79.49% / run_gate | low（已建契约不变量层，见 tests/test_contract_invariants.py） |
| ⑨ 交付与变更 | covered | architect-docs | ADR×9 + design/ + ROADMAP + run_gate 本地门禁 | high（本地 gate 可绕过） |
| ⑩ 运行与产品能力 | covered | architect-ops | scripts/ + projects/ 接入根 + QUICKSTART | medium |
| architect-frontend | partial | architect-frontend | Streamlit WebUI 静态分离 | medium（无前端分离） |
| architect-compliance | N/A | architect-compliance | 纯本地单机，非受监管产品；上云/接第三方数据则重查 | N/A（复检钩子已记） |
| architect-cost | N/A | architect-cost | 无云付费 API；接托管/LLM 计费则重查 | N/A（复检钩子已记） |
| architect-observability | partial | architect-observability | event_log + --report + --trace | low（无系统级 SLO） |
| architect-git / refactoring | covered | architect-git | 9 ADR + git log 规范提交 | low |

---

## ③ 各 skill 详细分析（L1 口径 · 逐项行级证据 · 维内风险分级）

### architect-security（安全与信任边界）
- 已兑现：ExecGate 去 shell（shell 恒 False）+ 解释器白名单（assert_interpreter 阻止，on_violation 审计）+ 输出存储切片上限 + timeout + env scrub；runtime_paths fail-closed 路径隔离。
- **风险 F1 [critical]** ⓥ：`ooda_pipeline.py` L390-392 script 分支用原生 `sp.run(_argv, shell=False, capture_output=True)`，**从不经 ExecGate** → 解释器白名单/输出上限/env scrub 全旁路，fail-closed 破坏。
- **风险 A1 [high]** ⓥ：`config_util.py:158` 默认 `backtest.script="../backtest/mock_backtest.py"` 相对 PROJECT_ROOT 解析**逃出仓库**（落到上级 my/）。
- **风险 F2/F3**：exec_gate 空即裸跑 / allow-list 空即放行。
- 防线：契约不变量 1（所有 spawn 必须经 ExecGate）。

### architect-agent（Agent/异步流程）
- 已兑现：OODA 7 步（Understand→Observe→Orient→Decide→Act→Verify→Learn）+ resume_guard 断电幂等恢复 + circuit_breaker HALF_OPEN 恢复。
- **风险 A2 [high]** ⓥ：`tokens_used` 只在 `orchestrator.py:224` 初始化为 0，**从不累加** → `run_loop.py:244` 和 `circuit_state.py:154` 的 `token_budget` 耗尽判定是**死条件**。
- 防线：契约不变量 2（每个 stop 条件，含 token_budget，必须有真实累加/触发路径）。

### architect-test（测试与质量门禁）
- 已兑现：64+ 测试文件、1760 passed / 0 xfailed / coverage 79.49%、coverage > fail_under 70、run_gate 本地门禁（改 `sloth_engine/`、`tests/`、`scripts/` 任一即触发，coverage ratchet 不降）。
- **缺口**：现有测试以功能/正向往为主，**缺"契约不变量/负向"层** → F1/A2/F6 这类契约背离抓不住。
- 防线：契约不变量测试层 `tests/test_contract_invariants.py`（5 条）。

### architect-data（数据与状态）
- 已兑现：memory_store SQLite v001-v006 幂等迁移 + provenance SHA 可追溯 + checkpoint 硬校验 + event_log JSONL 只追加事实源。
- **风险 C-1 [medium → 已修 P1]** ✅：event_log.py _write_event 加 RLock 串行化(append/append_step _seq 自增+写入同锁原子化) → 并发 append 无损(inv-4c 绿); replay 缺 status 不再默认 PASS→UNKNOWN + 坏 JSON 计数暴露(_last_replay_malformed, F6@replay 同族, inv-4d 绿)。
- **风险 C-2**：`_tx_conn` 非线程本地。
- 防线：契约不变量 4a/4b/4c/4d（4c 并发无损 + 4d replay 不静默 — 本批新增并绿）。

### architect-design / architect-workflow / architect-ops / architect-docs
- god-file 拆分（ADR-006/007）、clean architecture（orchestrator 组合根）+ signal_schema 强校验 + run_gate 门禁 + 文档齐全。均 low 风险，见②矩阵。

---

## ④ 问题点汇总统计（cspm 风格）

**风险分级计数（当前 as-built 已知，主存根 20 项）**：

| 风险级 | 数量 | 涉及维度 | 关键文件 |
|--------|------|---------|---------|
| critical | 1 | ⑦安全 | ooda_pipeline.py L390-392（F1） |
| high | 4 | ⑥Agent ⑦安全 ⑨交付 | config_util.py(A1)、orchestrator/run_loop(A2)、exec_gate 空放行(F2/F3)、本地 gate 可绕过 |
| medium | 11 | ⑤数据 ⑧测试 ④接口 ⑩运行 | event_log(C-1)、verifier(F6)、CSV/MD 绕过(F4)、path 迷宫(C1)、run_fast(D1) 等 |
| low | 4 | 跨维 | N-1/M-1/M-2、C-3/4/5、A3、D2 等 |

**覆盖计数**：covered 11 / partial 4 / N-A 2 / missing 0。
**高发维度 Top**：⑦安全（F1/F2/F3/A1）、⑥Agent（A2）、⑤数据（C-1/C-2）。

**半定量基线（沉淀供后续扫描引用）**：
- 单文件 >800 行 = god-file 风险锚点（重叠 architect critical 金样）。
- ExecGate 是 spawn 唯一出口；凡发现不经 ExecGate 的 `subprocess`/`sp.run` 即视为契约背离（critical）。
- 每个 stop 条件必须能在运行中真实置真，否则为死条件（high）。
- 覆盖率 fail_under=70 为已承诺底线，run_gate 不得让它回落（当前实测 coverage 79.49%，HEAD 门槛 70）。

---

## ⑤ 改进方案 —— Critical/High 阻塞项详述（含验证命令）

### C1（critical · F1 ExecGate 旁路）
- 现象：`exec.type:script` 分支绕过 ExecGate，解释器白名单/输出上限/env scrub 全失效。
- 证据：`sloth_engine/ooda_pipeline.py` L390-392 `sp.run(_argv, shell=False, capture_output=True, ...)`。
- 根因：ADR 未覆盖的旧执行分支；exec_gate 约束没下沉到所有 spawn 出口。
- 影响：fail-closed 安全边界被单点破坏，恶意/异常命令可绕过白名单执行。
- 修复顺序：**P0**（先加不变量 1 断言，再改走 ExecGate）。
- 验证命令：`tests/test_contract_invariants.py::test_invariant_execgate_single_exit` 必须绿。
- 响应时间：P0（阻断项）。

### H1（high · A2 token_budget 死条件）
- 现象：tokens_used 恒 0，token_budget 耗尽永远是死分支。
- 证据：`orchestrator.py:224`（不累加）+ `run_loop.py:244`/`circuit_state.py:154`（判定）。
- 根因：token 记账从未接入实际耗用。
- 影响：资源预算形同虚设，超长 run 无上限约束。
- 修复顺序：**P1**（先加不变量 2 断言再改）。
- 验证命令：`tests/test_contract_invariants.py::test_invariant_stop_conditions_reachable`。

### H2（high · A1 默认路径逃库）
- 现象：默认 backtest.script 相对 PROJECT_ROOT 解析逃出仓库。
- 证据：`config_util.py:158` + `backtest_adapter.py:100-103`。
- 修复：`[medium→P1]` 默认改为仓库内绝对路径解析或显式拒绝越库。
- 验证：配置作成后运行时 PATH 断言必须落在 runtime.root 内。

### H3（high · F6 verifier 未知 metric 假成功）
- 证据：`verifier.py` L24/L49-52 未知 metric → passed=None 记 unknown 不进 fail。
- 修复：**P1**，未知 metric 整轮判 fail（不变量 3）。
- 验证命令：`tests/test_contract_invariants.py::test_invariant_verifier_no_unknown_pass`。

### H4（high · 本地 gate 可绕过）
- 证据：run_gate.py 软约束自述（`--no-verify`/钩子可绕过，非 fail-closed CI）。
- 约束：gated 项（fail-closed CI/migration RPO/sandbox/REST/自主进化）**不抢跑**，保留为已知债务。复检钩子：接远程/托管 CI 时升级。

---

## 关键结论

sloth-loop 核心链路（OODA 编排 / Verifier 判定 / schema 强校验 / fail-closed 路径）健壮、可编译全通、迁移幂等。真正的债集中在**运行面外/契约外**的少量旧分支（script 执行、token 记账、event_log 并发、verifier unknown），共 20 项全部**非 gated**、有明确位置与修法。真正要补的机制是 **as-built 基线 + 契约不变量测试层**，让这类背离不再依赖人肉重扫。

## 已接受假设
- 测试基线 755/71.91% 为 2026-09-03 初建快照实测值（330caed 当时的上游源码基线）。**2026-10-17 刷新**：当时实测 1255 passed / 1 xfailed / coverage 72.68%（HEAD 7c6e6a8）；**2026-10-27 复刷新**：当前实测 **1760 passed / 0 xfailed / coverage 79.49%**（HEAD `fc492f0`）。
- coverage fail_under=70 为承诺底线（2026-10-17 由 64 提至 70）。
- 自进化整体搁置属用户决定，非缺陷。

## 未覆盖与建议新增
- 见②矩阵 N-A/partial 项（compliance/cost 复检钩子已记录）。
- 建议后续新增：系统级 SLO/告警（observability）、REST/WebUI-API 分层（net）。

## 验证命令与结果
```
.venv\Scripts\python.exe -m pytest -p no:cacheprovider --no-cov -q tests/ sloth_engine/tests/ --ignore=tests/test_p0_2_rerun.py
# 实测（历史快照）：758 passed / 3 xfailed / 1 xpassed，coverage 70.48% > fail_under 64
#   - 3 passed = 新增契约不变量 （invariant 4a replay / 4b 单点写 / 5 单一归档）
#   - 3 xfailed = 契约不变量登记的已知缺口（invariant 1 F1 / 2 A2 / 3 F6），修复后去 xfail 即转绿守护
.venv\Scripts\python.exe scripts/run_gate.py   # 本地门禁，coverage ratchet 不降
```


---

## ⑨ cycle-2 修订说明（2026-09-06 追加，承接 §① 2026-09-03 快照）

> 登记上一轮大任务循环（grand-loop cycle-2）对 AS-BUILT 快照的实质变化。原文 §① 保留为 2026-09-03 历史快照，以下为本轮修订增量。

### 9.1 关键模块行数变更（godfile 拆解，§① 表中下列行已过期）
- sloth_engine/memory_store.py：1432→783（8 原子切片，抽 pattern_store_io/queue/exclusion/checkpoint/l2/corrections/classify mixin）。
- sloth_engine/ooda_pipeline.py：拆出 ooda_steps_learn mixin→784。sloth_engine/orchestrator.py：拆出 orchestrator_safety mixin→789。
- 行为保持（MRO 继承），契约不变，pytest 零回归。

### 9.2 新增模块
- sloth_engine/telemetry.py（104 行）：可观测性维度 ⑩ 脚手架。TraceBackend Protocol + NoopTraceBackend（默认空实现）+ ConsoleTraceBackend + create_backend 工厂（缺失/未知/失败降级 Noop）。纯增量，目前无核心模块 import，热路径集成留 M1-2+。§① 表应据 9.1-9.2 增补一行 telemetry.py 职责。

### 9.3 代码/测试基线更新
- 代码停止基线 HEAD 见 git log（cycle-2 = 1fb4846 M1-1）；测试 772→780 passed；coverage ~71.91% 持平。

### 9.4 与 §② 维度矩阵的关系
- §③/⑤ 高①「godfile >800」缺口已闭合（§9.1）。
- §⑩ observability MISSING→M1-1 部分补（脚手架 backend 抽象；全量 SLI/SLO 留 M1-2+），可标 partial。
- 其余维度覆盖状态以原 §② 评估为准，本轮未变。

