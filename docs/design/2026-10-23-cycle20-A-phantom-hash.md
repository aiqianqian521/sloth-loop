# cycle-20 A：账本「幽灵哈希」全仓清扫 + 箭头链拓扑守卫 2026-10-23

> step A 提交 `d2affd3`；A3 提交 `748cecd`；B 增量 `edbcce0`（architect-skills：TES-16 + DOC-07）。
> 基线 1598 / 78.73 → **1604 / 78.73**（+6 例，coverage 不变）；本机三仓交叉取证。

## 一、缺陷家族（第五例）：prose 里的哈希从来没人守

cycle-16 门禁漏采测试 → cycle-17 门禁自身无人验证 → cycle-18 唤醒指针的提交链无人验证 →
cycle-19 缺陷描述复刻了错形态 → cycle-19 A2 守卫看不见「正在写」的文件 →
**cycle-20：正文散文里的哈希、`A→B→C` 箭头链没有任何守卫**。

用户直问：**「任何照链取证的 agent（回溯代码、写交接、做归因）都会拿到错哈希，而错哈希会被当成事实一路传递。这个修复了嘛？」**

**答：没修全。** cycle-18/19 只守住 `` `hash`(cycle-N) `` 声明形态与 GRAND-LOOP 的 `**cycle-5 → cycle-19**` 区块；
正文散文里的裸哈希与箭头链从未被检查。三仓交叉取证（sloth-loop / legacy `sloth-loop` / architect-skills）命中 **3 个幽灵哈希** —— 在任何仓库都解析不出：

| 文件 | 记录值 | 真值 | 性质 |
|---|---|---|---|
| `docs/flow/GRAND-LOOP.md` L53 | ❌错记 `11588a1` | `11542a1` | 转置错字 42→88；`1fb4846→?→edf2a55` 的真实中间提交 |
| `docs/design/2026-10-22-cycle14-C-state-history-export.md` L4 | ❌错记 `a67594c` | `a67594e` | 转置错字 c→e；该文档**自己的** step A 提交 |
| `docs/flow/2026-09-05-grand-loop-status.md` §13.9 | ❌错记 `8cf9d4c` | `eb9f4b6` | 完全不同的错值；真值是建 `sloth_engine/backpressure.py` 的 cycle-4 A4 |

取证方法（可复现）：把每个 7–40 位 hex token 在三个仓的 `git log --all` 缩写表里解析；❌错记 `11588a1` 无命中，
而 `git log --reverse 1fb4846..edf2a55` 显示真实存在的居间提交就是 `11542a1`。

> 粗扫还命中 `cfd2d6ef…`，但它是「外部发现重测产物」的 **md5**（文中有 `md5` 标签），不是提交哈希 → 守卫按标签排除。

## 二、step A：修 3 处 + 建守卫

1. 修正上表 3 处记录（每处 1 行）。
2. `tests/test_wake_pointer_chain.py`：10 → **16 例**
   - `test_no_shipped_document_names_a_nonexistent_hash`：**shipped `.md`**（`git ls-files --cached --others --exclude-standard`）里的每个哈希 token
     必须解析到**已知仓**；解析不出即违例（fail-closed）。token 形态 = 反引号哈希 + 箭头链裸哈希（反引号先展平）。
   - `test_shipped_arrow_chains_are_ancestor_ordered`：箭头链里**同仓相邻**哈希必须**祖先相关**（一次 `rev-list --all --topo-order --parents` 建祖先表）。
   - 阈值守卫（防「扫描器空转」）：`scanned > 30`、`runs >= 1`。
   - 负例自证 ×3：幽灵被捕获 / **被标记**的幽灵放行 / 乱序箭头被捕获（合成双分支仓；用 `-c core.hooksPath=` 绕开本机 20s 的 AK hook）。

### A2（自查发现，同 cycle-19 A2 家族）

自证探针里放一条**带反引号**的乱序箭头链 → 守卫**没报**。根因：`ARROW_RUN_RE` 只认裸哈希，带反引号的箭头链整段漏检。
修：匹配前把反引号展平为空格（`_tokens_in_line` 与 `arrow_topology_problems` **两处**都改）。修后探针立刻 FAIL。

> 教训（同族第三次）：**守卫的自证必须覆盖「守卫自己宣称能抓的每一种形态」** —— 否则守卫的说明与守卫的能力脱节，
> 脱节本身又是一次「记录 vs 真值」。

### A3（写文档时守卫反弹）

写完本文档后跑守卫，**守卫直接在本文档上报错**：`20261023` resolved in no known repo。
根因是守卫自己的精度缺陷（纯数字 token 被当成哈希），不是文档错。修：纯数字一律排除 + 边界自证用例。
教训：**守卫的第一个真实用户就是它自己的文档** —— 误报会直接把人逼向「把守卫关掉」。

## 三、边界与已知局限（诚实记录）

- 只扫**反引号哈希**与**箭头链**（不扫任意裸 hex），且**纯数字 token 一律排除**：
  `20261023` 这类日期/版本号是确定的误报源，而真·纯数字缩写（7 位约 3.7%）会漏 —— 已登记为已知局限。
  **约定**：账本里提交哈希一律反引号（或进箭头链）。
- **跨仓**箭头不做拓扑校验（跨仓祖先关系无定义），只做存在性。
- legacy `sloth-loop` / architect-skills 不在本机时，对应哈希降级为「未校验」（不静默通过；`_known_repos()` 显式列出在场仓）。
- 引用缺陷值必须**同行标记**（❌错记 / phantom / NOT-A-COMMIT），否则视为声明 —— 两条规则（存在性、拓扑）都吃这个豁免。

## 四、验证（实测）

| 项 | 结果 |
|---|---|
| 全量 pytest | **1604 passed / 1 xfailed / coverage 78.73%**?1598 ? +6? |
| 幽灵规则自证 | 探针行 ❌错记 `bad0bad` / ❌错记 `599ea55` → FAIL（解析不出）；删除 → 0 违例 |
| 拓扑规则自证 | 探针行 ❌错记 `f79f96a`→`92d6d0b`（都真实、都在 legacy、非祖先）→ FAIL；删除 → 0 违例 |
| B（architect-skills） | TES-16 / DOC-07；`validate-contracts.mjs` 19 atom / 0 错 / 0 警；`run-l1-tests.mjs` 32 passed |

## 五、结论

「错哈希被当事实传递」在 cycle-20 之前**只堵住了一半**：声明形态与唤醒指针区块有守卫，**散文与箭头链完全裸奔**，
且实测已有 3 处幽灵在链上流通。cycle-20 把它变成**机器持续保证**：任何 shipped `.md` 只要出现解析不出的哈希、
或同仓乱序箭头链，门禁即 FAIL。
