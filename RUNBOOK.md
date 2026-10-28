# RUNBOOK — 量化接入场景：跑通 loop 编排闭环

> v4.0-dev | 更新：2026-09-03
> 目标：在一台**只装了 Python 3.11+ 的干净机器**上，把「量化交易 → loop 编排」从 0 跑出第一个完整闭环
> （信号 → OODA → 回测 → 判定 → 经验沉淀 → 下轮排除）。
> 引擎：**`<repo_root>`**（v4.0-dev，1760 passed / 0 xfailed / coverage 79.49%，fail_under=70）。旧 `<repo_root>\legacy-loop` 仅作入口。
> 路径约定：本文 `<repo>` 指 sloth-loop 仓库根；`<scene>` 指本知识库目录（loop-接入场景）。

---

## 0. 你手里有什么

```
sloth-loop/
├── sloth_engine/                 ← 编排引擎（CLI 拆分后）
│   ├── orchestrator.py          # 组合根（~680 行）
│   ├── cli_router.py            # 命令分发
│   ├── run_loop.py              # 连续循环
│   ├── run_once_pipeline.py     # 单轮 execute→Verify→Learn
│   ├── ooda_pipeline.py         # OODA 7 步
│   ├── event_log.py             # JSONL 事实源
│   ├── memory_store.py          # SQLite 模式库 v001–v006
│   ├── verifier.py              # 对照 success_criteria 判定
│   ├── signal_schema.py         # 信号 schema 强校验
│   ├── runtime_paths.py         # containment
│   ├── runtime_exec.py          # ExecGate（去 shell+白名单）
│   ├── resume_guard.py          # 幂等恢复
│   ├── circuit_breaker.py       # 熔断半开多探针
│   ├── report_util.py           # --report 完结报告
│   ├── adapters/backtest_adapter.py   # 唯一耦合点
│   ├── adapters/task_runner.py        # TaskRunner ABC
│   ├── config.yaml              # 默认配置
│   └── data/                    # 模式库/种子信号
├── backtest/
│   ├── mock_backtest.py         # demo 回测（跑通流程用）
│   └── runtime_resolver.py      # 运行时/数据解析+溯源
├── scripts/
│   └── run_gate.py              # 提交门禁（coverage≥70）
├── projects/                    # 场景接入根
│   └── pm/ _template / book-distill / loop-round
└── tests/  + sloth_engine/tests/ # 1760 passed / 0 xfailed / cov 79.49% (fail_under=70)
```

**lh 场景资产在本知识库**（`<scene>/`）：
- `backtest-bridge/lh_bridge.py` —— lh 真实回测桥接（I/O 契约，portable 运行时解析）
- `pilot-lh-template/` —— pilot 配置模板 + 生成器 + 信号种子
- `architecture-plans/` —— loop 架构计划
- `mcp-server/` —— MCP 服务端（可选）
- 权威规范：`docs/PM框架-接入sloth-loop-流程规范.md`

---

## 1. 前置条件

- Python **3.11+**（`py -3.11` 或任意系统 Python）。
- sloth-loop 已建 `.venv` 并安装依赖（见 `docs/sloth-loop-DEV-SETUP.md`；requirements 含中文注释时按包名装）。
- 跑 demo 无需真实 lh 运行时；跑 lh 真实回测时才需按主机准备 `runtime-root`。

---

## 2. 环境自检（doctor）

```bash
cd <repo_root>
.venv\Scripts\python.exe sloth_engine/orchestrator.py --doctor
```

预期：无错误输出；契约探针能跑出交易（demo 用 `backtest/mock_backtest.py`）。
若报 `ContainmentError` → 配置路径越出仓库/runtime 根，改成仓库内相对路径。

---

## 3. 跑一轮（--once）

```bash
# demo（默认配置）
.venv\Scripts\python.exe sloth_engine/orchestrator.py --once

# 指定项目配置（推荐，接入真实任务时）
.venv\Scripts\python.exe sloth_engine/orchestrator.py --config config.yaml --once
```

预期：Act `status=completed items=N`、Verify `1/1 passed`、Learn 写失败/成功模式；
事件日志（含 provenance `loop.provenance.v1`）写入 `runtime.root/runs/`，模式库写 `runtime.root/db/patterns.db`。

---

## 4. 看攒下了什么（--status / --history / --inspect）

```bash
.venv\Scripts\python.exe sloth_engine/orchestrator.py --status
.venv\Scripts\python.exe sloth_engine/orchestrator.py --history
.venv\Scripts\python.exe sloth_engine/orchestrator.py --inspect timeline
.venv\Scripts\python.exe sloth_engine/orchestrator.py --inspect round --round 1
.venv\Scripts\python.exe sloth_engine/orchestrator.py --trace        # 本地 HTML trace
```

---

## 5. 人工审核失败 → 升级排除规则（--review）

