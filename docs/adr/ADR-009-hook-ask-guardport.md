# ADR-009：HookPipeline `ask` 与 GuardPort 出站闸门

- 状态：Accepted for dev；durable approval 为后续议题
- 日期：2026-08-31
- 范围：P2.3 W2-HOOK-01

## 决策

固定 HookOutput 决策优先级为 `block > ask > warn > allow`，排序使用不可变 `MappingProxyType`，调用方不能通过配置改序。新增 `GuardPort` 出站协议与 `InMemoryGuardPort` 适配器：`ask` 只进入 pending 队列，不同步调用 `input()`，不写入 checkpoint。

`hooks_check.guard_pattern_edit` 在检测到直接编辑模式库时产出 `ask`；`corrections.pre_check` 对待验证规则也产出 `ask`。函数和 CLI consumer 都通过 GuardPort route，保留 `HookOutput` 返回值供上层聚合。CLI 退出码固定为 block=1、ask=2、warn/allow=0，避免 ask 被宿主当作 allow。

## 原因

`make_ask()` 之前只有类型构造能力，没有真实生产方和人工闸门；如果继续以 warn 表达，会被下游静默放行，或诱发 hook 内同步询问。GuardPort 将“需要人决定”与 loop 执行状态分离，避免污染 checkpoint 和恢复幂等键。

## 取舍

- 采用内存 pending adapter：接口小、无新 schema、可在 CLI/测试验证；代价是进程退出后 pending 不持久化。
- 暂不实现 Web/SQLite 审批队列：需要明确 owner、授权、过期、审计和恢复语义，留到 P4/平台化条件满足后。
- 继续保留旧 `run_all_checks()`/`run_all_hooks()` 调用兼容；新增 guard 参数，不强迫 direct consumer 立即持久化。

## 验证

- `tests/test_hook_protocol.py --no-cov`：281 passed，覆盖 256 个 block/ask/warn/allow 组合、同级 ask 合并、MappingProxyType 不可变、真实 direct-edit ask、pre-check ask route、cp936/CLI exit gate。
- 全量 pytest（临时 uv + pytest-cov + pandas + PyYAML）：629 passed、1 xfailed，coverage 69.18%（fail-under 64）。
- 核心脚本回归 23 个全部 EXIT=0，compileall/diff-check 通过。
- 蜂群：最终短复核 PASS；早期三次请求真实返回 429，已写入 OODA/P9，不伪造全程蜂群绿。

## 后续门禁

1. 补 durable GuardPort（审批身份、过期、审计、恢复）前不得把 ask 自动升级为 allow。
2. P3.3 填充 `VerifierPort`，不得绕过 GuardPort 旁路。
3. P3.2 CI 固定 pytest/pytest-cov/PyYAML/pandas 依赖与 coverage ratchet。
