# DSH vs 文章 vs Loop — 对照分析

> 2026-08-20 | 基于 LangChain CEO 文章 + DSH 源码 + Loop 现状

## 一、文章中 11 个概念 × DSH 实现 × Loop 差距

| # | 文章概念 | DSH 实现 | Loop 差距 |
|:--:|------|------|------|
| 1 | Harness = 在正确时间给正确上下文 | ✅ `RuntimeContextProjection` 每次 step 重新投射上下文，只传变化部分 | ❌ Loop 每次 Act 传完整输入，不跟踪上下文变化 |
| 2 | Agent = 模型+Harness+上下文 | ✅ 三组件清晰分离（`agent-loop/model/session`） | ⚠️ 有 OODA 编排但模型/上下文层不明确 |
| 3 | 中间件定制：钩子+插件+核心循环 | ✅ `hook-protocol` + `agent/pre-step` waterfall + CC/Codex bridge | ⚠️ 有 hooks_check.py 但无瀑布式事件派发 |
| 4 | 认知架构引导模型行为 | ⚠️ ReAct + Plan Mode（二元开关） | ✅ OODA 7步比 ReAct 更结构化 |
| 5 | 分布内/外判断标准 | ✅ `agent/request` 根据模型动态切换工具实现 | ❌ 无分布检测机制 |
| 6 | 评估体系定义优秀标准 | ⚠️ `messageFeedback` 手动评分，无自动基准测试 | ⚠️ `success_criteria` 只看执行完成 |
| 7 | Harbour 基准测试框架 | ❌ DSH 没有，是 LangChain 的产品 | ❌ 无 |
| 8 | 可观察性被严重低估 | ✅ `session-telemetry-otel` + JSONL 不可变日志 | ⚠️ 有 JSONL 但无可视化/趋势分析 |
| 9 | 大多数故障出在上下文 | ✅ `compaction` 自动压缩 + surface 管理 | ❌ 无上下文质量评分 |
| 10 | 数据飞轮闭环 | ❌ **DSH 也没有！** compaction 只是压缩不是飞轮 | ❌ Loop 有 OODA 骨架，缺自动化 |
| 11 | LangSmith Engine 自动化 | ❌ DSH 没有，LangChain 的产品 | ❌ 无 |

## 二、DSH 中 Loop 可以直接参考的设计

### 2.1 RuntimeContextProjection（上下文增量投喂）

```
DSH: 每个 step 前检查上下文快照是否变化 → 变化才创建新 user/message
Loop 改造: Act 前对比本轮输入和上轮输入的 diff → 只传变化部分
```

### 2.2 事件瀑布（Waterfall Event Dispatch）

```
DSH: emit（fire-and-forget）| serial（有序等待）| waterfall（中间件拦截替换返回值）
Loop 改造: hook_protocol.py 加 waterfall 模式，支持中间件拦截 OODA 步骤
```

### 2.3 压缩摘要（Compaction Summary）

```
DSH: 8段结构化摘要（请求、概念、文件、错误、待办、当前、下一步、关键上下文）
Loop 改造: Learn 步骤后生成 compaction，多轮上下文过长时自动压缩
```

### 2.4 Surface / Event 分层

```
DSH: surface 事件（模型可见）vs 日志事件（仅记录）
Loop 改造: events JSONL 区分 surface（模型上下文）和 log（审计追溯）
```

### 2.5 分布内/外自适应

```
DSH: model配置文件根据当前模型动态切换工具实现
Loop 改造: risk_level 不靠配置，靠信号池特征自动推算分布距离
```

## 三、Loop 独有优势（DSH 没有的）

| Loop 特性 | DSH 对应 | 说明 |
|------|------|------|
| OODA 7步结构化 | ReAct 循环 | OODA 更细粒度，更适合作监督框架 |
| 模式库(patterns.db) | 无 | DSH 不持久化学习成果 |
| 缺陷报告(IMPROVEMENTS.md) | 无 | DSH compaction 不产生改进建议 |
| verification 断言 | 无(schema校验) | Loop 有语义验证，DSH 只有结构验证 |
| task.workspace 隔离 | session.cwd | 两者等价 |

## 四、实现优先级（按 DSH 参照）

| 优先级 | 改造项 | 对标 DSH | 行数 |
|:--:|------|------|:--:|
| P0 | 上下文增量投喂 | `RuntimeContextProjection` | ~ Prosecutor | Prosecutor |~30 |
| P0 | 压缩摘要(Learn 后) | `compaction` 8段结构 | ~40 |
| P1 | 事件瀑布 dispatch | `waterfall` 中间件模式 | ~50 |
| P1 | Surface/Log 分层 | `SURFACE_EVENT_TYPES` + deriveMessages | ~30 |
| P2 | 分布距离检测 | model profile 动态切换 | ~40 |
| P3 | 数据飞轮自动化 | LangSmith Engine（绿色地带） | ~100 |