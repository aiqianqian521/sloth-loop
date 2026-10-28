# sloth-loop 详细版本与变更说明（CHANGELOG）

> 面向 sloth-loop（dev 副本）的版本演化记录。生产 live 发布条件见 §六。
> 最后更新：2026-10-17 | 所在分支：`dev`（v4.2-dev 段由 git 逐轮提交折叠；v4.3-dev 段为本地工作区改动，暂无对应 git 提交）

## 一、版本总览

| 版本 | 日期 | 状态 | 关键内容 |
|---|---|---|---|
| v3.4 | 2026-08-21 | 已落地 | 架构扫描 19 项；book-to-skill 接入；未来路线图 |
| v3.5 | 2026-08-26 – 08-28 | 已落地 | EventLog ContextSnapshot；本地静态 HTML trace viewer (`--trace`)；W1-STORE-01 事务边界 |
| v3.6 | 2026-08-27 – 08-31 | 已落地 | W1-RESUME-01 幂等恢复（Slice 1–6）；provenance 契约；migration 隔离演练 |
| v4.0-dev | 2026-09-01 | 已落地（dev） | orchestrator godfile 拆分；fail-closed containment；ExecGate；circuit breaker 半开多探针；CI green-umbrella；pilot 配置模板化 |
| v4.1-dev | 2026-10-10 | 已落地（dev） | DSH 插件翻译扩展（schedule/jobs/document）+ Hindsight RAG 阶段2/4（分层记忆/Consolidation/MMR/图检索）+ Evolution 自动评审策略 |
| v4.2-dev | 2026-10-08 – 10-10 | 已落地（dev） | P0–P3 运行时接入批次：状态转换枚举/错误恢复阶梯/上下文压缩/并发工具调度/背压+熔断/HookBus 20事件/权限分层/immutable state/EventLog 标准化/子代理并行/Runtime wiring round2 — 全部按 git 逐轮提交折叠 |
| v4.3-dev | 2026-10-11 – 10-14 | 已落地（dev，未提交 git） | Guardian 审查预算按轮重置（长循环熔断 BUGFIX）；docs 目录治理（根目录 allowlist：锚文件归位 docs/state/、方法论长文入 docs/）；RAG 注释路径修正 |
| v4.0 | 待定 | 未发布 | 需满足 §六 生产门禁后才能宣称 |

> 说明：仓库内没有独立的 `__version__` 字符串；「版本」由 `docs/README.md`、`CLAUDE.md`、
> `sloth_engine/README.md` 与本文档共同约定。表中 v4.0-dev 为本次收敛后的统一代号。

## 一·补3. v4.4-dev（2026-10-16 – 10-17）

> L1 既定模式（接→化→发 + OODA + 三轮 md5 一致 + 破框）。分两批：
> 批二（P1 fail-closed 集中修复）+ 批三（剩余 5 项）+ docs 基线口径统一。

### 1. 批二 — P1 fail-closed 批次（commit 0560476）
- D9 purity BOM：`plugin_loader.purity_check` 改 `utf-8-sig` 读 `entry.py`，消除 BOM 假阳性。
- D8 非 UTF-8 signals：`signal_pool.load` 捕 `UnicodeDecodeError`，不再静默返回空池。
- D4 config 缺文件：`load_config(require_exists=True)` 显式 fail-closed（exit 2）。
- D7 threshold 型错：`verifier._compare` 先校验后使用，非数值判 fail-closed。
- P0D gate 假 SKIP：`run_gate.py` 新增 `--all`，无 staged/无 .git 也可一键全量验。
- 测试 +11（`tests/test_p1_failclosed_batch.py`）。1184 passed / cov 72.01%。

### 2. 批三 — 剩余 5 项 fail-closed 修复（一修一 commit）
| commit | 修复 |
|---|---|
| `572868f` | P2-1 `report_util` 的 input_ref 指向**真实**归档输入路径（非硬编码） |
| `bd7a658` | P1-3 损坏 DB → `CorruptDatabaseError`（可诊断、fail-closed） |
| `cd10878` | D5 空 `success_criteria` 不再静默默认 → `[WARN] CRITERIA-IMPLICIT` + `implicit_criteria` |
| `14a394a` | P1-6 归档每轮**原文**（复制 `io/_data/loop_backtest_{input,output}.json` 进 `data/`） |
| `751d7f2` | P1-4 `schema_validate` 默认 **true**（fail-closed；`=false` 可退） |

- 三轮一致：全量 `3×1194 passed`；外部发现重测 md5 `cfd2d6efd2c3c92374535b7d3c04f8f3`。
- 基线：666→1113→1184→**1194 passed / 1 xfailed / coverage 72.13%**；`fail_under` 64→70。

