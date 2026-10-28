---
skill_family: sloth-loop-self-evolution
skill_name: grand-loop-task-v1
template_version: v7
project: sloth-loop自进化+蒸馏大厂项目大循环
evaluatedAt: 2026-09-05
status: 已存储待执行（口令触发）
source: [distillation-flow-diagram §⑧/§⑨, AGENT_EXECUTION_TEMPLATE v7, 用户大循环确认2026-09-05]
aliases: [大任务循环, grand-loop, sloth-loop自进化大循环]
---

# 大任务循环指导文件（GRAND-LOOP-TASK）v1 · 按 AGENT_EXECUTION_TEMPLATE v7 严格约束

> 定位：sloth-loop 自进化 + 蒸馏大厂项目 **大任务集群**的可唤醒指导文件。
> 触发口令：**"开始执行sloth-loop自进化和蒸馏大厂项目"** = 唤醒并启动整个大循环。
> ⚠ **基线/路径时点声明**：本文件为 **2026-09-05 初建快照**，其下文的 `772 passed` / `71.91%` /
> `fail_under=64` / `<WORKSPACE_ROOT>\loop-dev` / 分支 `codex/w0-w2` 均为**当时值**。**当前为**
> `<WORKSPACE_ROOT>\loop-dev-next`（分支 `dev`，HEAD `751d7f2`，1194 passed / 1 xfailed / coverage 72.13%，`fail_under=70`）。
> 当前基线请以 `docs/sloth-loop-ROADMAP.md §0` 与 `CLAUDE.md` 为准；本节不再作为当前基线。
> 严格按 `<KB_ROOT>\500-AI Agent\组合工作流\AGENT_EXECUTION_TEMPLATE.md` v7（§0.1 14条 + 四步 A/B/C/D + G-1~G-9 + §8.1-8.4 判据-证据硬映射 N==M）；蒸馏流程 v2.1 纪律 D1-D13（distillation-flow-diagram §⑨）为其蒸馏语境翻译。

## §0 本文件是「指导文件」非「执行脚本」
- 拿到本文件先读 → 复述理解（§5B）→ 与用户确认范围（§5C）→ 执行。
- 用户确认前禁改环境/写文件/装服务（知识库存储本体除外）。

## §0.1 强制纪律（继承 v7 §0.1 #1-#14 + 蒸馏 D1-D13，最高优先级）
1 禁跳步（D1）/ 2 禁乱执行 / 3 禁只做部分（D2）/ 4 禁改判 / 5 禁编造证据（D3，②须真实 file:行段可回溯）/ 6 遇阻碍立即停+上报禁绕过（D4，路径不存在/provisional/上报）/ 7 唯一例外=用户确认调整（D5）/ 8 伴生函数覆盖（D6，per-entry cited 文件到行段）/ 9 诱因真实构造（D7，V3 反向未知样本真实 trigger 非改判据）/ 10 分支全覆盖（D8，回退/次级分支各独证）/ 11 三栏并存（D9，_INDEX 验证状态 V1/V2/V3/结论级 + 计数 + 去重）/ 12 打包清理命名规范 / 13 任务边界强制声明（D10，声明活跃任务+基线，禁混已结束任务，接入 loop 先声明归属）/ 14 禁擅自新增模板未要求文件。 / 15 记录完整性（v7 §8 缺一不合格；cycle-2 教训 2026-09-06）：每工作单元独立 OODA slice + 每轮 ISSUES/AGENT_ERROR_LOG 等价声明 + 被触发的 _INDEX 钩子同轮复检；缺一即本轮不合格（详 §8.4）。
> D1-D13 详见 distillation-flow-diagram §⑨.2；G-1~G-9 见 §9。

