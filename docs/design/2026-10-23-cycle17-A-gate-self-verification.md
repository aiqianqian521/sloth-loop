# cycle-17 A/C：门禁自证 —— 实测 vs 登记棘轮 + 门禁行为契约 + 收集扫描加固（2026-10-23）

> 本轮主题：**守护者无人守护**。cycle-16 修的是"被门禁漏掉的测试"；cycle-17 修的是"门禁自己没人验证"。
> 代码提交 `710a3af`；B 增量 `88fa263`（architect-skills）；基线刷新为 **1588 / 78.73**（原 1542 / 77.58）。

## ① 三个缺陷（同一类："守护者无人守护"）

1. **门禁接线只被源码 grep 守护（P1）**：`tests/test_orphan_mechanisms_gate.py::test_run_gate_invokes_the_orphan_gate` 与
   `tests/test_p1_failclosed_batch.py::test_run_gate_has_all_flag` 的全部断言是对 `scripts/run_gate.py` 做**字符串匹配**
   （`assert "check_orphan_mechanisms" in src`）。把某个检查挪到 `return 0` 之后、或删掉一段棘轮判定，字符串还在、测试全绿。
   实测：全仓 `git grep "run_gate\.main\|_triggered\|_parse_fail_under"` → **0 命中**（门禁主体从未被执行过）；
   `pyproject.toml` 的 `[tool.coverage.run] source = ["sloth_engine"]` → **`scripts/` 不在覆盖率分母内**。
2. **登记基线从不与实测对照（P2）**：`docs/baseline.json`（passed/coverage）是**手抄**值；
   `docs_baseline.check()` 只做 **文档 ↔ 登记** 互校，`run_gate.py` 只看退出码与 `fail_under` → **没有任何环节把登记值与真实运行比对**。
   失效模式：删掉一批测试 + 手改登记值与 9 个当前态文档 = 门禁全绿（`fail_under=70` 与实测 77.57% 之间 7.6pt 缓冲足以吸收）。
   同轮发现 `scripts/docs_baseline.py` docstring 仍写旧口径 `1196 passed / 72.13%`（文档腐化，已删硬编码）。
3. **收集扫描覆盖不全（P3）**：cycle-16 的 `tests/test_gate_collection_tripwire.py` 用
   `glob("test_*.py")`（**非递归**、只认 `test_` 前缀）。pytest 默认 `python_files = test_*.py *_test.py` 且**递归**收集 →
   `tests/<sub>/test_x.py` 或 `foo_test.py` 里的 0 收集文件可整体绕过，且扫描器本身没有测试（修了也没人知道）。

## ② 修复（step A，commit `710a3af`，5 files / +46 用例）

- `scripts/run_gate.py`：新增 **baseline-vs-measured 单向棘轮**（P2）——捕获 pytest `-q` 输出并**原样转发**，
  用新纯函数 `parse_pytest_summary()` 解析 `N passed` / `Total coverage: X%`，用 `baseline_violations()` 与
  `docs/baseline.json` 比对：**实测 passed < 登记 → FAIL**；实测 coverage < 登记 − 0.15（浮点容差）→ FAIL；
  摘要解析失败 → FAIL（fail-closed）；实测**高于**登记 → 允许（那是新增测试）。
  另抽 `_run_pytest()` 接缝，使门禁可在进程内被完整驱动。
- `scripts/docs_baseline.py`：docstring 去掉硬编码旧口径（`1196 passed / 72.13%`），改为"数字一律从 `docs/baseline.json` 读取"。
- `tests/test_gate_collection_tripwire.py`：改 `rglob` + 双命名（`test_*.py` / `*_test.py`），并加 2 例**扫描器自证**
  （合成 tmp 树：`test_a.py` / `b_test.py` / `sub/test_c.py` / `helper.py` → 只应看到前三个；子目录脚本式文件必须被揪出）。
- `tests/test_gate_self_verification.py`（**新增，20 例**）：`importlib` 加载 `run_gate.py`，单测纯函数
  （`_triggered` / `_parse_fail_under` / `parse_pytest_summary` / `baseline_violations`），并用 monkeypatch 替掉
  子进程 / git / 外部校验器接缝后驱动 `main()`，把**每条 fail 路径**变成可复现断言：
  未触发 SKIP / 缺依赖拒绝 / 棘轮下降拒绝 / 测试红灯拒绝 / 摘要不可解析拒绝 / 文档漂移拒绝 / orphan 拒绝 / 登记值落后拒绝 /
  全绿 PASS（并断言 `_run_pytest()` 真被调用、真读仓内 `docs/baseline.json`）。
