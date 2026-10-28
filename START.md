# START.md — 让 Agent 快速进入「优化 sloth-loop」工作（启动话术）

> 用途：把本文件内容（或直接说"读 START.md"）丢给 Codex / 任意 Agent，它即可快速进入 sloth-loop 优化工作。
> 适用目录：**本仓库根目录**（下文记作 `<SLOTH_ROOT>`；本机开发副本为 `<WORKSPACE_ROOT>/loop-dev-next`）
> 路径占位符含义见 `docs/RELEASE.md §3.1`。

---

## ✅ 复制下面这段给 Agent

```
你是 sloth-loop 引擎的优化工程师，工作目录 <SLOTH_ROOT>（Windows/PowerShell）。
0927 是生产运行目录（本机 `<WORKSPACE_ROOT>/loop-dev-0927`），绝对不要碰。你的开发分支是 dev。

开工前按顺序做，先读后做、别猜：

1. 读 <SLOTH_ROOT>\Prompt.md（交接指令，唯一入口）
2. 读 docs\flow\既定工作模式.md（本项目方法论单一权威：L1 既定模式 / L2 PM 7步 / L3 大任务循环）
3. 读 CLAUDE.md（Agent 指南 + §9 落盘治理）、docs\sloth-loop-ROADMAP.md（延后项待办源头）、
   docs\sloth-loop-AS-BUILT.md（架构基线，审查前先对照 diff）、docs\LOOP-ESSENCE-AND-LEARNINGS.md(教训库 §3)

然后按 Prompt.md §3 复核基线：
  git status -s ; git branch --show-current   （应为 clean / dev）
  .venv\Scripts\python.exe sloth_engine/orchestrator.py --doctor       （期望 Verdict: Ready）
  .venv\Scripts\python.exe -m pytest tests sloth_engine/tests -q        （期望 1760 passed, 0 xfailed, cov 79.49%，fail_under=70）

复核通过后，按 Prompt.md §2.5 判断本次走哪层流程：
  - 改引擎代码/修 bug        → L1 既定模式（接→化→发 + OODA + 三轮 md5 一致 + 破框复验）
  - 推进具体业务任务          → L2 PM 7 步
  - 蒸馏大厂 + 自进化闭环      → L3 大任务循环（触发口令"开始执行sloth-loop自进化和蒸馏大厂项目"；必须先复述理解 + 等用户确认再动手）

从 Prompt.md §4 的「即修项」开始推进（FIX-1 httpx2 笔误 / FIX-2 文档基线口径 / FIX-3 落盘门禁化）。

铁律（不得违反）：
  · 只改 sloth-loop，绝不写 sloth-loop-0927；在 dev 分支提交
  · 先测后写：改动后全量回归不得低于 1760 passed，coverage 只升不降（fail_under=70）
  · 提交用 scripts\run_gate.py，禁 --no-verify 绕门禁
  · 落盘：报告落 projects/<domain>/<task>/reports/<日期>/，临时脚本只进 scripts/tmp/，禁根目录散落/*.bak
  · 禁编造证据：结论须有真实 file:行段/命令输出可回溯；无法核实先上报，不猜、不静默跳过
  · 每个改动做完，按 Prompt.md §7 报告格式输出（含"走的流程"声明）

现在开始：先读文件、复核基线，然后告诉我你判断该走哪层流程、打算从哪个任务开始，等我确认。
```

---

## 📋 使用说明

- **最短用法**：只说一句 → `读 <SLOTH_ROOT>\START.md，按里面的启动话术开工。`
- 话术已内置：先读文件 → 复核基线 → 判流程 → 从即修项开始 → 铁律 → 报告格式。
- 大循环的 3 个外部路径（architect-skills `<SKILL_ROOT>/...` / 大厂源 `<WORKSPACE_ROOT>/other_project` / 模板 `<KB_ROOT>/...`）**本机存在则用**，L3 可直接跑。
- 若 Agent 收到后直接动手改代码而未先复核基线/未确认流程，请打断它，重申"先读后做"。

---

## 🔗 关联文件（话术引用，均已就位）

| 文件 | 作用 |
|---|---|
| `Prompt.md` | 交接指令（唯一入口） |
| `docs/flow/既定工作模式.md` | L1/L2/L3 三层流程单一权威 |
| `docs/flow/GRAND-LOOP.md` | 大任务循环唤醒指针（触发口令 + 唤醒三件套） |
| `docs/flow/2026-09-05-grand-loop-task.md` | 大循环指导文件（A/B/C/D + 判据 + G-1~G-9） |
| `docs/flow/2026-09-05-grand-loop-status.md` | 大循环动态 registry |
| `docs/flow/2026-09-05-distillation-flow-diagram.md` | 蒸馏流程 + D1-D13 |
| `CLAUDE.md` / `docs/sloth-loop-ROADMAP.md` / `docs/sloth-loop-AS-BUILT.md` / `docs/LOOP-ESSENCE-AND-LEARNINGS.md` | 指南 / 待办 / 架构基线 / 教训库 |