## §1 任务目标 + 任务边界（§0.1#13，须与用户核对一致）
- **base 组件/基线**：sloth-loop（`<WORKSPACE_ROOT>\loop-dev`，分支 `codex/w0-w2`，HEAD `64de89b`（cycle-1 A→B→C→D 闭合；动态状态见 2026-09-05-grand-loop-status.md），772 passed/cov 72.27 / cov 71.91%）+ architect-skills（`<SKILL_ROOT>\architect-skills-offline-bundle\architect-skills`，含 architect-router/16维/output/golden/docs/iteration-tracker/pipeline.config.json）
- **任务归属**：大任务循环（sloth-loop 自进化 + 蒸馏大厂项目）。**已结束 iter**（禁承接/混入）：iter#1=`766209c`、iter#2=`24be2bb`、iter#3=`56b1b6e`、Phase2=`039e67d`，均已提交。
- **活跃任务**：大循环 A→B→C→D 自驱回环（用户确认后回环内不再每步问，除非遇 §0.1#6 阻碍）。

## §2 目标场景（大循环 4 场景）
- **场景 A**：蒸馏大厂项目 + sloth-loop 代码自进化（A1 扫描→A2 蒸馏 file:行段→A3 V1/V2/V3+D7 反向→A4 改 loop 代码 adopted 回填(契约不变量+跑绿+gate)→A5 全量落盘+蜂群深化 D6/D13→A6 提交→A7 判"蒸馏流程无误?"→否回 A1 / 是进 B）
- **场景 B**：用大厂蒸馏实测结果修正 architect-skills（对象 `<SKILL_ROOT>\...\architect-skills`；architect-* 维检查点/architect-router/SKILL.md/ARCHITECTURE-COVERAGE.md/pipeline.config.json；按 Russell 周期重封存落盘：NEW 按日 `output/{project}/{date}/report.md`+golden 行+`docs/iteration-tracker/{project}-{date}.md`，非在线 append）
- **场景 C**：用修正后 architect-skills（16 维）评估当前 sloth-loop + 蜂群（subagent/swarm 编排，ToolRegistry 现为死分支）→ 覆盖矩阵+缺口+风险分级 → 修正 sloth-loop/蜂群（代码改造 adopted 回填）→ pytest+gate
- **场景 D**：把 A+B+C 梳理为一个"整个大任务"清单（动态维护）+ 执行中持续完善 + 大回环 A→B→C→D→完善→回 A（自进化闭环，永不停止；"流程无误"是 A 阶段收敛条件非全循环终止）

## §3 环境信息
- sloth-loop：`<WORKSPACE_ROOT>\loop-dev`（.venv py3.11，772 passed/cov 71.91%，gate `scripts/run_gate.py` fail_under=64）
- architect-skills：`<SKILL_ROOT>\architect-skills-offline-bundle\architect-skills`
- 大厂源根：`<WORKSPACE_ROOT>\other_project`（如 `TencentDB-Agent-Memory@2ee2239`）
- 模板源：`<KB_ROOT>\500-AI Agent\组合工作流\AGENT_EXECUTION_TEMPLATE.md` v7
- 蒸馏库：`docs/knowledge-distillation/`（_INDEX/SOURCE/_TEMPLATE/DISTILLATION-VERIFICATION/PROJECT-ANALYSIS-TEMPLATE v1.6（B 阶段断链闭合））
- 唤醒口令：**开始执行sloth-loop自进化和蒸馏大厂项目**

## §4 运行模式与入口
- 触发：用户口令"开始执行sloth-loop自进化和蒸馏大厂项目"
- 入口：读本指导文件 → 读 distillation-flow-diagram（流程 v2.1 状态）+ docs/knowledge-distillation/_INDEX.md（条目/计数）+ iteration-tracker（按日快照）→ §5 四步

## §5 test-agent/主控 执行流程（强制四步 + 全程留痕）
### 步骤 A 收集/学习：读本文件+权威记忆(distillation-flow-diagram §⑧/⑨ + docs/knowledge-distillation/_INDEX.md + iteration-tracker) + 核对 4 根路径存在(Test-Path) + 确认基线(772 passed)
### 步骤 B 复述理解：用自己的话完整复述大循环 A/B/C/D + 断言表（§7）+ 任务边界(§1)；复述存档 work_ooda/{date}-grand-loop/
### 步骤 C 确认范围：把理解列给用户，等确认后执行；用户修正按修正执行；确认往来存档
### 步骤 D 执行并记录：用户确认后按 A→B→C→D 大回环执行，每 OODA 轮 work_ooda 留痕；遇 §0.1#6 阻碍立即停+上报禁绕过

