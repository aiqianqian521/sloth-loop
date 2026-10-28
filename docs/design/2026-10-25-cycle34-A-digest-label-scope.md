# cycle-34 A · 开关的作用域不得大于它豁免的对象

- 日期：2026-10-25
- 来源：cycle-33 登记的候选「带摘要标签的行仍整体跳过」（`docs/flow/GRAND-LOOP.md` §next-target）
- 提交：cycle-34 A `706df02`（+4 用例）／ B（architect-skills）TES-29 + DOC-20

## 1. 取证方式（先驱动，再结论）

把一个解析不出的裸 token 与一个摘要标签写在**同一行**，观察守卫是否报红：

| 探针 | 修复前 | 修复后 |
|---|---|---|
| `fixed in commit <幽灵哈希>, md5=<摘要>` | 0 违规（摘要标签把整行关掉了） | 报「bare … resolves in no known repo」 |
| `md5=<摘要>`（仅标签与其值） | 0 违规 | 仍 0 违规（标签自身的值仍豁免） |
| `<摘要值> then fixed in commit <幽灵哈希>` | 0 违规 | 报（标签只豁免它标注的那个值） |

（幽灵哈希用运行时拼装的 7 位 token；摘要值用固定的 32 位十六进制常量，二者都不构成提交声明，也不写进任何出货文档。）

## 2. 病根：开关的作用域大于它豁免的对象

- `DIGEST_ANY_RE` 命中即让 `_bare_git_context_tokens()` **整行返回空**（cycle-21 的整行跳过）。
- 摘要标签本意是「这个值是校验和，不是提交引用」，作用域应只是**它标注的那个值**。
- 于是一行「fixed in commit <坏哈希>, md5=<摘要>」里的真提交声明**从不报红**，而产物看起来干净（假阴性）。
- 这是「宽窄不对称」族的第三轴：cycle-32 = 值（豁免太宽）／ cycle-33 = 触发（门控太窄）／ cycle-34 = **作用域**。

## 3. 修复（单点谓词 + 按对象豁免）

- 新增 `_digest_labelled(line, token, at)`：摘要标签只豁免它**紧邻标注的那个值**（标签须落在前缀末尾，`DIGEST_LABEL_RE` 锚定在行尾）。
- 反引号识别器与裸识别器**共用**该单点谓词（此前反引号路径自带一份等价但分离的判断，裸路径则整行一刀切——两处真相，D-S1 家族）。
- 移除整行跳过；`_bare_git_context_tokens` 只把**未被标签标注**的裸 token 纳入候选。
- 语料实测：本仓出货 markdown 中带摘要标签的行 **13 行**、被整行跳过掩盖的裸 token **0** ⇒ 潜伏洞、零回归（与 cycle-32 的 53 行同族）。

## 4. 已决定的边界（用负例钉死，不「修」）

- **分类器有意更宽**：`FINGERPRINT_EVIDENCE_RE` 仍是行级口径，可解释门禁会报的 token——它只放宽取证报告（跨仓账本），绝不放宽出货门禁；该不对称由 `test_the_classifier_is_deliberately_looser_than_the_gate` 钉死。
- **豁免锚定在值本身**：仅「靠近」标签的 token 不豁免（由 `test_the_digest_exemption_is_anchored_to_its_own_value` 固定）。
- **无「值」的摘要标签**（如标签后无 hex）不豁免任何东西。

## 5. B 轮口径（architect-skills）

TES-29 / DOC-20：**开关 / 豁免标签的作用域不得大于它豁免的对象**——一个只该豁免某个值的标签不得关掉整行 / 整块的检查；作用域必须按**对象**定义、由语料实测给出分界线并配负例；标签判定须收敛为**单点谓词**被所有识别器共用；分类器可以有意更宽，但该不对称必须作为决定钉死（只放宽取证报告，绝不放宽出货门禁）。

## 6. 验收

- `pytest tests sloth_engine/tests -q` → 1712 passed / 1 xfailed / **79.17%**（`tests/test_wake_pointer_chain.py` 60 → 64）
- `scripts/run_gate.py --all` → PASS；`docs_baseline.check() == []`；`scripts/audit_cross_repo_ledger.py` → unexplained 0 / exit 0
- B 侧：`node scripts/validate-contracts.mjs` → 19 atom / 0 错 / 0 警；`node tests/run-l1-tests.mjs` → 32 passed

## 7. 冻结项（不动）

N-3 / R3；coze I-1/I-3/I-4、cycle-12 条目 11/12/13；WebUI / 每项目文件沙箱；`guardian/risk_assessor.py::llm_review()`。
