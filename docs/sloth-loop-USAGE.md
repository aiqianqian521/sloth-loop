# sloth-loop 使用手册（Usage Guide）

> 面向「把你的真实任务接入 Loop 编排」的操作指南。
> 适用范围：`<repo_root>`（dev 副本）。**不要把 dev 副本直接用于生产 live。**
> 版本对应：见 [sloth-loop-CHANGELOG.md](sloth-loop-CHANGELOG.md)。

## 一、这是什么

`sloth_engine` 是一个 **CLI 驱动的自进化回测编排框架**。它不是 MCP Server，而是通过
`python orchestrator.py <args>` 作为子进程被调用（cron / shell / Claude Code / 手动命令行均可）。

核心循环是 OODA 7 步：

```
U(Understand) → O1(Observe) → O2(Orient) → D(Decide) → A(Act) → V(Verify) → L(Learn)
```

每次回测失败会被自动记录为 failure pattern，下次自动排除；成功被记录、下次复用；
L2 周期分析模式稳定性并给出规则变更建议（但**不自动**改动 status，需人工 `--review` 审批）。

## 二、目录与分层

| 路径 | 作用 |
|---|---|
| `sloth_engine/orchestrator.py` | CLI 组合根 + OODA 编排（已从整块拆为 peer 模块，见架构文档） |
| `sloth_engine/ooda_pipeline.py` | OODASteps：7 步的 step_start/step_end 事件 |
| `sloth_engine/memory_store.py` | SQLite 模式库 CRUD + schema ledger v001–v006 |
| `sloth_engine/event_log.py` | 自包含 JSONL 事件日志（只追加，事实源） |
| `sloth_engine/adapters/backtest_adapter.py` | 回测脚本适配层（与具体任务场景解耦的唯一接缝） |
| `sloth_engine/adapters/task_runner.py` | TaskRunner ABC + BacktestRunner |
| `sloth_engine/runtime_paths.py` | 运行产物隔离 + fail-closed containment |
| `sloth_engine/runtime_exec.py` | ExecGate：去 shell + 解释器白名单 + 资源轴节流 |
| `sloth_engine/circuit_breaker.py` | 熔断：CLOSED/OPEN/HALF_OPEN 半开多探针恢复 |
| `sloth_engine/resume_guard.py` | 断电/崩溃恢复的幂等与兼容校验 |
| \sloth_engine/config.yaml\ | 任务配置（默认 demo 回测）；具体任务场景配置见各自领域知识库 |

## 三、环境准备（一台新主机）

```bash
# 1) 进入仓库根
cd <repo_root>

# 2) 创建虚拟环境（Python 3.11+）
py -3.11 -m venv .venv

# 3) 安装运行依赖（注意：requirements 文件含中文注释，
#    若 pip 报 GBK 解码错，直接按包名安装）
.venv\Scripts\python.exe -m pip install "PyYAML>=6.0"
# 仅测试/门禁用：
.venv\Scripts\python.exe -m pip install "pytest==9.1.1" "pytest-cov==7.1.0" "coverage==7.16.0"

# 4）（可选，接入真实任务时）按主机准备运行产物根；pilot 配置模板与生成器已随任务场景存放（核心 demo 走默认 `config.yaml`，无需此步）

```

> 说明：`data/` 已内置 demo 信号样例（`signals_seed.json`）；接入真实任务时按其场景提供信号与运行时。

## 四、核心命令

以下命令均在 `sloth_engine/` 目录下执行（或用 `--config` 指定配置）。

