# sloth_engine — 自进化回测编排框架接入文档

> 版本: v3.4 | 更新: 2026-08-21 | 引擎单测基线（历史 2026-08-21）: 490 passed (98.4%) | 压力测试: 30 sigs/s | 本仓库当前全量基线见 `docs/baseline.json`：1760 passed / 0 xfailed / coverage 79.49%（fail_under=70）

## 一、架构概述：CLI 驱动，非 MCP

Loop 是一个 **CLI 命令行工具**，通过 `python orchestrator.py <args>` 运行。它**不是 MCP Server**，而是作为 Claude Code / cron / shell 的**子进程**被调用。

```
┌──────────────────────────────────────────────────────────┐
│                      接入层                               │
│  cron / shell / Claude Code subprocess / 手动命令行        │
└──────────────────────┬───────────────────────────────────┘
                       │ python orchestrator.py --once
                       ▼
┌──────────────────────────────────────────────────────────┐
│              Orchestrator (OODA Engine)                   │
│                                                          │
│  U(Understand) → O(Observe) → O(Orient)                  │
│  → D(Decide) → A(Act) → V(Verify) → L(Learn)            │
│                                                          │
│  每步写入结构化事件日志 (JSONL v3.0)                       │
│  跨轮状态通过 RoundContext 传递                            │
└──────┬───────────────┬───────────────┬───────────────────┘
       │               │               │
       ▼               ▼               ▼
┌──────────┐  ┌──────────────┐  ┌──────────────────┐
│ JSONL    │  │  SQLite      │  │  Subprocess       │
│ 事件日志  │  │  模式库       │  │  回测/PM脚本       │
│ work_ooda│  │ patterns.db  │  │  backtest/*.py    │
└──────────┘  └──────────────┘  └──────────────────┘
```

## 二、完整 CLI 接口

### 2.1 所有命令

```bash
# 环境自检
python orchestrator.py --doctor

# 单轮执行（完整 OODA 7步）
python orchestrator.py --once

# 快速模式（跳过 OODA）
python orchestrator.py --once --fast

# 连续循环运行
python orchestrator.py

# 查看模式库
python orchestrator.py --status

# 查看历史运行记录
python orchestrator.py --history

# 查看 JSONL 事件日志
python orchestrator.py --inspect runs          # 列出所有日志
python orchestrator.py --inspect timeline      # 时间线摘要
python orchestrator.py --inspect last-error    # 最近错误
python orchestrator.py --inspect round --round 3  # 第3轮详情

# 审核失败 → 升级排除规则
python orchestrator.py --review --yes --scope combo

# 指定信号文件
python orchestrator.py --once --signals data/my_signals.json

# 加载外部任务定义
python orchestrator.py --once --task config/pm_task.yaml

# 多项目模式
python orchestrator.py --project eth-usdc --once

# 覆盖最大轮数
python orchestrator.py --max-rounds 50

# 清空模式库（危险）
python orchestrator.py --reset --yes
```

### 2.2 完整参数表

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `--config` | str | `config.yaml` | 配置文件路径 |
| `--signals` | str | 配置文件中的值 | 候选信号 JSON 文件 |
| `--once` | flag | false | 运行单轮（完整 OODA 7步） |
| `--fast` | flag | false | 跳过 OODA 步骤 |
| `--doctor` | flag | false | 环境自检（Python/PyYAML/DB/回测脚本） |
| `--status` | flag | false | 查看模式库状态 |
| `--history` | flag | false | 查看历史运行记录 |
| `--review` | flag | false | 审核待处理失败 → 升级排除规则 |
| `--reset` | flag | false | 清空模式库（需 --yes） |
| `--yes` | flag | false | 非交互模式确认 |
| `--scope` | str | `combo` | 排除粒度: `combo`(信号@市场) / `pattern`(全局) |
| `--min-win-rate` | float | None | review 时最低胜率过滤 |
| `--max-rounds` | int | 配置文件值 | 覆盖最大轮数 |
| `--task` | str | None | 外部任务定义文件 (YAML/JSON) |
| `--project` | str | None | 多项目名称 |
| `--inspect` | str | None | JSONL 日志查询: runs/round/timeline/last-error |
| `--round` | int | None | 配合 --inspect round 指定轮次 |

## 三、配置文件 (config.yaml)

