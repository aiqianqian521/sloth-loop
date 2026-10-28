# <Q_PROJECT> loop 接入场景 — CLAUDE.md（Agent 指南）

> 版本：v4.0-dev ｜ 更新：2026-09-03 ｜ 本文件是 AI Agent 进入「量化交易的 loop 接入场景」时的第一份指南。
> 权威来源：**当前唯一开发库为 `<repo_root>`**（分支 `dev`，v4.0-dev，HEAD `0b8afab`，1760 passed / 0 xfailed / coverage 79.49%）。
> 旧 `<repo_root>\legacy-loop` 只是**旧基线副本/入口**，不作为新的开发/运行目标。

## 1. 场景定位

本目录 = 量化交易项目在 loop 编排下的**接入场景资产**（2026-09-02 commit `a2af4f0` 发布级剥离后沉淀于此）。

- **lh**：面向 ETH/USDC 5 分钟 K 线的严格信号监控与因果回测研究项目。
- **loop**：通用 **CLI 驱动的自进化编排引擎**（与业务解耦）。核心是「用户定义成功、Loop 自主逼近」：
  给一批候选信号 + 你写的 `success_criteria`，它自主跑 OODA 7 步、失败自动沉淀为排除经验、成功复用为优先信号。
- **主项目已去 lh 化**：sloth-loop 只保留通用编排框架；lh 专属的桥接/试点/架构/文档已整体移入本目录。

## 2. 本目录内容

| 资产 | 内容 | 说明 |
|---|---|---|
| `backtest-bridge/lh_bridge.py` | lh 真实回测桥接 | 按 loop `backtest_adapter` I/O 契约，经 `lh_runtime` 动态解析运行时与数据 |
| `pilot-lh-template/` | lh 试点配置模板 + 生成器 + 信号种子 | `config.pilot-lh.yaml.example`、`make_pilot_config.py`、`signals_lh.json` |
| `architecture-plans/` | loop 架构计划 | system-architecture / loop-plan / roadmap / implementation-options|
| `mcp-server/` | loop 的 MCP 服务端 | （可选接入） |
| `RUNBOOK.md` | 从零跑通闭环的手册 | 见本文件后续章节 |
| `mcp-config.json` | MCP 配置 | 按主机填 |

> 权威规范：PM 框架接入 sloth-loop 见 `docs/PM框架-接入sloth-loop-流程规范.md`；
> PM 可执行资产见 `..\PM\qupm-loop\`；完整最新文档见 `<repo_root>\docs\`。

## 3. sloth-loop 核心代码入口（v4 拆分后）

| 模块 | 路径 | 说明 |
|---|---|---|
| CLI 组合根 | `sloth_engine/orchestrator.py` | 组合根 + OODA 编排（~680 行，godfile 拆分后） |
| CLI 路由 | `sloth_engine/cli_router.py` | 命令分发（doctor/once/run/resume/inspect/trace/review…） |
| 单轮管线 | `sloth_engine/run_once_pipeline.py` | execute → Verify → Learn |
| 连续循环 | `sloth_engine/run_loop.py` | 连续 OODA 循环 |
| OODA 7 步 | `sloth_engine/ooda_pipeline.py` | U→O→D→A→V→L 步骤事件 |
| 事件日志 | `sloth_engine/event_log.py` | JSONL 事实源（只追加） |
| 模式库 | `sloth_engine/memory_store.py` | SQLite schema ledger v001–v006 |
| 成功判定 | `sloth_engine/verifier.py` | 对照 success_criteria 判定 |
| 输入强校验 | `sloth_engine/signal_schema.py` | 信号 schema 强校验（fail-closed） |
| 运行时隔离 | `sloth_engine/runtime_paths.py` / `runtime_exec.py` | containment + ExecGate（去 shell + 白名单） |
| 幂等恢复 | `sloth_engine/resume_guard.py` | 断电/崩溃恢复 |
| 熔断 | `sloth_engine/circuit_breaker.py` | CLOSED/OPEN/HALF_OPEN 多探针恢复 |
| 报告输出 | `sloth_engine/report_util.py` | `--report` → `projects/<domain>/<task>/reports/<date>/REPORT.md`（domain=--project 首段，domain==task 退化单层，见 §9.4） |
| 适配器 | `sloth_engine/adapters/backtest_adapter.py` | Loop 与实际任务的唯一耦合点 |
| 任务执行器 | `sloth_engine/adapters/task_runner.py` | TaskRunner ABC + BacktestRunner |
| 门禁 | `scripts/run_gate.py` | green-umbrella：coverage ≥ `fail_under`=70 只升不降 |
| 回测运行时 | `backtest/runtime_resolver.py` | 运行时/数据路径解析 + SHA-256 溯源 |

## 4. 编码约定

- Python 3.11+，零依赖优先（PyYAML 可选，仅知识库导入用）。
- **测试基线**：`tests/` + `sloth_engine/tests/` = **1760 passed / 0 xfailed / coverage 79.49%**（单一来源 `docs/baseline.json`，`run_gate` 自动校验）。HEAD `0b8afab`（最近一次 A 提交；轮次与提交链见 `docs/flow/GRAND-LOOP.md`）。
- **提交门禁**：`scripts/run_gate.py`（coverage ≥ `fail_under=70`，相对 HEAD 只升不降）。
- **路径铁律**：业务脚本用仓库内相对路径；运行产物只写 `runtime.root`（仓库外）；越界 = fail-closed，不是 bug。
- **模式库铁律**：Failure 默认证据、Rule 默认人工 `--review` 审批后控制；禁止自动改 status。

## 5. 运行命令（在 `sloth-loop/sloth_engine/` 下执行）

```bash
# 环境自检（含契约探针）
.venv\Scripts\python.exe orchestrator.py --doctor

