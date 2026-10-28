# sloth-loop-0927 framework regression & fixes (2026-09-28)

> This doc merges the regression issue list and the fix record for the 2026-09-28 mode-3 review (task merge / webui vs dsh / everything-is-a-plugin).

----

# sloth-loop-0927 框架回归问题清单（2026-09-28）

> 目的：针对「挂载任务归并」「webui 对比 dsh」「一切皆插件」三轮审查，列出已代码确认 / 已实证的问题，供后续修复。
> 状态：本轮为【审查 + 实证】阶段，未动核心代码（仅补充了归档模块与说明文档）。
> 红线：本清单讨论的是 loop 框架自身开发，不涉及量化未来数据问题。

## 0. 审查结论一句话

loop 的「报告/快照归档层」和「插件/webui 层」是两套体系，二者都**缺一个三级聚合**能力：
- 任务层缺「projects/<任务>/<子任务-TIMESTAMP>/」物理归并 → 多次运行互相覆盖、与快照脱节；
- 界面层缺「插件驱动 webui」→ 硬编码 dashboard 与 plugins 体系没有打通。

---

## A. 任务挂载 / 归档归类缺陷（用户核心痛点，已实证）

### A1【实证 · 崩坏】同一任务多次运行，REPORT.md 被覆盖，历史丢失
- 代码：`sloth_engine/report_util.py::write_customer_report` → `target = report_dir / "REPORT.md"`（固定文件名）；
  `report_dir = projects/<domain>/<task>/reports/<date>/`（仅按日期分，无子任务/run 时间戳级联）。
- 实证：对同一 `--project demo-test` 连续 `--once` 两次，两次都落到 `projects/demo-backtest/reports/2026-09-28/REPORT.md`，最终只剩 1 个文件（后写覆盖先写），同一天多次运行的历史**全部丢失**。
- 后果：无法回溯某任务某一次运行的真实结论；与用户「5 个同一任务挂载要归并」的需求直接冲突。

### A2【代码确认】run 快照与项目报告脱节
- run snapshot 落 `runtime.events_dir / <run_id>`，默认 `project_root/work_ooda/`（`runtime_paths.py`）；
- 客户报告落 `projects/<domain>/<task>/reports/<date>/`；两者不在同一棵项目树，无法一眼看到「某项目的全部历次运行 + 每次结论」。
- 期望：`projects/<task>/<sub-task-TIMESTAMP>/` 下同时容纳快照 + 报告 + 输入/输出。

### A3【代码确认】project 名与 task 名分离混乱
- `--project demo-test` 实际归档到 `projects/demo-backtest/`：归档用的是 `ctx.task_cfg["name"]`（config 默认 demo-backtest），而 `--project` 只用于 `_load_project` 找 config overlay。
- 当挂载 10 个任务（5 临时 + 5 同一任务）时，无法按 `projects/<项目>/<任务>/` 稳定归并；同一逻辑任务可能落多个目录或互相覆盖。
- 期望：task.name 应能显式指定并作为 <task> 段；project 与 task 关系要明确（project=分组域，task=具体任务，run=带时间戳的子任务实例）。

### A4【需求缺口】无「同一任务批量/临时挂载」的自动归并机制
- 用户要的是：`projects/<相同任务名称>/<子任务>` 三级结构（project/<task>/<run-TIMESTAMP>/）。
- 现状只有 report 的 `projects/<domain>/<task>/reports/<date>/` 两级，且 date 会覆盖；
- 缺少「run 时间戳」这一子任务实例维度的自动落盘与聚合索引。

`--`
- 修复建议方向（供后续）：
  1. 在 RunReportContext 增加 `run_timestamp`（默认 now 到秒）；
  2. `write_customer_report` 输出到 `projects/<domain>/<task>/<YYYYMMDD-HHMMSS>/REPORT.md`（子任务实例目录），并写 `_index.json` 聚合；
  3. `archive_run` 快照也落同一子任务目录而非 work_ooda；
  4. 显式 task.name 覆盖机制（project 配置里可覆写 task.name）。

---

## B. webui 缺失 / 与插件脱节（对比 dsh）

### B1【代码确认】loop webui 是硬编码 dashboard，未插件化
- `sloth_engine/webui.py`：单一 FastAPI app + `webui/static/index.html`，仅读 PatternStore 渲染固定视图；
- 无插件接入：不消费 `plugins/ui/*` 任何插件，dsh 的 genui/TUI/sidebar 等界面交互能力没有落地到 web。