Agent 只负责"发现并建议"，排除规则升级由你拍板（防过拟合/防误杀）。

```bash
.venv\Scripts\python.exe sloth_engine/orchestrator.py --review --yes --scope combo
```

- `--scope combo`（默认）：`信号 @ 市场` 组合级规则，只在该市场封杀。
- `--scope pattern`：全局封杀（更激进）。

---

## 6. 连续循环 / 断电续跑

```bash
.venv\Scripts\python.exe sloth_engine/orchestrator.py          # 连续循环
.venv\Scripts\python.exe sloth_engine/orchestrator.py --resume  # 从 checkpoint 恢复
```

自动停止条件：`max_rounds` 上限 / 连续 `no_progress_stop` 轮无新发现 / 连续执行错误熔断 / L2 健康分达标。

---

## 7. lh 真实回测接入（用本场景的 bridge）

1. 用 pilot 模板生成本机隔离配置（消除旧机路径残留导致的 ContainmentError）：
   ```bash
   cd <repo>
   .venv\Scripts\python.exe scripts/make_pilot_config.py \
     --task lh --runtime-root "<RUNTIME_ROOT>/pilot-lh"
   ```
2. 把 `backtest-bridge/lh_bridge.py` 作为该任务的 wrapper：`--input` 读 loop 信号 → 调 lh 运行时跑因果回测 → `--output` 写契约 JSON。
3. 配置 `task.success_criteria`（≥3 条，operator 限 `gt/gte/lt/lte/eq/ne`，threshold 数值）：
   ```yaml
   task:
     name: "pm-<task>"
     success_criteria:
       - metric: "trades_count" ; operator: "gt"   ; threshold: 0
       - metric: "win_rate"     ; operator: "gte"  ; threshold: 0.35
   ```
4. 先 `--doctor` 过契约探针，再 `--once` 跑闭环；完了 `--report` 输出客户可读 md。

> 详细逐任务流程、信号部署、模式库注入：见 `docs/PM框架-接入sloth-loop-流程规范.md`。

---

## 8. I/O 契约（bridge 必须满足）

- **入参** `--input <in.json>`：`{"signals":[...], "params":{...}, "success_starting_points":[...]}`
- **出参** `--output <out.json>`：`{"trades":[...], "pnl":{"total":..}, "win_rate":"..", "sharpe":..}`
- **退出码**：0=成功；非0=失败（stderr 记入失败库）。
- 空 trades/坏 JSON/非零退出码 → `backtest_adapter` 判为 error 并触发熔断。

---

## 9. 回归测试与提交门禁（改完代码先跑）

```bash
cd <repo_root>
# 全量核心测试
.venv\Scripts\python.exe -m pytest -p no:cacheprovider --no-cov -q tests/ sloth_engine/tests/ \
  --ignore=tests/test_p0_2_rerun.py
# 期望 1760 passed / 0 xfailed / coverage 79.49% (fail_under=70)

# 提交门禁（coverage≥70，只升不降；缺依赖 fail-closed）
.venv\Scripts\python.exe scripts/run_gate.py
```

> 主机专属脚本 `test_p0_2_rerun.py`（本仓默认不存在；上面的 `--ignore=` 是防御性空操作）依赖外部 verdict-engine wrapper 与详细 CSV；
> 缺数据时 `pytest.importorskip` + `isfile` 保护会**干净 skip**，不影响主套件。

---

## 10. 常见问题

| 现象 | 原因 / 处理 |
|---|---|
| `.venv` 报 No Python at ... | venv 指向的 Python 已不存在；重建 `.venv` |
| `pip install -r` 报 GBK 编码错 | requirements 含中文注释；按包名安装 |
| doctor/once 报 ContainmentError | 配置路径越出仓库或 runtime 根；改用仓库内相对路径 |
| 真实回测产不出交易（trades=0） | 信号 `signal_pattern`/`market_condition` 与 bridge 判定逻辑不匹配；提高 `--max-bars` |
| 中文文件名提交 gate 崩溃 | 已修复为 UTF-8；确认 run_gate subprocess 带 `encoding="utf-8"` |
| 连续报错后循环停了 | 正常熔断保护；先 `--doctor` 修环境再跑 |

---

## 11. 权威文档（意外情况先读）

- 完整介绍/架构：`<repo_root>\docs\sloth-loop-项目介绍与规划.md`
- 上手：`<repo_root>\docs\sloth-loop-QUICKSTART.md`
- 使用手册：`<repo_root>\docs\sloth-loop-USAGE.md`
- 环境/门禁：`<repo_root>\docs\sloth-loop-DEV-SETUP.md`
- 变更：`<repo_root>\docs\sloth-loop-CHANGELOG.md`
- 路线：`<repo_root>\docs\sloth-loop-ROADMAP.md`
- PM 接入：`docs/PM框架-接入sloth-loop-流程规范.md`
