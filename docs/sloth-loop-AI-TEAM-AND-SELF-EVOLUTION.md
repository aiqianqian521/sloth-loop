# sloth-loop 后续扩展：AI Team / 蜂群 与 自主进化（规划 · 未实现）

> 状态：**规划文档，未实现** —— 本文只登记设计结论与落地顺序，不含任何代码改动，
> 也不改变引擎的「零 LLM」边界。
> 来源：2026-10-28 对一次真实接入场景评审结论（内部笔记）在 sloth-loop 侧的提炼。
> 关联：`docs/sloth-loop-ROADMAP.md`（§4b 自主进化·搁置）、`sloth_engine/subagent_spec.md`
> （Maker / Checker 分离，未实施）、`agent-prompts/`、`sloth_engine/prompt_registry.py`。
> 当前基线（单一来源 `docs/baseline.json`）：**1760 passed / 0 xfailed / coverage 79.49%**（`fail_under=70`）；本文是**规划**，数字不随实现推进而变 —— 若与 `docs/baseline.json` 不一致，以该文件为准。

## 0. 一句话结论

**先把「判定权」外置，再谈 AI Team。** 当前缺的不是「更多角色」，而是「什么算对」的
机器可判定表达（`success_criteria` + 纯计算 `wrapper`）。顺序反了，团队只会把
「一个 LLM 打转」放大成「N 个 LLM 互相点赞」，成本 ×N、正确率不涨。

## 1. sloth-loop 可信性的 4 个承重件（已有）

| # | 机制 | 载体 | 为什么能产生「可信」 |
|---|---|---|---|
| 1 | 成功定义前置 | `success_criteria = metric + operator + threshold` | 「什么算对」写死在输入里，**不由 LLM 事后解释** |
| 2 | 判定权外置 | `wrapper`（纯计算，**不调 LLM**） | 判定是**算**出来的，不是**说**出来的 |
| 3 | 确定性复算 | 三轮 `--once`，产物 **md5 逐字节一致** | 排除随机性与一次性巧合 |
| 4 | 破框复验 | 换币种 / 周期 / 剔参数 / 换独立实现重跑 | 排除「单样本拟合」 |

配套：失败 / 成功模式库（沉淀，且 status 变更**需人工审批**）、`scripts/run_gate.py` 门禁。

## 2. 蜂群在 sloth-loop 里的真实位置（现状）

- 只在**方法论层**出现：大任务循环 L2 的第 2、3 步「用 p9 + 蜂群评估方案有效性 /
  提出 3-5 个致命问题场景」，原文标注 **「半对齐（agent / 人工动作）」**；
- `sloth_engine/subagent_spec.md` 头部写 **「状态：设计阶段，未实施」**；
- `README.md`「关键状态」写 **「自主进化整体搁置」**。

> 即：**蜂群在 sloth-loop 是「方法论步骤」，不是引擎能力；Maker / Checker 分离尚未实现。**

## 3. 结论：**不要**把 AI Team / 蜂群用在「裁决」上

| 判断 | 理由 |
|---|---|
| ❌ 不做多 agent 编排做裁决 | 任务**强串行**、交付物是**单人签名的单一产物**；失败模式是**证据自洽性**而非吞吐 —— 团队化只会成本 ×N、正确率不涨 |
| ✅ 只保留执行层横向并行 | 多机采集 / 多脚本改造 / 多 item 搭环境：子任务**可独立验收**，这是蜂群唯一甜点区 |
| ⛔ 顺序 | **判定外置（真值表 + 判定脚本）→ 才轮到角色分离**；顺序反了就是放大器 |

> 动机例证（抽象化）：一次真实评审里，只用**单维度取证**就下了结论、未做破框；
> 换成**第二条独立取证路径**后立刻得到相反且正确的结论。**若判定写进脚本，这个错不会发生** ——
> 这正是「判定权外置」优先于「更多角色」的理由。

## 4. 后续扩展清单（按优先级，**均未实现**）