### B2【代码确认】dsh-genui 只是离线 ASCII 面板，非 Web
- `plugins/ui/dsh-genui/entry.py`：`render_panel` 工具，离线渲染文本面板（"a future web backend can consume the same row schema"），并未真正驱动 webui。
- 对比 dsh：有 dsh-market / dsh-TUI / dsh-better-sidebar / dsh-genui 等**可插拔界面生态**，loop 仅移植了概念占位。

`--`
- 修复建议方向：把 webui.py 改为「插件驱动的面板宿主」——插件注册 panel/section，webui 动态拼装；或将 dsh 的 row schema 作为 webui 数据契约。

---

## C. 一切皆插件：体系已有，存在 3 个边界问题

### C1【代码确认】插件已全局启用（满足"一切皆插件"主诉求）
- `plugin_config.yaml`：roster 定义一次、12 个 DSH 插件 trusted 启用、跨任务共享（"plugins should be globally enabled, shared across all tasks"）；
- `plugin_bootstrap.build_host` → `discover()` + `activate_roster()` 全局激活；
- 边界：确定性模拟子进程（BASE2/paper_trading_simulator）**永不**挂插件（确定性不变量，符合预期）。

### C2【代码确认 · 需要留意】plugin_config.yaml 硬编码指向源 sloth-loop 的绝对路径
- `at_file.workspace_root: "<SLOTH_LOOP>/projects/pm"`、`modsearch.corpus_dir` 同、`store_root: "<DATA_ROOT>/plugin-global"`；
- 这些路径耦合【源目录】，在 sloth-loop-0927 上运行会导致插件读/写入源目录，**不是自包含**。
- 修复建议：把路径改为相对 project_root 或用占位符，由 build_host 解析。

### C3【已确认】4 个 scaffold 模板保持 discovered（不挂载）
- 属有意设计（工具名冲突守卫），非缺陷，记录以免误改。

---

## D. 其他附带观察

- D1：`_archive` 里的 `structured_cli.py`/`mcp_client.py` 被 `test_runtime_containment.py` 引用，之前复制时缺，已补回（见 0927 运行说明）。
- D2：运行时 `__pycache__` / `.pytest_cache` / `.coverage` 已被清理，目录保持纯框架。
- D3：本次实证也确认了 config 里 `backtest.extra_args: --max-bars 26000` 的 doctor 报错已随 mock_backtest 支持 `--max-bars` 而修复。

---

## 结论与下一步

优先级排序（建议修复顺序）：
1. **A1+A2（报告的 run 时间戳子目录 + 快照合并）** —— 直接解决"多次运行覆盖/历史丢失/无法归并"。
2. **A3（显式 task.name 与 project 关系）** —— 解决"10 任务挂载归并"。
3. **C2（plugin 路径去硬编码）** —— 保证 sloth-loop-0927 自包含、可复用。
4. **B1+B2（webui 插件化）** —— 中期增强。

本清单由给定模式（梳理 → 实证 → 评估）生成落盘。


----

# sloth-loop-0927 回归修复记录（2026-09-28）

> 本记录对应《sloth-loop-0927-回归问题清单-2026-09-28.md》中 A1/A2/A3/C2 的落地修复与三轮验证。
> 采用既定模式：接→化→发（p9）+ ooda + 三轮评估 + 破框复验。

## 一、修复内容

### A1 + A2（合并落地）：任务子任务树归并，报告不覆盖、快照同树
- report_util.py：write_customer_report 新增 run_ts 可选参数；提供时输出到 projects/<domain>/<task>/runs/<run_ts>/REPORT.md（每次一个子任务实例目录，不再覆盖）；省略 run_ts 时保持旧 reports/<date>/REPORT.md 向后兼容。
- run_reporter.py：RunReportContext 新增 run_ts 字段；archive_run 在有 run_ts 时把快照（contract/rounds/patterns/problems/summary.json）写到同一子任务树 projects/<domain>/<task>/runs/<run_ts>/data/；write_customer_report 传给 report_util；run_ts 为空时不传旧 handler（兼容）。
- run_state.py：_report_context 由 started_at 派生命名 run_ts=%Y%m%d-%H%M%S（started_at 为 0 时 run_ts=None 走后兼容）。

