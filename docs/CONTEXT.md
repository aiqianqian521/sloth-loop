# Loop 领域术语表

| 术语 | 唯一定义 | 不要混淆 |
|---|---|---|
| Task | 一次完整的任务编排生命周期，可能包含多个 Run | 不等于 Round |
| Run | 一次可恢复的连续执行实例，有唯一 `run_id` | 不等于单个进程 |
| Round | Run 中的一次 OODA 迭代 | 不等于 Step |
| Step | Round 中的 Understand/Observe/Orient/Decide/Act/Verify/Learn 之一 | 不等于事件日志行 |
| Signal | 进入 TaskRunner 的候选输入 | 不等于 Pattern |
| Pattern | Learn 产生的失败或成功经验记录 | 不等于主动生效的 Rule |
| Rule | 经过人工审批后用于排除或约束的规则 | 不等于原始 Pattern |
| Checkpoint | 用于恢复控制状态的最新快照 | 不等于事实 Event |
| Event | 已发生事实的追加记录，不覆盖、不回写 | 不等于可修改的状态 |
| Artifact | Task 产生的文件或结构化输出 | 不等于日志 |
| Verifier | 判断 execution/output/business 是否满足契约的端口 | 不等于 TaskRunner |
| **implicit_criteria** | 空 `success_criteria` 被调度器推导出的隐式判据（非人工写入） | 不等于显式声明的 success_criteria |
| **CorruptDatabaseError** | memory_store 打开损坏 SQLite 时抛出的可诊断 fail-closed 错误 | 不等于静默降级为空 DB |
| **schema_validate** | 输入 schema 强校验开关，默认 true（fail-closed），`=false` 可退 | 不等于默认放行 |

## 命名铁律

- 用 `run_id` 指代可恢复执行实例；不要用 `task_id` 代替。
- 用 `round` 指代 OODA 轮次；不要用 `event` 或 `step` 代替。
- Pattern 默认是证据，Rule 默认是审批后的控制；禁止把 Learn 结果直接当 Rule。
- EventLog 是事实源；Checkpoint 是控制源；PatternStore 是经验物化视图。

## 引用路径约定（为什么有些路径在本仓不存在）

本仓是 sloth-loop 的精简/脱敏后继仓；文档中出现的下列路径**有意不在本仓**，属设计而非断链。全量离线链接审计（`docs/` 引用扫描，2026-10-21）命中的 76 条缺失引用均落在此表内，统一判为**非缺陷**。

| 类别 | 路径样例 | 说明 |
|---|---|---|
| 私有/脱敏目录 | `docs/state/`、`docs/PM框架-接入sloth-loop-流程规范.md`、`docs/research/`、`docs/iteration-tracker/`、`docs/knowledge-distillation/` | 内部开发上下文/私有笔记，`.gitignore` 排除；打包排除见 `docs/RELEASE.md` |
| 任务运行工作区 | `projects/*`（含 `projects/pm/*`、`projects/demo-backtest/*`；保留 `projects/pm/_template/`） | 运行产物/私有任务，`.gitignore` 排除 |
| 上游原始仓库布局 | `scripts/pm-diag/`、`scripts/make_pilot_config.py`、`scripts/make_pm_task_config.py`、`tests/test_basic.py`、`tests/test_addition.py`、`backtest/my_script.py` | 属原仓/私有工作区；本仓 `scripts/` 仅保留 5 个正式工具，文档中的这些名字是命令示例或历史布局 |
| 历史快照文档 | `docs/GRAND-LOOP.md`（现于 `docs/flow/`）、`docs/self-evolving-assessment-2026-09-02.md`、`docs/evolution-tier1-implemented-2026-09-02.md`、`docs/sloth-loop-P2-拆解-2026-09-03.md` | 已迁移或为历史快照；旧路径保留属有意（整改登记 DOC-5 已 ACCEPTED） |
| 可选外部脚本 | `tests/test_p0_2_rerun.py` | 主机专属，本仓默认不存在；命令里的 `--ignore=` 为防御性空操作 |

> 判据：**当前态文档只保证「入口 / 契约 / 基线」三类引用可达**；上表路径属私有、历史或外部，不参与可达性门禁。
