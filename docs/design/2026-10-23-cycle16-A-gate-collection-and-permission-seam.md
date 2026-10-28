# cycle-16 A/C：失效的权限门 + 6 个"伪测试"不在门禁内（A 修复 + C 19 维增量复评 + 用户裁定登记）（2026-10-23）

> 起点：代码 head `797f1f5`（基线 1485 passed / 1 xfailed / 76.11%）。本文件记录 step A 的三个缺陷定位与修复、
> step C 的 19 维增量复评，以及 **2026-10-23 用户裁定**的登记。代码提交 `a09421a`；基线刷新为 **1542 / 77.58**。
> （文件名沿用 architect-skills `ARCHITECTURE-COVERAGE.md §5` cycle-16 条的引用。）

---

## ① 三个缺陷（同一类："看起来有、实际不生效"）

1. **权限门调用点漂移（P0 级）**：`sloth_engine/tool_registry.py::dispatch` 调用
   `self._permission_gate.check(tool.name, tool.source)`，但 `PermissionGate` 只提供
   `check_tool_call(tool_name, tool_args, *, level=None)` —— `.check` 早已不存在。
   后果：**任何** `set_permission()` 之后的 `dispatch()` 必抛 `AttributeError`，7 级权限门（P3-A3）形同虚设。
   该分支此前**无任何测试**（模块覆盖率 65%），故长期隐藏。
   *反向样本（修复前实测）*：
   ```
   r.set_permission(PermissionLevel.DEFAULT); r.dispatch("write_file")
   -> AttributeError: 'PermissionGate' object has no attribute 'check'
   ```
   同一接缝的另一处调用（`tool_pipeline.py` step 8）用的是**正确**的 `check_tool_call(name, params)` 且有测试
   —— 典型"一处有测试、另一处静默漂移"。

2. **6 个"伪测试"不在门禁内（约 630 行断言从不执行）**：`tests/test_execution_contracts.py`、
   `test_orchestrator_boundaries.py`、`test_result_contract.py`、`test_result_contract_failure_matrix.py`、
   `test_w0_isolation.py`、`test_wave3_boundaries.py` 全是**脚本式**（`def main(): ...` + `if __name__ == '__main__'`，
   零个顶层 `def test_*` / `class Test*`）。pytest 对它们报 `no tests ran`，`run_gate.py` 从未执行过其中断言。
   *反向样本（补齐前实测）*：`pytest tests/test_execution_contracts.py -q` → `no tests ran in 2.15s`。

3. **零覆盖的 EXEMPT 参考实现**：`sloth_engine/tool_concurrency.py` 覆盖率 **0%**（batch 调度器，无生产调用方 →
   orphan-gate 显式豁免）。**豁免接线 ≠ 免测**：屏障切分/有界池/顺序回填/兄弟取消从未被执行过一次。

## ② 修复（step A）

| 文件 | 改动 |
|---|---|
| `sloth_engine/tool_registry.py` | 权限门改用共享接缝的 `check_tool_call(tool.name, {"source":..., "args":..., "kwargs":...})`；`params` 构造提前以复用同一形状；注释记明漂移史 |
| 6 个伪测试文件 | 各加 `def test_contract(): main()` 薄入口（**body 一行未改**），使其断言进入门禁 |
| `tests/test_gate_collection_tripwire.py`（新，2 例） | AST 扫描 `tests/**/test_*.py`：**收集数 = 0 即失败**（防复发）；含"守护者自身可被收集"的自检 |
| `tests/test_tool_registry_contract.py`（新，28 例） | 注册面 + 权限接缝（含"原缺陷会抛 AttributeError"回归）+ pre-hook + 单调 guard + handler/post-hook 失败 + hook-bus 事件 + MCP 发现 + 上下文工具策略 |
| `tests/test_tool_concurrency_contract.py`（新，19 例） | fail-closed 配置 + 独占屏障切分 + 有界池 + 提交序回填 + 兄弟取消 + 批间中止 |
| `sloth_engine/tool_concurrency.py` | 仅 1 处加入 `# pragma: no cover - defensive`（`future.result()` 兜底异常：`_safe_execute` 已吞掉全部工具错误，该分支只在 worker 自身死亡时可达） |