## §6 日志记录（强制落盘）
- 目录：`work_ooda/{YYYYMMDD-HHMMSS}-grand-loop-{round}/`（OODA 轮次）+ `docs/knowledge-distillation/_INDEX.md` + architect-skills `docs/iteration-tracker/{project}-{date}.md`（周期重封存）
- 必记：时间线+理解过程(A/B/C) / 每命令原文+退出码+stdout/stderr / 每条目②证据 file:行段+实测核验 / 异常/歧义 / 用户确认往来

### §6.1 每轮 OODA 必出文件清单（v7 §8 缺一不合格；cycle-2 2026-09-06 固化）
- 每工作单元一份独立 slice：Observe/Decide/Act/Verify + verdict-evidence 表 + 命令+exit+stdout/stderr + G-2 伴生函数覆盖 + G-4 分支覆盖；session 最后一个单位也必须出 slice（M1-1 缺 slice 教训）。
- 每轮合集 RECORD 等价（时间线 + 理解过程 A/B/C + 每命令原文+退出码+stdout/stderr + 异常/歧义 + 用户确认往来）。
- ISSUES.md 等价声明：写明无遗留或列 continued 非 issue 项；文件不得缺席（全通过也必须落）。
- AGENT_ERROR_LOG.md 等价声明：写明无幻觉/无编造证据/无静默跳过，或记录自纠；文件不得缺席（全通过也必须落）。
- §8.4 记录完整性自校验在 §5D 收尾前 + §8.2 提交前各跑一次。

## §7 判定（写死真值，非填即错）
| 判据编号 | 场景 | 期望真值 |
|---|---|---|
| GL-A7 | 蒸馏流程无误 | distillation-flow-diagram open audit 全清零（D6 9/9 + D7 + Russell + D12）+ 流程 v2.x 自洽 |
| GL-B | architect-skills 修正 | 按 Russell 周期重封存落盘（golden 行+iteration-tracker，非 append）；实测真值校正检查点 |
| GL-C | 评估+修正 sloth-loop/蜂群 | 16 维覆盖矩阵+缺口+风险分级；adopted 回填契约不变量 pytest 跑绿+run_gate PASS+commit |
| GL-D | 大任务清单维护 | 动态清单+commit 链+OODA 每细节跟进 |
| GL-adopted | 每条 adopted 回填 | 契约不变量 xfail→passed + 全量回归无回归 + run_gate PASS + commit 证据 |
- 关键路径/文件不存在：先上报"环境未就绪"（§0.1#6），禁判 FAIL 或静默跳过。

## §8 交付物（每轮，缺一不合格）
1. commit（docs-only → gate SKIP；代码改 → gate 必过 + pytest 无回归）
2. reports/_INDEX/iteration-tracker 更新
3. work_ooda OODA 轮次留痕
> 全通过也必须落盘 ISSUES/AGENT_ERROR_LOG 等价声明（无遗留/无执行错误）。

## §8.1 判据-证据一一对应（硬映射 N==M）
- 每判据唯一证据文件，禁合并/改名/缺省；RECORD 声称数 == evidence 实际数才允许提交（D12）。

## §8.2 提交前核对清单
- [ ] work_ooda 轮次留痕 / [ ] _INDEX 计数 N==M / [ ] ②证据 file:行段实测可回溯(D3/D6) / [ ] adopted 已契约+跑绿+gate / [ ] commit UTF-8 no BOM 中文 conventional

- [ ] 每工作单元均有独立 OODA slice（含 session 最后一个）
- [ ] ISSUES.md 等价声明已落盘（无遗留或列 continued）
- [ ] AGENT_ERROR_LOG.md 等价声明已落盘（无执行错误或自纠）
- [ ] 本轮 loop 自进化触发的 _INDEX 钩子已同轮复检 + 回填状态推进（D9）

## §8.3 证据一致性硬校验（防编造）
- 每条②行段附"实际存在核验"（存在✅/缺失❌ + Select-String/Test-Path 摘要）；_INDEX 声称数 M == 实际文件数 N 才过 L3。

