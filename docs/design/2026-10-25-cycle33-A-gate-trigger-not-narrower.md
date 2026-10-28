# cycle-33 A · 门控的触发条件必须不窄于它识别的声明

- 日期：2026-10-25
- 来源：cycle-32 登记的候选「豁免类机制的方向性对称面」（`docs/flow/GRAND-LOOP.md` §next-target）
- 提交：cycle-33 A `7eabdb3`（+3 用例）／ B（architect-skills）TES-28 + DOC-19

## 1. 取证方式（先驱动，再结论）

写一行「git 关键词 + 一个解析不出的 7 位 hex，且该行没有别的引用」，观察守卫是否报红：

| 探针 | 修复前 | 修复后 |
|---|---|---|
| `fixed in commit <幽灵哈希>`（本行无其它引用） | 0 违规（共现门控没看它） | 报「bare … resolves in no known repo」 |
| 同一行再放一个真哈希 | 报（共现门控生效） | 同左 |
| `the commit history was rewritten; the defaced record was effaced` | 0 违规 | 仍 0 违规（远距离英文词必须静默） |

（幽灵哈希用运行时拼装的 7 位 token，避免把假声明写进文档本身——全仓扫描会读 `.md`。）

## 2. 病根：门控的触发条件窄于声明

- `_bare_git_context_tokens()` 的 cycle-21 共现门控：裸哈希**仅当同一行已有可解析提交引用**时才被检查。
- 它挡住了 defaced / effaced 这类全 hex 英文词，代价是把**唯一的**裸声明漏掉：一行仅写「fixed in commit <坏哈希>」从不报红——门控决定「要不要看」，而它看开了。
- 这正是用户关心的「照链取证的 agent 拿到错哈希、并被当成事实一路传递」。

## 3. 修复（「紧邻性，而非共现性」）

- 新增 `GIT_ADJACENT_RE`：git 关键词（commit / HEAD / baseline / tag / revision / sha / merge …）**紧邻**其后的裸 token 本身就是声明。
- `_bare_git_context_tokens` 改为「共现 **或** 紧邻」；放宽由**紧邻性**（局部、可实测）定义，绝不用**共现性**（全局、会漏）。
- 三仓语料实测：新增 **4 处命中，全部是真提交引用、误报 0**（全 hex 英文词 / 数据指纹 / 运行 id 从不紧邻关键词）。
- 其中唯一一处无法解释的（legacy 冻结期 OODA 证据文档里的 HEAD 引用，任何克隆都不存在）按既有约定登记进 `REGISTERED_UNRESOLVABLE` 并附收据。

## 4. 已决定的边界（用负例钉死，不「修」）

- **带摘要标签（md5=…）的行整体跳过**：cycle-21 的决定，未变。
- **紧邻性由关键词集定义**：新增关键词须同时补实测（0 误报）与用例，不自动扩宽。
- **远距离的英文词必须静默**：由 `test_a_git_keyword_only_widens_the_gate_when_it_is_adjacent` 固定。

## 5. B 轮口径（architect-skills）

TES-28 / DOC-19：门控 / 触发条件 / 前置过滤必须**不窄于它识别的声明**——不能因「缺少旁证」把唯一的、形态上明确的声明漏掉；放宽必须用**紧邻性**（局部、可实测）而不是**共现性**（全局、会漏）定义；每个放宽都要用语料实测证明零误报；门控要有正例 + 负例双向测试。

## 6. 验收

- `pytest tests sloth_engine/tests -q` → 1708 passed / 1 xfailed / **79.17%**（`tests/test_wake_pointer_chain.py` 57 → 60）
- `scripts/run_gate.py --all` → PASS；`docs_baseline.check() == []`
- B 侧：`node scripts/validate-contracts.mjs` → 19 atom / 0 错 / 0 警；`node tests/run-l1-tests.mjs` → 32 passed；跨仓账本 `unexplained 0 / exit 0`

## 7. 冻结项（不动）

N-3 / R3；coze I-1/I-3/I-4、cycle-12 条目 11/12/13；WebUI / 每项目文件沙箱；`guardian/risk_assessor.py::llm_review()`。