- `tests/test_orchestrator_cli_surface.py`（**新增，21 例**）：`orchestrator.py` 的 CLI 面此前**从未被门禁执行**
  （`status()` / `review()` / `_show_history()` / `reset()` / `build_orchestrator()` / `main()`）——
  覆盖空库与有数据库的 `status`；`review` 的 5 条分支（无 open / 非 tty / --yes / --min-win-rate 跳过与保留 / 交互 skip·quit·all / 不可解析 win_rate）；
  `reset` 有/无 --yes；`_show_history` 三种库态与 4 类 stop_reason；`build_orchestrator` 的 fail-closed 与真 YAML 加载；
  `main()` 的依赖装配与退出码映射。

### 契约不变量（本轮新增钉死）

- 门禁的**登记数字**必须来自 `docs/baseline.json` 且与实测做棘轮比对（实测不得低于登记）。
- 门禁**每条 fail 路径**都必须有一条进程内可复现的断言（源码 grep 不算验证）。
- 收集扫描必须覆盖 pytest 的**全部**可收集命名与深度，且扫描器自身有自证用例。

## ③ 验证

```
.\.venv\Scripts\python.exe -m pytest tests sloth_engine/tests -q   # 1588 passed / 1 xfailed / 78.73%
.\.venv\Scripts\python.exe scripts\run_gate.py --all              # PASS（含 baseline-vs-measured: OK）
.\.venv\Scripts\python.exe scripts\docs_baseline.py               # OK
.\.venv\Scripts\python.exe scripts\check_orphan_mechanisms.py     # wired 73 / test_only 15 / exempt 1 / orphan 0 / stale 0
```

- `orchestrator.py`（被 orphan 门禁归类为 `test_only` 的 **CLI 入口**）覆盖率 **53% → 86%**。
- 全量 **1542 → 1588 passed**（+46）；coverage **77.57% → 78.73%**。

## ④ A 阶段对既有登记项的影响

- 关闭 cycle-16 §13.41 留下的"门禁盲区"类观察项（本轮即由审计发现并闭合 3 项）。
- **新观察项（如实登记，本轮未改行为）**：orphan 门禁的 `test_only` 分类**会把 CLI 入口误记为"参考实现"**——
  本仓 7 个 `if __name__ == "__main__"` 入口中 5 个（`orchestrator` / `migrate` / `webui` / `hooks_check` / `session_projection`）
  落在 `test_only` 名单里，因为它们是**被直接执行**而非被 import。该标签不可当"参考实现"读；
  门禁输出（`_report`）已足以区分，但**文档口径**需谨慎。若将来要做"入口覆盖"专项，再评估是否给分类器加"入口"类别。
- **未做（如实登记）**：`orchestrator.py` 剩余 61 行未覆盖主要为防御分支（containment 审计 sink、features 导入失败、
  相对 config 路径解析、内存插件替换）与 `if __name__ == "__main__"` 行；`migrate.py` 54%、`pattern_compactor.py` 69%、
  `webui.py` 73%（用户裁定不动）维持现状。

## ⑤ step C 增量复评（19 维，相对 cycle-16）+ 用户裁定登记

> 口径同上轮；本轮 B 增量为 architect-test **新增 TES-12 / TES-13** 与 architect-agent **新增 AGE-22**（atom 目录数不变，仍 19）。

| 项 | cycle-16 | cycle-17 | 依据 |
|---|---|---|---|
| 矩阵行数 | 19 | 19（不变） | 无新维度 |
| covered / partial / N/A | 14 / 4 / 1 | 14 / 4 / 1（不变） | 无缺口新闭合、无缺口新增 |
| `test` 维度检查清单 | TES-01..11 | **TES-01..13**（+TES-12 收集扫描覆盖；+TES-13 登记 vs 实测棘轮） | architect-skills `88fa263` |
| `agent` 维度检查清单 | AGE-01..21 | **AGE-01..22**（+AGE-22 门禁须行为验证） | architect-skills `88fa263` |
| `agent` SKILL 摘要表 | 19 行（滞后，缺原则 20） | **21 行**（补 20/21；描述"19条"→"21条"） | 本轮顺手修 |
| 质量（真实缺陷发现率） | — | 本轮由"门禁自证审计"暴露 3 个静默盲区（接线可被绕过 / 登记从不与实测对照 / 扫描覆盖不全） | §① |

**用户裁定登记（沿用 2026-10-23 裁定，本轮无新增裁定）**：
- **N-3（真实厂商额度源）+ R3（真实模型调用 / 24h soak）＝ 不做**（仅文档登记，不作为 blocked 跟踪）。
- **coze I-1/I-3/I-4 与 cycle-12 条目 11/12/13 ＝ 维持 candidate-pending，无解封条件不启动**。

**仍未做（如实登记，未绕过 §0.1#6）**：R2（每项目沙箱）、WebUI、`guardian/risk_assessor.py::llm_review()` 维持不动。
