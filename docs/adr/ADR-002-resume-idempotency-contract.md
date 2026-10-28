# ADR-002: 以 Step Checkpoint + 幂等键保证恢复安全

## Status

proposed

## Context

当前已具备 round 边界 checkpoint 和 `--resume`，但在 Act/Learn 中断时仍可能重复外部副作用或经验写入。仅保存 STATE.md 无法证明某个 Step 是否已经完成。

## Decision

W1 采用以下恢复契约：

```text
idempotency_key = run_id + round + step + attempt + input_hash
checkpoint      = run_id + round + step + attempt + event_seq + config_hash + pool_hash
```

每个 Step 完成后原子写 checkpoint；恢复时校验 schema/config/pool hash，只重做未完成 Step。Pattern、Problem 和 Learn 记录使用幂等键 UPSERT。

## Alternatives Considered

- 只依赖 STATE.md：实现简单，但无法区分半轮状态，拒绝。
- 整轮重跑：兼容旧代码，但会重复外部副作用，暂不接受。
- 引入完整工作流框架：能提供状态图，但不解决现有 SQLite/业务幂等问题，延后。

## Consequences

正面影响：进程 kill/restart 后最多重做当前 Step，Learn 不重复污染模式库。  
负面影响：需要为外部 TaskRunner 定义幂等和补偿语义；无法回滚已经发生的第三方副作用时必须记录人工处理状态。  
验收：七个 OODA Step 各执行一次故障注入，恢复后无重复 Pattern/Problem，事件 trace 连续。