```yaml
# ── 存储 ──
memory:
  sqlite_path: "data/patterns.db"

# ── 循环控制 ──
loop:
  signals: "data/signals_seed.json"
  batch_size: 3
  max_rounds: 20
  max_seconds: 1800
  no_progress_stop: 3
  meta_analyze_every: 5

# ── 预算合同 (hard=框架可自执行, soft=意图声明) ──
budget:
  hard:
    max_rounds: 20
    max_runtime_minutes: 30
    max_consecutive_failures: 2
  soft:
    max_tokens_per_round: 50000
    max_sub_agents: 3

# ── 停止条件 ──
stop:
  completion: [all_criteria_met, max_rounds_reached]
  safety: [budget_exhausted, consecutive_failures, denylist_hit]

# ── 回测配置 ──
backtest:
  script: "backtest/mock_backtest.py"
  timeout_sec: 3600
  python: ""
  cwd: ""
  extra_args: "--max-bars 26000"

# ── OODA 设置 ──
ooda:
  enabled: true
  uq_enabled: true
  delta_enabled: true
  annotation_enabled: true

# ── L2 进化循环 ──
l2:
  enabled: true
  progress_window: 5
  periodic_every: 5
  queue_trigger: 3
  anomaly_trigger: true
  stagnation_trigger: 2

# ── 区域权限 (green=自动批准, yellow=警告, red=阻断) ──
zones:
  green: [batch_size, timeout_sec, meta_analyze_every, max_rounds]
  yellow: [exclusion_rule, success_criteria, filter_thresholds]
  red: [hard_constraints, core_safety_rules, ooda_step_sequence]

# ── 任务定义（可被 --task 文件覆盖）──
task:
  name: "demo-backtest"
  workspace: "workspace/"        # 可选：任务专属工作目录（I/O 隔离）
  success_criteria:
    - metric: "trades_count"
      operator: "gt"
      threshold: 0
  scope:
    allow: ["data/", "signals/", "backtest/"]
    deny:  ["secrets/", "keys/"]

# ── PM 脚本接入 ──
pm_tasks:
  phase2_merge_scan:
    name: "pm-phase2-merge-scan"
    execution:
      type: "script"
      entry: "python skills/quant-project-manager/qupm-data/phase2_merge_scan.py"
    success_criteria:
      - metric: "trades_count"
        operator: "gt"
        threshold: 0
```

## 四、信号文件格式

```json
[
  {
    "signal_pattern": "极端位置追单",
    "market_condition": "H240趋势"
  },
  {
    "signal_pattern": "趋势跟踪金叉入场",
    "market_condition": "H1震荡"
  }
]
```

必填字段: `signal_pattern`。可选字段: `market_condition`（默认 "unknown"）。

## 五、任务定义文件 (--task)

支持三种执行模式：

### 5.1 脚本模式 (subprocess)

```yaml
name: "my-backtest-task"
execution:
  type: "script"
  entry: "python backtest/my_script.py --max-bars 10000"
success_criteria:
  - metric: "trades_count"
    operator: "gt"
    threshold: 0
```

### 5.2 Agent Prompt 模式 (Python 模块动态加载)

```yaml
name: "my-agent-task"
execution:
  type: "agent_prompt"
  entry: "my_module.task_runner.MyTaskRunner"
success_criteria:
  - metric: "win_rate"
    operator: "gte"
    threshold: 0.50
```

### 5.3 ToolRegistry 模式 (已注册工具)

```yaml
name: "my-tool-task"
execution:
  type: "my_registered_tool"
  entry: ""
success_criteria:
  - metric: "sharpe"
    operator: "gt"
    threshold: 0.5
```

## 六、接入方式

### 6.1 Cron 定时任务

```bash
# crontab: 每 5 分钟跑一轮
*/5 * * * * cd /path/to/loop && bash sloth_engine/cron_wrapper.sh

# cron_wrapper.sh 逻辑:
#   1. 获取文件锁 (.loop.lock) 防并发
#   2. 执行 python orchestrator.py --once
#   3. 日志输出到 logs/ 目录
```

### 6.2 Claude Code / Harness 集成

Loop 通过以下机制与 Claude Code 交互：

#### a) 子进程调用

```
Claude Code 执行:
  ! python sloth_engine/orchestrator.py --doctor     # 先自检
  ! python sloth_engine/orchestrator.py --once       # 跑一轮
  ! python sloth_engine/orchestrator.py --status     # 查看状态
```

#### b) Hook 触发 (hooks.json + hooks_check.py)

```json
// sloth_engine/hooks.json
{
  "hooks": {
    "PreToolUse": [{
      "matcher": "Bash",
      "hooks": [{
        "type": "command",
        "command": "python sloth_engine/hooks_check.py enforce_before_backtest"
      }]
    }]
  }
}
```

Hook 检查点:
- `enforce_before_backtest` — 回测命令前，提醒读取失败模式库
- `enforce_after_backtest` — 回测命令后，提醒记录结果
- `guard_pattern_edit` — 直接编辑模式库时，提醒走工具而非手动

