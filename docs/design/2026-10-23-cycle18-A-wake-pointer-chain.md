# cycle-18 A/C：唤醒指针提交链自证（提交链 vs git 实测 + TES-14/DOC-06）· 2026-10-23

> step A 的代码提交 `c758387`（B 增量 `ee725bf`，architect-skills 仓），本轮基线刷新为 **1596 / 78.73**（原 1588 / 78.73）。
> 本文件为 step C（19 维增量评估 + 观察项登记）与用户裁定登记，随 D 轮唤醒指针一并落盘。

## 一、缺陷：守护者无人守护（同族第三处）

cycle-16 修「被门禁漏掉的测试」，cycle-17 修「门禁自己没人验证」，本轮修 **「唤醒指针的提交链没人验证」**。
`docs/flow/GRAND-LOOP.md` 是新 agent 读的第一份文件，它用一段「提交链」把"哪个 cycle 由哪个 commit 落地"记下来：

```
（修复前原文照拄；`❌错记` 标记由本次审计添加）
`b2dd73e`(architect-skills cycle-15 B：…) → `710a3af`(❌错记 cycle-16 A：权限门调用点修复 …) →
`006eea4`(architect-skills cycle-16 B：…) → `710a3af`(cycle-17 A：门禁自证 …) → `88fa263`(…)
```

**缺陷（severity high）**：

1. **cycle-16 A 的哈希是错的**：被记成 `710a3af`，而 `710a3af` 实际是 **cycle-17 A** 的提交；
   cycle-16 A 的真哈希 `a09421a` 在全文中 **0 次出现**。
2. **重复哈希把缺失掩盖成"看起来完整"**：同一段文字里出现两次 `710a3af`，肉眼扫过去"每个 cycle 都有哈希"，
   没有人会去数哈希是否唯一。
3. **没有任何门禁会报警**：`run_gate.py` 校验基线口径、孤儿机制、pytest 与覆盖率，但不校验唤醒指针；
   `tests/` 里也不存在任何解析 GRAND-LOOP 提交链的测试。
4. **危害面大**：任何照链取证的 agent（按链回溯代码、写交接摘要、做归因/复盘）都会拿到错哈希，
   而错哈希在"记录 → 推理 → 结论"的链条里会一路被当成事实。

## 二、修复（step A：commit `c758387`，5 files→2 files / +8 用例）

