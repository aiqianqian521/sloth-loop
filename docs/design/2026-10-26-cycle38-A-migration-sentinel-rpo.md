# cycle-38 A · 由被观测方声明的「事实」不是事实：业务提交哨兵与时间点 RPO

- 日期：2026-10-26
- 来源：ROADMAP P0「migration sentinel RPO」（其依赖 fail-closed CI 已于 cycle-37 交付）；镜头从「控制能不能被关掉」转到「证据到底由谁产生、能不能绕过事实」
- 提交：cycle-38 A `529ec97`（+6 用例）／ B（architect-skills）`fbe1f91` TES-33 + DOC-24

## 1. 取证方式（先驱动，再结论）

1. 静态：`scripts/migration_rehearsal.py` 的 `rpo` 是 `mode="row_count_proxy"` / `verified=false`，字段 `last_committed` 只是 `_row_count(source_snapshot)` 求和。
2. 反例（它答不出的问题）：行数一致**并不**意味着「恢复到某个已提交业务单元」——同一行数可以由「删一行 + 加一行」得到；它把「计数相等」当成了「时间点可达」。
3. 设计约束（决定实现形态）：恢复点标记若由业务代码在写完业务行之后补写，那么「忘了补写」「补写前崩溃」「另一条写入路径不补写」都会让标记比事实更乐观。

| 事实 | 修复前 | 修复后 |
|---|---|---|
| 标记的生产者 | 应用（`_row_count` 求和推导） | 数据库（SQLite 触发器，随业务行写入） |
| 原子性 | 无（派生量） | 与业务写入**同一事务**；回滚不留标记 |
| 时间语义 | 无（行数） | `committed_at`（UTC ISO-8601 毫秒、字典序可排）+ `seq` 同毫秒消歧 |
| 历史数据 | 无 | 引入时**恰好回填一次**（水印 = 迁移时刻「确认已提交」） |
| 演练输出 | `row_count_proxy` / `verified=false` | `sentinel_timestamp` / `verified=true` + `restores_to_cutoff` / `units_lost_on_restore` / `window_ms` |
| 缺失时行为 | 静默返回行数 | fail-closed（拒绝出具 evidence） |

## 2. 病根：「声明」被当成「事实」

- 证据的价值取决于**它由哪一层产生**：应用自己写下的标记是**承诺**；只有当业务写入与标记由同一原子操作产生时，它才是**事实**。
- **代理指标 ≠ 语义指标**：「行数相等」是代理，读者要的是「恢复到哪一刻」；把代理当语义上报，等价于用更弱的条件宣称更强的结论。
- 这是 cycle-32~37 的同族延伸：那几轮问「判定宽窄」「缺省往哪走」「谁有权关掉控制」，本轮问「**这条证据是谁造的、它能不能绕过事实**」。

## 3. 修复

- **schema v6**（`sloth_engine/migrations/v006_commit_sentinel.py`）：`commit_sentinel(seq, scope, committed_at)`（append-only）+ 在 `rounds` / `run_learns` / `failure_patterns` / `success_patterns` / `l2_suggestions` 的 INSERT/UPDATE 上建触发器。触发器由数据库执行 → **任何写入路径都绕不过**，回滚的业务写入不留标记。`down` 只丢弃标记表与触发器，重新 `apply` 会重建并**恰好回填一次**。
- **演练**（`scripts/migration_rehearsal.py`）：在隔离副本上记录 backup cutoff 水印 → 用 `PatternStore` 真实提交 M 笔业务行 → 从 cutoff 备份恢复 → 断言恢复副本的哨兵**恰好等于** cutoff；输出 `units_after_cutoff` / `units_lost_on_restore` / `window_ms` / `restores_to_cutoff`；哨兵表缺失即 `RuntimeError`（fail-closed）。`rpo_last_committed` 保留为行数兼容字段。
- **自证**（`tests/test_commit_sentinel.py` 5 例 + `tests/test_migration_rehearsal_cli.py` 1 例）：业务写入产生分域哨兵 / **回滚不留哨兵** / `down` 丢弃且 `apply` 重建 / 历史行**恰好回填一次** / 哨兵缺失即失败关闭；CLI 断言 `mode`、`verified`、`restored_last_committed <= backup_cutoff`、`units_lost == units_after`。

## 4. 真实库证据（同一轮，非模拟）

本机真实 `sloth_engine/data/patterns.db` 仍停在 v5，测试集合期被 `PatternStore` fail-closed 拒绝 → 用仓库自带的显式迁移门禁迁移：

```
.venv\Scripts\python.exe migrate.py sloth_engine\data\patterns.db up \
  --backup _data\migration-backup\patterns.db.pre-v6-20261026.bak \
  --allowed-root <repo_root>
# applied [6]; integrity ok; foreign_key_errors 0; commit_sentinel = 131 行
```

131 = 10 failure_patterns + 8 success_patterns + 61 rounds + 52 run_learns —— 回填口径与业务行数一一对应。

## 5. 信任边界与诚实作用域

- 这是**隔离副本上的演练**：证明的是「按记录的 cutoff 恢复会精确落回该 cutoff」，**不是**生产停写窗口实测；生产 RTO/RPO 仍需按 runbook 在停写窗口复核。
- 历史行的 `committed_at` 是**迁移时刻**（水印 = 「确认已提交」），不是真实提交瞬时时间——刻意写清，避免被读成「历史行在那一刻提交」。
- 哨兵不覆盖 `schema_versions` 迁移账本本身（它有自己的 checksum + integrity 校验）。

## 6. B 轮口径（architect-skills）

TES-33 / DOC-24：**由被观测方自己声明的事实是承诺不是事实**——标记必须由承载事实的那一层在同一原子操作内产生（触发器 / 约束 / 同事务），任何应用写入路径都绕不过；代理指标不得冒充语义指标；历史回填必须恰好一次且可重放重建；自证必须含「业务写入回滚后标记不存在」与「标记缺失 fail-closed」。文档侧：不得把代理指标写成语义指标，必须写明生产者与原子性口径、历史回填口径、作用域（演练 / 生产实测）与未覆盖范围。

## 7. 验收

- `pytest tests sloth_engine/tests -q` → 1756 passed / 0 xfailed / **79.47%**（+6 例）
- `scripts/run_gate.py --all` → PASS；`docs_baseline.check() == []`；`scripts/audit_cross_repo_ledger.py` → unexplained 0 / exit 0
- B 侧：`node scripts/validate-contracts.mjs` → 19 atom / 0 错 / 0 警；`node tests/run-l1-tests.mjs` → 32 passed

## 8. 同轮登记（未改的候选）

- `tests/test_v2_p1p2.py` 在**收集期**就打开仓库内 `sloth_engine/data/patterns.db`（git 忽略的本地库）：fresh clone 会在仓库里创建 DB，旧版本库则让整套测试 fail-closed。属「测试卫生 / 隔离」同族，本轮只登记不修（改动面涉该文件 75 个用例与 `_ENGINE/data` 的报告落点）。

## 9. 冻结项（不动）

N-3 / R3（仅文档登记）；coze I-1/I-3/I-4、cycle-12 条目 11/12/13（candidate-pending）；WebUI / 每项目文件沙箱 / P2 OS 沙箱（不做）；`guardian/risk_assessor.py::llm_review()`（不做）；REST API + Webhook / W2-BOUNDARY-01（等第 2 个真实多模块任务）。
