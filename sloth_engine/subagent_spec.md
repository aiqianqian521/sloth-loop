# Subagent 分工规范 (Maker / Checker 分离)

> 历史文档 | 2026-08-11 | 状态: 设计阶段，未实施
> 维度: 规则强制（软约束层的一种实现）
> 来源: 清华论文 + 中金方案均强调「生成与验证必须独立」
> 适配: Claude Code 原生支持 Agent tool（subagent spawn）

## 为什么必须分离

- **自 bias 风险**: 同一 Agent 既生成信号又验证信号，会在自己先验上打转
- **信用分配**: 生成和验证分开，才能定位「哪一步起作用」
- **对齐漂移防护**: Checker 加载不同上下文/不同 Skill，独立判断

## 角色定义

### Maker Agent（信号生成）
- 输入: 市场快照 + 成功模式库起点
- 职责: 生成候选信号
- 工具: 代码读取、信号生成、知识库检索
- **禁止**: 读取失败模式库的 exclusion 判定结果、自我声明信号有效

### Checker Agent（独立验证）
- 输入: Maker 输出的候选信号 + 失败信号模式库
- 职责: 逐条对照排除规则，输出 passed / excluded
- 工具: 失败模式库读取、排除判定
- **禁止**: 修改信号定义、修改模式库

## 编排方式

```
主 Agent (Orchestrator 或人)
  │
  ├─ spawn Maker   → 候选信号 signals[]
  │
  ├─ spawn Checker(signals[], 失败模式库)
  │     → passed[] / excluded[]
  │
  ├─ run_backtest(passed[])
  │
  └─ record_result(结果) → 写入库
```

## 与 MCP 方案的关系

| 层 | Subagent | MCP |
|---|---|---|
| 生成/验证分离 | ✅ 原生 spawn | ✅ 工具分离 |
| 强制力 | 中（约定） | 硬（接口） |
| 成本 | 低 | 中高 |
| 适用阶段 | Step1-3 | Step4 |

**渐进路径**: 先用 Subagent 软约束跑通 Maker/Checker 分离 → 流程稳定后升级 MCP 硬约束。
