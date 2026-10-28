# cycle-25 A 设计说明 · 『指向下一步』的导航标号必须被机器校验

> 结论：2026-10-24。本循环走 A→B→C→D。step A 提交 `460ff36`，B 轮 `6fe1031`（architect-skills，TES-21 + DOC-12）。
> 实况 1621 / 78.73 → **1625 / 78.73**（+4 用例；coverage 持平）。

## 1. 背景

`docs/flow/GRAND-LOOP.md` 的状态行以『下一目标（自动，按 §13.N 排序）』收尾——一个**手写指针**，指向 append-only 的状态注册表 `docs/flow/2026-09-05-grand-loop-status.md`。每轮 C/D 手动把 N +1；注册表的最新小节也由人工追加。

**两者之间没有任何校验**：一个过期的指针会把下一个执行者引到旧的『下一目标』清单（该清单正是「还要做什么」的唯一来源）。

## 2. 发现（可复现证据）

把指针从 §13.50 改成过期 §13.49：`tests/test_wake_pointer_chain.py` 仍 30 passed、`docs_baseline` 仍 OK——**没有检查发现指针指向了旧清单**。

## 3. 边界

- 校验的是**标号**（章节号 / 序号）与注册表的一致性，不校验『下一目标』清单的**内容**（内容正确性仍靠人）；
- 只校验 `13.N` 这一形态的注册表小节（本仓现状）；其他编号体系未纳入；
- 只增测试，不改任何既有文档编号语义。

## 4. 方案（step A，commit `460ff36`）

`tests/test_wake_pointer_chain.py`（30 → 34）：

1. 指针标号 == 注册表里最新 `### 13.N` 小节；
2. 注册表编号严格递增且连续（append-only，无缺号 / 重号）；
3. fail-closed：指针缺失 / 注册表为空即失败；
4. 自证：过期指针、重号、缺号、指针缺失 —— 四种都被测到。

## 5. 验证

- 修复前：指针改成过期 §13.49 → 守卫 30 passed、docs_baseline OK（漏报）；
- 修复后：同一改法 → `test_next_target_pointer_matches_the_registry_head` **FAIL**；
- `pytest tests sloth_engine/tests -q` → **1625 passed / 1 xfailed / coverage 78.73%**（1621 → 1625）；
- `run_gate.py --all` → PASS；architect-skills `validate-contracts.mjs` → 19 atom / 0 错 / 0 警、`run-l1-tests.mjs` → 32 passed。

## 6. 残余风险

- 只校验『指针 == 最新标号』，不校验指针**语义**（例如注册表最新小节写的是 cycle-25、而指针文案说「下一目标」——两者的业务一致性仍靠人）；
- 注册表的**内容**（每轮是否如实登记）不在校验范围；
- 若未来出现第二套编号（如 §14.x），本轮规则不覆盖。
