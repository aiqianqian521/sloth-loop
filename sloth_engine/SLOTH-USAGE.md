# Loop 任务接入指南 v3.2

> **本文档专门解答：如何将任意任务接入 Loop 的 OODA 监督 + 自进化框架。**
> 零依赖，Python 3.11 直接用。
> CLI 完整参数、配置、日志、WebUI 规划见 `sloth_engine/README.md`
> 从零开始跑通闭环见 `sloth_engine/README.md`
> 更新: 2026-09-24 — v3.4: 补项目命名规范;  v3.3: 新增 verification 验证机制（断言+蜂群+回归+风险等级）

## 一、快速开始（3 步）

### Step 1: 准备信号文件

Loop 通过 `SignalSource` 自动识别格式。支持 **CSV / JSON / Markdown 表格**。

**CSV 示例** (`my_signals.csv`):

```csv
trigger_type,direction,price,score
MA_cross,buy,2300.0,3.5
Fib_retrace,sell,2250.0,2.1
```

**JSON 示例** (`my_signals.json`):

```json
[
  {"signal_pattern": "MA_cross", "market_condition": "uptrend", "price": 2300},
  {"signal_pattern": "Fib_retrace", "market_condition": "downtrend", "price": 2250}
]
```

**Markdown 示例** (`my_signals.md`):

```markdown
| signal_pattern | market_condition | score |
| --- | --- | --- |
| MA_cross | uptrend | 3.5 |
| Fib_retrace | downtrend | 2.1 |
```

### Step 2: 定义任务配置

创建 `my_task.yaml`:

```yaml
task:
  name: "my-task"               # 必填：任务名称
  workspace: "workspace/"       # 推荐：任务专属工作目录（I/O 隔离）
  success_criteria:             # 可选：如何判断成功
    - metric: "win_rate"
      operator: "gte"
      threshold: 0.55
  execution:
    type: "script"              # script | agent_prompt
    entry: "python my_script.py --input signals.json"
  scope:                        # 可选：文件访问边界
    allow: ["data/", "output/"]
    deny: ["secrets/"]
```

**关于 workspace**：配置后，Loop 自动创建该目录，所有 I/O 文件（输入 JSON、输出 JSON）落入 `workspace/_data/` 下，不再使用全局 `_data/`。不配置则回退到全局路径（向后兼容）。推荐多任务场景务必配置，避免 I/O 文件互相覆盖。

### Step 3: 运行

```bash
# 进入 sloth_engine 目录
cd <SLOTH_ROOT>/sloth_engine

# 医生模式，确认配置
python orchestrator.py --doctor

# 指定信号文件运行
python orchestrator.py --signals my_signals.csv --max-rounds 20

# 使用自定义任务配置
python orchestrator.py --task my_task.yaml --signals my_signals.json

# 查看结果
python orchestrator.py --status

# 查看 JSONL 事件日志
python orchestrator.py --inspect timeline
python orchestrator.py --inspect round --round 1
```

---

## 二、项目模式（推荐）

多任务场景推荐使用 `--project` 模式，每个任务一个独立项目目录，配合 `workspace` 做到完全隔离：

```bash
projects/
└── my-task/
    ├── config.yaml          # 项目配置（task.workspace 指向 workspace/）
    ├── data/
    │   └── signals.json     # 信号文件
    ├── workspace/           # 自动创建：I/O 文件、日志
    │   └── _data/
    └── patterns.db          # 模式库（可选，默认 data/patterns.db）
```

运行：
```bash
python orchestrator.py --project my-task --once
```

项目配置中 `task.workspace` 的相对路径相对于项目目录解析。

-
### 项目命名规范（2026-09-24 补，防空目录/时间戳错误）

> 触发：`pm-replay-regen-20260924-000000` 时分秒写死为 000000（未取真实时间）→ 已改正。

**命名格式**（统一）：
```
projects/<domain>/<task>-<yyyyMMdd>-<HHmmss>/
```
- `<domain>`：场景/域（PM 场景统一放 `projects/pm/`；通用放根下 `projects/`）。
- `<task>`：任务短名（小写连字符）。
- `<yyyyMMdd>` + `<HHmmss>`：**必须动态取当前时间**，禁止手写 `000000` 占位。

