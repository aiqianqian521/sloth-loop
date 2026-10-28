# cycle-28 A · 护栏门禁的三重盲区 + 首次建库竞态

- 日期：2026-10-25
- 触发：`loop-test-output/loop-eval-20261025-fullstress` 独立复跑（T2/T4/T6）
- 轮次：cycle-28 A（commit `a58bf55`）/ C/D（本文件提交）

## 1. 为什么既有 1642 用例全绿却仍有真缺陷

Guardian 位于**每一次 subprocess spawn 之前**，但：

| 模块 | 既有测试 | 结论 |
|---|---|---|
| `guardian/risk_assessor.py` | 0 处直接引用 | `assess()` 从未被驱动；覆盖数字来自模块导入 |
| `guardian/permission_matrix.py` | 0 处 `arg_rules/resolve_risk` | 层级语义无人校验 |
| `runtime_paths.ContainmentError` | 0 处断言其渲染 | 报文语义无人校验 |
| `memory_store` 的迁移拒绝分支 | 0 处断言 | 竞态不可见 |

**面（module）被导入 不等于 逻辑被驱动**。本轮把「安全护栏的行为覆盖」登记为第 13 个缺陷面。

## 2. D-G1 · 路径段关键字被当成命令（功能性阻断）

- 复现：runtime root = `.../loop-eval-20261025-fullstress/runtime/smoke`，`--once` → exit 1，
  `回测解释器被拒绝: guardian . escapes runtime root .`。
- 取证（直接调 `RiskAssessor.assess`）：`decision=deny`, `score=0.6`,
  `reason="Dynamic code evaluation"`, 命中跨度落在 `loop-eval-2026` 的 `eval`（(136,140)）。
- 修复：`_is_intermediate_path_segment()`——匹配落在路径 token 非末段则忽略；
  末段仍判定（`/usr/bin/sudo` 仍拦）。
- 残余：路径若含**空格**（`E:/x/nc -l/y`），跨空格的模式仍可能误判；已在用例注释中标注。

## 3. D-G2 · 策略拒绝的诚实渲染

修复前 `ContainmentError(Path("."), Path("."), kind="guardian")` 渲染为
`guardian . escapes runtime root .`；适配器再包 `回测解释器被拒绝`（且与**真的**解释器越界报文不可区分）。
修复后：

```
回测被安全策略拒绝: guardian policy denied the command (security gate; no path escape):
                   Infinite loop pattern (risk=0.60)
回测解释器被拒绝: interpreter <python> escapes runtime root <RUNTIME_ROOT>/t6/deny-interp
```

## 4. D-G3 · arg_rules 层级语义

文档承诺 `{"command": {"rm -rf*": BLOCK}}` 通配语义，实现只做等值匹配 ⇒
`sudo ` / `chmod 777` / `nc -l` / `:(){` 等 BLOCK 字面量从未命中。
修复：`*` 结尾 = 前缀；否则 = 子串。残余 `curl |` / `wget |`（流水线中间隔 URL），
仍被 `_HIGH_RISK_PATTERNS` 拦下（escalate 1.0），行为不变。

## 5. D-C1 · 并发首建库

`exists() and size>0` 是 TOCTOU：竞态进程先建文件、后提交账本 ⇒ 观察者读到 v0/v2/v3 ⇒
`auto_migrate=False` 直接抛「需要迁移」。修复后并发失败者转为**运行锁**拒绝
（T4 S1：migration required 3 → **0**，Cannot acquire run lock 0 → **3**）。

## 6. 复验

- `pytest tests sloth_engine/tests -q` → 1668 passed / 1 xfailed / **78.87%**
- `scripts/run_gate.py --all` → PASS
- T1..T7 全绿；T6 矩阵 0 mismatch；T4 并发无残留锁、SQLite `ok`
- 冻结项（N-3 / R3 / coze I-1/I-3/I-4 / cycle-12 11/12/13 / WebUI / `llm_review()` / 每项目沙箱）未触碰