### 契约不变量
1. **权限接缝两处调用点同名同语义**：`set_permission(DEFAULT)` 下写工具必 `blocked` / `error_code=permission_denied`
   （且 `metrics.permission_level` 与 `trades=[]`），读工具必放行；`BYPASS` 全放行；`PLAN_ONLY` 放只读、拒写/执行。
2. **测试文件必须可被门禁收集**（收集数 > 0）。
3. **`tool_concurrency` 屏障语义**：串行调用 flush 当前批并自成一批；结果按**提交顺序**返回（与完成顺序无关）；
   `abort_on_first_error` 取消未启动的兄弟并补 `"cancelled (sibling error)"`；批间严格串行且中止后不再启动后续批。

## ③ 验证

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_tool_registry_contract.py tests/test_tool_concurrency_contract.py tests/test_gate_collection_tripwire.py -q   # 49 passed
.\.venv\Scripts\python.exe -m pytest tests sloth_engine/tests -q    # 1542 passed / 1 xfailed / 77.58%
.\.venv\Scripts\python.exe scripts\check_orphan_mechanisms.py      # wired 73 / test_only 15 / exempt 1 / orphan 0 / stale 0
.\.venv\Scripts\python.exe scripts\run_gate.py --all               # PASS
node scripts/validate-contracts.mjs                                # 19 atom / 0 错 / 0 警
node tests/run-l1-tests.mjs                                        # 32 passed
```

- 覆盖率 76.11 → **77.58**；`tool_registry.py` 65% → **100%**；`tool_concurrency.py` 0% → **100%**。
- 1 warning 仍为第三方 `StarletteDeprecationWarning`（与既有基线同源，非本轮引入）。

## ④ A 阶段对既有登记项的影响

- 低优先两项 **全部闭合**（§13.40 登记）：`tool_registry.dispatch` 主路径、`tool_concurrency`。
- **新增观察项（如实登记，本轮未改行为）**：pre-hook 返回的改写 params 只替换 guard/审计视图
  （`{name, args, kwargs}` 形状），**不改变交给 handler 的实参** —— 即 pre-hook 能收窄/阻断调用，但不能改写调用实参。
  已按现有语义钉住（`test_pre_hook_param_rewrite_feeds_the_guard_view_not_the_call_args`）；
  若将来出现"必须改写实参"的真实用例，再评估是否改 `dispatch` 语义（避免无需求的行为变更）。

## ⑤ step C 增量复评（19 维，相对 cycle-15）+ 用户裁定登记

> 口径同上轮；本轮 B 增量为 architect-test **新增 TES-11** 与 architect-agent **新增 AGE-21**（atom 目录数不变，仍 19）。

| 项 | cycle-15 | cycle-16 | 依据 |
|---|---|---|---|
| 矩阵行数 | 19 | 19（不变） | 无新维度 |
| covered / partial / N/A | 14 / 4 / 1 | 14 / 4 / 1（不变） | 无缺口新闭合、无缺口新增 |
| `test` 维度检查清单 | TES-01..10 | **TES-01..11**（+TES-11 收集数 ≠ 0） | architect-skills `006eea4` |
| `agent` 维度检查清单 | AGE-01..20 | **AGE-01..21**（+AGE-21 接缝多调用点等价断言） | architect-skills `006eea4` |
| 质量（真实缺陷发现率） | — | 本轮由"契约补齐"直接暴露 1 个 P0 级隐藏缺陷（权限门） | §①.1 |

**用户裁定登记（2026-10-23）**：
- **N-3（真实厂商额度源）+ R3（真实模型调用 / 24h soak）＝ 不做**。仅作文档登记，**不再作为 blocked 项跟踪**；
  宿主若将来愿意把真实用量写入 JSON，`LOOP_QUOTA_FILE` 文件探针可零改动接入。
- **coze I-1/I-3/I-4 与 cycle-12 条目 11/12/13 ＝ 维持 candidate-pending，无解封条件不启动**
  （解封条件见 §13.41 与 `_INDEX.md` 各条目 ⑦）。

**仍未做（如实登记，未绕过 §0.1#6）**：R2（每项目沙箱）、WebUI、`guardian/risk_assessor.py::llm_review()`
维持用户裁定不动；上述 candidate 条目维持暂缓。