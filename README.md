# sloth-loop（树懒 Loop） · 自进化任务回测编排引擎

> 版本：v4.0-dev · 更新：2026-10-28 · 基线 commit 0b8afab
> **项目更名（2026-10-27）**：本项目原名 **loop / loop-dev**，自 2026-10-27 起正式更名为 **sloth-loop（树懒 Loop）**。代码与目录统一为 `sloth-loop` / `sloth_engine`；历史文档里写 “loop” 的旧称按当时事实保留。
> **一句话定位**：sloth-loop 是**零 LLM 的任务编排引擎（身体）**——把「一次跑出结果」固化成**可复用的流程**（SOP 骨架 + 偏差模式库 + 矫正规则库）；「思考」外包给你挂载的 Agent（大脑），也**只有 Agent 才消耗 LLM 额度**。
> *Slow is smooth, smooth is fast.* — **Never do the same work twice.**

## 三个必须说清的标记：本意 / 是什么 / 与 Agent 的区别

1. **项目的本意（为什么做它）**：把「一类对象的完整认知流程」——分发候选 → 跑 → 判定对错 → 提炼规则——固化成可复用的东西。同类对象（另一个币种 / 项目 / 领域）**只换输入、照同一流程自动跑**，不再重复人工劳动。它解决的是**重复劳动 + 经验不沉淀**，不是「更聪明的推理」。
2. **项目到底是什么**：一个**零 LLM 的编排状态机 + 状态/规则库**（CLI 工具；不是 MCP Server，也不是 Agent）。它负责 OODA 7 步的调度、并发、重试、熔断、限流、状态持久化、模式沉淀；业务通过 `projects/<domain>/<task>/` 的 config + wrapper 接入；「什么是成功」由使用者在 `success_criteria` 里写死，loop 只按这个定义逼近。
3. **Agent 与本项目的区别**：Agent 是**推理主体（大脑）**，本项目是**编排状态机（身体）**。Agent 内含 LLM、是额度的唯一消耗方；本项目**不含 LLM**（无 SDK、无凭据、不发起 LLM 调用），只通过 CLI + Hook + Prompt 资产把「思考」外包给挂载它的 Agent（Codex / Claude）。因此 → **loop 执行任务消耗的是挂载方 Agent 的额度**。

| 维度 | sloth-loop（本项目） | Agent（Codex / Claude …） |
|---|---|---|
| 本质 | 编排状态机（身体） | 推理主体（大脑） |
| 是否含 LLM | 不含：无 SDK / 无凭据 / 不发起调用 | 就是 LLM |
| 消耗额度 | 不消耗 | 唯一消耗方 |
| 谁定「成功」 | 你写死的 `success_criteria` | 生成候选 / 判断 / 补救 |
| 关系 | 把 Agent 的一次性输出沉淀成可复用流程 | 提供思考，被 loop 挂载使用 |

> 五要素关系（用户模型 / 用户 Agent / 用户任务 / loop / 结果）与四个接触面的完整推导，见 `docs/design/loop-vs-agent-quota-and-boundary.md`。
## 项目沿革（过去 / 现在）

> **过去**：本项目原名 **loop**（方法论与引擎的旧称）；引擎开发仓叫 `loop-dev`（分支 `codex/w0-w2`），
> 从它 clone 出生产运行目录 `loop-dev-0927` 与升级改造副本 `loop-dev-next`；引擎包目录曾叫 `loop-engine`。
> **现在（2026-10-27 起）**：正式更名为 **sloth-loop（树懒 Loop）**，引擎包为 `sloth_engine/`，Apache-2.0 开源。
> 名字取「树懒」——**慢就是稳，稳就是快**。历史文档里写的 “loop” 是当时的事实，原样保留、不追溯改写。
> 完整沿革（名字演进 / 里程碑 / 经历过什么 / 保留的教训）见 [`docs/HISTORY.md`](docs/HISTORY.md)。

## 这是什么
sloth-loop 是通用「自进化编排引擎」：给定候选信号 + 你定义的『什么是成功』，
它自主跑任务（OODA 7 步），自动沉淀失败/成功模式，可持续演化出新候选并由人审纳入。
它**不绑定业务**——业务通过 `projects/<domain>/<task>/` 的 config + wrapper 接入
（量化回测 / 文档蒸馏 / 通用脚本任务均可）。