### 3. docs 基线口径统一 + 优化（docs-only）
- `pyproject.toml` 依赖笔误 `httpx2>=1.0` → `httpx>=0.27`（FIX-1）。
- 全库**当前态**文档统一到实测 1194 / 1 xfailed / 72.13%：
  `Prompt.md`、`README.md`、`CLAUDE.md`、`RUNBOOK.md`、`ONBOARDING.md`、`docs/sloth-loop-AS-BUILT.md`、
  `docs/sloth-loop-ROADMAP.md §0`、`docs/sloth-loop-DEV-SETUP.md`、`docs/sloth-loop-USAGE.md`、
  `docs/sloth-loop-项目介绍与规划.md`。
- **历史里程碑数字按约定保留为证据并加注**：`ROADMAP §4`、本 CHANGELOG 历史段、
  `AS-BUILT` cycle-2（如 780 passed）、`项目介绍与规划 §16`（2026-09-02）。
- 飘移文档补齐：`docs/flow/2026-09-05-grand-loop-status.md` 新增 §13.7/§13.8；
  `grand-loop-task.md` / `GRAND-LOOP.md` 加**时点声明**（真源已为 sloth-loop @ dev）。
- `docs/CONTEXT.md` 补术语：`implicit_criteria` / `CorruptDatabaseError` / `schema_validate`。

> 回归：docs-only 不改源码，1194 passed 不变；`run_gate.py --all` PASS；`--doctor` Ready。

### 4. 缺陷报告离根修复 + docs 基线口径守护（2026-10-17，L1）
- **修复（commit 6f8d3ac）**：`run_state._produce_defect_report` 无 workspace 时不再回退仓库根，显式落 `runtime.root/projects/<name>/IMPROVEMENTS.md`；`.gitignore` 加 `/IMPROVEMENTS.md` 兜底；新增契约不变量 invariant-8/8b。
  - 基线：1194 → **1196 passed / 1 xfailed / coverage 72.13%**。
- **新增 docs 基线口径守护**：`docs/baseline.json`（单一来源）+ `scripts/docs_baseline.py`（校验当前态文档），
  接入 `run_gate.py`（fail-closed：口径漂移即拒提交）。将 2026-10-17 人工 grep “文档==实测”变为可守护。
- **GL-D-1 收口**：本地重建 `docs/knowledge-distillation/` L3 账本骨架（gitignored，不随发布）。

## 一·补. v4.1-dev（2026-10-10）

> 大任务循环四周目 · DSH 插件翻译 + RAG 阶段2/4 + Evolution 自动评审。
> 三轮既定模式一致性校验通过；全量 1113 passed / 1 xfailed（无回归）。

### 1. DSH 插件翻译扩展（Python 移植，非复制）

| 插件 | 类型 | 工具 | 域本质 |
|---|---|---|---|
| dsh-schedule | skill | schedule_create/list/delete/due | after/at/every/cron；严格 UTC instant(ms,Z)；every≥60s；cron 400 年上限+边界校验 |
| dsh-jobs | ops | job_submit/list/read/kill | 有界输出环（绝对字节偏移/头部驱逐不移位/非消费式读/UTF-8 安全截尾）；幂等 settle；result 仅交付一次 |
| dsh-document | skill | doc_convert/status/list | 内容身份 `sha256(ext\0bytes)` 共享转换 + 有界 LRU；PDF 输出校验；`OfficeToPdfError` 分类 taxonomy |
| dsh-fs | skill | fs_read/write/edit/stat | 路径围栏的读/写/编辑：行号分页读、原子写、唯一字面量替换、稳定错误码（2026-10-10 必要性评估后新增） |

- `plugin_manifest.py` VALID_TYPES 增加 `ops` 类型；roster 12→18（+ todo/credentials 上一轮 + schedule/jobs/document + fs）。
- 注册器工具数 34→49。

### 2. Hindsight RAG 阶段2/4 + MMR（零依赖）

- 新增 `sloth_engine/rag_layers.py`：实体提取 / 三层记忆(mental_models>observations>raw) /
  Consolidation(provenance) / MMR 多样性 / 图检索 Spreading Activation / 统一 `layered_recall`。
- `plugins/rag/dsh-rag-kb/entry.py`：`search()` 末尾接入 MMR 多样性 pass。

### 3. Evolution 候选自动评审策略（确定性三态）

- 新增 `sloth_engine/evolution_review.py`：`ReviewPolicy` + `review_candidates_deterministic`（accept/reject/defer）。
- `evolution_loader.py`：`auto_review_candidates` + `review_candidates(auto=)` + shadow evaluation。
- `cli_router.py`：`--auto-review`（无需 `--yes`）。

### 4. 测试基线

- 新增 `tests/test_rag_layers.py`（13）、`tests/test_evolution_review.py`（11）、
  `tests/test_features_and_agents.py` 追加 12（schedule/jobs/document）。
- 全量 pytest：1089 → 1102 → 1113 passed / 1 xfailed。

## 一·补2. v4.2-dev（2026-10-08 – 10-10）

> 大任务循环 · P0–P3 运行时接入批次。本节按 **git 逐轮提交**折叠归档（截至 2026-10-10 共 39 commits，
> 其中 38 个开发提交 + 1 个 Initial commit 2026-09-28）。测试基线 1113 passed / 1 xfailed。