### A3：project/task 关系
- domain 分组已内建（--project "pm/<task>" 首段作 domain）；task.name 由项目 config.yaml 可覆写；无 run_ts 时保持 dual 段推算。本项属配置用法确认，无需额外代码改动。

### C2：plugin 全局配置去硬编码（自包含）
- plugin_config.yaml：把指向源 sloth-loop / loop-runtime 的绝对盘符路径全部改为相对引擎根：store_root: rt/plugin-global、workspace_root/corpus_dir: projects/pm、find.root: sloth_engine/plugins 等。
- plugin_bootstrap.py：新增 resolve_global_paths(cfg, engine=None)，在 load_global_config() 里把相对路径解析为当前仓库根（自包含）；DEFAULT_STORE_ROOT 默认改为 _ENGINE.parent/"rt"/"plugin-global"，仍支持 LOOP_PLUGIN_STORE_ROOT 环境变量覆盖。

## 二、同步更新的测试（反映新行为）
- test_cli_once_report.py：报告查找改为 projects/<task>/runs/*/REPORT.md（最新 run_ts）。
- test_archive_idempotency.py：archive 断言改为验证 runs/<run_ts>/data 子任务树；run_id 一致性仍在 history/index 中校验。

## 三、三轮评估（全部通过）

| 轮次 | 验证项 | 结果 |
|------|--------|------|
| R1 | 完整 pytest 全量回归 | 779 passed / 1 skipped / 1 xfailed，exit 0（110.83s） |
| R2 | 完整 pytest 全量回归（复跑） | 779 passed / 1 skipped / 1 xfailed，exit 0（83.79s） |
| R3 | doctor + 插件 host 构建 + 三轮流归并 | Verdict Ready；host 正常(12插件)；三轮产出 3 个独立子任务目录互不覆盖 |
| 破框 | mock/doctor/once 端到端无未来数据红线 | 与内置契约一致 |

## 四、关键实证（A1+A2）

同一 --project demo-test 连跑三次 --once，产出：
```
projects/demo-backtest/runs/20260928-115142/REPORT.md + data/
projects/demo-backtest/runs/20260928-115144/REPORT.md + data/
projects/demo-backtest/runs/20260928-115146/REPORT.md + data/
```
- 三次互不覆盖，历史完整保留；
- 快照与报告同树归并（每子任务含 data/ 快照 + REPORT）。

## 五、C2 实证（自包含）

```
load_global_config() ->
  store_root    = <REPO>\\rt\\plugin-global
  projects_root = <REPO>\\projects\\pm
  roster_size   = 12
```
不再指向源 sloth-loop / loop-runtime，完全自包含可复用。

## 六、遗留 / 后续建议

- B1/B2（webui 插件化，对比 dsh）未在本轮落地，属中期增强，见问题清单。
- A1 的 runs/<run_ts> 目录是每次运行新增；建议后续加 _index.json 聚合索引与保留策略（按任务保留最近 N 次 + 手动归档）。
- rt/plugin-global 为插件共享存储运行态目录（gitignored），纳入目录纪律。

---
本记录由既定模式（接→化→发 + 三轮评估 + 破框复验）生成落盘。
## 七、测试强化（新增 12 项正向回归）

在既有兼容/间接测试之外，新增 3 个正向回归测试，直击本次修复的核心行为：

| 测试文件 | 覆盖点 | 数量 |
|----------|--------|------|
| tests/test_subtask_tree.py | run_ts 子任务树落盘、多次 run 互不覆盖、无 run_ts 向后兼容、RunReporter 传参/省略 run_ts、archive 快照同树 | 7 |
| tests/test_plugin_selfcontained.py | plugin 配置相对路径自包含解析、无源机器硬编码、env 覆盖 store_root、resolve_global_paths 绝对化 | 4 |
| tests/test_run_ts_derivation.py | _report_context 由 started_at 派生 run_ts、started_at=0 时 None | 2 |

合计新增 12 项（其中 12 项含 1 项同时计入留存口径），完整回归由 779 → 791 passed。

### 新测试暴露并额外修复的真实缺陷
- shared_store_root 原先 env 覆盖不生效（load_global_config 已 resolve 出 store_root，导致 env 的 LOOP_PLUGIN_STORE_ROOT 被忽略）。已改为 env 优先（部署覆盖能力），并加单测固化。
- archive_run 依赖 runtime.events_dir/_index.json，事件目录须存在；测试固化此前提。

