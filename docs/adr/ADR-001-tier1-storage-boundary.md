# ADR-001: 保留 Tier-1 SQLite + JSONL 存储边界

## Status

accepted

## Context

Loop 当前是单机 CLI/cron 编排器，核心需求是事务查询、可恢复状态、追加事件和零基础设施部署。DSH/Cordis 提供了可借鉴的 seam 和生命周期思想，但引入 PostgreSQL、消息队列或完整插件树会增加部署和迁移风险。

## Decision

- SQLite 保存 Pattern、Problem、Round、Checkpoint 和迁移 ledger。
- JSONL 保存不可变事件事实；事件不回写覆盖。
- RuntimePaths 将所有可变数据绑定到显式 runtime root。
- 连接策略统一为 WAL、foreign keys、busy timeout；跨进程不共享连接。

## Alternatives Considered

- PostgreSQL：并发能力更强，但当前规模不值得承担服务化和运维成本。
- 单一 JSON：部署简单，但缺少事务、查询和并发保护。
- 全量 DSH/Cordis：扩展性强，但会把问题从 Loop 正确性转移到框架迁移。

## Consequences

正面影响：单机可部署、事实与控制状态分离、迁移路径清晰。  
负面影响：SQLite 写并发和备份恢复仍需压力测试；跨机器调度需要未来重新评估。  
复审条件：出现多机并发、数据库锁等待持续超阈值或 RTO 无法满足时重新评审。