### A. P0 — 治理与状态地基（2026-10-08）

| commit | 内容 |
|---|---|
| `c3251a6` | P0: sloth-loop-0927 独立环境 + PM 清理 |
| `4c9bada` | P1: 补齐 pyproject.toml [项目] 依赖声明 |
| `b0a3326` | C场景: 第2轮破框验证纳入开发路线 |
| `f4808a5` | P0-1: 状态转换枚举 — TerminalReason / ContinueReason / RecoveryState |
| `c0cd117` | P0-2: 错误恢复阶梯 — ErrorRecoveryLadder |
| `5269e3a` | P0-3: 上下文压缩管线 — ContextCompactor + collapse_drain + reactive_compact |
| `b9a2042` | P0-3: plugin_registry manifest 校验 |

### B. P1 — 执行管线与追踪（2026-10-08）

| commit | 内容 |
|---|---|
| `4ccfd81` | P1-N1: 工具执行管线增加 guard 层（waterfall） |
| `b21012c` | P1-N2: Step 级任务追踪 |
| `a4a9457` | P1-N3: EventLog 可诊断化 |
| `2b059f7` | P1-N4: BM25 多路融合检索 |
| `717e3bf` | P1-1: MentalModels 规则版 |
| `00a4be4` | P1-1: 并发工具调度 — ConcurrencyConfig + partition_tool_calls + execute_batch_parallel |
| `b442bb7` | P1-2+P1-4+P2-1: BackpressureQueue + CircuitBreaker + LoopConfig/LoopState/LoopDeps |
| `da0cba4` | P1-3: 子代理增强 — AgentContext + run_subagent + run_subagents_parallel |

### C. P2 — 架构模式升级（2026-10-08）

| commit | 内容 |
|---|---|
| `7175d91` | P2-N3: Session Projection 层 + DSH/ClaudeCode 深度对标分析 |
| `37a1503` | P2-N1: SystemPrompt 段注册表 |
| `7909f74` | P2-N6: Immutable State Transitions |
| `8258620` | P2-N5: 权限模式分层 |
| `1855045` | P2-N4: Async Generator 模式 |

### D. P3 — Hook体系 / 权限 / 事件（2026-10-08）

| commit | 内容 |
|---|---|
| `197e815` | P3-A1: immutable_state 集成到 run_loop |
| `0537044` | P3-A2: async_loop 集成 — RunLoopMixin.iter_loop() |
| `5c6b0c5` | P3-A3: permission_levels 集成到 tool_registry |
| `d06e076` | P3-B1: Hook 事件体系扩充 — 20 个 HookEvent 枚举 + HookBus |
| `8ae5cea` | P3-B2: HookBus 接入核心循环 |
| `67805bf` | P3-E2/E4: EventLog 标准化 + 工具审批链 |
| `c3eb544` | P3-E4: EvolutionCycle 生命周期 hooks 完善 |

### E. Runtime Wiring · 运行时接入（2026-10-10）

| commit | 内容 |
|---|---|
| `680bf36` | Phase 2/3/4 complete: Features 五阶段 + RAII SpawnReservation + InputQueue + SkillPolicy |
| `1ece4d3` | Runtime wiring: Features/ContextFragment/AgentRegistry/MCP 接入运行时 |
| `1ce7518` | Wiring round 2: ErrorRecoveryLadder + TaskTracker 接入 orchestrator |
| `0b9100d` | docs: 更新进化路线图 — 运行时接入 round2 + 全引擎破框扫描结果 |

### F. 文档 / 架构师 skill 复核（2026-10-10）

| commit | 内容 |
|---|---|
| `7984c78` | task2: 架构师 skill 三轮复核（18-atom）+ 补充 scheme 透传（f2 字段） |
| `aaf61cf` | task3: Evolution 候选自动评审策略（确定性三态） |
| `1f2986c` | docs: 既定模式完整性复核修正 |

### G. DSH 插件翻译批次（2026-10-10）

| commit | 内容 |
|---|---|
| `14bead7` | task3: DSH todo/credentials 插件翻译（Python port） |
| `4e4ad7e` | task1: DSH schedule/jobs/document 三插件翻译（Python port） |
| `f0908be` | task2: Hindsight RAG 阶段2/4 + MMR（零依赖） |
| `006863f` | dsH-fs: 必要性评估后翻译 tool-fs 插件（read/write/edit/stat, 路径围栏） |

> 说明：以上逐轮提交摘要已折叠入本 CHANGELOG；后续每轮 loop 提交应同步追加到本段（用户 2026-10-14 要求）。

## 一·补3. v4.3-dev（2026-10-11 – 10-14）

> 本地工作区改动，**尚无对应 git 提交**（git 最新提交停在 `006863f` 2026-10-10）。
> 本节由工作区 diff + 落盘文档回填，待后续统一提交时对齐。