核心入口：`python sloth_engine/orchestrator.py`（CLI 工具，非 MCP Server）。

## 应用场景的本质

loop 的本质不是「某一次跑出指标」，而是**把一个对象的「分析 → 判定对错 → 提炼规则」完整认知流程固化成可复用的东西**：同类对象（另一个币种 / 项目 / 领域）**只换输入，照同一流程自动跑**，不再重复人工输入。（本体定义见 `docs/LOOP-ESSENCE-AND-LEARNINGS.md` §一 —— 由用户校准，高于本节的工程表述。）

它靠一条闭环把「一次性报告」升级为「可复用流程（SOP 骨架 + 偏差模式库 + 矫正规则库）」：**用户定义成功 → loop 照定义逼近 → 未达标自动沉淀为排除经验 → 达标复用为优先信号**。即：**「什么是成功」由你在输入里写死，loop 只负责按这个定义做可行性 loop 逼近** —— 这是它区别于普通脚本 / Agent 引擎的本质。

### 通用接入契约（任何任务都收敛成三件套）

| 输入件 | 含义 |
|---|---|
| `signals` | 一批「候选做法」（参数组合 / 方案 / 步骤） |
| `success_criteria` | 你写的成功判定式 `metric + operator + threshold`（如 `win_rate >= 0.35`；operator 仅 gt/gte/lt/lte/eq/ne） |
| `wrapper` | 把信号变成可测结果的一段脚本（回测 / 校验 / 渲染…），纯计算、不调 LLM |

### 三类典型场景（同一条契约，只换 wrapper 与判定式）

| 场景 | signals | success_criteria（示例） |
|---|---|---|
| 回测 / 参数扫描 | 参数组合 | `trades_count > 0`、`win_rate >= 0.35`、`sharpe >= 1.0` |
| 数据校验 / 清洗 | 不同清洗方案 | `row_count >= N`、`null_ratio <= 0.01`、`schema_valid == true` |
| 文档 / 报告核对 | 候选结构草案 | `no_forbidden_words == true`、`all_claims_have_source == true` |

### 边界：loop 不是 Agent

它是**零 LLM 的编排状态机（身体）** —— 不含 LLM 客户端、不持凭据、不发起 LLM 调用；「思考」通过 CLI + Hook + Prompt 资产外包给挂载它的 agent（Codex / Claude，= 大脑，也是**唯一烧额度的方**）。因此 **loop 执行任务消耗的是挂载方 agent 的额度**。详见 `docs/design/loop-vs-agent-quota-and-boundary.md`。

## 快速上手（新主机 5 分钟）
直接看 [docs/sloth-loop-QUICKSTART.md](docs/sloth-loop-QUICKSTART.md)：
按场景（量化回测 / 文档蒸馏 / 通用任务）把 sloth-loop 跑起来，含最小模板与自查清单。

```
.venv/Scripts/python sloth_engine/orchestrator.py --doctor   # 环境自检
.venv/Scripts/python sloth_engine/orchestrator.py --once     # 单轮 OODA
.venv/Scripts/python sloth_engine/orchestrator.py --status   # 模式库
.venv/Scripts/python sloth_engine/orchestrator.py --history  # 历史运行
.venv/Scripts/python sloth_engine/orchestrator.py            # 连续循环
```

