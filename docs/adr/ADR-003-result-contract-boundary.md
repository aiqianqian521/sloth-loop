# ADR-003: 统一执行结果契约边界

## Status

accepted for dev validation; production promotion requires Yellow gates to close

## Context

Loop 的 Backtest、script、agent_prompt 和 registry 路径历史上返回不同形状的结果，部分错误只能从本地化字符串推断。这样会让 Verify、Learn 和上层编排无法稳定区分进程失败、输出不可用和业务未评估。

## Decision

保留 `status/error/trades/metrics/raw_output` 兼容字段，同时将 `execution`、`output`、`business`、`provenance` 作为机器消费边界。Backtest 当前入口使用固定 error code；旧实现保留作兼容考古但不作为新调用入口。

## Alternatives Considered

- 立即引入全量 schema/migration 框架：拒绝，当前为 additive 变更，扩大回归面。
- 只改错误字符串：拒绝，消费者仍需解析文本。
- 立即重写 Orchestrator：拒绝，先锁定结果语义再拆 RunReporter/CLI router。

## Consequences

- 正面：失败矩阵可枚举；执行、输出和业务状态不再混淆；旧调用保持可用。
- 负面：registry/agent_prompt 的深度业务契约仍需后续适配；当前只能判定 dev-ready，不能视为生产发布许可。

