# Prompt.md — sloth-loop 升级改造交接指令（给 AI Agent / Codex）

> 你在 `<SLOTH_ROOT>`（本机开发副本 `<WORKSPACE_ROOT>/loop-dev-next`；Windows，PowerShell）。这是一个 **sloth-loop 引擎的升级改造副本**。
> **路径占位符**：`<SLOTH_ROOT>` = 你当前所在的仓库根；其余 `<...>` 含义见 `docs/RELEASE.md §3.1`。
> 本文件是本次会话的**唯一入口指令**：先读完本文件 + §2 列出的必读文档，再动手。
> 生成时间：2026-10-16（v2：补齐方法论层）；基线于 **2026-10-27 刷新**（HEAD `fc492f0`）：`1760 passed / 0 xfailed / coverage 79.49%`（fail_under=70；单一来源 `docs/baseline.json`）。
> **v2 新增**：§2.1 方法论资产 + **§2.5 本项目既定工作模式与流程校验（全套流程校验）** + §6.1 流程校验项 + 铁律 11/12。

---

## 0. 一句话背景（为什么有 next 这个目录）

- `<WORKSPACE_ROOT>/loop-dev-0927` = **PM 任务的生产运行目录**，正在/将要跑真实 pm 量化任务，**不要动它**。
- `<WORKSPACE_ROOT>/loop-dev-next` = 从 0927 `git clone` 出来的**升级改造专用副本**，你在**这里**开发。
- 两者物理独立、各自有 `.venv`，互不影响。你在 next 里的任何改动**不会**影响 0927 的运行。

### 目录/分支约定
| 项 | 值 |
|---|---|
| 工作目录 | `<SLOTH_ROOT>`（本机 `<WORKSPACE_ROOT>/loop-dev-next`） |
| 你的开发分支 | `dev`（**已切好，就在这里干活**） |
| 对照基线分支 | `master`（指向 `origin/master` @ `0e7a9f0`，**只读对照，别在它上面提交**） |
| Python | `.venv\Scripts\python.exe`（Python 3.11.4，已建好、依赖已装） |
| 源仓库 | `<WORKSPACE_ROOT>/loop-dev-0927`（只读参考，**禁止写入**） |

### 环境已验证（接手先自己复核一遍，见 §3）
- `--doctor` → `Verdict: Ready`
- 全量回归 → 1760 passed, 0 xfailed, coverage 79.49%
- 门禁脚本 `scripts/run_gate.py` 存在（有变更时才真正执行）

---

## 1. 铁律（违反 = 返工）

1. **只改 `sloth-loop`，绝不写 `sloth-loop-0927`**。0927 是生产运行目录。
2. **在 `dev` 分支上提交**。功能做完、回归通过后再合回 `master`。
3. **先测后写**：任何代码改动前先跑基线（§3），改动后必须重跑全量回归，**不得低于基线**（`1760 passed`；coverage 不得低于 70，且相对 HEAD 只升不降）。
4. **提交门禁**：用 `scripts/run_gate.py`；它的 coverage ratchet 只升不降，不许手动下调 `pyproject.toml` 里的 `fail_under`。
5. **落盘规约（CLAUDE.md §9）**：
   - 引擎侧报告落 `projects/<domain>/<task>/reports/<日期>/REPORT.md`（`report_util` 已治本）。
   - 临时脚本唯一合法落点 = `scripts/tmp/`（gitignored，用完即删）。
   - 根目录是 allowlist，禁止散落脚本/草稿/日志/`*.bak`。
6. **运行时隔离**：回测脚本用仓库内相对路径；运行产物只写 `runtime.root`（仓库外）；越界 = fail-closed，**不是 bug，别去改断言**。
7. **Pattern vs Rule**：Learn 产出的是 Pattern（证据）；Rule 必须人工审批后才生效。**禁止**自动把 Learn 结果当 Rule 改 status。
8. **文档单一总账（§9.8）**：同一主题只维护一份权威文档，禁止另起 MASTER/ALL/v1/v2 多版本。
9. **Windows 中文路径/文件**：git 提交信息建议 `git commit -F <file>`（UTF-8），避免编码问题。
10. **不许 `--no-verify` 绕门禁**。
11. **按流程走（§2.5 全套流程校验）**：改引擎走 L1 既定模式（含三轮 md5 一致 + 破框）；推进业务任务走 L2 7 步；长期自进化走 L3 大任务循环（**复述+等用户确认后才动手**）。任何任务都要在报告里声明走了哪层、并给流程验收证据。
12. **禁编造证据**：所有结论须有真实 `file:行段`/命令输出可回溯；无法核实的先上报，不猜、不静默跳过。