**正确创建命令**（PowerShell）：
```powershell
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'   # 例: 20260924-111957
$dir   = "projects/pm/pm-replay-regen-$stamp"
```

**运行方式（易错点）**：
- 任务目录在 `projects/pm/<task>/`（PM 域）时，loop 的 `--project <name>` **只认根下** `projects/<name>/`。因此对 `projects/pm/<task>/` 必须用：
  ```bash
  python orchestrator.py --config projects/pm/<task>/config.yaml --signals projects/pm/<task>/data/signals.csv --max-rounds N
  ```
- 若用 `--project`，任务目录须放 `projects/<task>/`（根下）。

**自查**：目录名中出现 `000000` 时戳 = 未取真实时间，应改正。


## 三、执行模式

### 模式 A: script（推荐）

Loop 通过 subprocess 调用脚本。

**I/O 契约**:

```
Loop 调用: python your_script.py --input <in.json> --output <out.json>

输入 in.json:
  {"signals": [...], "params": {...}}

输出 out.json:
  {"trades": [...], "pnl": {"total": 0.05}, "win_rate": "55%", "sharpe": 1.2}

退出码: 0=成功, 非0=失败
```

**脚本模板** (`my_script.py`):

```python
import json, sys, argparse

parser = argparse.ArgumentParser()
parser.add_argument("--input", required=True)
parser.add_argument("--output", required=True)
args = parser.parse_args()

with open(args.input) as f:
    data = json.load(f)
signals = data["signals"]

results = []
for sig in signals:
    # === 你的业务逻辑 ===
    results.append({
        "signal_pattern": sig.get("signal_pattern", "unknown"),
        "market_condition": sig.get("market_condition", "unknown"),
        "pnl": 0.01,
        "failure_reason": "",
    })

output = {
    "trades": results,
    "pnl": {"total": sum(r["pnl"] for r in results)},
    "win_rate": f"{sum(1 for r in results if r['pnl'] > 0) / max(len(results), 1) * 100:.0f}%",
    "sharpe": 1.0,
}
with open(args.output, "w") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)
sys.exit(0)
```

### 模式 B: agent_prompt

Loop 通过 importlib 加载 Python 类。类需继承 `TaskRunner`。

```python
# my_runner.py
from adapters.task_runner import TaskRunner, TaskInput, TaskResult

class MyRunner(TaskRunner):
    def run(self, input: TaskInput) -> TaskResult:
        signals = input.signals or []
        # ... 你的逻辑 ...
        return TaskResult(status="completed", metrics={"trades_count": len(signals)})
```

配置:

```yaml
task:
  execution:
    type: "agent_prompt"
    entry: "my_runner:MyRunner"     # module:ClassName
```

### 模式 C: 跨 Python 版本 subprocess（容器检查脚本等）

当任务脚本需要不同 Python 版本（如 Python 2.7），wrapper 作为中间层调用 subprocess：

```python
# real_wrapper.py — Loop (Python 3) → subprocess → Python 2.7 脚本
def execute_script(signal_pattern, plugin_dir, python27):
    code = '''
import sys; sys.path.insert(0, r"{plugin_dir}")
m = __import__("{mod_name}")
result = m.start()
print("__LOOP_OK__:" + str(result)[:1000])
'''.format(plugin_dir=plugin_dir, mod_name=signal_pattern)
    proc = subprocess.run([python27, "-c", code], capture_output=True, text=True, timeout=30)
    # parse __LOOP_OK__ / __LOOP_ERROR__ markers
```

错误分类示例：
```python
ERROR_TAGS = {
    "ImportError": "missing_dependency",
    "SyntaxError": "encoding_or_syntax",
    "AttributeError": "api_mismatch",
}
```

通过 `backtest.extra_args` 传入动态参数（如 `--plugin-dir`）。

---

## 四、信号格式规范

每个信号至少包含:

