# cycle-31 A · 识别器的每个语法定点必须收敛为单一常量

- 日期：2026-10-25
- 来源：cycle-27 登记的候选「守卫的语法定点仍窄于现实」（`docs/flow/GRAND-LOOP.md` §next-target）
- 提交：cycle-31 A `f4dd5e7`（+5 用例）／ B（architect-skills）TES-26 + DOC-17

## 1. 取证方式（先驱动，再结论）

不看注释，直接把一条链条目改成全角括号、并把它的 cycle 标注改错，观察守卫是否变红：

| 探针 | 修复前 | 修复后 |
|---|---|---|
| 链条目改用全角括号 + cycle 标注改错 | `chain_entries` 仍 56，`chain_violations` 仍 `[]`（静默丢弃） | 条目被看见 → 报「annotated cycle-N but its commit says cycle-M」 |
| 哈希旁的 cycle 标注改为逗号 / 破折号分隔 | 不被 `claim_problems` 看见 | 仍不被看见（**已决定的边界**，见 §4） |

## 2. cycle-27 留下的缺口 —— 同一个类，换了个槽位

- cycle-27 把**哈希字母表**统一成 `[0-9a-f]{7,40}`，并让 `CLAIM_RE` 认全角括号；但**链条目解析器** `ENTRY_RE` 仍是 ASCII-only 的 `\(([^)]*)\)`。
- 于是「记录被静默丢弃」的老问题换了个槽位又活了一次：全角括号的链条目即使 cycle 标注写错，`chain_violations` 也返回 `[]` —— 一条**错哈希 / 错轮次**可以被当成事实一路传递（正是用户关心的「照链取证的 agent 拿到错哈希」）。
- 同族第二处：`HEAD_PREFIX` 同时写在内联字面量与测试常量里 —— 同一个前缀两处真相（D-S1 家族：常量必须与引用它的实现单点对齐）。

## 3. 修复（「一个定点，一个常量」）

- `BOPEN` / `BCLOSE` 收成单常量，`ENTRY_RE` 与 `CLAIM_RE` **共用**（全角 / 半角括号同宽）。
- `HEAD_PREFIX` 单点定义；`HEAD_RE` 由 `re.escape(HEAD_PREFIX)` 构造 —— 字面量不可能与图案漂移。
- 唤醒指针新增**唯一性**断言：出现第二个「代码 head <hash>」即 FAIL（此前只比对第一个，第二条隐形）。
- 识别器的语法槽位因此各有一个常量：**哈希字母表**（cycle-27）、**括号类**、**前缀**、**分隔符**。

## 4. 已决定的边界（用负例钉死，不「修」）

- **哈希旁的「逗号 / 破折号 + cycle-N」不是机器声明**：把 `CLAIM_RE` 扩到任意分隔符会把散文（「截至 cycle-N」）读成声明而产生**误报**；cycle-19/20 已定「只有括号形态是机器声明」。该决定由 `test_an_unbracketed_cycle_annotation_is_a_decided_boundary` 固定；**哈希本身仍受存在性规则管辖**（不是「不管了」）。
- **`HEAD_RE` 的前缀仍是本仓约定写法**：换了前缀会 fail-closed 报「无法定位指针」（红），不是静默绿 —— 因此不是假阴性风险，仅登记。
- **`ENTRY_RE` 仍要求哈希带反引号**：裸哈希走 `_bare_git_context_tokens` 的「同行 git 上下文」门控（cycle-21 的决定）。

## 5. B 轮口径（architect-skills）

TES-26 / DOC-17：识别器的**全部**语法定点（字母表 / 括号类 / 前缀 / 分隔符）必须收敛为单一常量并被所有识别器共用、且**不窄于它审计的现实**；不被覆盖的形态必须是被负例钉死的**决定**；要求唯一的记录必须断言「恰好一条」；自证 = 把记录改成识别器看不见的合法写法并写错标注，扫描器必须变红。

## 6. 验收

- `pytest tests sloth_engine/tests -q` → 1697 passed / 1 xfailed / **79.17%**（`tests/test_wake_pointer_chain.py` 44 → 49）
- `scripts/run_gate.py --all` → PASS；`docs_baseline.check() == []`
- B 侧：`node scripts/validate-contracts.mjs` → 19 atom / 0 错 / 0 警；`node tests/run-l1-tests.mjs` → 32 passed；跨仓账本 `unexplained 0 / exit 0`

## 7. 冻结项（不动）

N-3 / R3；coze I-1/I-3/I-4、cycle-12 条目 11/12/13；WebUI / 每项目文件沙箱；`guardian/risk_assessor.py::llm_review()`。