## §8.4 记录完整性自校验（cycle-2 教训 2026-09-06 固化，防缺口复发）
> 上一轮 cycle-2 暴露 3 类记录缺口已回填（m1-slice / ISSUES / AGENT_ERROR_LOG / _INDEX 回填见 cycle-2 commits）。本节固化为每轮硬校验，缺一则本轮不合格。
- 8.4.1 slice 完整性：本轮工作单元数 == OODA slice 文件数（含 session 最后一个单位）；缺即不合格（M1-1 教训：长 session 末单元易漏 slice）。
- 8.4.2 交付物齐全：ISSUES.md + AGENT_ERROR_LOG.md 等价声明每轮必落（v7 §8 缺一不合格）；全通过也写『无遗留 / 无执行错误』，文件不得缺席或省略。
- 8.4.3 钩子同轮复检：_INDEX 中任一 candidate 的复检钩子被本轮 loop 自进化触发时，本轮必须同轮更新该条目回填状态，禁跨轮留挂（D9/G-5；M1-1 触发 tencentdb-telemetry-stack 钩子已同轮回填示范）。
- 8.4.4 时机：每轮 §5D 收尾前 + §8.2 提交前各跑一次三件套；不满足即停 + 上报 + 补齐后再提交（§0.1#6）。

## §9 通用闭环条款（继承 v7 G-1~G-9）
G-1 修复前复现 / G-2 伴生函数覆盖(D6) / G-3 诱因真实构造(D7) / G-4 分支全覆盖(D8) / G-5 三栏并存(D9) / G-6 命名清理规范 / G-7 交付缺一不合格(D11) / G-8 编译判据独立证据+正确解释器 / G-9 判据-证据硬映射(D12)

## §10 参考
- `docs/flow/2026-09-05-distillation-flow-diagram.md`（流程 v2.1 + D1-D13 + Russell §⑧.5 + open audit §⑧.6）
- `docs/knowledge-distillation/PROJECT-ANALYSIS-TEMPLATE.md` v1.5
- `docs/knowledge-distillation/DISTILLATION-VERIFICATION.md`
- `<KB_ROOT>\500-AI Agent\组合工作流\AGENT_EXECUTION_TEMPLATE.md` v7
- `<SKILL_ROOT>\architect-skills-offline-bundle\architect-skills\architect-router\SKILL.md`

---

## 唤醒块（路径 / 模式 / 上下文条件，确保可恢复）
- **路径（4 根）**：
  1. sloth-loop = `<WORKSPACE_ROOT>\loop-dev`（HEAD `74d7ad9`，772 passed）
  2. architect-skills = `<SKILL_ROOT>\architect-skills-offline-bundle\architect-skills`
  3. 大厂源根 = `<WORKSPACE_ROOT>\other_project`
  4. 模板源 = `<KB_ROOT>\500-AI Agent\组合工作流\AGENT_EXECUTION_TEMPLATE.md`
- **权威记忆**：`docs/flow/2026-09-05-distillation-flow-diagram.md`（流程状态）+ `docs/knowledge-distillation/_INDEX.md`（条目/计数）+ architect-skills `docs/iteration-tracker/`（按日快照）+ `docs/flow/2026-09-05-grand-loop-status.md`（动态 registry）
- **模式**：大循环 A→B→C→D 回环 + 蒸馏流程 v2.1（阶段0-6 + L1-L4 + D1-D13）+ AGENT_EXECUTION v7（四步 + G-1~G-9）
- **上下文条件**：口令"开始执行sloth-loop自进化和蒸馏大厂项目"触发 + 基线 772 passed + open audit 状态（iter#3 全 closed：D6 9/9/D7/Russell/D12）+ commit 链 `766209c→24be2bb→56b1b6e→039e67d→74d7ad9→93f86a4→8ba5117→321030f→64de89b（cycle-1 B/C/D）` + 已结束 iter 禁混入（动态 registry 见 2026-09-05-grand-loop-status.md）
- **唤醒动作**：读本文件 → 读 distillation-flow-diagram §⑧/⑨ → 读 docs/knowledge-distillation/_INDEX.md → §5 四步 A 收集/B 复述/C 确认/D 执行大回环

> v1 存储于 2026-09-05（先存储后执行）。本条目为 reference 级（大任务指导本身）；其下 A/B/C/D 各阶段的蒸馏条目另按 _TEMPLATE 落盘。