### 1. Guardian 审查预算按轮重置（长循环熔断 BUGFIX，2026-10-13）

**症状**：长时自主循环（loop 挂载回测任务）跑到第 N 轮后，后续合法 spawn 一律
`escalate/deny`，表现为 `ContainmentError: 'guardian ... escapes runtime root ...'` → 熔断停机。

**根因**：`ExecGate` 的 Guardian `ReviewBudget` 是「单会话」上限（20）；loop 每轮都会 spawn
回测子进程，预算被多轮耗尽后误拦合法任务。

**修复**：
| 文件 | 改动 |
|---|---|
| `sloth_engine/runtime_exec.py` | `ExecGate` 新增 `reset_review_budget()`：重建 `ReviewBudget` + 清空 `_operation_history`（审查上限按「轮」而非按「会话」计量） |
| `sloth_engine/run_loop.py` | `RunLoopMixin` 每轮开头调用 `_exec_gate.reset_review_budget()`（fail-safe：`try/except` + `getattr` 守卫，向后兼容） |
| `sloth_engine/guardian/review_session.py` | 去除文件头 BOM（`﻿`），修正 UTF-8 编码 |

> 语义权衡：保留限流（防止单轮内无限 spawn），又不再阻断合法的长循环任务。

### 2. docs 目录治理（根目录 allowlist，2026-10-14）

**目标**：根目录只保留必要入口/配置，其余文档归位 `docs/`。

| 动作 | 内容 |
|---|---|
| 根目录 allowlist 收紧 | 仅留 `CLAUDE.md / README.md / RUNBOOK.md / ONBOARDING.md` + 工程配置（pyproject/requirements/uv.lock/.obsidian.yaml.example/.gitignore） |
| 唤醒锚归位 | `WAKEUP.md` · `NEXT.md` · `IMPROVEMENTS.md` · `WAKEUP.sloth-loop-core.md` → `docs/state/` |
| 方法论长文归位 | `LOOP-ESSENCE-AND-LEARNINGS.md` → `docs/` |
| 引用同步修复 | `CLAUDE.md §9.1` allowlist 表、`README.md` 根目录树、`ONBOARDING.md §八` 路径全部更新为 `docs/state/...` |
| `.gitignore` 加固 | 追加 `_scratch_archive_*/`、`*_archive_*/` 防残留入库 |
| `docs/README.md` | 重写为文档入口索引（84 行改动） |
| 打包 | `sloth-loop-0927_package_20261014.zip`（232 文件 / 0.70MB，排除 .git/.venv/tests/projects/logs/rt/_data/work_ooda/归档残留） |

### 3. 其他

- `sloth_engine/rag_layers.py`：Hindsight 对标注释路径修正（指向 `docs/_archive-from-0927/research/rag-comparison-hindsight-vs-loopdev.md`）。
- `docs/sloth-loop-ROADMAP.md`、`docs/design/sloth-loop-evolution-roadmap-20261009.md`：路线图小幅更新（+2 行）。

### 4. 版本更新要点（git 提交 ↔ CHANGELOG 对照）

- **v4.2-dev**（10-08 – 10-10）：39 个 git 提交已全部折叠（见 §一·补2，A–G 七组）。
- **v4.3-dev**（10-11 – 10-14）：**本地工作区改动，未进 git**（用户 2026-10-14 确认"没有 .git 文件覆盖，属正常"）。
  后续若统一提交，建议拆 4 个 commit：①Guardian 预算重置修复 ②docs 根目录治理 ③引用同步 ④RAG 注释修正。

## 二、v3.4（2026-08-21）

- 完成架构问题扫描：19 项（4 critical / 6 major / 9 minor），记录于
  `docs/architecture-problem-scan-report.md`。
- 接入 book-to-skill 通用任务（projects/book-distill/wrapper.py）。
- 测试基线：490 passed（275 pytest + 215 自定义 runner），压力测试 30 sigs/s。
- 已有代码基线：`47a383b`。

## 三、v3.5（2026-08-26 ~ 08-28）

- EventLog 接入 ContextSnapshot（OODA 步事件携带跨轮快照）。
- 新增 `--trace`：本地静态 HTML trace 报告（`sloth_engine/trace_viewer.py`）＋ EventLog 自动加载。
- W1-STORE-01：Learn 单元使用原子事务边界（commit `c380100`）。
- 跨主机的 `.obsidian.yaml` + docs 路径可移植化（commit `6ddf516`）。
- `.gitignore` 排除 `work_ooda/runs-*` 运行产物（commit `7b656cc`）。

## 四、v3.6（2026-08-27 ~ 08-31）

