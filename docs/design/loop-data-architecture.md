# Loop 数据架构设计

> P9 架构分析 | 2026-08-19 | 触发: 数据存储分层、展示分层、用户确认门禁

---

## 一、核心判断：三层存储模型

Loop 的数据不应该堆在一个 SQLite 里。参考 DSH 的事件溯源 + Surface 投影模型，分为三层：

```
┌─────────────────────────────────────────────────────┐
│                    展示层 (人看)                      │
│  IMPROVEMENTS.md, _index.md, 控制台 OODA 状态栏       │
│  格式: Markdown / 终端 ASCII art                    │
│  生命周期: 按任务生成，可删除（可从下层重建）            │
├─────────────────────────────────────────────────────┤
│                    查询层 (机器查)                    │
│  SQLite: task_sessions, patterns, rounds, problems   │
│  格式: 结构化关系表                                   │
│  生命周期: 永久保留（除非手动清理）                     │
├─────────────────────────────────────────────────────┤
│                    事件层 (真实源)                    │
│  JSONL: work_ooda/runs-*/events-*.jsonl              │
│  格式: 不可变追加日志                                  │
│  生命周期: 永久保留（审计追溯）                         │
└─────────────────────────────────────────────────────┘
```

**原则**: 展示层可以从查询层/事件层重建，不应作为唯一真实源。事件层是"发生了什么"，查询层是"怎么快速查"，展示层是"怎么给人看"。

---

## 二、存储分层：热数据 vs 冷数据 vs 永久数据

| 分层 | 数据类型 | 存储 | 生命周期 | 示例 |
|:--:|------|------|------|------|
| 🔥 热 | 当前轮状态 | 内存 + STATE.md | 本轮存活 | cursor 位置、本轮 signals |
| ❄️ 冷 | 聚合结果 | SQLite patterns.db | 永久 | 模式库、轮次记录 |
| 🧊 永久 | 原始事件 | JSONL 文件 | 永久 | 每轮 16 条事件 |
| 📄 展示 | 格式化报告 | Markdown 文件 | 按需重建 | IMPROVEMENTS, _index |

### task_sessions 表设计

```sql
CREATE TABLE task_sessions (
    id TEXT PRIMARY KEY,              -- YYYYMMDD-HHMMSS-{task}
    task_name TEXT NOT NULL,          -- 任务名称
    project_name TEXT,                -- 项目名称
    status TEXT DEFAULT 'pending',    -- pending|confirmed|running|done|blocked
    user_input TEXT,                  -- 原始任务描述
    understanding TEXT,               -- 5W1H 理解结果 JSON
    signals_count INTEGER DEFAULT 0,  -- 信号总数
    verification_cfg TEXT,            -- verification 配置 JSON
    risk_level TEXT DEFAULT 'low',    -- high|medium|low
    created_at TEXT,                  -- 创建时间
    confirmed_at TEXT,                -- 用户确认时间
    started_at TEXT,                  -- 首次执行时间
    finished_at TEXT,                 -- 完成时间
    total_rounds INTEGER DEFAULT 0,   -- 总轮次
    success_count INTEGER DEFAULT 0,  -- 成功信号数
    failure_count INTEGER DEFAULT 0,  -- 失败信号数
    stop_reason TEXT,                 -- 停止原因
    defect_report_path TEXT,          -- IMPROVEMENTS.md 路径
    last_health_score REAL DEFAULT 0  -- 最终健康分
);
```

**区分**: `task_sessions` 存"任务是什么+结果怎样"（冷数据），`events-*.jsonl` 存"每一步发生了什么"（永久数据）。

---

## 三、展示分层：人看的 vs 机器查的

| 需求 | 格式 | 存储位置 | 生成时机 |
|------|------|---------|---------|
| OODA 状态栏 | ASCII 终端 | stdout | 实时 |
| 单轮摘要 | JSONL 事件 | work_ooda/runs-*/ | 每轮结束 |
| 缺陷报告 | Markdown | IMPROVEMENTS.md | 有失败时 / 每5轮 |
| 知识库索引 | Markdown 表格 | _index.md | 每次蒸馏成功 |
| 任务总报告 | Markdown | TASK_REPORT.md | 任务完成时(新增) |
| 模式库查询 | JSON(CLI) | patterns.db | --status 命令 |
| 事件查询 | JSONL 解析 | events-*.jsonl | --inspect 命令 |

