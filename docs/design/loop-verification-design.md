# Loop 验证机制设计文档

> 状态: 设计阶段 | 日期: 2026-08-19 | 触发: 1+1=3 问题分析

## 一、问题定义

当前 Loop 的 `success_criteria`（metric/operator/threshold 三元组）只检查"任务是否执行完成"（trades_count>0），不验证"结果是否正确"。脚本算出 1+1=3 会被判定为成功。

## 二、两门禁验证模型

| 门禁 | 配置 | 职责 | 失败后果 |
|------|------|------|---------|
| 1. success_criteria | 必须配置 | 执行是否完成 | error → 重试/熔断 |
| 2. verification (新增) | 可选配置 | 结果是否正确 | defect → IMPROVEMENTS.md |

## 三、verification 字段设计

```yaml
verification:
  mode: "swarm"              # single | swarm
  assertions:
    - type: "equals"         # equals | range | regex | callback
      field: "trades.0.pnl"
      expected: 2.0
      tolerance: 0.01
  regression:
    tests:
      - "tests/test_basic.py::test_addition"
```

## 四、蜂群模式

多个独立验证器并行检查同一结果，任意一个 FAIL 则整体 FAIL。每个验证器单一职责、独立并行、失败隔离。

## 五、配置强制策略

| 风险等级 | verification | 示例 |
|:---:|------|------|
| high | 强制，≥2 assertions | 交易计算 |
| medium | 推荐，≥1 assertion | 数据蒸馏 |
| low | 可选 | 探索任务 |

## 六、实现阶段

| 阶段 | 内容 | 预估行数 |
|:--:|------|:--:|
| P0 | verification 字段 + assertion 执行 | +50 |
| P1 | swarm 并行验证 | +30 |
| P2 | 回归测试引用 | 复用 backtest_adapter |
| P3 | 风险等级强制检查 | +20 |

## 七、蜂群模式 vs 传统测试对比

| 维度 | 传统单元测试 | 蜂群验证 |
|------|------------|---------|
| 触发时机 | 代码提交时 (CI) | 每次 Loop 执行后 |
| 验证对象 | 代码逻辑 | 任务输出结果 |
| 失败反馈 | CI 日志 | IMPROVEMENTS.md + 模式库 |
| 可进化 | 否（静态用例） | 是（失败模式自动学习） |
| 并行度 | 测试框架控制 | Loop 控制每个验证器独立进程 |