---

## 2. 必读文档（按顺序，读这些就够，别全库乱翻）

1. `CLAUDE.md`（根）—— Agent 指南 + §9 落盘治理规约。
2. `docs/sloth-loop-项目介绍与规划.md` —— ⭐ 权威架构总览。
3. `docs/sloth-loop-AS-BUILT.md` —— as-built 单点基线 + 15 维覆盖矩阵（**审查前先对照它 diff，别从零人肉重扫**）。
4. `docs/sloth-loop-ROADMAP.md` —— 延后项唯一待办源头 + 触发条件 + 铁律。
5. `docs/CONTEXT.md` —— 领域术语（Task/Run/Round/Step/Pattern/Rule/Checkpoint/Event）。
6. `docs/RELEASE.md` —— 发布/打包规范 + 必须包含/排除清单。
7. `docs/sloth-loop-CHANGELOG.md`、`docs/sloth-loop-USAGE.md`、`docs/sloth-loop-DEV-SETUP.md`（按需）。

### 2.1 方法论与流程资产（**升级改造/接任务前必读**，见 §2.5 详解）
8. `docs/flow/既定工作模式.md` —— ⭐ **本项目方法论的单一权威**：既定模式（接→化→发+OODA+三轮+破框）+ PM 7 步 + 大任务循环。**接手任何"升级/校验"任务前先读它。**
9. `docs/flow/GRAND-LOOP.md` —— 大任务循环唤醒指针（触发口令 + 唤醒三件套）。
10. `docs/flow/2026-09-05-grand-loop-task.md` —— 大任务循环**指导文件**（A/B/C/D 四场景 + 四步 + 判据 + 交付 + G-1~G-9）。
11. `docs/flow/2026-09-05-grand-loop-status.md` —— 大循环**动态 registry**（执行状态 + backlog）。
12. `docs/flow/2026-09-05-distillation-flow-diagram.md` —— 蒸馏流程图 + D1-D13 纪律。
13. `docs/LOOP-ESSENCE-AND-LEARNINGS.md` —— loop 本体哲学 + 教训库 §3（错1-错9）。

> 注意：`docs/state/`、`docs/PM框架-接入sloth-loop-流程规范.md`、`docs/knowledge-distillation/` 被 gitignore（私有，不随发布）。故方法论资产**落在 `docs/flow/`（可入库）**。

---

## 2.5 本项目既定工作模式与流程校验（**全套流程校验 · 强制**）

> sloth-loop 不是"随便改代码"，它有**三层既定流程**。任何"升级/改造/校验"任务都必须按流程走、留痕、验收。
> 本节是 `docs/flow/既定工作模式.md` 的执行摘要；**细节以该文件为准**，两者冲突以该文件为准。

### 2.5.0 三层流程体系（先分清在做哪一层）
| 层 | 名称 | 何时用 | 权威 |
|---|---|---|---|
| L1 | **既定模式（工程侧）** | 每次改引擎/修 bug 的固定走法 | `docs/flow/既定工作模式.md §1` |
| L2 | **既定流程 7 步（PM 侧）** | 业务任务（量化等）标准推进 | 同上 §2 |
| L3 | **大任务循环 GRAND-LOOP** | 跨多任务长期自进化闭环 | 同上 §3 + `GRAND-LOOP.md` |

> 关系：**L3 每轮内部**用 L1；L3 的 A/C 场景若涉业务任务，再用 L2。

### 2.5.1 L1 既定模式（工程侧）——**改任何引擎代码都走这个**
**= 接→化→发（p9） + OODA 严格模式 + 三轮评估（md5 一致） + 破框复验。**

1. **接→化→发（p9）**：接（想明白根本目标/产出放哪/怎么算完）→ 化（转化为可复用判据、**方案落盘**）→ 发（执行 + 沉淀教训库）。
2. **OODA 严格模式**：Understand→Observe→Orient→Decide→Act→Verify→Learn；硬门 = **Observe 必先读真实文件核现状，禁凭印象**。载体 `sloth_engine/ooda_pipeline.py`。
3. **三轮评估**：同一任务 `--once` 跑 **3 遍**，产物**逐字节一致（md5 一致）**才算通过（`ONBOARDING.md §八`）。
4. **破框复验**：换**币种/周期/剔参数/换独立实现**重跑，确认非"拟合单一样本"。

**L1 验收（缺一不合格）**：方案已落盘 / OODA 每步留痕（`work_ooda/`）/ 三轮 md5 一致 / 破框通过 / 教训回抽 `LOOP-ESSENCE-AND-LEARNINGS.md §3`。

