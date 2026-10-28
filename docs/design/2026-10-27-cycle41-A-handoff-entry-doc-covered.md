# cycle-41 A · 交接入口文档必须被口径守护覆盖（START.md 纳入 CHECK_FILES）

- 日期：2026-10-27
- 来源：打包交接包 `sloth-loop-new` 时的入口文件复核
- 提交：cycle-41 A `fc492f0`（用例数不变）

## 1. 取证方式（先驱动，再结论）

1. 打开「新 agent 第一个读」的 `START.md`，对照 `docs/baseline.json`。
2. 实测：`START.md:24` / `START.md:35` 引用 **1159 passed / 71.76%**，基线为 **1760 / 79.49%**（差 601 个用例）。
3. 对照：`python -c "import docs_baseline as d; print(d.check())"` → `[]`（**通过**）。
4. 定位：`docs_baseline.CHECK_FILES` 这份**手写清单**未收录 `START.md` —— 清单外 = 无人校验。

| 事实 | 修复前 | 修复后 |
|---|---|---|
| START.md 基线 | 1159 passed / 71.76% | 1760 passed / 79.49%（fail_under=70） |
| START.md 在 CHECK_FILES | 否（无人校验） | **是** |
| 守护作用域 pin | 只钉唤醒指针 | 钉住「唤醒指针 + 交接入口」两份 |
| 全量用例数 | 1760 | 1760（不变） |

## 2. 病根：手写清单可以静默漏掉一个输入

- `docs_baseline` 的价值来自它的**作用域**：列进 `CHECK_FILES` 的文档才被断言。
- 一份「谁第一个读」的入口文档若不在清单内，它引用的基线数字就**没有任何断言**——差 601 个用例仍然 `check() == []`（假绿）。
- 这是 cycle-24「校验器的作用域本身必须被校验」的同一族，只是这次漏掉的是**交接入口** `START.md`，而不是唤醒指针 `docs/flow/GRAND-LOOP.md`。

## 3. 修复

- **`START.md`**：两处数字更新为 1760 / 0 xfailed / 79.49%（fail_under=70）。
- **`scripts/docs_baseline.py`**：`CHECK_FILES` 纳入 `START.md`（附 cycle-41 注释说明为何是它）。
- **`tests/test_gate_self_verification.py`**：
  - `WAKE_POINTER` + 新增 `HANDOFF_ENTRY`；
  - 作用域 pin 由「唤醒指针在清单内」改为「两份入口文档都在清单内」；
  - 漂移负控由单文件改为对两份入口文档逐个自证（改坏数字 → 守护必须报红）。
  - 均为**改写既有用例**（不新增用例），故全量口径保持 1760。

## 4. 证据（实测）

```
python -c "import sys;sys.path.insert(0,'scripts');import docs_baseline as d;
           print('START.md' in d.CHECK_FILES, d.check())"
-> True []

pytest tests sloth_engine/tests -q  ->  1760 passed / 0 xfailed / 79.49%
run_gate.py --all                 ->  PASS (docs-baseline: OK)
```

## 5. 诚实作用域

- 本轮只把 `START.md` 这类「交接入口」纳入；`sloth_engine/README.md`（v3.4 头，490 passed）与 `docs/sloth-loop-项目介绍与规划.md` 仍不在清单内，是否属当前态**待裁定**（已登记候选）。
- 历史/日期化的文档（`docs/design/*`、ADR、knowledge-distillation、`docs/flow/2026-09-05-grand-loop-task.md`）刻意不在清单内。
- 本轮未做 architect-skills B 轮不变量。
