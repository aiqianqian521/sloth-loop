# 项目沿革（Project History）· 树懒 Loop / sloth-loop

> 本文件回答三个问题：**过去是什么样、现在是什么样、这个项目经历过什么**。
> 它只叙述事实与形态，**不指向任何一台机器的真实目录**；文中 `<...>` 均为路径占位符
> （含义见 `docs/RELEASE.md §3.1`）。仓库里发布物**零本机绝对路径**。
> 最后更新：2026-10-28

---

## 1. 一句话沿革

`loop`（方法论 / 引擎的旧称）→ `loop-dev`（引擎开发仓）→ `loop-dev-next`（升级改造副本）→
**`sloth-loop`（树懒 Loop）**：一套**零 LLM 的任务编排引擎**。
它从「把一次跑出的结果固化成可复用的流程」这件事出发，走过 42 轮 A→B→C→D 回环，
长成一个 **1760 passed / coverage 79.49%**、Apache-2.0 开源的自进化编排框架。

---

## 2. 名字与目录的演进

| 时期 | 名字 | 形态 | 说明 |
|---|---|---|---|
| 早期 | `loop` | 方法论 + 引擎 | “loop / 大循环 / 既定模式”都是这一时期的叫法。**如今它作为方法论名词保留**（`GRAND-LOOP.md`、`LOOP-ESSENCE-AND-LEARNINGS.md`、`sloth_engine/loop_*` 等沿用旧称） |
| 中期 | `loop-dev` | 引擎开发仓（分支 `codex/w0-w2`） | 位于开发机工作区 `<WORKSPACE_ROOT>/loop-dev`；同期从它 clone 出生产运行目录 `<WORKSPACE_ROOT>/loop-dev-0927` 与升级改造副本 `<WORKSPACE_ROOT>/loop-dev-next` |
| 中期 | `loop-engine` | 引擎包目录名 | 后来整体改名为 `sloth_engine/` |
| **2026-10-27 起** | **`sloth-loop`（树懒 Loop）** | 发布 / 交接仓 | 代码、目录、文档 token 统一为 `sloth-loop` / `sloth_engine`：引擎包 `sloth_engine/`、使用手册 `SLOTH-USAGE.md`、路径基名 `sloth_engine_path.py` |

> **命名边界（重要）**：**产品身份**自 2026-10-27 起叫 `sloth-loop`；**历史文档里写的 “loop” 是当时的事实，原样保留**，不追溯改写。
> 名字取自「树懒」——**慢就是稳，稳就是快**（*Slow is smooth, smooth is fast.*）：不追一次跑赢，追每一次都不返工。

---

## 3. 这个项目经历过什么（里程碑）

- **起点（cycle-1 之前）**：把「候选 → 跑 → 判定对错 → 提炼规则」的重复劳动固化下来；`success_criteria` 里写死“什么是成功”，引擎只做逼近。当时基线约 `772 passed` / coverage 约 71.91%。
- **cycle-1…cycle-17**：引擎硬化——四路并行检索、背压、失败域分类 + 两级熔断、stall 看门狗、上下文域工具策略门、步骤级异常策略 + 双窗配额、文件型额度探针；门禁自证（实测 vs 登记的单向棘轮）。
- **cycle-18…cycle-26**：**“记录本身也要被校验”**——唤醒指针提交链自证、假哈希全仓扫描、跨仓账本扫描、校验器作用域自证、“当前态 vs 历史态”口径守护。
- **cycle-27…cycle-37**：识别器 / 护栏类缺陷——字母表不得窄于现实、括号语法定点收敛为单一常量、护栏规则可达性与出口语义、fail-closed CI 推送门禁 + 密钥/家目录扫描。
- **cycle-38…cycle-42**：业务提交哨兵、测试隔离与可复现（收集期不再触碰仓库运行态）、当前态文档口径守护扩容。
- **2026-10-27**：**更名 + 开源**——`loop-dev` → `sloth-loop`；补齐 `LICENSE`(Apache-2.0) / `NOTICE` / `TRADEMARK.md` / `CITATION.cff` / `CONTRIBUTING.md`；README 顶部钉死「**项目本意 / 项目到底是什么 / 与 Agent 的区别**」。
- **2026-10-28**：**发布物去本机化 + 本文件**——仓库不再内嵌任何开发者绝对路径，全部改为占位符；历史档案只保留「当时是什么」的叙事。

---

## 4. 现在是什么样（当前态）

- **定位**：零 LLM 的 **任务编排引擎（身体）**；“思考”外包给挂载它的 Agent（大脑，也是**唯一消耗 LLM 额度的方**）。
- **能力**：OODA 7 步调度、并发、重试、熔断、限流、状态持久化、模式沉淀；业务经 `projects/<domain>/<task>/` 的 config + wrapper 接入。
- **规模**：**1760 passed** / 0 xfailed / coverage **79.49%**（单一来源 `docs/baseline.json`；`fail_under=70`）。
- **仓库**：sloth-loop，Apache-2.0；入口 `README.md` / `START.md` / `Prompt.md`。

---

## 5. 沿革里被刻意保留的教训

- **路径字面量 ≠ 产品身份**：更名时若把真实存在过的历史路径一并替换，历史提交哈希将解析不到（唤醒指针链守卫立刻变红）。
  因此治理路径时只把“指向”改成占位符，**不改写事实**。
- **记录会漂移**：错哈希、陈旧基线、未标注的历史数字，都曾把“旧值”当成“今天的值”传播；
  现在由 `scripts/docs_baseline.py` 与 `tests/test_wake_pointer_chain.py` 等守卫钉住。
- **当前态 vs 历史态**：当前态文档必须等于基线；历史档案只须标明“这是当时值”。

---

## 6. 相关文档

| 文件 | 作用 |
|---|---|
| `README.md` | 项目本意 / 是什么 / 与 Agent 的区别（项目门面） |
| `docs/LOOP-ESSENCE-AND-LEARNINGS.md` | 本体定义与教训库（该“loop”是方法论名词，非旧产品名） |
| `docs/flow/GRAND-LOOP.md` | 大任务循环唤醒指针 + 提交链回环锚 |
| `docs/sloth-loop-AS-BUILT.md` / `docs/sloth-loop-ROADMAP.md` | 架构基线 / 延后项 |
| `docs/RELEASE.md §3.1` | 路径占位符约定（发布物零本机路径） |