### 2.5.2 L2 既定流程 7 步（PM 侧）
1 列方案（落 `RULEBOOK.md`）→ 2 p9+蜂群评估 → 3 p9+蜂群提 3-5 致命场景（翻成 config `judge_criteria`）→ 4 OODA 严格修复 → 5 走 3 遍评估 → 6 确认改造 + 全文件检查 → 7 **破框重验**。
> 铁律：**loop 是编排器，不是计算器/评估器**；p9/蜂群评估、场景设计、全文件检查是 **agent/人工先行**，结论写进 config 判据，loop 才执行/验证。**别把通用 OODA 状态栏当整体流程**（OODA 只是第 4、6 步）。

### 2.5.3 L3 大任务循环 GRAND-LOOP
**触发口令**：`开始执行sloth-loop自进化和蒸馏大厂项目`。
**A→B→C→D 回环**：A（蒸馏大厂+loop 码自进化：A1扫→A2蒸馏 file:行段→A3 V1/V2/V3+D7 反向→A4 改码 adopted 回填→A5 落盘+蜂群→A6 提交→A7 判"流程无误?"）→ B（修 architect-skills，Russell 周期重封存）→ C（16 维评估 loop/蜂群→覆盖矩阵+缺口+风险→修正）→ D（梳理大任务清单+动态维护+回环）。
**四步执行**（§5，**用户确认前禁动手**）：A 收集/学习（核对 4 根路径 Test-Path + 确认基线）→ B 复述理解（存档 `work_ooda/`）→ C 确认范围（等用户确认）→ D 执行记录（每 OODA 轮留痕；遇阻**立即停+上报，禁绕过**）。
**强制纪律（§0.1）**：禁跳步 / 禁只做部分 / 禁改判 / **禁编造证据（须 file:行段可回溯）** / 遇阻立即停+上报 / 唯一例外=用户确认调整 / 伴生函数覆盖 / 诱因真实构造 / 分支全覆盖 / 三栏并存 / 任务边界强制声明 / 记录完整性。
**判据（§7，写死真值）**：GL-A7 / GL-B / GL-C / GL-D / GL-adopted（详见 `docs/flow/2026-09-05-grand-loop-task.md §7`）。
**交付物（§8，每轮缺一不合格）**：commit + `_INDEX`/iteration-tracker 更新 + `work_ooda` 留痕 + **`ISSUES.md`/`AGENT_ERROR_LOG.md` 等价声明**（全通过也写"无遗留/无执行错误"）；硬映射 N==M。
**G-1~G-9**：修复前复现 / 伴生函数覆盖 / 诱因真实构造 / 分支全覆盖 / 三栏并存 / 命名清理 / 交付缺一不合格 / 编译判据独立证据 / 判据-证据硬映射。

> ⚠️ **路径重定向**：大循环原指导文件的 4 根路径指向**旧仓**。在 next 执行时：
> `<WORKSPACE_ROOT>/loop-dev` → `<WORKSPACE_ROOT>/loop-dev-next`；其余三根（architect-skills `<SKILL_ROOT>/...` / 大厂源 `<WORKSPACE_ROOT>/other_project` / 模板 `<KB_ROOT>/...`）**本机存在则用，不存在先上报"环境未就绪"，禁判 FAIL 或静默跳过**（§0.1#6）。

### 2.5.4 流程选择决策（接手先判断）
- 只改引擎代码/修 bug？→ 走 **L1 既定模式**（§2.5.1）。
- 有具体业务任务（量化等）要推进？→ 走 **L2 7 步**（§2.5.2）。
- 是"蒸馏大厂 + 自进化"的长期闭环，或用户下了触发口令？→ 走 **L3 大任务循环**（§2.5.3），**且必须先复述+等确认**。
- 不确定 → **先复述你的理解给用户，等确认再动手**（各层都适用）。

### 2.5.5 中间产物落点（流程留痕）
- 引擎侧报告：`projects/<domain>/<task>/reports/<日期>/REPORT.md`。
- OODA 留痕：`work_ooda/{YYYYMMDD-HHMMSS}-<场景>-{round}/`。
- 临时脚本：`scripts/tmp/`（gitignored，用完即删）。
- 方法论/流程资产：`docs/flow/`（可入库）。
- 禁用：根目录散落、`*.bak`。

---

## 3. 第一步：复核基线（每次接手都先做）

```powershell
cd <SLOTH_ROOT>
git status -s                                   # 应为 clean
git branch --show-current                       # 应为 dev
.venv\Scripts\python.exe sloth_engine/orchestrator.py --doctor   # 期望 Verdict: Ready
.venv\Scripts\python.exe -m pytest tests sloth_engine/tests -q    # 期望 1760 passed, 0 xfailed, cov ~79.49%
```