### 4.1 W1-RESUME-01：断电/崩溃恢复幂等（Slice 1–6）
- Slice 1：resume 兼容 4 元校验（task_name、config_hash、schema_version、provenance）。
- Slice 2：按 `(run_id, round)` 做 Learn 幂等 + 单源 hash。
- Slice 3：step 级 checkpoint + resume 步骤跳过（崩溃点之后步骤不重跑）。
- Slice 4：pool_hash 门（恢复时 pool 变了拒绝以旧游标索引新 pool）。
- Slice 5：7 点幂等矩阵测试（`test_resume_idempotency.py`）。
- Slice 6：v005 `idempotency_signature` 迁移 + attempt（首遍/续跑）区分。
- 语义：Checkpoint＝控制游标原子替换；EventLog＝事实；PatternStore＝经验物化视图。三者严格分离。

### 4.2 Provenance（回测结果溯源）
- `backtest/runtime_resolver.py`：runtime/data 解析 + chunked SHA-256 fingerprint。
- `sloth_engine/adapters/backtest_adapter.py` 携带 provenance（`loop.provenance.v1`、`provenance_digest`、`data_source`；原 `backtest/lh_bridge.py` 已随场景移入 lh 知识库）。
  `data_source`。
- `sloth_engine/adapters/backtest_adapter.py`：bridge provenance 放入 `TaskResult.provenance.source`，
  不污染 metrics。
- EventLog `act/result` 写无完整主机路径的 `provenance_ref`。

### 4.3 Migration 隔离演练
- `scripts/migration_rehearsal.py`：backup sidecar SHA、隔离 down/up、restore-only、
  evidence JSON、RTO 计时。
- 所有破坏性 down 在隔离 copy 上执行，source DB 不被迁移。
- 测试：`test_migration_rehearsal.py` + `test_migration_rehearsal_cli.py`（11 passed）。

## 五、v4.0-dev（2026-09-01，本次收敛）

### 5.1 Orchestrator godfile 拆分（ADR-006 / ADR-007）
- `orchestrator.py` 从 ~3300 行收敛到 ~680 行（组合根）。
- 拆出 peer 模块：
  - `ooda_pipeline.py`（OODASteps）
  - `status_bar.py`、`log_tee.py`、`run_lock.py`（UI/运行基础设施）
  - `run_state.py`、`l2_meta.py`、`project_loader.py`（C1–C4 mixin 基）
  - `inspection_service.py`（per-instance `--inspect`）
- 保留 back-compat 再导出；`_legacy` 死方法已 purge 并有回归护栏。

### 5.2 Fail-closed containment + ExecGate（W2-BOUNDARY-01 / H2）
- `runtime_paths.py`：`assert_under` / `assert_under_root` / `assert_interpreter`（deny-by-default）。
- `runtime_exec.py`：ExecGate＝去 shell + 解释器白名单 + timeout/资源轴节流。
- `structured_cli.py`：字符串命令经 `shlex` 解析，不再 `shell=True`。
- `BacktestRunner` 可注入 exec_gate。

### 5.3 Circuit Breaker 半开多探针恢复（W1-CB-01 / ADR-008）
- HALF_OPEN 需连续 N 次探针成功才关闭（默认 1 保持旧行为），任一失败重置计数。
- 新增 `on_transition` 出站端口（转换审计，模块内无 I/O）。
- EventLog 接受 `circuit/transition` 事件类型。

### 5.4 CI green-umbrella（P3.2 / ADR-005）
- `pyproject.toml`：pytest + coverage 单一来源；`fail_under=64`。
- `scripts/run_gate.py`：缺依赖 fail-closed、coverage 不降（ratchet）、按改动路径触发。
- 修复 Windows 下 git stdout 用 GBK 解码导致中文文件名 `stdout=None` 崩溃的问题 → 强制 UTF-8。

### 5.5 Pilot 配置模板化
- `config.pilot-lh.yaml.example`（模板）与生成器 `scripts/make_pilot_config.py` 已随 lh 场景移入知识库。
- 新增 `scripts/make_pilot_config.py`：按主机 `runtime-root` 生成本地配置。
- 消除旧机残留绝对路径 `<SLOTH_LOOP>` 导致的 `ContainmentError`。
- 端到端验证：真实信号 + 真实数据跑通 doctor（探针 3 trades）与 once（7/7 OODA、1/1 criteria）。

### 5.6 测试基线
- `tests/` + `sloth_engine/tests/`：**666 passed, 1 skipped, 1 xfailed**。
- 排除项：`test_p0_2_rerun.py`（仅依赖外部 verdict-engine `wrapper`，已做 skip 保护）。

## 六、生产发布门禁（未满足，不要宣称可发布 live）

| 门禁 | 状态 | 说明 |
|---|---|---|
| Resume provenance 校验 | ✅ dev 已落 | checkpoint 校验 provenance_digest |
| Migration 恢复演练 | ✅ dev 已落 | backup/up/down/restore/RTO 隔离演练 |
| fail-closed CI | ⚠️ 未接 | 当前仅本地 run_gate（可绕过）；需远程 CI（pre-receive / hosted） |
| Migration sentinel RPO | ✅ 已交付（cycle-38 A `529ec97`） | v6 `commit_sentinel`（触发器同事务写入）+ 演练业务时间点 RPO（`sentinel_timestamp` / `verified=true`）；行数代理退役 |
| OS/network sandbox | ⚠️ 未做 | dev 有 containment，生产需系统级沙箱 |
| Orchestrator legacy 清理 | ⚠️ 进行中 | 已拆分，仍有边角清理 |