# 跑一轮完整 OODA（默认 demo 配置）
.venv\Scripts\python.exe orchestrator.py --once

# 指定项目/任务配置
.venv\Scripts\python.exe orchestrator.py --config config.yaml --once
.venv\Scripts\python.exe orchestrator.py --project <task> --once
.venv\Scripts\python.exe orchestrator.py --task <task>.yaml --once

# 连续循环 / 断电续跑
.venv\Scripts\python.exe orchestrator.py
.venv\Scripts\python.exe orchestrator.py --resume

# 查询
.venv\Scripts\python.exe orchestrator.py --status      # 模式库状态
.venv\Scripts\python.exe orchestrator.py --history     # 运行历史
.venv\Scripts\python.exe orchestrator.py --inspect runs           # 日志列表
.venv\Scripts\python.exe orchestrator.py --inspect timeline       # 时间线
.venv\Scripts\python.exe orchestrator.py --inspect round --round 3
.venv\Scripts\python.exe orchestrator.py --trace       # 本地 HTML trace

# 审核失败 → 升级排除规则（人工审批）
.venv\Scripts\python.exe orchestrator.py --review --yes --scope combo

# 认证/回归/门禁
.venv\Scripts\python.exe -m pytest -p no:cacheprovider --no-cov -q tests/ sloth_engine/tests/ --ignore=tests/test_p0_2_rerun.py   # --ignore 防御性空操作：该文件为可选外部脚本，本仓默认不存在
.venv\Scripts\python.exe scripts/run_gate.py
```

## 6. lh 场景如何接入（基于本目录资产）

1. 用 `pilot-lh-template/make_pilot_config.py` 按本机 `runtime-root` 生成 isolate pilot 配置
   （消除旧机残留路径导致的 `ContainmentError`）。
2. `backtest-bridge/lh_bridge.py` 即 lh 真实回测的 wrapper：`--input` 读 loop 信号、
   调用 lh 运行时（core/signals/backtest）跑因果回测、`--output` 写符合契约的 JSON。
3. 配置 `task.success_criteria`（如 `trades_count>0`、`win_rate>=0.35`），`sloth-loop` 据此自主判定、沉淀经验。
4. 先 `--doctor` 过契约探针，再 `--once` 跑闭环；结果经 `--report` 输出客户可读 md。

## 7. 权威文档入口（意外情况先读这些）

| 需要 | 入口 |
|---|---|
| 完整项目介绍/架构 | `<repo_root>\docs\sloth-loop-项目介绍与规划.md` |
| 超简上手 | `<repo_root>\docs\sloth-loop-QUICKSTART.md` |
| 使用手册 | `<repo_root>\docs\sloth-loop-USAGE.md` |
| 版本变更 | `<repo_root>\docs\sloth-loop-CHANGELOG.md` |
| 路线/延后项 | `<repo_root>\docs\sloth-loop-ROADMAP.md` |
| PM 接入规范 | `docs/PM框架-接入sloth-loop-流程规范.md` |

## 8. 禁止事项

- 禁止 look-ahead bias：回测只用「决策时点之前」的数据。
- 禁止跳过预过滤：每轮必须读失败模式库排除已知失败（Orchestrator 自动做）。
- 禁止跳过结果记录：每轮结果必须写回模式库（自动；改 wrapper 时别破坏输出契约）。
- 禁止自动改 status：失败→规则升级必须人工 `--review`。
- 禁止无方法硬过滤：不得用未经验证的固定阈值一刀切。
- 禁止把 dev 副本直接用于生产 live（生产门禁未满足）。
- 禁止在仓库根目录散落临时脚本/草稿/运行产物：一次性脚本只放 `scripts/tmp/`（gitignored）且用完即删；根目录是 allowlist 制（见 §9）。


## 9. 目录纪律与临时文件治理（强制，每会话起效）

> 一次会话内创建的一次性脚本/草稿/运行产物，不得散落仓库根目录或核心代码目录。本节是 agent 行为硬约束，与 §4 编码约定、§8 禁止事项同等效力。
> 动机（root cause）：PS5.1 ConstrainedLanguage + 单命令 ~8KB 限制使内联 `python -c` 困难，agent 倾向写一次性 `.py`；若无落点规则与「用完即删」约束，残留如 `_tmp_fix_coverage.py` / `_fix_renderer.py` 会不断在根目录堆积（实证：2026-09-14 一次清理后，并发 DSH 评估任务又立刻在根目录留下 5 个 `_tmp_fix_*.py`）。

### 9.1 根目录文件 allowlist（只许这些文件在根）

| 类别 | 允许在根目录的文件 |
|---|---|
| 根目录仅留入口 | CLAUDE.md / README.md / RUNBOOK.md / ONBOARDING.md |
| 唤醒/计划锚（已归位 2026-10-14） | docs/state/WAKEUP.md · docs/state/NEXT.md · docs/state/IMPROVEMENTS.md · docs/state/WAKEUP.sloth-loop-core.md |
| 方法论长文（已归位 2026-10-14） | docs/LOOP-ESSENCE-AND-LEARNINGS.md |
| 被引用分析脚本 | (已归位 2026-09-14：fetch_articles.py→scripts/，monthly_breakdown*.py + r6c_channel_diag.py→scripts/pm-diag/) |
| 机器本地状态 | (已归位 2026-09-14：signal_driven_state.json→_data/) |
| 仓库配置 | .gitignore / pyproject.toml / requirements-dev.txt / uv.lock / .obsidian.yaml |

**根目录禁止新增任何** `_*.py` / `_*.txt`(草稿) / `_tmp_*` / `tmp_*` / `_fix_*` / `_probe_*` / `_*.bak` / 散落 `*.log` / `.coverage`。

### 9.2 目录用途矩阵

| 目录 | 用途 | 写入规则 |
|---|---|---|
| `sloth_engine/` | 核心引擎 | 仅框架开发改；量化 PM 轨只读复用，产物不写此 |
| `backtest/` | 回测运行时解析 + mock | 慎改 |
| `tests/` `sloth_engine/tests/` | 自动化测试 | 可加测试；勿丢临时脚本 |
| `projects/` | 业务场景按域/任务自包含（pm/*、loop-plugin-arch/、arch-dsh-eval/） | 产物写 `projects/<domain>/<task>/(reports\|candidates\|workspace)/`（domain=--project 首段，详见 §9.4）；任务内 `_fix_*.py` 用完即删 |
| `scripts/` | 正式工具（run_gate.py、带日期一次性工具如 `_archive_sloth_<d>.py`） | 带日期/用途命名 |
| **`scripts/tmp/`** | **唯一合法临时脚本落点（已 gitignore）** | 用完立即删；跨回合存活须升级为 `scripts/<日期用途>.py` 正式工具并登记 |
| `config/` `agent-prompts/` | 引擎配置 / prompt 资产 | 慎改 |
| `work_ooda/` | OODA 工作草稿（loop-\*/runs-\*/ 已 gitignore） | 禁止累积 `_fix*.py` |
| `docs/` | 文档入口（QUICKSTART 等） | 只放正式文档，早期快照草稿定期归档 |
| `logs/` | 运行日志（滚动，gitignored） | 旧滚动日志定期归档 |
| `_data/` | 回测默认 I/O（PROTECTED：backtest_adapter.py 默认路径）+ `evolution/` | 禁删默认 IO 文件 |
| `_archive/` | 归档历史残留（mv 不删，只读证据） | 不在此做新工作 |
| `.venv` `.git` `.idea` `.pytest_cache` `.workbuddy` `.claude` `__pycache__` | 工具/缓存 | 自动管理，勿手编 |

### 9.3 临时文件治理铁律

1. **禁止在仓库根目录创建临时/一次性脚本或草稿**。根目录是 allowlist 制。
2. **临时脚本唯一合法落点 = `scripts/tmp/`**（gitignored）。优先内联 `python -c`；必须落文件时用此目录。
3. **一次性脚本用完即删**（本回合结束前删除自己在 `scripts/tmp/` 创建者）。跨回合需存活的，升级为 `scripts/<带日期用途>.py` 正式工具并在 NEXT/RC 登记。
4. **运行产物只写 runtime.root（仓库外）**（复用 §4 铁律）；仓库内仅 `_data/`(默认 IO) + `logs/` + `projects/<domain>/<task>/(reports\|candidates\|workspace)/` 可写产物（domain 推导见 §9.4）。
5. **并发会话纪律**：多 agent/loop 并行时各自临时脚本用完自清；发现他人遗留 `_tmp_*/_fix_*` 不擅删（可能并发在用），交由定期清理轮回收到 `_archive/`。
6. **定期卫生**：重大 session 结束前可重跑 `scripts/_archive_sloth_<date>.py`（dry-run → 审查 → --apply，含 PROTECT 安全网），回收新残留。

### 9.4 项目按 domain 分组落盘约定（Fix-A 落地，2026-09-14）

**根因**：旧 `report_util.write_customer_report` 落 `projects/<task>/reports/` 踢掉 domain；`run_reporter` 硬编码 `domain=task.name`。pm/* 项目报告散落顶层 `projects/pm-<task>/reports/`，与工作区 `projects/pm/pm-<task>/` 被路径拆散（2026-09-14 实测 48 顶层壳只含 reports，pm/ 内 48 工作区无 reports）。

**修复链（已落地）**：`--project pm/pm-<task>` → `project_loader._load_project` 存 `self._project_path` → `run_state._report_context` 传 `RunReportContext.project_path` → `run_reporter.write_customer_report` 取首段作 domain → `report_util.write_customer_report` 落 `projects/<domain>/<task>/reports/<date>/REPORT.md`。`evolution_bridge.persist_candidates` 同步：候选落 `projects/<domain>/<task>/candidates/<date>/`。

**退化兜底（强制，测试守护）**：`domain == task` 或 domain 空（`--project <task>` 单段、默认 sandbox）→ 退单层 `projects/<task>/reports/`，禁重复段 `projects/<task>/<task>/`。`test_write_customer_report_no_dup_path`（demo/demo→单层、`"demo/demo" not in rel`）守护此不变量。

**历史归并（2026-09-14 已执行，mv 不删可逆）**：48 顶层 pm-* 壳的 49 个 REPORT.md（pm-exit-design 双报告）归并到 `projects/pm/<对应任务>/reports/<日期>/`，0 冲突 0 遗留，空壳保留。非 PM 族 9 个（arch/book-distill/loop 基础）未动，留各自 domain 另立轮。

**新项目接入**：`--project <domain>/<task>`（pm/arch/distill）自动按 domain 分组；单域单任务仍可 `--project <task>` 退单层。


### 9.5 PM wrapper 写出规约（治本方向，2026-09-14 实证：PM wrapper 域，非 sloth-loop engine 域）

**根因**：N 个 PM wrapper 各自硬编码 `PM_KB` 常量，指向 `projects/pm`（pm-exit-design / pm-exit-sim-and / pm-exit-swarm-verify / pm-r6-entry-filter / pm-context-distill）或 `projects/loop-plugin-arch`（pm-exit-buy-sym / pm-exit-buy-sym-4h / pm-entry-r6-counter / pm-exit-and-times），不统一。把 RC/VERDICT/RESULT 报告写到这些域根散落。实证：pm/ 根散落 63 .md + 3 .csv；loop-plugin-arch/ 散落 14 PM-*；PM 文档交叉引用密集（PM-EXIT-DESIGN-RC 被 10 文件引用、PM-LESSONS-LEARNED 被 14）。

**与 §9.4 的区分**：§9.4 = sloth_engine `report_util` 域（已单点治本，报告落 `projects/<domain>/<task>/reports/`）。§9.5 = PM `wrapper.py` 域（各 wrapper 自写 RC，散点未治本）。两者不同：engine 域已治本，wrapper 域立此规约作治本方向。

**规约（PM wrapper 写出应遵循）**：
1. RC/VERDICT/RESULT 报告写到对应 `projects/pm/<task>/reports/<日期>/`，**禁直接散落 `projects/pm/` 根或 `projects/loop-plugin-arch/` 根**。
2. `PM_KB` 常量应指向 `projects/pm/<对应task>/reports/`（task 自身），而非域根 `pm/` 或无关的 `loop-plugin-arch/`。
3. 双写（task `reports/` + runtime `OUT_ROOT/reports/`）可选，但**至少一份进 task `reports/` 子目录**。

**治本路径（PM 量化工作流，非 sloth-loop 落盘规制）**：统一改各 wrapper `PM_KB` → `projects/pm/<task>/reports/`，同步更新 PM 文档交叉引用 + WAKEUP/NEXT/RC 引用路径。属散点修复（9+ wrapper），留 PM 量化主线收口。sloth-loop 已在 engine 域（§9.4）治本，wrapper 域立此规约定方向。

**历史散落归位地图**：详见 `<KB_ROOT>/02_项目/loop/pm-landing-regulation-20260914/SCATTER2-MAP.md`（66+14 文件清点 + single-match 17 归位建议 + 全局 45 待 PM 工作流裁定 + 引用风险矩阵）。本轮**不执行移动**——66+14 文件交叉引用密集（10-14 处），盲归位断引用风险高；治本须先统一 wrapper PM_KB + 同步引用，属 PM 量化主线。

### 9.6 根目录脚本归位规约（2026-09-14 实操，补 §9.1 allowlist）

**规约**：根目录禁散落分析脚本/数据。PM 量化诊断脚本归 `scripts/pm-diag/`；通用工具归 `scripts/`；数据归 `_data/`。§9.1 allowlist 是"允许在根的最小集"，不是"容忍散落的清单"——发现散落即归位，非列为准许。

**实操（2026-09-14，5 文件归位，mv 不删可逆）**：`fetch_articles.py`→`scripts/`；`r6c_channel_diag.py`/`monthly_breakdown.py`/`monthly_breakdown_exit.py`→`scripts/pm-diag/`；`signal_driven_state.json`→`_data/`。7 处文档引用同步（§9.1 allowlist 两行标"已归位" + README 目录树 + NEXT/pm-WAKEUP/PM-R6C-DIAG/docs-README）。零代码 import → 归位低风险，测试 29 passed 不破坏。

**与 §9.4/§9.5 呼应**：§9.4（engine 域 report_util 治本）+ §9.5（wrapper 域 PM_KB 规约）+ §9.6（根目录脚本归位）= 落盘治理三域规约。未来 `run_gate` 落盘门禁应校验此三域（见 05-ARCH-SKILL-EVAL 建议）。

### 9.7 任务目录命名规约（A·a 方案落地，2026-09-14：projects/<domain>/<task>-<YYYYMMDD>-000000/）

**约定（已落地，55 个 pm 任务目录全部改名）**：域内任务目录统一 `projects/<domain>/<task>-<YYYYMMDD>-000000/`（pm 项目稳定，task 是带时间戳的子任务）。时间戳 = 该任务最新报告日期（无报告回退当日 `YYYYMMDD`），HHMMSS 用定值 `000000` 防撞。下列字段与目录名保持一致：
- 目录名：`projects/pm/<task>-<YYYYMMDD>-000000/`
- `task.name`：`<task>-<YYYYMMDD>-000000`（唯一，不再裸挂旧基础名）
- `backtest.script`：指向时间戳目录内 `wrapper.py`（机械随目录搬家，无独立时间戳语义）

**自持续（追加非覆盖）**：子任务下记录一律追加写入，新建任务自动用 `scripts/make_pm_task_config.py` 生成带时间戳目录，杜绝覆盖。

**保持不变（仓库外数据树）**：`runtime.root` / `loop.signals` 保持基础名（如 `<RUNTIME_ROOT>/pm-exit-and-times`），不随目录带时间戳——仓库外运行/信号根与仓库内代码目录解耦，改名不影响历史 runtime 快照（`<RUNTIME_ROOT>/<task-band>/runs/<run_id>`）。

**cross-ref 已同步**：14 个 wrapper 的仓库内跨任务路径引用已从旧名改到新名（pm-diff-sc / pm-with-plugins / pm-plugin-monthly-eval / pm-regime-exit 等）；其余 `<LOOP_RUNTIME_ROOT>\...` 引用是 runtime 根（保持基础名）属正确、未动。

**报告落位**：`projects/pm/<task-ts>/reports/<date>/REPORT.md`；runtime 快照 `<RUNTIME_ROOT>/<task-band>/runs/<run_id>`（runtime root 名保持基础名）。迁移映射清单（回滚用）：`scripts/rename_backup_2026-09-14/rename_manifest.tsv`（本轮改名可逆 mv，BASE2 全程未触）。


### 9.8 执行流程文档单一总账规约（2026-09-23 实操：消除“一干活就 56 个版本”）

**问题（教训）**：同一天把同一份「PM 全流程执行」文档起了 3 个版本（MASTER / ALL / DETAIL），又在知识库复制 2 份归档，最后版本杂乱、无人清理，处于“不知道哪个是最新”状态。这违反了「合并优先于新增、文件数增长是坏信号」的知识库维护原则。

**规约（强制）**：
1. **每个可复用主题（执行流程/设计/结论/RUNBOOK）只维护一份权威文档**，即“单一总账”。更新只改这一份，禁止另起带不同后缀/编号的新版本。
2. **命名用语义名 + 日期**，不用 MASTER/ALL/DETAIL/v1/v2… 这类“同主题多版本”后缀；确需区分演进时用 `YYYY-MM-DD` 日期前缀并覆盖旧版（保留 git 历史即可，不必留多份物理文件）。
3. **新增前先检索同主题**：写入前遍历关联目录，能合并就合并进已有文档；只有主题完全不重叠才新建。
4. **合并旧版本时不丢内容**：把各旧版独有章节并入总账（记录来源），再移除重复物理文件。内容必须无损（核对章节/mermaid 数/md5）。
5. **落盘两处一致**：知识库权威归档（`09_可复用流程/` 等）+ sloth-loop 工作稿，两处 md5 保持一致，禁止一处更新一处不更新造成漂移。
6. **登记**：每份总账文末注明「本文为单一权威版，后续只改本文」，并在治理总表/蒸馏登记该文档为权威锚。
7. 违反即视为“版本泛滥/未治本”，须先合并清理再继续推进。

**落地实例（2026-09-23）**：PM 全流程执行文档 -> 合并为单一权威 `PM量化全流程执行总账-2026-09-23.md`（`<KB_ROOT>/09_可复用流程/` + sloth-loop `projects/pm/` 各一份，md5 一致）；已删 5 个重复版本（MASTER/ALL/DETAIL + 知识库 2 份重复归档）。
