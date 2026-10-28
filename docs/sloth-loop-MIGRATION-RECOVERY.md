# 迁移与恢复演练（Migration & Recovery Rehearsal）

> 演练 SQLite 模式库的 **备份 → 前向迁移 → 回滚复制 → 恢复校验** 流程，
> 全部破坏性 down 操作在隔离副本上执行，**source DB 绝不原地迁移**。
> 目的：在 dev 阶段提前演练崩溃/断电后的恢复路径，验证 RTO/RPO。

## 一、为什么需要

Loop 的模式库（`patterns.db`）是「经验物化视图」，采用不可变迁移（schema ledger v001–v006）。
v006 起增加**业务提交哨兵** `commit_sentinel`：恢复点由业务写入的事实（触发器同事务写入）产生，不由计数推导。
任何版本迁移如果失败，都不能污染既有经验。恢复路径必须先经过隔离演练，
否则不能在宕机时干净恢复。

## 二、演练脚本

`scripts/migration_rehearsal.py` 依赖 `sloth_engine/migrations` 的 `MigrationRunner`
（已有 checksum、事务、snapshot、integrity、restore_copy）。

```bash
# 完整演练：backup → down/up → restore → evidence JSON
python scripts/migration_rehearsal.py \
  --database <DATA_ROOT>/<project>/db/patterns.db \
  --work-dir  <DATA_ROOT>/rehearsal-work

# 只看恢复：用已验证的 backup 做 restore-only
python scripts/migration_rehearsal.py \
  --database <DATA_ROOT>/<project>/db/patterns.db \
  --work-dir  <DATA_ROOT>/rehearsal-work \
  --backup   <DATA_ROOT>/rehearsal-work/<backup>.db \
  --restore-only

# 机器可读 JSON（CI / 校验用）
python scripts/migration_rehearsal.py --database ... --work-dir ... --json
```

约束：
- `--work-dir` 必须是隔离目录，不能是 source DB 所在目录或 `.db` 文件。
- `--restore-only` 必须给 `--backup`；backup 旁路 `backup.sha256` 需与 backup SHA-256 一致，
  损坏 backup 会非零退出。

## 三、通过条件（evidence 校验）

| 条目 | 要求 |
|---|---|
| `status` | `ok` |
| backup SHA-256 | 与 sidecar `.sha256` 一致 |
| `before_version < after_version` | 迁移确实前向推进 |
| restore integrity | `ok` 且 `foreign_key_errors == 0` |
| `evidence_path` | 可读 |
| `rto_ms` | `>= 0`（实测恢复耗时） |
| `rpo.mode` | `sentinel_timestamp`（业务时间点口径，不再是行数代理） |
| `rpo.verified` | `true`（哨兵缺失即演练失败，fail-closed） |
| `rpo.restores_to_cutoff` | `true`（恢复副本的哨兵恰好等于 backup cutoff） |
| `rpo.units_after_cutoff` / `rpo.units_lost_on_restore` | 两者相等且 `>= 1`（cutoff 之后提交的业务单元，正好是恢复会丢的那批） |

测试覆盖：`tests/test_migration_rehearsal.py`、`tests/test_migration_rehearsal_cli.py`、
`tests/test_store_migration.py`（11 passed）。

## 四、当前局限（已知）

- **RPO 已是业务时间点**（`rpo.mode = "sentinel_timestamp"`、`verified=true`）：schema v6 的 `commit_sentinel(seq, scope, committed_at)` 由 SQLite 触发器在业务表 INSERT/UPDATE 时**同事务**写入 —— 标记由数据库产生，任何应用写入路径都绕不过，业务写入回滚后不留标记；演练在隔离副本上记录 backup cutoff、真实提交 M 笔业务行，再从 cutoff 备份恢复并断言哨兵**恰好等于** cutoff。哨兵缺失 / 不可读即 fail-closed（拒绝出具 evidence）。
- **历史行的时间点口径**：引入哨兵时对既有行**恰好回填一次**（水印 = 迁移时刻「确认已提交」）。历史行没有真实提交瞬时时间 —— 这是刻意的诚实口径，不要读成「历史行在那一刻提交」。
- **restore 覆盖语义**由调用方负责：脚本只使用 fresh artifact；生产恢复前仍需
  quiesce（停写窗口）与 runbook。
- 尚未在生产停写窗口实测 restore，不能宣称生产 RTO/RPO。

## 五、测试命令

```bash
.venv\Scripts\python.exe -m pytest -q tests/test_migration_rehearsal.py \
  tests/test_migration_rehearsal_cli.py tests/test_store_migration.py tests/test_commit_sentinel.py
```

## 六、下一步（若需推进到生产）

1. ~~用真实业务 sentinel（id/committed_at）替换 row-count proxy，记录备份 cutoff 与恢复后的最后提交点。~~ ✅ 已完成（cycle-38 A：v6 `commit_sentinel` 由触发器同事务写入；演练给出业务时间点 RPO）。
2. 在隔离 staging 做 WAL checkpoint、停写窗口、原子替换的恢复演练。
3. 把 evidence 校验接入 CI（在 fail-closed CI 落地后）。
