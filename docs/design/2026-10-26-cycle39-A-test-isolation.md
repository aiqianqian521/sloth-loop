# cycle-39 A/A2 · 测试观察的必须是被测系统，而不是它碰巧运行的那台机器

- 日期：2026-10-26
- 来源：cycle-38「新鲜副本（handoff）验证」登记的两条候选（当时只登记未修）
- 提交：cycle-39 A `9f2d5f3`（+3 用例）／ A2 `142fb5d`（同族补齐 5 个写入点）／ B（architect-skills）`f50b574` TES-34 + DOC-25

## 1. 取证方式（先驱动，再结论）

1. 静态：`tests/test_v2_p1p2.py:15` 是模块级 `store = PatternStore(_ENGINE / "data" / "patterns.db")` —— 在 **import（收集）期**就打开仓库运行态库。
2. 复现 A（写仓库）：在 `git clone` 出的空副本里跑 `pytest --collect-only tests/test_v2_p1p2.py` —— **不运行任何用例**，代码树里就出现约 110KB 的 `sloth_engine/data/patterns.db`。
3. 复现 B（旧库打断整套会话）：把一份 v5（旧 schema）库放到 `sloth_engine/data/patterns.db` 再跑全量 —— pytest 在**收集期**整体失败：`RuntimeError: database migration required: v5 -> v6`，输出 `no tests collected, 1 error`。一个模块的本地状态问题被升级成「整轮没有测试」。
4. 复现 C（还有谁）：逐文件扫描（每个测试文件单独跑一次、跑完检查仓库内 db 是否存在）—— 修复前有 5 个文件 `CREATES-DB`。
5. 反例 D（门禁消息）：cycle-38 登记 —— `run_gate.py` 通过行打印 `coverage 79.35% >= 79.47%`，而判定实际含 `COVERAGE_TOLERANCE = 0.15`：判定通过、消息字面为假。

| 事实 | 修复前 | 修复后 |
|---|---|---|
| 测试输入 | 机器上既有的 `sloth_engine/data/patterns.db` 内容 | 私有临时库 + 确定性种子（2 failure / 1 success / 1 round / 1 run_history） |
| 收集期副作用 | 打开 / 创建仓库内 DB（约 110KB 写进代码树） | 无（导入只建临时库） |
| 旧 schema 库在树里 | 整套 pytest 收集期 ERROR | 全量照常（1759 passed / 79.48%） |
| 写入点数量 | 6（`test_v2_p1p2` + 5） | 0（逐文件扫描实测） |
| 门禁通过行 | `coverage X% >= recorded`（容差未显性，可字面为假） | `coverage X% >= floor Y% [recorded Z%, slack S%]`（与判定同一表达式取反） |

## 2. 病根：测试观察的是「机器」而不是「被测系统」

- 运行态产物（数据库 / 缓存 / 状态文件）**不是测试输入**：测试读它，结论就随机器漂移（cycle-38 已实测到本机 79.47% vs 全新副本 79.35% 的 0.12pp 耦合）。
- 写在**收集期**的副作用尤其坏：它把一个模块的本地状态问题升级为**整个会话**的 error —— 不是「一个用例失败」，而是「没有用例被收集」。
- 门禁同理：**判定与消息必须同源**。手工复述阈值，就会在容差内出现「判定通过、消息自相矛盾」。

## 3. 修复

- **A（`9f2d5f3`）**：`test_v2_p1p2.py` 的 store 改为 `tempfile.mkdtemp()` 下的私有库 + `_seed_store()` 确定性种子；新增 `test_store_is_isolated_from_the_repo_tree`（断言 `store.db_path` 不在仓库树内）；`run_gate.py` 抽出 `coverage_floor(recorded, tolerance) = recorded - tolerance` 作唯一定义，`baseline_violations` 判 `measured < floor`，通过行打印 `coverage X% >= floor Y% [recorded Z%, slack S%]`，失败行同口径；+2 例（临界通过路径为真 + `recorded - floor == slack`；失败行含 floor / slack）。
- **A2（`142fb5d`）**：逐文件扫描出的 5 个写入点全部切到私有临时库 / 临时配置 —— `test_webui_auth_config.py`（改为断言解析出的默认路径，与 `_store()` 同一表达式）、`test_webui_static.py`（autouse fixture 把 webui 数据目录指到 `tmp_path`）、`test_contract_invariants.py`、`test_evolution_bridge.py`（`_isolated_cfg()`：只把 `memory.sqlite_path` 指到 tmp，保持 containment 语义）、`test_loop.py`（CLI 冒烟传一份 `sqlite_path` 指向临时目录的配置副本）。
- **B（`f50b574`）**：`architect-test` 33→34（TES-34）、`architect-docs` 24→25（DOC-25）。

## 4. 证据（新鲜副本 handoff 场景，两场景实测）

```
# 场景① 空库（全新克隆）
pytest tests sloth_engine/tests -q   ->  1759 passed, 1 warning; coverage 79.48%
git status                          ->  仅本轮预期改动；sloth_engine/data/ 无 patterns.db

# 场景② 预置 v5 旧库（修复前该场景 = no tests collected, 1 error）
<copy v5 db to sloth_engine/data/patterns.db>
pytest tests sloth_engine/tests -q   ->  1759 passed; coverage 79.48%
ledger max(version) after run       ->  5（旧库未被改写）
```

本仓库全量同为 1759 passed / 79.48% —— 基线从「与本机 DB 内容耦合」变为**确定性**。

## 5. 诚实作用域

- 只覆盖 `sloth_engine/data/patterns.db` 这一个耦合点；仓库根 `_data/` / `work_ooda/` / `logs/` 等 gitignore 运行态目录仍会被测试创建（历史行为，另一族）。
- 门禁仍是本地软约束（`--no-verify` / `core.hooksPath` 可绕过）—— 强制由 cycle-37 的 pre-receive 服务端门禁承担。
- `COVERAGE_TOLERANCE = 0.15` 保留（本轮只统一口径，未收紧策略）。