- `docs/flow/GRAND-LOOP.md`：`710a3af`(❌错记 cycle-16 A）→ `a09421a`(cycle-16 A）。
- 新增 `tests/test_wake_pointer_chain.py`（8 例），解析**活文档**（不使用桩夹具），fail-closed 五条：
  1. 链段落可定位：标题行 `**cycle-A → cycle-B …**` 起，到首个空行或下一个 `**` 行为止；`head` 指针可定位；
  2. 每条 `cycle-N` 记录须在 git 中存在，且其**提交主题**里的 cycle 号不得与之矛盾（允许主题不带 cycle 号）；
  3. 同一哈希不得标注两个不同 cycle；
  4. 链标题跨度 `cycle-A → cycle-B` 的 B 必须等于最新条目；
  5. `head` 指针的哈希必须等于 `docs/baseline.json.head`（跨源交叉）。
- 兄弟仓（architect-skills）的 B 提交：**兄弟仓存在时必须校验**（提交主题须含 `cycle-N`），
  兄弟仓不存在时登记为"机器本地缺口"、**不降级**为静默通过；另有覆盖度自证（解析条目数 ≥ 阈值、本地条目数 ≥ 阈值）。
- 工效：git 查询批量化（每仓一次 `git log --all` + 进程内记忆化）。首版逐条目 spawn git 使该文件耗时 ~45s，
  **这本身就是门禁质量缺陷**（守卫拖慢套件 → 被人为跳过），优化后 10s。

### 自证（可复现）

把真实文本改回缺陷态后运行守卫：

```
live violations: []
pre-fix(cycle-16 A == 710a3af) violations:
  - hash 710a3af is annotated with conflicting cycles [16, 17]
  - hash 710a3af annotated cycle-16 but its commit says cycle-17 (fix(cycle-17 A): make the local gate prove itself …)
```

另有 4 条负例测试（错标注 / 重复哈希 / 标题跨度不符 / 锚点丢失 / head 漂移）保证守卫自身有效：
**一个不会失败的守卫等于没有守卫**。

## 三、验证（实测）

| 项目 | 结果 |
|---|---|
| 全量 pytest | **1596 passed / 1 xfailed / coverage 78.73%**（原 1588 / 78.73，+8 用例，coverage 持平） |
| `scripts/run_gate.py --all` | PASS（含 baseline-vs-measured 单向棘轮 OK） |
| `scripts/docs_baseline.py` | OK（9 个当前态文档口径一致） |
| `scripts/check_orphan_mechanisms.py` | OK（wired 73 / test_only 15 / exempt 1 / orphan 0 / stale 0） |
| architect-skills `validate-contracts.mjs` | 19 atom / 0 错 / 0 警 |
| architect-skills `run-l1-tests.mjs` | 32 passed |

## 四、step B：architect-skills 增量（commit `ee725bf`，master）

- `architect-test` 检查清单 13→**14（TES-14）**：文档/指针里的提交链与哈希引用必须被机器校验
  （存在性 + 主题不矛盾 + 同哈希不得双标 + 标题跨度 + 跨源 `head` 交叉），守卫须有负例自证与覆盖度自证。
- `architect-docs` 检查清单 5→**6（DOC-06）**：文档中的机器可读引用（提交哈希 / 版本号 / 基线数字 / 配置键名）
  必须有校验器并与单一事实源交叉，禁止只靠人工同步。
- 二者均补 `guide.md` 检查清单行 + `## cycle-18 实测增补` 节 + 口径演进注；`ARCHITECTURE-COVERAGE.md §5` 记 cycle-18。

## 五、step C：19 维增量评估（cycle-17 → cycle-18）

| 维度 | cycle-17 | cycle-18 | 备注 |
|---|---|---|---|
| 维度总数 | 19 | 19（不变） | 本轮不新增维度 |
| covered / partial / N/A | 14 / 4 / 1 | 14 / 4 / 1（不变） | 缺陷落在既有维度内 |
| `test` 维清单 | TES-01..13 | **TES-01..14**（+TES-14 提交链/哈希引用机器校验） | architect-skills `ee725bf` |
| `docs` 维清单 | DOC-01..05 | **DOC-01..06**（+DOC-06 机器可读引用须校验器 + 单一事实源） | architect-skills `ee725bf` |
| GRAND-LOOP 唤醒指针 | 提交链无人校验 | 链被行为校验（活文档解析 + 负例 + 覆盖度自证 + 跨源 head） | 本轮新增 |
| 同族缺陷计数 | 2（cycle-16/17） | **3** | "记录 vs 真值"：被漏掉的测试 / 门禁自身 / 提交链 |

## 六、观察项与用户裁定

**观察项（如实登记，不夸大）**：

1. 链中**不带 cycle 标注**的条目（如 `3da60e1`(基线 1343/73.50)）只做存在性校验，不做语义校验 ——
   它们没有可对照的标注，属于"低风险但未闭合"的残余面。
2. 兄弟仓缺失时，architect-skills 的 B 提交条目退化为"未校验"；已用 **覆盖度阈值** + 兄弟仓存在时**强制校验**兜底，
   但跨机行为仍有差异（本机存在，因此始终被校验）。
3. 守卫校验的是**提交主题与标注的一致性**，不校验"这条 commit 是否真的是该 cycle 的工作"（语义真值），
   后者需要人工/评审，故登记为残余风险。

**用户裁定沿用（2026-10-23，本轮无新增）**：N-3（真实厂商额度源）/ R3（真实模型·24h soak）**不做**，仅文档登记；
coze I-1/I-3/I-4、cycle-12 条目 11/12/13 维持 **candidate-pending**；**R2（每项目沙箱）/ WebUI /
`guardian/risk_assessor.py::llm_review()` 不动**（未碰，如实登记）。

## 七、step D：回归与收口

- `docs/flow/GRAND-LOOP.md` 唤醒指针刷新（head `c758387`、基线 **1596/78.73**、提交链追加 cycle-18 条目、
  标题跨度 cycle-5 → cycle-18、下一目标指向 §13.43）。
- `docs/baseline.json`（单一事实源）：passed 1588 → **1596**，head `710a3af` → **`c758387`**，coverage 78.73 不变。
- 9 个当前态文档口径同步（README / CLAUDE / RUNBOOK / ONBOARDING / Prompt / AS-BUILT / ROADMAP / DEV-SETUP / USAGE）。
- 工作树 clean；全量无跳过（D11）；本轮无残余执行错误。
