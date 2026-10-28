# ADR-004：版本化 SQLite Migration Gate

- 状态：Accepted for dev；live 发布为 Yellow Gate
- 日期：2026-08-23

## 决策

所有 schema 变化使用连续、不可变的 migration registry。每个版本必须有独立 `up`/`down`，checksum 同时绑定描述、fingerprint 和实际函数实现。执行前预检完整链；forward migration 必须显式指定备份；down 默认拒绝，只允许在隔离副本演练；生产回退使用已验证备份或 forward-fix。

恢复采用“备份源校验 → 恢复到临时文件 → integrity/FK/row-count/schema fingerprint 校验 → 原子替换”。不存在或空的备份直接失败。up/down 对空 checksum 和 drift 均 fail closed；禁止通过 description 重写 checksum。变更命令必须显式提供 `--allowed-root`，数据库、备份、副本和恢复目标不得越界。

## 原因

旧 `_migrate()` 在进程启动时直接 ALTER，并用当时 schema checksum 伪装 v1/v2 ledger：无法证明版本实现、无法完整回滚，也无法阻止多版本 rollback 半途落地。

## 取舍

获得可追溯、可演练、可阻断的迁移路径；代价是旧库首次升级必须经过显式命令和备份，普通运行进程不再替用户修改旧 schema。

## 验证

- `tests/test_migration_rehearsal.py`：v1→v3 up、v3→v0 down、re-apply、数据保留、checksum drift、缺失备份、restore 校验。
- `tests/test_store_migration.py`：事务、legacy 显式升级、ledger、幂等。
- `sloth_engine/migrate.py`：status、带备份 up、隔离 rehearse-down、restore。

示例（仅开发 runtime）：

```powershell
python migrate.py <LOOP_RUNTIME_ROOT>\w0-w2\db\patterns.db up --backup <LOOP_RUNTIME_ROOT>\w0-w2\db\patterns.pre-up.bak --allowed-root <LOOP_RUNTIME_ROOT>\w0-w2
python migrate.py <LOOP_RUNTIME_ROOT>\w0-w2\db\patterns.db rehearse-down --copy <LOOP_RUNTIME_ROOT>\w0-w2\db\patterns.down-rehearsal.db --target 0 --allowed-root <LOOP_RUNTIME_ROOT>\w0-w2
```

## 发布门禁

live 前必须在生产数据库副本上执行一次完整备份/升级/恢复演练，记录 RPO/RTO、行数和业务抽样；不得在 live 原地执行 down。
