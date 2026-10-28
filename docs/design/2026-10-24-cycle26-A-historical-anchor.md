# cycle-26 A 设计说明 · 一致性校验必须区分『当前态』与『历史态』

> 结论：2026-10-24。本循环走 A→B→C→D。step A 提交 `b222d45`，B 轮 `29e7fc1`（architect-skills，TES-22 + DOC-13）。
> 实况 1625 / 78.73 → **1632 / 78.73**（+7 用例；coverage 持平）。

## 1. 背景

`scripts/docs_baseline.py`（cycle-17 A 交付、cycle-24 A 扩了作用域）以 `docs/baseline.json` 为单一来源，断言每份当前态文档都引用同一套基线数字。它的判据是 `search`：文档里**出现过** `1625 passed` 就算过。

cycle-24 A 的 §6 已把这条登记为**已知边界**：

> `docs_baseline` 只断言「文档里出现该数字」，不断言「只出现该数字」……

本循环把这个边界收掉。收紧方式不是「只允许出现基线数字」（那会与历史叙述冲突），而是 **「其余数字必须被显式标注为历史」**。

## 2. 发现（可复现证据）

- `docs/sloth-loop-AS-BUILT.md:169`：`# 实测：758 passed / 3 xfailed / 1 xpassed，coverage 70.48% > fail_under 64`——在 `## 验证命令与结果` 的代码块里，与文件顶部的 1625 只隔几十行；
- `docs/sloth-loop-ROADMAP.md` §4：`734 / 745 / 755 / 758 passed` 四组历史里程碑，全部无锚点；
- 旧守卫对以上 7 处**零报告**（`docs_baseline` OK）。

一份把 758 与 1625 并排、又不标注「758 是旧的」的文档，正是「旧数字被读成现值」的入口——而本仓读者主要是 agent。

## 3. 边界（刻意不做的）

- 不要求「只出现基线数字」：历史叙述合法，硬性唯一会与历史记录冲突；
- 不校验「锚点 ↔ 数字」的**对应关系**（有锚点即可，锚点是否是那天的真值仍靠人）；
- 不纳入迁移 / 设计记录类文档（不在 `CHECK_FILES` 内是刻意的）；
- 3 位以下数字（`1/1 passed`、`3 passed` 这类步骤计数）不在口径内。

## 4. 方案（step A，commit `b222d45`）

`scripts/docs_baseline.py`：

1. `blocks(text)`：把文档切成**块**——非空行为单位，列表项 / 标题 / 引用起新块；
   - 曾试过「锚点取最近的标题」，但 `# 期望：…（2026-10-24…）` 这种**代码块里的注释**会被当成标题，把整篇文档洗白 → 作用域改为「块」，并顺带把块级判定暴露成可单测的函数；
2. `unanchored_suite_counts(text, passed)`：返回「既不是基线、又不在带锚点块内」的 3 位以上 `N passed`（含行号）；
3. `check()` 逐份 `CHECK_FILES` 报出，违反项附文件名 + 行号 + 数字；
4. 锚点 = 日期 `20xx` / `cycle-N` / 「历史」，可在**块内任意行**（列表项续行也算）。

文档侧：7 处历史数字补「（历史快照）」。

`tests/test_gate_self_verification.py`（26 → 33）：无锚点 stale 必须 FAIL；日期 / cycle / 「历史」三种锚点通过（且可在块的任意行）；基线与步进计数豁免；合成仓 `check()` 红绿；真实仓逐文件 fail-closed 扫描。

## 5. 验证

- 收紧前：同一批数字 → `docs_baseline` OK（漏报）；收紧后 → FAIL 7 条（逐条点名行号），补锚点后 OK；
- `pytest tests sloth_engine/tests -q` → **1632 passed / 1 xfailed / coverage 78.73%**（1625 → 1632）；
- `run_gate.py --all` → PASS（baseline-vs-measured / docs-baseline / orphan-mechanisms 全 OK）；
- architect-skills：`validate-contracts.mjs` → 19 atom / 0 错 / 0 警、`run-l1-tests.mjs` → 32 passed、跨仓账本扫描 unexplained 0 / exit 0。

## 6. 残余风险

- 锚点只要求「可识别」，不校验「锚点 ↔ 数字」的对应——人肉可以糊弄；
- 「历史」是一个**词**而不是结构：给一节标题加「历史」即可豁免该节全部数字。这是刻意保留的粗粒度逃生口，但也是新的缩水面；
- 哈希旁的**轮次标注**（`CLAUDE.md` 的 `HEAD <hash>（cycle-16 A：…）`）本轮顺手改成不绑定轮次的措辞，但「哈希 ↔ 轮次标注一致」仍无机器校验（下一轮候选）；
- 基线若以非 `N passed` 形态出现（如覆盖率单独成句），本规则不覆盖。
