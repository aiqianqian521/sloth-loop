# cycle-30 A · 产出的证据引用必须在写出时解析到真实文件

- 日期：2026-10-25
- 来源：2026-10-25 全量压测交付目录（`loop-test-output/loop-eval-20261025-fullstress`）收尾复核时，顺 `--report` 只读面取证
- 提交：cycle-30 A `852fb84`（+10 用例）／ B（architect-skills）TES-25 + DOC-16

## 1. 取证方式（先驱动，再结论）

不看注释，直接跑 `--report` 生成带日期客户报告，再把报告里每条 `file:line:` 的目标逐个做存在性判断：

| 证据列写法 | 报告旁实际存在的文件 | 结论 |
|---|---|---|
| `file:line: data/rounds.json:1` | 无（快照在 `<runtime>/projects/<task>/runs/<ts>/data`） | 断链 |
| 其余五行 | 同左 | 断链 |

六条全断链，而报告内自校验 `validate_risk_evidence` 仍打印「干净」——它只 grep 了 `ref:` / `file:line:` 的**字面标签**。

## 2. D-R1 —— 为什么「引用前缀」是编造的

- `RunReporter` 非 run_ts 分支把 `data_dir` 算成 `<runtime.events_dir>/<run_id>`，而归档从不创建该路径；相对化后得 `..\runs\<run_id>`，再被 `except ValueError` 兜成字面量 `data`。
- 于是报告写出的 `data/<x>.json` 是一条**约定的常量前缀**，与「快照到底在哪里」无关 ⇒ 生产端在写一条自己都无法背书的事实。
- 自校验只匹配标签（「表里有标签」≠「标签指向的文件存在」）⇒ 对断链 100% 失明。这与 D-S1（把锁路径写成 `<repo>/sloth_engine/.loop.lock`，I4 不变量成空断言）同族。

## 3. 修复（「引用必须解析」）

- `validate_risk_evidence(md, base_dir=None, repo_root=None)`：逐行取 `file:line:` 路径并做**存在性**校验；相对路径对「报告目录 + 仓根」双锚点解析（`docs/...` 风险引用是仓相对的）；**无锚点＝不判**（保持旧调用者行为）。
- 生产端 `_resolve_data_ref`：快照可达 → 相对 posix；跨盘 → 绝对；否则若报告旁确有 `data/` 目录 → `data`；再无 → `SELF_CITE`（自引 `REPORT.md` §2）。
- `run_reporter._latest_archive_data_dir`：dated 报告引 `<runtime>/projects/<task>/runs/*/data` 下最新归档快照。

## 4. 边界（刻意，不「修」）

- dated `reports/<date>/REPORT.md` 是**交付物**，按 §9.4 落项目规约目录（在仓内），是 cycle-29 A 明确登记的例外，不受 `runtime.root` 约束；本轮只改它写出的引用。
- 无同目录快照时**自引**而非编造路径：引用可以指回报告自身（数字就渲染在这里），但不得指向不存在的外部文件。
- 报告内自校验只在**写出时**执行；读回旧报告不会补跑校验（登记为残余边界）。

## 5. B 轮口径（architect-skills）

TES-25 / DOC-16：**产出的证据引用必须在写出时解析到真实文件；无同目录快照必须自引；产物自带自校验必须校验存在性，且需传入解析锚点**（只匹配标签＝对断链失明）。与 cycle-23「交付的验证器本身必须被验证」同族——从「验证器被执行」推进到「验证器校验的对象真实存在」。

## 6. 验收

- `pytest tests sloth_engine/tests -q` → 1692 passed / 1 xfailed / **79.17%**
- `scripts/run_gate.py --all` → PASS；`docs_baseline.check() == []`；`tests/test_wake_pointer_chain.py` 全绿
- B 侧：`node scripts/validate-contracts.mjs` → 19 atom / 0 错 / 0 警；`node tests/run-l1-tests.mjs` → 32 passed；跨仓账本 `unexplained 0 / exit 0`

## 7. 冻结项（不动）

N-3 / R3（真实额度源、真实模型 24h soak）；coze I-1/I-3/I-4、cycle-12 条目 11/12/13；WebUI / 每项目文件沙箱；`guardian/risk_assessor.py::llm_review()`（保持 `NotImplementedError`）。
