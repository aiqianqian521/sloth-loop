# cycle-14 A/C：不可达的状态历史导出（A 修复 + C 19 维增量复评）（2026-10-22）

> 起点：代码 head `65cf5a0`（基线 1453 passed / 1 xfailed / 75.22%）。本文件记录 step A 的缺陷定位与修复、
> step C 的 19 维增量复评。代码提交 `a67594e`；基线刷新为 **1460 / 75.76**。
> （文件名沿用 architect-skills `ARCHITECTURE-COVERAGE.md §5` cycle-14 条的引用；内容含 A 与 C 两步。）

---

## ① 缺陷（两条叠加，均属"未落地"）

1. **不可达分支**：`sloth_engine/run_loop.py` 里 P3-A1 的导出块写在 `run()` 的 `return {...}` **之后** ——
   `StateHistory.to_jsonl` 从未被调用过；`iter_loop()` 则完全没有任何导出。也就是说，"审计导出"在代码上存在，
   在运行上从不发生（三种既有测试都没碰过它）。
2. **伪序列化**：`sloth_engine/immutable_state.py::StateHistory.to_jsonl` 实现为
   `str(s.to_dict()).replace("'", '"')` —— 用 Python repr 冒充 JSON：值里出现单引号（如 `it's`）会被朴素替换成双引号，
   产出**非法 JSON 行**；`json.loads` 直接报 `Expecting value`。

### 反向样本（修复前实测）
- 以"3 轮 run、每轮出快照"跑一遍：`_state_history.count == 2`，但 `work_dir` 下**没有**任何 `state-history-*.jsonl`。
- 手工调用 `to_jsonl` 后逐行 `json.loads`：`JSONDecodeError: Expecting value: line 1 column 160`。

## ② 修复（step A）

| 文件 | 改动 |
|---|---|
| `sloth_engine/run_loop.py` | 提取 `_export_state_history()`（无快照时 no-op，返回导出路径）；在 `run()` 返回前与 `iter_loop()` 收尾处各调用一次 |
| `sloth_engine/immutable_state.py` | `to_jsonl` 改 `json.dumps(s.to_dict(), ensure_ascii=False, default=str)`（真 JSON；中文保留；非原生类型显式兜底） |
| `tests/test_state_history_export.py`（新，7 例） | run() 导出、iter_loop() 导出、0 轮不写、helper no-op、单导出点 + 调用先于 `return` 的源侧 tripwire |
| `tests/test_immutable_state.py` | +`test_to_jsonl_is_valid_json_even_with_quotes`（单引号 + 中文 → 仍可 `json.loads`） |

### 契约不变量
1. 导出行数 == `orch._state_history.count`（**不保证**等于 `total_rounds`：末轮可能在被 snapshot 之前因契约上限 break）。
2. 每行都是合法 JSON，关键字段（`round_num` 等）与内存态一致。
3. 无快照（0 轮）→ 不产生空文件（no-op，而非写空壳）。
4. 导出语句唯一（单点 helper），且在 `run()` 的 `return` 之前可达。

## ③ 验证

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_state_history_export.py tests/test_immutable_state.py -q   # 36 passed
.\.venv\Scripts\python.exe -m pytest tests sloth_engine/tests -q      # 1460 passed / 1 xfailed / 75.76%
.\.venv\Scripts\python.exe scripts\check_orphan_mechanisms.py       # wired 73 / orphan 0 / stale 0
.\.venv\Scripts\python.exe scripts\run_gate.py --all                # PASS
```

- 覆盖率 75.22 → **75.76**：`run_loop.py` 的导出路径由新用例真实覆盖（此前为不可达，故 0 覆盖）。
- 1 warning 仍为第三方 `StarletteDeprecationWarning`（与既有基线同源，非本轮引入）。

## ④ A 阶段对既有登记项的影响

- 低优先项「`run_loop.run()` 不可达 `_state_history` 导出」→ **本轮闭合**（§13.37/§13.38 均登记过该项）。
- 未新增 blocked 项、未绕过任何既有 blocked 项。

## ⑤ step C 增量复评（19 维，相对 cycle-13）

> 口径同上轮；本轮 B 增量为 architect-observability **新增 OBS-11**（atom 目录数不变，仍 19）。

| 项 | cycle-13 | cycle-14 | 依据 |
|---|---|---|---|
| 矩阵行数 | 19 | 19（不变） | 无新维度 |
| covered / partial / N/A | 14 / 4 / 1 | 14 / 4 / 1（不变） | 无缺口新闭合、无新增 |
| `observability`（#7）质量 | covered（但审计导出实为"纸面"） | covered（**导出可达 + 真 JSON + 端到端断言**） | `tests/test_state_history_export.py`(7) + `to_jsonl` 契约用例 |
| `observability` 检查清单 | OBS-01..10 | **OBS-01..11**（+OBS-11） | architect-skills `9ef5c40` |

**仍未做（如实登记，未绕过 §0.1#6）**：N-3 残余（真实厂商源）与 R3（真实模型 / 24h soak）仍 **blocked**；
R2（每项目沙箱）、WebUI、`guardian/risk_assessor.py::llm_review()` 维持用户裁定；`tool_pipeline` 其余 13 步契约测试
仍在低优先（本轮已闭合其中的 `_state_history` 导出项）。