#### c) 前置矫正检查

```bash
python sloth_engine/corrections/pre_check.py              # 检查全部规则
python sloth_engine/corrections/pre_check.py --rule R4    # 只查参数扫描
python sloth_engine/corrections/pre_check.py --work-dir work_ooda/loop-2026-08-18
```

#### d) 通过 --task 注入 PM 任务

Claude Code 写 YAML 任务文件 → `python orchestrator.py --once --task <file>` → 读取结果 JSONL

### 6.3 多项目模式

```bash
projects/
├── my-task/
│   ├── config.yaml          # task.workspace: "workspace/"
│   ├── data/signals.json    # 信号文件
│   └── workspace/           # 自动创建，I/O 文件隔离
│       └── _data/
└── another-task/
    ├── config.yaml
    └── ...

python orchestrator.py --project my-task --once
```

**项目模式 + workspace**：每个项目的 I/O 文件落在自己的 `workspace/_data/` 下，不和全局 `_data/` 或其他项目冲突。不配 `task.workspace` 则回退到全局 `_data/`，行为与 v3.0 一致。

## 七、日志系统 (v3.0 JSONL)

### 7.1 日志格式

每轮 OODA 生成一个 JSONL 文件：`work_ooda/runs-YYYY-MM-DD/events-{timestamp}.jsonl`

```json
{"ts":"2026-08-18 14:30:25.096","task":"demo-backtest","round":1,"step":"round:start","status":"START","message":"signals_in=2"}
{"ts":"2026-08-18 14:30:25.097","task":"demo-backtest","round":1,"step":"understand","status":"START","message":""}
{"ts":"2026-08-18 14:30:25.098","task":"demo-backtest","round":1,"step":"understand","status":"PASS","message":"goal= | boundary= | success="}
{"ts":"2026-08-18 14:30:25.108","task":"demo-backtest","round":1,"step":"observe","status":"PASS","message":"signals_input=2 | signals_excluded=0 | patterns_loaded=0"}
{"ts":"2026-08-18 14:30:25.110","task":"demo-backtest","round":1,"step":"orient","status":"PASS","message":"severity=normal | issue_count=0"}
{"ts":"2026-08-18 14:30:25.112","task":"demo-backtest","round":1,"step":"decide","status":"PASS","message":"action=execute | approach=standard_backtest"}
{"ts":"2026-08-18 14:30:25.750","task":"demo-backtest","round":1,"step":"act:result","status":"PASS","message":"status=completed trades=2 637ms"}
{"ts":"2026-08-18 14:30:25.752","task":"demo-backtest","round":1,"step":"verify","status":"PASS","message":"pass_count=1 | total=1 | fail_count=0"}
{"ts":"2026-08-18 14:30:25.754","task":"demo-backtest","round":1,"step":"learn","status":"PASS","message":"new_failures=0 | new_successes=0"}
```

### 7.2 错误场景示例

```json
{"ts":"2026-08-18 14:30:26.450","task":"demo","round":3,"step":"act:retry","status":"FAIL","message":"standard — timeout","error":"script timeout after 300s","elapsed_ms":300449}
{"ts":"2026-08-18 14:30:27.001","task":"demo","round":3,"step":"act:retry","status":"FAIL","message":"longer_timeout — also failed","error":"exit_code:1","elapsed_ms":600551}
{"ts":"2026-08-18 14:30:27.002","task":"demo","round":3,"step":"act:result","status":"SKIP","message":"status=skipped | ERROR: retries_exhausted"}
```

### 7.3 查询 API

```python
from event_log import EventLog

elog = EventLog("work_ooda/runs-2026-08-18/events-1723456789.jsonl")

# 总览
elog.get_summary()
# → {"total_events": 16, "status_counts": {"PASS": 10, "START": 6}, "failures": []}

# 按轮查询
elog.get_round_events(3)

# 最近失败
elog.last_event_by_status("FAIL")

# 重试历史
elog.get_retry_history(round_num=3)
```

## 八、WebUI 接入规划

日志 v3.0 的每个 JSONL 行即自包含——`ts/task/round/step/status/message/error` 七字段可直接渲染。

### 数据源

| 数据 | 位置 |
|------|------|
| 实时事件流 | `work_ooda/runs-YYYY-MM-DD/events-*.jsonl` (tail -f) |
| 历史运行 | `data/patterns.db` → `run_history` 表 |
| 模式库 | `data/patterns.db` → `failure_patterns` / `success_patterns` 表 |
| 问题队列 | `data/patterns.db` → `problem_queue` 表 |