| 序 | 动作 | 落地物（将来） | 对应现有机制 |
|---|---|---|---|
| 1 | roster 链合并：把 `subagent_spec.md`（未实施）+ `prompt_registry.py` + `prompt_renderer.py` 合成**一条链** | `roles.yaml → renderer → spawn → verifier` | `prompt_registry` / `prompt_renderer` |
| 2 | Maker / Checker 硬约束**用工具权限实现**（Checker 只读模式库、禁改信号 / 库） | 角色权限表 | `permission_levels.py` / ExecGate |
| 3 | 三轮 md5 复算**扩展到 role / prompt 定义**（`roles.yaml` 与渲染后 prompt 的 md5 纳入复算） | md5 复算范围扩充 | 三轮一致性 |
| 4 | `run_gate.py` 增 **team gate**：每个产物须有**独立 verifier 签名** + 证据 `N==M` | gate 规则 | `scripts/run_gate.py` |
| 5 | 每个角色必须有**退出条件** | 角色契约字段 | 防「蜂群永远在开会」 |
| 6 | 给蜂群一个**可验收的 `success_criteria`**（不同数据源 / 冲突必须升级留痕） | team `success_criteria` | `success_criteria` |

**零 LLM 边界不变**：以上 1-6 全是「确定性编排 + prompt 资产 + 权限约束」；真正的「思考」
仍由挂载的 agent 承担，sloth-loop 只做渲染 / 分派 / 校验，**不引入任何 LLM SDK / 凭据 / 调用**。

## 5. 若要引入「prompt 驱动的 agent 团队」，先解这 6 个风险

| # | 风险 | 说明 | 解法 |
|---|---|---|---|
| 1 | **顺序风险（最大）** | 角色数量 ↑ 而判定权未外置 → 团队只是放大器 | 先做 §4 的第 1、2 项 |
| 2 | **需求口述漂移** | 口述的「需要的角色」≠ 任务真实需要的角色 | 从产物反推角色；初始化只做一句话确认 |
| 3 | **自构造 prompt 不可靠** | 现造的 prompt 常缺判据 / 缺失败出口 | 模板 + schema 校验 + 版本化 md5 |
| 4 | **上下文隔离落错位置** | 把「Checker 不许看 Maker 先验」写在 prompt 里 = 靠自觉 | 隔离落在**权限**：不同工作目录 / 只读挂载 / 不同 memory 视图 |
| 5 | **成本闸缺失** | N agent × 每轮 OODA = 额度与时间 ×N | 先有预算闸（复用 `quota_window` / `backpressure` / `rate_limiter`） |
| 6 | **team 自身不可验收** | 无法判断「多角色」是否真的更可信 | team `success_criteria`：不同数据源 + 冲突必须升级留痕 |

**可复现 vs 对话生成**：初始化对话**只允许「选择 + 参数化」，不允许「创造」**；
产物落 `roles.yaml` 进 git 并算 md5，把「角色定义」纳入三轮复算范围。

## 6. 与「自主进化」的关系

- 自主进化当前**整体搁置**：不实时运行 → 无失败 / 回测数据输入 → 引擎只会空转（判定为负债）。
  唤醒路径与已完成件（信号演化、自改码门禁）见 `docs/sloth-loop-ROADMAP.md` §4b。
- AI Team / 蜂群是自主进化的**编排层**扩展，排在「自改码门禁（SelfModifyGate）」之后。
- **触发条件**：L3 有资源，或出现「需要多机并行采集 / 多 item 搭环境」的真实任务（蜂群唯一甜点区）时，再启动。

## 7. 本阶段明确「不做」

- 不实现 `roles.yaml / renderer / spawn / verifier`（无代码）；
- 不改内核、不引入 LLM（保持零 LLM 边界）；
- 不把蜂群用于任何**裁决**路径。

---
*本文与 `docs/sloth-loop-ROADMAP.md` 同源：ROADMAP 登记触发条件与执行顺序，本文登记设计结论与风险。*
