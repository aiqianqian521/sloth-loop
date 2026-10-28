# cycle-32 A · 缺陷豁免必须窄于它所豁免的缺陷

- 日期：2026-10-25
- 来源：cycle-31 登记的候选「`_is_defect_line` 整行豁免宽于缺陷」
- 提交：cycle-32 A `9ba0b5f`（+8 用例）／ B（architect-skills）TES-27 + DOC-18

## 1. 取证方式（先驱动，再结论）

写一行「普通英文词 + 一个解析不出的 7 位 hex」，观察守卫是否报红：

| 探针 | 修复前 | 修复后 |
|---|---|---|
| `cycle-20 fixed the phantom issue in <幽灵哈希>` | 0 违规（`phantom` 是标记 ⇒ 整行豁免） | 报「resolves in no known repo」 |
| 同一行去掉 phantom 一词 | 报「resolves in no known repo」 | 同上 |

（幽灵哈希用运行时拼装的 7 位 token，避免把假声明写进文档本身——全仓扫描会读 `.md`。）

## 2. 病根：豁免的边界宽于缺陷

- `_is_defect_line()` 只要行内出现任一 `DEFECT_MARKERS` 词就**整行豁免**该行的全部哈希。
- 其中一个「标记」是普通英文词 `phantom`——正是本模块自己的函数名 `phantom_hash_problems`。于是一句仅仅**提到函数名**的注释就豁免了整行。
- 全仓 53 行仅靠 phantom 一词免检（其中无一行藏有坏哈希 ⇒ 潜伏假阴性）。真正的缺陷形态是 `❌错记 <哈希>`（标记紧邻，2 字符）。

## 3. 修复（「豁免必须窄于缺陷」）

- `DEFECT_MARKERS` 收敛为纯**写作约定**（❌ / 错记 / NOT-A-COMMIT）：**代码标识符永不充当标记**。
- 豁免**按 token**：标记须在 token 之前且相距 ≤ `MARK_WINDOW`(24)（阈值由语料实测分界线给出：真标注 2..15 字符、最宽散文 / 表格间隔 25..63）。
- 枚举是一个槽位：以斜杠连接的哈希列表，**仅当首项被标注**才整列豁免。
- 行级豁免**记账化**：`ROW_MARKED_RULES` 显式登记 cycle-22 台账表格行；守卫断言登记仍存在、仍可解析、仍生效、不外溢到别的文件（cycle-23 同族：登记不可静默腐坏）。

## 4. 已决定的边界（用负例钉死，不「修」）

- **标记必须在 token 之前**：标记在 token 之后不豁免（fail-closed）；由 `test_a_marker_must_precede_the_token_it_labels` 固定。
- **斜杠列表的兄弟豁免只限同一行同一列表**：别的分隔符枚举须走行级登记，不自动扩宽。
- **行级登记按（路径 + 行 stem）**：文件重命名 / stem 改写会让守卫报警（fail-closed）。

## 5. B 轮口径（architect-skills）

TES-27 / DOC-18：豁免 / 白名单 / 例外类机制必须**窄于它豁免的缺陷**——标记须来自**穷尽枚举**（不得是代码标识符 / 普通词）、须**紧邻**被标记物、列表仅首项被标注才整体豁免；无法紧邻的行级形态必须**显式登记**且登记不得静默腐坏；自证 = 把标记换成普通词、或把它挪远超阈值，豁免必须失效。

## 6. 验收

- `pytest tests sloth_engine/tests -q` → 1705 passed / 1 xfailed / **79.18%**（`tests/test_wake_pointer_chain.py` 49 → 57）
- `scripts/run_gate.py --all` → PASS；`docs_baseline.check() == []`
- B 侧：`node scripts/validate-contracts.mjs` → 19 atom / 0 错 / 0 警；`node tests/run-l1-tests.mjs` → 32 passed；跨仓账本 `unexplained 0 / exit 0`

## 7. 冻结项（不动）

N-3 / R3；coze I-1/I-3/I-4、cycle-12 条目 11/12/13；WebUI / 每项目文件沙箱；`guardian/risk_assessor.py::llm_review()`。