### 新增: TASK_REPORT.md（任务完成报告）

```
# 任务报告: book-distill
- 用户输入: "蒸馏 <BOOK_ROOT>\booktest 296本书"
- 5W1H 理解: Who=<owner>, What=290本skill, ...
- 执行: 100轮, 552.6s
- 结果: 295/296 成功, 1 失败(mobi)
- 校验: 4/4 assertions passed
- 缺陷: IMPROVEMENTS.md (1 issue)
- 知识库: outputs/success/_index.md
```

此报告从 `task_sessions` 表 + `rounds` 表 + events JSONL 综合生成，任务完成时自动输出。

---

## 四、日志策略

```
日志三通道:
  ┌──────────┐  ┌──────────────┐  ┌────────────────┐
  │ 控制台    │  │ 文件日志      │  │ JSONL 事件      │
  │ stdout   │  │ logs/*.log   │  │ events-*.jsonl  │
  ├──────────┤  ├──────────────┤  ├────────────────┤
  │ 人实时看  │  │ 排查回溯      │  │ 结构化审计       │
  │ 有颜色    │  │ 按天轮转      │  │ 机器可解析       │
  │ 不持久    │  │ 7天保留       │  │ 永久保留         │
  └──────────┘  └──────────────┘  └────────────────┘
```

**不变式**: JSONL 事件日志是唯一不可变的真实源。控制台和文件日志都可以从 JSONL 重建。

---

## 五、用户确认门禁

```
用户输入任务
    │
    ▼
┌─────────────────────────────────────┐
│ [Understand] 5W1H 分析              │
│ → 写入 task_sessions.understanding  │
│ → 展示 TASK_PREVIEW (格式化预览)     │
└─────────────────────────────────────┘
    │
    ▼  AskUserQuestion
┌─────────────────────────────────────┐
│ 用户确认:                            │
│ "任务: 蒸馏296本书, 验证: 3 assertions│
│  风险: medium, 预计: 100轮"          │
│ → [确认执行] / [需要调整]             │
└─────────────────────────────────────┘
    │ 确认
    ▼
┌─────────────────────────────────────┐
│ task_sessions.status → confirmed    │
│ → 开始 Loop 执行                     │
└─────────────────────────────────────┘
    │ 完成
    ▼
┌─────────────────────────────────────┐
│ task_sessions.status → done         │
│ → 生成 TASK_REPORT.md               │
│ → 如有缺陷 → IMPROVEMENTS.md         │
└─────────────────────────────────────┘
```

**强制规则**: `risk_level=high` 且无 verification → 拒绝执行。`status != confirmed` → 不进入 Loop。

---

## 六、数据流全景

```
用户输入
  │
  ▼
[5W1H 理解] ──────────────────────────────────────► task_sessions.understanding
  │                                                    (JSON, 冷数据)
  ▼
[用户确认] ◄── TASK_PREVIEW (展示层, Markdown, 临时)
  │
  ▼ 确认
[Loop 执行]
  │
  ├── 每轮 ──► events-*.jsonl (事件层, 不可变追加)
  │            patterns.db (查询层, 聚合更新)
  │            STATE.md (热数据, 覆盖)
  │
  ▼ 完成
[TASK_REPORT.md] ◄── task_sessions + rounds + events
  (展示层, 从查询层重建)

[IMPROVEMENTS.md] ◄── patterns.failure_patterns
  (展示层, 从查询层重建)

[outputs/] ◄── wrapper 脚本产物
  (业务数据, 独立于 Loop 框架)
```

---

## 七、实现优先级

| 优先级 | 改动 | 影响 |
|:--:|------|------|
| P0 | task_sessions 表 + CRUD | 填补"谁在什么时候做了什么"的空白 |
| P1 | 用户确认门禁 | risk_level=high 拒绝执行 |
| P2 | TASK_REPORT.md 生成 | 任务完成后自动输出格式化总报告 |
| P3 | events→TASK_REPORT 重建 | 从 JSONL 重建历史任务报告 |

> 📌 Loop 的数据架构规则：事件层不可变（JSONL），查询层可聚合（SQLite），展示层可重建（Markdown）。三层不互相替代——JSONL 是唯一真源，SQLite 是加速索引，Markdown 是人机界面。用户确认是任务进入 Loop 的唯一合法入口。