若任一项不符，**先停下来对齐环境**，不要带着未知状态开工。

---

## 4. 升级改造任务清单（按优先级；P0 先做）

> 口径说明：以下 P0/P1/P2 部分直接引自 `docs/sloth-loop-ROADMAP.md` 的既定规划（**未达触发条件的 gated 项不要抢跑**），
> 另一部分是本副本的**即修项**（明确、低风险、可立即做）。

### 🔧 即修项（立即可做，无需触发条件）

- **FIX-1 · `pyproject.toml` 依赖笔误**
  - 现状：`dependencies` 里写着 `"httpx2>=1.0"`，应为 `"httpx>=...`（正常是 `httpx`）。
  - 要做：改正为 `httpx>=0.27`（与本副本 venv 实际安装版本对齐；如项目有既定上界，以既定为准）。
  - 验收：`pip install -e .`（或 `pip install .`）不报错；回归不下降。
  - 备注：本副本的 `.venv` 已按正确包名 `httpx` 装好，改的是声明一致性。

- **FIX-2 · 文档基线口径统一**
  - 现状（2026-10-16 开单）：`ROADMAP.md` 写 `1113 passed`（2026-10-10），`AS-BUILT.md` 写 `755 passed`，`README/CLAUDE.md` 写 `755/1159` 不一。
  - **进展（2026-10-17，已收口）**：统一到本轮实测值（目标口径：`1194 passed / 1 xfailed / coverage 72.68%`），并在 ROADMAP §0 写明"以实测为准"。
  - 验收：全库 `grep` 测试基线数字，除历史 CHANGELOG（保留历史不改）外，当前态文档一致。
  - 关联：CLAUDE.md §9.8 单一总账。

- **FIX-3 · 落盘治理三域门禁化（ROADMAP 提到的"未来 run_gate 落盘门禁"）**
  - 目的：把 CLAUDE.md §9.4（engine 报告落点）/§9.5（wrapper PM_KB 规约）/§9.6（根目录脚本归位）从"规约"升级为 `run_gate.py` 的**可自动校验项**。
  - 要做：在 `scripts/run_gate.py` 增加规则——检测根目录是否散落非 allowlist 文件、是否新增 `*.bak`/散落日志；对 staged 变更做落盘合规校验。
  - 验收：故意在根目录放一个 `_x.txt` 并 stage → gate FAIL；移除 → PASS。新增对应单测。
  - 依赖：无。

### 🔴 P0（ROADMAP 既定，触发条件满足时做）

- **P0-1 · fail-closed CI 接入**：把本地 `run_gate.py` 升级为**远程不可绕过**的 CI（hosted CI 或 pre-receive hook），并补 provenance 扫描（secrets/keys/`.env` + 主机绝对路径污染）。
  - 验收：绕过本地 hook 仍无法 push 非绿色提交；敏感/路径污染提交被拒。
  - 注：本仓库**无 remote**（纯本地）。若要落地，需先建远程；否则此项目前无法真正落地，**先与用户确认**。
- **P0-2 · migration sentinel RPO**：迁移恢复从"行数代理"升级为"业务时间点"（Learn/Pattern 行加 `id`/`committed_at` sentinel；`scripts/migration_rehearsal.py` 的 `rpo` 输出改时间点，`verified=true`）。
  - 依赖：P0-1（evidence 入 CI）。

### 🟠 P1（触发后做）

- **P1-1 · REST API + Webhook（W4 平台化）**：抽象"任务引擎"config 驱动任意项目；REST 触发/查 status/history/模式库；Webhook 出站通知。**前置**：Orchestrator per-instance 化（去模块级单例锁，W2-BOUNDARY-01）。
  - 触发条件：出现第 2 个真实多模块任务，或需要外部驱动 Loop。

### 🟡 P2（触发后做）

- **P2-1 · OS/network sandbox**：ExecGate 之上加系统级沙箱（进程权限/容器化 + 默认禁止出网）；文档化信任边界。触发条件：把 Loop 暴露给不可信输入或部署生产前。

### ✅ 已决策/搁置（勿重复、勿擅自重启）

- 自主进化（evolution tier1/tier2 首块）**当前主动搁置**——见 `ROADMAP.md §4b`：它是"运行驱动"能力，不跑无数据输入；唤醒路径已写在 §4b，**未触发不要开发**。
- WebUI（P2-A 方案 A）、run_parallel Windows 并行、测试卫生等**已完成**，见 `ROADMAP.md §4`，勿重做。