## 目录结构（截至 2026-09-14，归档后）
```
<SLOTH_LOOP>/
├── sloth_engine/          # 核心引擎：orchestrator(CLI+OODA) / cli_router / adapters / ooda_pipeline ...
├── backtest/             # 回测运行时解析 + mock
├── tests/  sloth_engine/tests/   # 自动化测试
├── projects/             # 业务场景按域/任务自包含（pm/*、loop-plugin-arch/、arch-dsh-eval/）
├── scripts/              # 正式工具（run_gate.py 门禁 + 带日期一次性工具如 _archive_sloth_<d>.py）
│   └── tmp/              # 【唯一合法临时脚本落点，gitignored，用完即删】
├── config/  agent-prompts/      # 引擎配置 / prompt 资产
├── work_ooda/            # OODA 工作草稿（loop-*/runs-*/ 已 gitignore）
├── docs/                 # 文档入口（QUICKSTART 等）
├── logs/                 # 运行日志（滚动，gitignored）
├── _data/                # 回测默认 I/O（PROTECTED）+ evolution/
├── _archive/             # 归档历史残留（mv 不删，只读证据）
├── .venv .git .idea .pytest_cache .workbuddy .claude __pycache__   # 工具/缓存
├── CLAUDE.md README.md RUNBOOK.md ONBOARDING.md      # 根目录仅保留入口文档
├── docs/state/           # 唤醒/计划锚：WAKEUP.md NEXT.md IMPROVEMENTS.md（2026-10-14 归位）
└── docs/LOOP-ESSENCE-AND-LEARNINGS.md  # 方法论长文（2026-10-14 归位）
└── scripts/pm-diag/  # (根目录分析脚本已归位 2026-09-14: fetch_articles.py→scripts/, monthly_breakdown*.py+r6c_channel_diag.py→scripts/pm-diag/, signal_driven_state.json→_data/)
```
> 根目录是 **allowlist 制**：除上述锚/配置/被引用分析脚本外，禁止散落临时脚本、草稿、`.bak`、散落日志、`.coverage`。临时文件的**唯一合法落点 = `scripts/tmp/`**（gitignored，用完即删）。完整目录纪律与临时文件治理见 **CLAUDE.md §9**。

## 测试 / 提交门禁
```
.venv/Scripts/python -m pytest tests sloth_engine/tests -q   # 全量回归(1760 passed / 0 xfailed / coverage 79.49%)
.venv/Scripts/python scripts/run_gate.py       # 提交前绿夹(fail_under=70, 软约束可 --no-verify 绕过; 含 docs 基线一致校验)
```

## 关键状态
- **自主进化整体搁置**：当前资源受限、不实时运行；已完成件(--report/U&Q/schema/信号演化/自改码门禁)
  保留可复用，将来按`<KB_ROOT>/sloth-loop自主进化后续计划-2026-09-02.md`唤醒。
- **后续扩展（规划，未实现）**：AI Team / 蜂群编排层（roster 链）+ 自主进化，见 [docs/sloth-loop-AI-TEAM-AND-SELF-EVOLUTION.md](docs/sloth-loop-AI-TEAM-AND-SELF-EVOLUTION.md)（ROADMAP 触发条件见 docs/sloth-loop-ROADMAP.md §4b）。
- 详细介绍：docs/sloth-loop-项目介绍与规划.md（全景架构图、使用者视角、成功判定、上下文实现、接入规范）。

## 配套 Skill 仓库（关联项目）

本项目是「身体」——零 LLM 的编排状态机；「能力」由下面 4 个独立的 skill 仓库提供。为避免版本互相绑架，它们以 **git submodule** 形式挂在 `skills/` 下，各自独立迭代、按需 pin 版本。

| submodule 路径 | 仓库 | 在本项目里的角色 |
|---|---|---|
| `skills/architect-skills` | [aiqianqian521/architect-skills](https://github.com/aiqianqian521/architect-skills) | 19 个架构评估 skill：18 个维度 atom + 1 个路由编排（Agent / RAG / 安全 / 合规 / 可观测性…） |
| `skills/obsidian-skills` | [aiqianqian521/obsidian-skills](https://github.com/aiqianqian521/obsidian-skills) | Obsidian 知识库的采集 / 整理 / 查询 / 索引 |
| `skills/ooda` | [aiqianqian521/ooda_skill](https://github.com/aiqianqian521/ooda_skill) | OODA 执行循环纪律（Observe→Orient→Decide→Act 直到收敛） |
| `skills/ai-skill-output-template` | [aiqianqian521/ai-skill-output-template](https://github.com/aiqianqian521/ai-skill-output-template) | 统一 skill 输出模板（声明式多模板注册中心） |

一键克隆主仓 + 全部 skill：

```bash
git clone --recurse-submodules https://github.com/aiqianqian521/sloth-loop.git
# 已有仓库补齐 / 更新子模块
git submodule update --init --recursive
git submodule update --remote --merge   # 拉取各 skill 最新主干
```

> 边界不变：`sloth-loop` 自身不发起任何 LLM 调用，skill 只提供流程与提示词资产，思考仍由挂载它的 Agent 承担。
>
> 互链：上面 4 个仓库的 README 里都有「配套项目」区块反向链接回本仓——本仓是这组 skill 的编排入口与唯一消费方。
