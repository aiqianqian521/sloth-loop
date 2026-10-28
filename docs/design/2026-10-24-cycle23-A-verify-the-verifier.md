# cycle-23 A 设计说明 · 交付的验证器本身必须被验证

> 结论：2026-10-24。本循环走 A→B→C→D。step A 提交 `feac425`，B 轮 `14112db`（architect-skills，TES-19 + DOC-10）。
> 实况 1615 / 78.73 → **1618 / 78.73**（+3 用例；coverage 持平）。

## 1. 背景

cycle-22 交付了 `scripts/audit_cross_repo_ledger.py`：它是分类器 `classify_document(..)` 的**唯一调用方**，把「不可解析值 → 分类 → 未解释即 exit 1」写成了一条判定。但这条判定**没有任何测试**：

- 该脚本 **0 覆盖率**；
- 它的 exit code 从未被任何门禁或测试跑过；
- `REGISTERED_UNRESOLVABLE` 是一张手写登记表，可以静默腐烂（某条一旦开始可解析，脚本仍会把它当「已登记」放过）。

这是 cycle-16..22 同族的**第 8 个面**：前七个面分别是「漏测」「门禁没自证」「提交链没人验证」「缺陷描述复刻假形态」「散文 / 箭头链裸奔」「裸哈希裸奔」「守卫示例被复刻进文档」；本面是**「交付了验证器」≠「验证器被验证」**。

## 2. 发现

- `scripts/audit_cross_repo_ledger.py::main` 返回 `1 if unexplained else 0`，是断言型出口，此前**无任何断言**；
- `classify_document` 只被该脚本调用，因此该脚本 0 覆盖 = 分类器在真实语料上的行为从未被端到端跑过；
- `REGISTERED_UNRESOLVABLE` 的每一条都是「接收凭证」，而凭证本身没有校验器。

## 3. 边界

- 单测只驱动**合成语料仓**（一次性 `git init` checkout + 一份 `corpus.md`），并**清空 `DEFAULT_TARGETS`**，绝不扫本机的 legacy / architect-skills 兄弟仓——否则单测退化成环境依赖，也与 cycle-22「门禁不得依赖兄弟 checkout」冲突；
- 覆盖 ≠ 正确：本轮只补测试，不改脚本判定逻辑（判定语义已在 cycle-22 冻结）；分类器证据仍只服务取证报告，不接入 pytest 门禁。

## 4. 方案（step A，commit `feac425`）

`tests/test_wake_pointer_chain.py`（27 → 30）：

1. **exit code 是断言**：合成语料 = `_CROSS_REPO_SAMPLE` + 一条未解释幽灵 → `main` 必须 `exit 1`、恰好 1 个 `phantom`，且三个可解释类仍出现；
2. **全部可解释 → exit 0**：只放 `_CROSS_REPO_SAMPLE` → `exit 0`、`unexplained == []`、`files == 1`；
3. **登记表不可静默腐烂**：遍历 `REGISTERED_UNRESOLVABLE`，每条都必须 `_resolve_any(token, repos) is None`；一旦某条开始可解析，凭证陈旧，测试 FAIL。

## 5. 验证

- `pytest tests/test_wake_pointer_chain.py` → **30 passed**（27 → 30）；
- `pytest tests sloth_engine/tests -q` → **1618 passed / 1 xfailed / coverage 78.73%**（1615 → 1618，coverage 持平）；
- `scripts/audit_cross_repo_ledger.py` 实跑 → legacy `sloth-loop` 20 处 / architect-skills 9 处，`unexplained 0`、exit 0；
- B 轮 architect-skills：`validate-contracts.mjs` → 19 atom / 0 错 / 0 警；`run-l1-tests.mjs` → 32 passed；TES-18 → **19**、DOC-09 → **10**。

## 6. 残余风险

- 合成语料只覆盖已知的三类可解释形态 + 未解释；**新出现的**合法不可解析形态仍会被误报为 phantom（fail-closed 是刻意的：宁可误报，不可漏报）；
- `REGISTERED_UNRESOLVABLE` 的「接收凭证」仍由人维护，测试只能保证「此刻仍解析不出」，不能保证凭证的**理由**仍然成立（例如某仓真的被删了）；
- exit code 只被单测驱动，未接入任何门禁；这是刻意的（门禁不得依赖兄弟 checkout）。
