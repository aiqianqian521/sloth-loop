# cycle-22 A 跨仓账本扫描 · 分类器与边界

> 触发：2026-10-24，用户「继续 启动大任务循环吧」。step A 提交 `fb993dc`，B 提交 `f34dad6`（architect-skills：TES-18 + DOC-09）。
> 基线 1608 / 78.73 → **1615 / 78.73**（+7 用例），coverage 持平。

## 1. 背景

cycle-18~21 造出一条「待校验账本」守卫：本仓 shipped `.md` 里出现的每个提交哈希都必须在已知仓真实存在；解析不出且未标记缺陷 = FAIL。四轮里它抓出 6 个假哈希，并把「只认反引号 × 只认 `hash(cycle-N)`」扩到「反引号 + 裸哈希 + 箭头链拓扑」。

但这套账本**一直在一个仓里自我校验**。cycle-22 第一次把同一套规则指向**兄弟语料**：legacy `sloth-loop`（2300 篇 shipped `.md`）与 architect-skills（86 篇）。

## 2. 现象

跨仓扫描 32 处 finding，**0 处是幽灵提交**：

| 类别 | 数量 | 例 |
|---|---|---|
| data fingerprint（❌非提交声明） | 14 | ❌`verify input_hash 三轮一致 `6decf46b459cece9``、`matrix_md5=3c8e35f6…` |
| runtime-id（❌非提交声明） | 6 | ❌ 容器 `940e36878ccc1`、pod `511560a95a06b` |
| registered-external（❌非提交声明） | 9 | ❌ amend 掉的中转提交 `441cef4`/`f6ea7aa`；外部仓 cspm-agent 基线 `9d51fcd`/`e9714fe` |
| 守卫自身示例（❌第 7 例，已修） | 3 | ❌ architect-test/guide.md 逐字复刻的 defaced / effaced / abc123d |

修掉 3 处自伤后剩 29 处全部可解释（`unexplained 0`，脚本 exit 0）。

## 3. 归因

规则没错，**语料不同**：git 对象库之外的世界（容器运行时、数据集指纹、被 amend 掉的提交、没 checkout 的外部仓）本来就充满「像哈希但不是提交」的值。把 fail-closed 门禁直接挪到外部语料，会把 32 个合法值全部报成假哈希 —— 假阳性淹没真信号。

## 4. 修复（step A，commit `fb993dc`）

`tests/test_wake_pointer_chain.py`

1. **全长度哈希解析**：缩写表只有 `%h`（7 字符），8~40 字符的哈希在任何仓都解析不出 → 误报。新增 `_subject_direct()`（`git log -1 <h>^{commit}`）与 `_to_full()` 的 `len(h) > 7` 分支。
2. **带分隔符的指纹标签**：`DIGEST_LABEL_RE` 原要求标签在**行尾**，`matrix_md5=<32hex>` 因此被读成提交声明 → 允许 `[:=]` 分隔符。
3. **分类器（fail-closed）**：`classify_finding()` 只回答「为什么它不是提交声明」，默认仍是 `phantom`：
   - 缺陷标记行 → `defect-marked`；
   - `REGISTERED_UNRESOLVABLE` 登记值（amend 中转 / 外部仓基线，逐条带出处）→ `registered-external`；
   - 行内出现 md5/sha/checksum/digest/input_hash/指纹 或 token 长度 ∈ {16,32,64} → `fingerprint`；
   - token 出现在**同一篇文档**的运行时对象行（crictl/pod/sandbox/容器/沙箱）上 → `runtime-id`；
   - 其余 → `phantom`。
4. `scripts/audit_cross_repo_ledger.py`：同一套规则跑向兄弟语料并逐条打印分类；**只剩无法解释的 `phantom` 才 exit 1**。它是取证报告工具，**不接入 pytest 门禁**。

## 5. 验证

- `pytest tests/test_wake_pointer_chain.py` → **27 passed**（20 → 27）；全量 `pytest tests sloth_engine/tests -q` → **1615 passed / 1 xfailed / coverage 78.73%**（1608 → 1615，coverage 持平）。
- `python scripts/audit_cross_repo_ledger.py` → sloth-loop 20 处（runtime-id 6 / fingerprint 14）、architect-skills 9 处（registered-external 9）、**unexplained 0**、exit 0。
- architect-skills：`validate-contracts.mjs` → 19 atom / 0 错 / 0 警；`run-l1-tests.mjs` → 32 passed。

## 6. 边界（关键）

- **门禁仍只扫本仓**：`ledger_targets()` = 本仓 tracked+pending `.md`；兄弟仓只在**解析**时作为已知仓参与。分类器**只用于取证脚本**；本仓账本依旧走 `phantom_hash_problems()` 的无分类 fail-closed 判定 → 伪造的 16/32 位哈希在本仓仍是硬 FAIL。
- 分类器**故意粗糙**：行内只要**命名**了 digest（哪怕没有 `=`/`:`）就归 fingerprint；16/32/64 位 hex 一律视为摘要。残余风险：一篇文档在「校验和」语境下写出的**伪造**提交声明会被豁免 —— 已被「分类器不参与门禁」这条边界封住。
- `runtime-id` 是**文档级**判定：文档里有一行 crictl，该文档内所有短 hex token 都归 runtime-id。风险同上，且有界。
- 语料口径 = 各仓 **shipped markdown**；机器可读契约 JSON 里的规则文案（TES-15/17/18 的 trigger 文本本身会举例）不算账本。
- 「守卫示例」也是账本内容：architect-test/guide.md 曾用代码跨度逐字复刻守卫示例 token，一旦该语料被纳入扫描，文档自己就 FAIL；已改为不带代码跨度的普通文字。

## 7. 结论

**「只在一个仓里校验的守卫」=「只在一个仓里成立的事实」**：守卫的能力边界必须和它的**语料边界**一起写下来，否则跨仓引用一多，守卫就会从「找错」退化成「报假阳性」。

同族缺陷已累计七例（cycle-16 漏测 → 17 门禁没自证 → 18 提交链没人验证 → 19 缺陷描述复刻假形态 → 20 散文/箭头链裸奔 → 21 裸哈希裸奔 → 22 守卫示例被复刻进文档）。长期结论不变：**「没人校验的记录」=「还没被发现的错」**；每加一层守卫，先用已知坏样本自证抓得住，再证明当前语料 0 误报。