---

## 5. 工作流（每个改动走一遍）

```powershell
cd <SLOTH_ROOT>

# 0) 开工前：确认基线（§3）

# 1) 改代码（在 dev 分支）
#    ... 编辑 ...

# 2) 先测后写：全量回归
.venv\Scripts\python.exe -m pytest tests sloth_engine/tests -q

# 3) 门禁（有变更时会真正跑；coverage 只升不降）
.venv\Scripts\python.exe scripts\run_gate.py

# 4) 提交（中文信息用 -F，UTF-8）
git add -A
git commit -F .\commitmsg.txt     # 或 git commit -m "..."（注意编码）

# 5) 改动稳定后合回 master
git switch master
git merge --no-ff dev
git switch dev
```

---

## 6. 验收标准（Definition of Done）

任一任务完成，必须同时满足：
- [ ] 全量回归 **≥ 1760 passed**（新功能要新增测试，表现为"只增不减"）。
- [ ] coverage **≥ 70** 且相对开工前的 HEAD **不下降**。
- [ ] `scripts/run_gate.py` PASS。
- [ ] `--doctor` 仍 `Verdict: Ready`。
- [ ] 无新增根目录散落文件 / `*.bak` / 临时脚本（临时脚本只进 `scripts/tmp/`）。
- [ ] 相关权威文档同步更新（单一总账原则，不新起版本）。
- [ ] 未触碰 `<WORKSPACE_ROOT>/loop-dev-0927`。

### 6.1 流程校验项（**全套流程校验 · 按 §2.5 走**，缺一不合格）
- [ ] **明确本次走的是哪一层流程**（L1 既定模式 / L2 PM 7 步 / L3 大任务循环），并在报告里声明。
- [ ] L1：方案已落盘 + OODA 每步留痕（`work_ooda/`）+ **三轮 md5 一致** + 破框复验通过 + 教训回抽 `LOOP-ESSENCE §3`。
- [ ] L2：按 7 步走全（方案→p9+蜂群→3-5 致命场景→OODA 修复→3 遍→全文件检查→破框），每步落盘。
- [ ] L3：四步（收集/复述/确认/执行）——**复述+等用户确认后才动手**；每轮 commit + `_INDEX`/tracker + `work_ooda` 留痕 + `ISSUES.md`/`AGENT_ERROR_LOG.md` 等价声明；判据 GL-* 逐条给证据（N==M）。
- [ ] 中间产物落点合规（报告 `reports/<日期>/`、留痕 `work_ooda/`、临时 `scripts/tmp/`）。
- [ ] 若走 L3 且关键外部路径不存在 → 已上报"环境未就绪"，未静默跳过/未判 FAIL。

---

## 7. 交付报告格式（做完在回复里给出）

```
## 本次改动
- 任务：<FIX-x / P0-x ...>
- 走的流程：<L1 既定模式 / L2 PM 7步 / L3 大任务循环>  ← 必填（§2.5）
- 文件：<逐条列出 改动的文件路径>
- 关键 diff 摘要：<1-3 句>

## 验证证据
- pytest: <passed/failed/xfailed>  (baseline 1760 passed / 0 xfailed)
- coverage: <xx%>  (baseline 79.49%)
- run_gate: PASS/FAIL
- --doctor: Ready/其他

## 未做/被阻塞
- <列明原因，如 gated 未触发 / 需用户确认远程仓库>

## 建议下一步
- <1-3 条>
```

---

## 8. 边界与纪律

- **不确定就查文档、就测**，不要猜。AS-BUILT 是唯一架构基线，改架构先对照 diff。
- 遇到 gated 项（P1 REST/Webhook、P2 sandbox、自主进化）**未达触发条件不要抢跑**；写清"未触发，未做"即可。
- 任何"看起来是 bug 的越界/失败"先核实是否 fail-closed 设计（安全即正确）。
- 保持 `master` 干净可对照；`dev` 承载你的所有提交。
- 若发现 0927 与 next 的基线差异（如 0927 已领先），**以本副本的实测为准**记录，不要回写 0927。

---

### 附：快速命令卡

| 目的 | 命令 |
|---|---|
| 环境自检 | `.venv\Scripts\python.exe sloth_engine/orchestrator.py --doctor` |
| 全量回归 | `.venv\Scripts\python.exe -m pytest tests sloth_engine/tests -q` |
| 提交门禁 | `.venv\Scripts\python.exe scripts\run_gate.py` |
| 状态/历史 | `.venv\Scripts\python.exe sloth_engine/orchestrator.py --status` / `--history` |
| 当前分支 | `git branch --show-current` |