### 最小 HTTP API

```python
from flask import Flask, jsonify
from event_log import EventLog
import glob, sqlite3

app = Flask(__name__)

@app.route("/api/runs")
def list_runs():
    return jsonify(glob.glob("work_ooda/runs-*/events-*.jsonl"))

@app.route("/api/events/<path:logfile>")
def get_events(logfile):
    elog = EventLog(logfile)
    return jsonify({"summary": elog.get_summary(), "events": elog.as_dicts()})

@app.route("/api/status")
def get_status():
    conn = sqlite3.connect("data/patterns.db")
    conn.row_factory = sqlite3.Row
    rounds = [dict(r) for r in conn.execute("SELECT * FROM rounds ORDER BY id DESC LIMIT 20")]
    return jsonify(rounds)
```

## 九、目录结构

```
loop/
├── sloth_engine/
│   ├── orchestrator.py        ← 主入口 CLI + OODA Engine
│   ├── event_log.py           ← 事件日志 v3.0（一行自解释 JSONL）
│   ├── round_context.py       ← Act→Orient 跨轮状态载体
│   ├── memory_store.py        ← SQLite 模式库 CRUD
│   ├── config.yaml            ← 配置文件
│   ├── config_util.py         ← 零依赖配置加载
│   ├── hook_protocol.py       ← Hook 标准化输出
│   ├── hooks_check.py         ← Claude Code Hook 检查脚本
│   ├── hooks.json             ← Hook 触发配置
│   ├── signal_source.py       ← 信号生成器
│   ├── tool_registry.py       ← 工具注册表
│   ├── cron_wrapper.sh        ← cron 包装脚本
│   ├── _archive/       ← 被取代遗留：structured_cli(被 ExecGate 取代)、mcp_client(旧 MCP)、loop_pipeline(被 backpressure/circuit_breaker 取代, cycle-11)
│   ├── adapters/
│   │   ├── backtest_adapter.py   ← 回测适配器
│   │   └── task_runner.py        ← 通用任务执行器 ABC
│   ├── corrections/
│   │   ├── pre_check.py       ← 前置矫正检查（R1-R6）
│   │   └── playbook.json      ← 矫正规则手册
│   └── data/patterns.db       ← SQLite 数据库
├── tests/
│   ├── test_loop.py           ← 74 回归测试
│   ├── test_act_orient_chain.py ← 63 Act→Orient 链路测试
│   ├── test_v2_p0.py / test_v2_p1p2.py ← v2.0 测试 (26+75)
│   └── test_adapters/event_log/... ← pytest 275 tests total
├── work_ooda/                 ← OODA 过程记录 + JSONL 日志
├── backtest/                  ← 回测脚本目录
└── projects/                  ← 多项目目录
    └── book-distill/          ← book-to-skill 蒸馏任务 (296→301 本)
```

## 十、典型工作流

```bash
# 1. 首次使用
python sloth_engine/orchestrator.py --doctor       # 环境自检
python sloth_engine/orchestrator.py --once         # 单轮试跑
python sloth_engine/orchestrator.py --status       # 查看结果
python sloth_engine/orchestrator.py --review --yes # 审核 → 排除规则
python sloth_engine/orchestrator.py                # 连续循环

# 2. Claude Code 驱动
# 用户: "用 book-to-skill 蒸馏这 3 本书"
# Claude:
#   [写信号 JSON → 配 backtest.script → orchestrator.py --once]
#   [读 JSONL 日志 → 查看蒸馏结果 → 决定是否继续]

# 3. 通用任务接入
# 用户: "这是我的爬虫脚本，帮我接入 Loop 自动重试+学习"
# Claude:
#   [准备信号文件 + task YAML → orchestrator.py --once --task my_task.yaml]
#   [观察 OODA 流程 → 失败自动记录 → review 升级排除规则]
```

## 十一、测试

```bash
# pytest 套件 (275 tests)
python -m pytest tests/ -x --tb=short -q

# 自定义 runner (215 tests)
python tests/test_loop.py              # 74 回归
python tests/test_v2_p0.py             # 26 v2.0 P0
python tests/test_v2_p1p2.py           # 75 v2.0 P1-P2
python tests/test_act_orient_chain.py  # 40 OODA 场景 (pytest mode)

# 合计（历史 2026-08-21，event_log v3.0 迁移期）: 490 passed, 8 pre-existing failures
# 综合通过率: 98.4%

# 压力测试
python -c "
from orchestrator import Orchestrator
# 500 signals × 10 rounds OODA → 30 sigs/s, 零崩溃
"
```