## 七、向后兼容说明
- EventLog 数据结构 v3.0 起为自包含扁平 JSONL；后续只追加类型（如 `circuit/transition`）不回写。
- PatternStore schema ledger：v001 → v002 → v003 → v004（Learn 幂等 ledger）→ v005（signature）。
- resume 对「无 digest 的老 checkpoint」保持兼容（legacy_provenance），一旦有 digest 则 fail-closed。
## 八、大循环 cycle-2（2026-09-06）· godfile 拆解 + observability 脚手架 + 记录补齐

> 追加于 2026-09-06，登记上一轮大任务循环（grand-loop cycle-2）代码自进化成果与本轮记录补齐；承接 §六未达门禁状态。

### 8.1 H1 godfile 拆解（3 文件 >800 → 全 <800）
- memory_store.py 1432→783（8 原子切片 P1a-h，抽 pattern_store_io/queue/exclusion/checkpoint/l2/corrections/classify mixin，MRO 行为保持）。
- ooda_pipeline.py 930→784（_learn→ooda_steps_learn mixin）。orchestrator.py 805→789（_safe_run_component→orchestrator_safety mixin）。
- 每切片独立 atomic commit + pytest 跑绿 + run_gate PASS，零回归。

### 8.2 M1-1 可观测性脚手架（维度 ⑩）
- 新增 sloth_engine/telemetry.py（104 行）：TraceBackend Protocol + NoopTraceBackend + ConsoleTraceBackend + create_backend 工厂；4 条分支（空/None、未知键、console、构造失败）均降级 NoopTraceBackend，永不抛入核心路径。
- 新增 tests/test_telemetry.py（8 测试）。pytest 772→780 passed。
- 对齐 architect-observability B 校正项；映射 TencentDB tencentdb-telemetry-stack 蒸馏条目（部分回填，见 _INDEX cycle-2 节）。纯增量未接热路径；trace_id + SLI/SLO 留 M1-2+。

### 8.3 记录补齐（AGENT_EXECUTION_TEMPLATE v7 §8 缺一不合格，本轮回填）
- M1-1 独立 OODA slice 补：work_ooda/20260906-040818-grand-loop-round2-P1e/m1-slice.md（Observe/Decide/Act/Verify + verdict-evidence + G-2/G-4 分支覆盖）。
- ISSUES.md + AGENT_ERROR_LOG.md 等价声明补（无遗留/无执行错误；1 项记录流程偏差已自纠）。
- _INDEX.md 回填 cycle-2（tencentdb-telemetry-stack 钩子复检→部分回填；candidate 计数 23 不变 N==M）。
- grand-loop-task.md 矫正：每轮必出独立 slice + ISSUES/AGENT_ERROR_LOG + §8.4 记录完整性自校验（防 M1-1 类缺口复发）。

### 8.4 测试基线
- 772→780 passed（+8 telemetry）；coverage 持平 ~71.91%；run_gate PASS（ratchet fail_under=70 持平 HEAD；70→72 待 cov 实测差异核查后单升）。

### 8.5 commit 链 / 状态指针
- 见 docs/flow/GRAND-LOOP.md 唤醒锚与 docs/flow/2026-09-05-grand-loop-status.md registry 9.x/10.x。

### 8.6 未达门禁（承接 §六）
- fail-closed CI 仍未接；orchestrator legacy 边角清理已随拆分完成（<800）；其余门禁状态同 §六。