| 字段 | 必须 | 说明 |
|------|:--:|------|
| `signal_pattern` | ✅ | 信号唯一标识 |
| `market_condition` | 推荐 | 市场/环境条件 |
| `aliases` | 推荐 | 排除规则匹配标签 |

其他字段自由扩展。

### 字段映射

源数据字段名不同时，用 `column_map`:

```python
from signal_source import load_signals

signals = load_signals("data.csv", column_map={
    "trigger_name": "signal_pattern",
    "market": "market_condition",
}, aliases_from=["direction", "trigger_name"])
```

---

## 五、OODA 循环

每轮执行完整 7 步：

```
[U] Understand → 确认任务理解
[O] Observe    → 加载模式库 + 排除检查 + Delta 对比
[O] Orient     → 根因诊断 + 严重度判定（含上轮 Act 错误回流）
[D] Decide     → skip / execute / skip_backtest
[A] Act        → 执行任务（standard → longer_timeout → graceful_skip 三级重试）
[V] Verify     → 对比 success_criteria
[L] Learn      → 去重 → 写入模式库 → 问题队列
```

停止条件（自动触发，无需手动干预）：
- `max_rounds` 轮数上限
- 连续 `no_progress_stop` 轮无新发现
- 连续 `error_stop` 次执行错误（熔断）
- L2 健康分达标自动停止

---

## 六、完整示例：XPath 爬虫接入 Loop

### 爬虫脚本 (`xpath_crawler.py`)

```python
import json, sys, argparse, requests

parser = argparse.ArgumentParser()
parser.add_argument("--input", required=True)
parser.add_argument("--output", required=True)
args = parser.parse_args()

with open(args.input) as f:
    data = json.load(f)

results = []
for sig in data["signals"]:
    try:
        url = sig.get("url", "")
        resp = requests.get(url, timeout=10)
        results.append({
            "signal_pattern": sig["signal_pattern"],
            "pnl": 1 if resp.status_code == 200 else -1,
            "failure_reason": "" if resp.status_code == 200 else f"HTTP {resp.status_code}",
        })
    except Exception as e:
        results.append({
            "signal_pattern": sig["signal_pattern"],
            "pnl": -1,
            "failure_reason": str(e)[:200],
        })

output = {
    "trades": results,
    "pnl": {"total": sum(r["pnl"] for r in results)},
    "win_rate": f"{sum(1 for r in results if r['pnl'] > 0) / max(len(results), 1) * 100:.0f}%",
    "sharpe": 0,
}
with open(args.output, "w") as f:
    json.dump(output, f, ensure_ascii=False)
sys.exit(0)
```

### 信号文件 (`xpath_urls.csv`)

```csv
signal_pattern,url
page_a,https://example.com/page1
page_b,https://example.com/page2
```

### 任务配置 (`xpath_task.yaml`)

```yaml
task:
  name: "xpath-crawler"
  success_criteria:
    - metric: "win_rate"
      operator: "gte"
      threshold: 0.8
  execution:
    type: "script"
    entry: "python xpath_crawler.py"
```

### 运行

```bash
python sloth_engine/orchestrator.py --task xpath_task.yaml --signals xpath_urls.csv --max-rounds 10
```

---

## 七、模式库操作

```bash
python orchestrator.py --status              # 模式库状态
python orchestrator.py --review --yes        # 批量审批 → 升级排除规则
python orchestrator.py --history             # 历史运行记录
python orchestrator.py --inspect timeline    # 事件时间线
```

## 八、进阶

### 方法级经验规则

```python
from memory_store import PatternStore

store = PatternStore("data/patterns.db")
store.append_failure([{
    "id": "F-method-001",
    "signal_pattern": "method_error",
    "failure_mode": "EXTREME_CHASE",
    "status": "resolved",
    "exclusion_rule": "methodology:single_window",
    "rule_type": "methodology",
    "root_cause": "单窗口结论不可信",
}])

# 检查测试方法合规性
store.check_methodology({"windows": 3})  # → {"passed": False, ...}
```

### 事件溯源审计

