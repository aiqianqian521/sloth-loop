# cycle-24 A 设计说明 · 校验器的「作用域」本身必须被校验

> 结论：2026-10-24。本循环走 A→B→C→D。step A 提交 `f127664`，B 轮 `eafd45c`（architect-skills，TES-20 + DOC-11）。
> 实况 1618 / 78.73 → **1621 / 78.73**（+3 用例；coverage 持平）。

## 1. 背景

cycle-17 交付 `scripts/docs_baseline.py`：用一份手写清单 `CHECK_FILES` 断言「每份当前态文档都引用同一套基线数字」，期望值从 `docs/baseline.json` 读取。但**清单本身无人校验**：

- `docs/flow/GRAND-LOOP.md`（wake pointer，新 agent 第一个读的文件，且引用同一套数字）**不在清单里**；
- wake-pointer 守卫只交叉核对它的 `head` 哈希，从不看它旁边的 `N passed / coverage X%`。

## 2. 发现（可复现证据）

把 wake pointer 的基线数字改坏成 `9999 passed / coverage 55.55%`：`docs_baseline` 仍 `OK`、`tests/test_wake_pointer_chain.py` 仍 30 passed。**最该被信任的文件恰恰没人查。**

## 3. 边界

- 历史 / 快照 / 设计记录类文档不纳入一致性校验是**刻意的**（它们记录的是当时的数字）；
- 入口文档不纳入**不是**刻意的，故纳入；
- 本循环只改「校验作用域 + 自证测试」，不改任何被测数值（baseline 由真实 run 决定）。

## 4. 方案（step A，commit `f127664`）

1. `scripts/docs_baseline.py`：`CHECK_FILES` 增加 `docs/flow/GRAND-LOOP.md`；
2. `tests/test_gate_self_verification.py`（23 → 26）：
   - 入口文档在清单内（`WAKE_POINTER in CHECK_FILES`）；
   - 合成仓自证：把 wake pointer 的 passed 数字改坏 → `docs_baseline.check()` 必须报错；
   - 真实仓断言：`docs_baseline.check(REPO) == []`。

## 5. 验证

- 修复前：改坏入口文档 → `docs_baseline` OK / 守卫 30 passed（漏报）；
- 修复后：同一改法 → `docs_baseline` FAIL（exit 1，点名 `docs/flow/GRAND-LOOP.md`）；
- `pytest tests sloth_engine/tests -q` → **1621 passed / 1 xfailed / coverage 78.73%**（1618 → 1621）；
- `run_gate.py --all` → PASS；architect-skills `validate-contracts.mjs` → 19 atom / 0 错 / 0 警、`run-l1-tests.mjs` → 32 passed。

## 6. 残余风险

- `docs_baseline` 只断言「文档里出现该数字」，不断言「只出现该数字」：同一文档内混入一个旧数字不会被抓（实验中只改 wake pointer 的 header 行、保留最新 bullet 里的旧值，校验器即漏报）。彻底修法是「文中每个 `N passed` 形态都必须等于基线」，但那会与历史叙述冲突，属**已知边界**；
- 清单仍由人维护，测试只固定「入口文档在内」，不保证未来新增的当前态文档被及时纳入。
