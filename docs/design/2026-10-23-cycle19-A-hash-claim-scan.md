# cycle-19 A/C：假哈希声明全仓扫描（缺陷引用不得伪装成声明 + TES-15）· 2026-10-23

> step A 的代码提交 `42928fa`（B 增量 `d3f2ea6`，architect-skills 仓），本轮基线刷新为 **1598 / 78.73**
> （原 1596 / 78.73）。本文件为 step C（19 维增量评估 + 观察项登记）与用户裁定登记，随 D 轮唤醒指针一并落盘。

## 一、缺陷：记录里的否定句被读成肯定句（同族第四处）

cycle-16 修「被门禁漏掉的测试」→ cycle-17 修「门禁自己没人验证」→ cycle-18 修「唤醒指针的提交链没人验证」。
cycle-18 的修复本身是对的，但**它自己的缺陷描述又把错哈希写回成了声明形态**：

- `docs/design/2026-10-23-cycle18-A-wake-pointer-chain.md`：2 处（含一段"修复前原文照抄"的栅栏块），
  写成「哈希 + 紧跟 (cycle-16 A」；
- `docs/flow/2026-09-05-grand-loop-status.md` §13.43：1 处，同样形态；
- `work_ooda/.../cycle18-A.../RECORD.md`（未纳版本控制）：1 处。

cycle-18 的守卫**只解析 GRAND-LOOP 的链段落**，所以这几处假声明照旧存活：一个 agent 只要 grep 证据，
就会读到一个"cycle-16 A = 710a3af"的**机器可读假声明**。换言之：**修完"记录错了"，没修"记录里写着那个错"**。

## 二、修复（step A：commit `42928fa`，3 files / +2 用例）

1. **全仓扫描**（`tests/test_wake_pointer_chain.py`）：
   - `test_no_document_claims_a_hash_for_the_wrong_cycle`：遍历 `git ls-files --cached --others --exclude-standard`（tracked + 待提交）与本机 `work_ooda/**/*.md` 的 .md/.json/.py，
     对每条「哈希 + 紧跟 (cycle-N」声明对照 git 提交主题（存在性 + 主题不矛盾），fail-closed；
   - **覆盖度自证**：命中数必须 >= 15（防"解析为空 → 全绿"）；
   - **负例自证**：`test_the_repo_scan_catches_a_doctored_claim`（把真实文本改坏必须报错）。
   - 复用 cycle-18 的批量化 `git log --all` 缓存（每仓一次），不让守卫拖慢套件。
2. **缺陷引用改用可区分形态**：文档里的错哈希写成「哈希 + (❌错记 cycle-16 A」并在引用块顶加图例
   （`（修复前原文照抄；❌错记 标记由本次审计添加）`），使 **"提到错值" 与 "声明记录" 在机器上可区分**。

### 首跑证据（修复前）

三条告警（为避免把该形态又写回文档，此处只作描述）：

- `docs/design/2026-10-23-cycle18-A-wake-pointer-chain.md`：2 处（含“修复前原文照拄”栅栏块）
- `docs/flow/2026-09-05-grand-loop-status.md` §13.43：1 处
- 形态：错哈希 + 紧跟「(cycle-16 A」，而该哈希的提交实际是 cycle-17。

即：同一条假声明在**缺陷记录本身**里被复现 3 次。修复后同一扫描 0 违规。

## 三、验证（实测）

| 项目 | 结果 |
|---|---|
| 全量 pytest | **1598 passed / 1 xfailed / coverage 78.73%**（原 1596 / 78.73，+2 用例，coverage 持平） |
| 新扫描（tracked 全仓） | 命中 >= 15 条声明，**0 违规** |
| `scripts/run_gate.py --all` | PASS |
| `scripts/docs_baseline.py` | OK |
| `scripts/check_orphan_mechanisms.py` | OK（wired 73 / test_only 15 / exempt 1 / orphan 0 / stale 0） |
| architect-skills `validate-contracts.mjs` | 19 atom / 0 错 / 0 警 |
| architect-skills `run-l1-tests.mjs` | 32 passed |

## 四、step B：architect-skills 增量（commit `d3f2ea6`，master）

- `architect-test` 检查清单 14→**15（TES-15）**：文档里的"负例/缺陷引用"必须与机器可读的声明形态可区分
  （禁止把错值照抄成声明形态）；扫描须覆盖设计文档 / status / 交接记录；须带覆盖度自证与负例自证。
- `guide.md` 检查清单行 + `## cycle-19 实测增补` 节 + 口径演进注；`ARCHITECTURE-COVERAGE.md §5` 记 cycle-19。

## 五、step C：19 维增量评估（cycle-18 → cycle-19）

| 维度 | cycle-18 | cycle-19 | 备注 |
|---|---|---|---|
| 维度总数 | 19 | 19（不变） | 本轮不新增维度 |
| covered / partial / N/A | 14 / 4 / 1 | 14 / 4 / 1（不变） | 缺陷落在既有维度内 |
| `test` 维清单 | TES-01..14 | **TES-01..15**（+TES-15 缺陷引用不得伪装成声明） | architect-skills `d3f2ea6` |
| 全仓假声明扫描 | 无 | tracked .md/.json/.py 全量扫描 + 覆盖度/负例自证 | 本轮新增 |
| 同族缺陷计数 | 3（cycle-16/17/18） | **4** | "记录 vs 真值"：被漏掉的测试 / 门禁自身 / 提交链 / 缺陷引用的形态 |

## 六、观察项与用户裁定

**观察项（如实登记，不夸大）**：

1. 扫描覆盖 tracked + 待提交（未忽略）文件（`git ls-files --cached --others --exclude-standard`），**加上本机存在时的 `work_ooda/**/*.md`**：
   本轮修正的 cycle-18 工作记录 1 处因此已被机器覆盖；`work_ooda/` 的非 markdown 产物、`_data/` 仍靠例惯。
2. 扫描只覆盖 .md/.json/.py 三类扩展名（不含 .yml / .txt / .yml 等）；如需扩展，改 `SCAN_EXT` 即可。
3. 扫描校验"哈希与 cycle 标注不矛盾"，不校验语义真值（该提交是否真的属于该 cycle），后者仍需人工评审。

**用户裁定沿用（2026-10-23，本轮无新增）**：N-3 / R3 **不做**（仅文档登记）；coze I-1/I-3/I-4、cycle-12 条目
11/12/13 维持 **candidate-pending**；**R2 / WebUI / `guardian/risk_assessor.py::llm_review()` 不动**（未碰，如实登记）。

## 七、step D：回归与收口

- `docs/flow/GRAND-LOOP.md` 唤醒指针刷新（head `42928fa`、基线 **1598/78.73**、链追加 cycle-19 条目、
  标题跨度 cycle-5 → cycle-19、下一目标指向 §13.44）。
- `docs/baseline.json`：passed 1596 → **1598**，head `c758387` → **`42928fa`**，coverage 78.73 不变。
- 9 个当前态文档口径同步（README / CLAUDE / RUNBOOK / ONBOARDING / Prompt / AS-BUILT / ROADMAP / DEV-SETUP / USAGE）。
- 工作树 clean；全量无跳过（D11）；本轮无残余执行错误。