```bash
# JSONL 日志位置
cat work_ooda/runs-2026-08-18/events-*.jsonl | head -5

# 用 jq 查看事件流
cat work_ooda/runs-*/events-*.jsonl | jq -r '[.ts, .status, .step, .message] | @tsv'

# 或用 --inspect CLI
python orchestrator.py --inspect timeline
python orchestrator.py --inspect round --round 1
```

## 九、缺陷改进报告（v3.2 新增）

Loop 的 Learn 步骤结束后，自动从模式库分析失败根因，生成 `IMPROVEMENTS.md` 指向原始任务的改进建议。

### 触发条件

- 本轮发现新失败模式（`new_failures > 0`）
- 每 5 轮周期性生成
- 第 1 轮强制生成

### 报告结构（参考 DSH Errors and Fixes）

```markdown
# 缺陷改进报告

### 1. 🔴 文本编码兼容性不足

**严重度**: critical | **状态**: open
**缺陷位置**: `parsers/text.py` 的 read_text_file()
**根因**: 假设输入为 UTF-8，未处理 GBK/GB18030
**改进方案**: 编码链加 gb18030/gbk + errors="replace"
**验证方法**: 用 10 本中文 txt 测试，全部通过即修复
```

### 缺陷分类

| 错误类型 | 映射缺陷 | 严重度 |
|---------|---------|:---:|
| `UnicodeDecodeError` / `gbk` / `encode` | 编码兼容性不足 | critical |
| `mobi` / `format not supported` | 格式支持不完整 | major |
| `ModuleNotFoundError` / `ImportError` | 运行时依赖缺失 | critical |
| `EmptyOutput` / `no output` | 输出格式不符预期 | major |
| `Timeout` | 执行超时 | major |

### 报告位置

```
projects/<name>/IMPROVEMENTS.md
```

人工审核后应用到原始任务，Loop 重新执行验证修复效果——形成完整的"运行→发现→分析→建议→修复→验证"闭环。

---

## 十、结果验证机制（v3.3 新增）

Loop 支持两层门禁验证：`success_criteria` 判执行是否完成，`verification` 判结果是否正确。

### 快速示例

```yaml
task:
  name: "math-check"
  risk_level: "medium"
  verification:
    mode: "swarm"              # single | swarm（并行）
    assertions:
      - type: "range"
        field: "trades.0.pnl"
        min: -2.0
        max: 1.0
      - type: "equals"
        field: "trades.0.pnl"
        expected: 1.0
        tolerance: 0.01
      - type: "exists"
        field: "trades.0.signal_pattern"
      - type: "regex"
        field: "trades.0.failure_reason"
        pattern: "^$"
      - type: "min_size"
        field: "trades.0._meta.output_text"
        threshold: 100
      - type: "callback"
        script: "verify_result.py"
    regression:
      tests:
        - "tests/test_addition.py::test_basic"
```

### 断言类型

| 类型 | 参数 | 说明 |
|------|------|------|
| `equals` | expected, tolerance | 字段值等于预期（浮点可设容差） |
| `range` | min, max | 字段值在范围内 |
| `exists` | field | 字段路径存在且非空 |
| `regex` | pattern | 字段值匹配正则 |
| `min_size` | threshold | 文件大小 >= N 字节 |
| `callback` | script | 调用外部脚本验证 |

### field 路径格式

- `trades.0.pnl` → 第一笔交易的 pnl 字段
- `trades.0.meta.pages` → 第一笔交易的 meta.pages
- `_meta.passed` → 顶层 _meta.passed 字段

### 风险等级

| 等级 | verification 要求 |
|:--:|------|
| `high` | **强制**配置 assertions |
| `medium` | 推荐配置 |
| `low` | 可选 |

---

## 十一、接入检查清单

- [ ] 信号文件含 `signal_pattern`（或 column_map 映射）。注意：`_load_pool` 当前仅支持 JSON 格式
- [ ] 执行脚本符合 `--input / --output` 契约
- [ ] 输出含 `trades` 数组，每项含 `pnl`
- [ ] 定义 `success_criteria`
- [ ] 多任务场景：配置 `task.workspace` 隔离 I/O 文件
- [ ] `--doctor` 通过
- [ ] 首次运行观察 OODA 流程正常