```bash
# 环境自检（首跑向导，展示关键参数 + 干跑确认）
python orchestrator.py --doctor

# 接入真实任务时用其项目配置跑 doctor / once（demo 用默认 config.yaml 即可）
python orchestrator.py --config config.yaml --doctor
python orchestrator.py --config config.yaml --once

# 单轮完整 OODA（用默认配置）
python orchestrator.py --once

# 快速模式（跳过 OODA 分析步骤，直接 检查→回测→记录）
python orchestrator.py --once --fast

# 连续循环运行（受 max_rounds / max_seconds / no_progress_stop 约束）
python orchestrator.py

# 崩溃/断电后续跑（从最新 checkpoint 恢复）
python orchestrator.py --resume

# 查看模式库状态
python orchestrator.py --status

# 查看运行历史
python orchestrator.py --history

# 查看 JSONL 事件日志
python orchestrator.py --inspect runs            # 列出所有日志
python orchestrator.py --inspect timeline        # 时间线摘要
python orchestrator.py --inspect last-error      # 最近错误
python orchestrator.py --inspect round --round 3 # 第 3 轮详情

# 本地静态 HTML trace 报告
python orchestrator.py --trace

# 审核失败 → 升级排除规则（注意：**不会自动改 status**，需人工审批）
python orchestrator.py --review --yes --scope combo

# 清空模式库（危险，谨慎使用）
python orchestrator.py --reset --yes

# 指定信号文件 / 外部任务 / 多项目 / 覆盖最大轮数
python orchestrator.py --once --signals data/my_signals.json
python orchestrator.py --once --task config/pm_task.yaml
python orchestrator.py --project eth-usdc --once
python orchestrator.py --max-rounds 50
```

## 五、接入真实任务怎么跑

> 本节以「把任意真实任务接入 Loop」的通用流程说明。具体场景（如量化、PM、文档蒸馏等）
> 的任务配置与运行时，见各自领域知识库；sloth-loop 只提供编排框架与契约。

1. 准备该任务的运行脚本与数据，放在仓库内相对路径（`backtest/`、`data/`、`skills/...` 等）。
2. 生成/确认该任务的项目配置（`--config <project>.yaml`），并填好：
   - `task.success_criteria`：该任务的**成功判定**（metrics + operator + threshold，或 assertions）。
   - `backtest.script`：回测/执行脚本的相对路径。
   - 运行产物根 `runtime.root`（仓库外，按主机填）。
3. 跑 doctor 确认合约探针通过（会实际执行一次极小回测）：
   ```
   [OK] Contract probe
   Verdict: Ready — run python orchestrator.py --once
   ```
4. 跑一次完整闭环：
   ```
   python orchestrator.py --config config.<project>.yaml --once
   ```
   预期输出：Act `status=completed items=N`、Verify `1/1 passed`、Learn 记录失败/成功模式，
   事件日志（含 `provenance_ref`：schema `loop.provenance.v1` + runtime/data SHA-256）写入
   `runtime.root/runs/`，模式库写入 `runtime.root/db/patterns.db`。
5. 查看结果：
   ```
   python orchestrator.py --history    # 运行历史
   python orchestrator.py --status     # 模式库/问题队列
   ```

## 六、测试与提交门禁

```bash
# 全量测试（含 sloth_engine/tests，排除仅依赖外部主机的 test_p0_2_rerun）
python -m pytest -p no:cacheprovider --no-cov -q tests/ sloth_engine/tests/ \
  --ignore=tests/test_p0_2_rerun.py

# 提交前本地门禁（green-umbrella：缺依赖 fail-closed + coverage 不低于基线）
python scripts/run_gate.py
```

当前基线：**1760 passed / 0 xfailed / coverage 79.49%**（fail_under=70）。

**跨仓账本扫描（取证工具，不进门禁）**：`python scripts/audit_cross_repo_ledger.py` 把「文档里的提交哈希必须可解析」这套守卫指向**兄弟语料**（legacy `sloth-loop`、architect-skills），逐条打印分类（数据指纹 / 运行时对象 id / amend 中转与外部仓基线 / 守卫自身示例），只有**无法解释的幽灵**才 exit 1。本仓账本仍由 pytest 内的守卫 fail-closed 判定（**无分类豁免**）；`--json` 输出机读结果，`--repo NAME=PATH` 可加扫其他语料（repeatable）。

## 七、常见问题

- **`.venv` 报 "No Python at ..."**：venv 指向的 Python 已不存在，重建即可（第三节第 2 步）。
- **`ContainmentError`**：配置里的 `backtest.script`/`cwd`/`signals` 路径越出仓库或 runtime 根，
  改为仓库内相对路径。
- **中文文件名提交时 gate 崩溃（stdout=None）**：已修复为 UTF-8 解码；若仍遇到，确认
  `scripts/run_gate.py` 里 subprocess 均带 `encoding="utf-8"`。
- **真实回测产不出交易（trades=0）**：多为候选信号与回测窗口不匹配；检查信号 `signal_pattern`、
  \market_condition\ 是否与回测执行脚本（\acktest/mock_backtest.py\ 或该任务真实脚本）的判定逻辑一致，或提高 \--max-bars\。