> [2026-10-10 文档整理] 本处引用的 `docs/knowledge-distillation/`、`docs/flow/GRAND-LOOP.md`、`docs/research/` 等研究/过程稿已移至 `sloth-loop\docs\_archive-from-0927\` 备份保留；成品 docs/ 仅保留使用/交付所需文档。


## 2026-10-13 — Guardian 审查预算耗尽导致长循环熔断（BUGFIX）

**现象**：长循环任务（如 pm-interceptor-coverage，需 >20 轮 spawn 回测）在第 21 轮起，
所有 subprocess spawn 被 Guardian 拒绝，报 `回测解释器被拒绝: guardian . escapes runtime root .`，
连续 2 次执行错误 → 熔断停机（`reason: 2 consecutive errors, circuit breaker (limit=2)`）。

**根因**：
- `guardian/review_session.py` 的 `ReviewBudget.max_requests = 20`（**单会话**上限）。
- `runtime_exec.ExecGate` 只在 `__init__` 建一次 `ReviewBudget`，跨所有轮共享。
- 第 20 轮后预算耗尽 → `RiskAssessor.assess()` 走 `_escalate` → `ExecGate._guardian_check`
  抛 `ContainmentError(Path("."), Path("."), kind="guardian")` → 字符串渲染为 `guardian . escapes runtime root .`。

**修复**：
- `ExecGate.reset_review_budget()`：重建 `ReviewBudget` 并清空 `_operation_history`。
- `run_loop.py` 每轮开头调用 `self._exec_gate.reset_review_budget()`（按**轮**限流，保留安全语义）。
- 验证：5 轮 × 5 spawn = 25 次全部放行（重置后剩余 15）。

**教训**："单会话"类预算/限流器用于长时自主循环时必须改为"每轮/滑动窗口"口径，
否则会在第 N 轮静默阻断合法操作并触发熔断。定位信号：`guardian ... escapes runtime root`。

## 2026-10-26 — cycle-39：测试隔离（收集期不得写仓库）+ 门禁通过行口径与判定同源

**背景**：cycle-38 的「新鲜副本验证」登记了两条候选——`tests/test_v2_p1p2.py` 在**收集期**打开仓库内运行态库；`scripts/run_gate.py` 的通过行打印的比较与判定不一致。

**缺陷（实测）**：
- 全新克隆仅 `pytest --collect-only tests/test_v2_p1p2.py` 就写出约 110KB 的 `sloth_engine/data/patterns.db` 到代码树；把一份旧版（v5）库放进树后，整套 pytest 在收集期直接 ERROR（`RuntimeError: database migration required: v5 -> v6`）——一个无关模块打断整个会话。
- 逐文件扫描又发现 4 个同族写入点：`test_webui_auth_config.py`、`test_webui_static.py`、`test_contract_invariants.py`、`test_evolution_bridge.py`、`test_loop.py`（CLI 冒烟）都会创建同一文件。
- `run_gate.py` 判定 `measured + 0.15 >= recorded`，通过行却打印 `coverage 79.35% >= 79.47%`（字面为假）。

**修复**：
- 5 个写入点全部切到私有临时库 / 临时配置（`memory.sqlite_path` → tmp）；`test_v2_p1p2.py` 用私有临时库 + 确定性种子，并新增 `test_store_is_isolated_from_the_repo_tree` 钉住「store 路径在仓库树之外」。
- 抽出 `run_gate.coverage_floor(recorded) = recorded - tolerance` 作唯一定义：判定 `measured < floor`，通过行打印 `coverage X% >= floor Y% [recorded Z%, slack S%]`，失败行同口径；+2 例钉住「刚好落在容差内」的通过路径。

**验证**：逐文件扫描 → 修复前 5 个 CREATES-DB，修复后 0 个；新鲜副本全量在「空库」与「预置 v5 旧库」两场景下均 **1759 passed / 0 xfailed / 79.48%**，仓库树零写入、旧库未被改写。全量 1756 → **1759 passed** / 79.47% → 79.48%。

**教训**：测试的输入必须由测试自建且确定——被测仓库的运行态不是测试输入；收集期不得有文件系统副作用。门禁的**通过消息必须与判定同源**（同一表达式取反），容差必须显式给出实际生效下界，否则会出现「判定通过、消息自相矛盾」。

## 2026-10-27 — cycle-40：测试结论必须可复现（残留与并发时序不得决定结果）

**背景**：cycle-39 的「新鲜副本验证」登记了一条残差——干净克隆 79.47% vs 本机 79.48%，差 1 条分支。

**缺陷（实测，三层漂移）**：
- `sloth_engine/tests/_tmp_*`（插件草稿包，gitignored）跨运行残留，`dsh-mneme` / `dsh-rag-kb` 的 `_ensure` 在「store 已存在 / 缺失」间翻转（90%/88%、70%/69%）。
- `run_reporter._archive_raw_io` 最后一级回退直读仓库根 `_data`（热机有、干净克隆无，88%/89%）。
- `sub_agent.AgentRegistry._release` 的循环 / if 分支只被线程竞态覆盖——同一命令连跑 6 次，4 次记 4 partial、2 次记 5 partial（79.48% vs 79.47%）。

**修复**：
- A（`74253b4`）：新建 `sloth_engine/tests/conftest.py`（session 级 autouse 夹具清理 `_tmp_*`）；`run_reporter` 抽出可注入的 `_data_root()`，`test_archive_raw_io_missing_is_non_fatal` 用 `monkeypatch` 指到空临时目录。
- A2（`7471e41`）：新增单线程测试直接驱动 `AgentRegistry._release` 的三种形状，让分支覆盖不再依赖线程时序；原并发测试保留。

**验证**：同一命令连续两次 **1760 passed / 0 xfailed / 79.49%**（4424/670）逐字一致；`git clone` 到空目录后全量同值、仓库树零写入。全量 1759 → **1760 passed** / 79.48% → 79.49%。

**教训**：测试的**结论**必须可复现——登记基线是干净克隆可逐字重现的观测，不是一次性读数；测试自身的残留与并发时序都不许决定结果。「落在容差内」不得掩盖「两次结果不同」。

## 2026-10-27 — cycle-41：交接入口文档（START.md）纳入口径守护

**背景**：打包交接包时复核入口文件，发现 `START.md`（新 agent 第一个读的交接入口）两处仍引用旧基线。

**缺陷（实测）**：
- `START.md:24` 写「（期望 1159 passed, 1 xfailed, cov ~71.76%）」、`START.md:35` 写「不得低于 1159 passed」——实际基线 **1760 / 0 xfailed / 79.49%**，差 601 个用例。
- `docs_baseline.check() == []`：`CHECK_FILES` 这份手写清单**没有** `START.md`，所以这两处旧数字无人校验（cycle-24 唤醒指针缺口同族）。

**修复**：
- `START.md` 两处数字更新（1760 / 0 xfailed / 79.49%，fail_under=70）。
- `scripts/docs_baseline.py`：`CHECK_FILES` 纳入 `START.md`。
- `tests/test_gate_self_verification.py`：作用域 pin 与漂移负控改为覆盖 `WAKE_POINTER` + `HANDOFF_ENTRY` 两份入口文档（用例数不变）。

**验证**：`docs_baseline.check() == []`；全量 **1760 passed / 0 xfailed / 79.49%**（口径不变）；`scripts/run_gate.py --all` → PASS。

**教训**：判定「当前态文档」的清单是**手写**的——一份「谁第一个读」的入口文档若不在清单内，它的数字会静默腐烂到差 601 个用例仍显示 OK。清单本身必须把入口文档列全，并由用例钉住。


## 2026-10-27 — cycle-42：当前态文档口径守护扩容 + 陈旧基线 / 乱码修复

**背景**：cycle-41 收口后，用户要求「确保 loop 相关文档、README 都更新到最新版本」——对交付包逐文件复核。

**缺陷（实测，同族）**：`docs_baseline.check() == []`，但它**不覆盖**这些当前态文档（不在 `CHECK_FILES`）：
- `Prompt.md:5` 头部仍写 `1282 passed / 1 xfailed / 72.91%`（commit `ea097b6`），而实际基线 **1760 / 0 xfailed / 79.49%**（差 478 个用例）。
- `docs/sloth-loop-QUICKSTART.md:71` 自查清单写「700+ 全绿, coverage>=64%」，且命令漏了 `sloth_engine/tests`。
- `sloth_engine/README.md:3` 头部写「v3.4 | 测试基线: 490 passed (98.4%)」，`:486` 写「490 passed, 8 pre-existing failures」。
- `docs/sloth-loop-项目介绍与规划.md` 4 处写 `1194 passed / 1 xfailed / 72.13%`（§1 结论 / §10.6 门禁 / §13 基线）。
- `docs/sloth-loop-AS-BUILT.md:158` 的「当前实测 1255 / 72.68%」与本文件头部（1760 / 79.49%）自相矛盾。
- 附一：`CLAUDE.md:49` / `docs/sloth-loop-ROADMAP.md:28` 的「coverage ≥64」陈旧（现为 `fail_under=70`）。
- 附二：`docs/LOOP-ESSENCE-AND-LEARNINGS.md` 的错21 段**编码损坏**（非 ASCII 字节全被替换为 `?`，git 历史中亦已损坏，无源可恢复）。

**修复**：
- 上述 7 份文档数字 / 口径修正；错21 段按**未损坏**的标识符（`status="ok"` / `run_accomplished` 附近 `run_lock` 6h / `verifier._compare` operator None / `pytest tests sloth_engine/tests`(71.98%) 等）**忠实重建**。
- `scripts/docs_baseline.py`：`CHECK_FILES` **11→14**（+`docs/sloth-loop-QUICKSTART.md` / +`sloth_engine/README.md` / +`docs/sloth-loop-项目介绍与规划.md`；中文路径用 `\u` 转义保持源码 ASCII）。
- `tests/test_gate_self_verification.py`：作用域 pin（`test_the_baseline_guard_covers_the_entry_documents`）与漂移负控由 `WAKE_POINTER` + `HANDOFF_ENTRY` 扩到 `ENTRY_DOCS`（5 份），只改写既有用例（用例数不变）。
- 交付包改为**只含 git 跟踪文件**（按 `RELEASE.md`「发布版 = `git archive` 产物」）：此前的 copy 式打包把 **465 个 gitignored 文件**（`scripts/tmp/` 398、pytest 草稿 `_tmp_*` 45、私有 `docs/knowledge-distillation/` 20、`sloth_engine/STATE.md`、`sloth_engine/data/handoff.json`）打进了交付包，与既有 `sloth-loop-0927_release_*.zip`（0 垃圾）不一致。

**验证**：`docs_baseline.check() == []`；全量 **1760 passed / 0 xfailed / 79.49%**（口径不变）；`scripts/run_gate.py --all` → PASS。

**教训**：守护清单是**手写**的，而交付面在扩大（新增入口 / 组件 / 介绍文档）——清单必须同步扩大，否则同一套基线会在交付包里出现多个不同旧版本号，而校验器仍报 OK；打包必须走 `git archive`（跟踪文件），不得用工作树 copy。
