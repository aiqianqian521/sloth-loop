# sloth-loop 超简上手（QUICKSTART · 新主机 5 分钟接入模板）
> 日期：2026-09-02 · 目标：让任何人在「新的主机」按场景把 sloth-loop 跑起来，不看长篇 toc。
> 基线刷新 2026-10-27：当前全量基线 `1760 passed / 0 xfailed / coverage 79.49%`（fail_under=70，单一来源 `docs/baseline.json`）。

## 1. 这是什么
sloth-loop 是「自进化回测/任务编排引擎」：给一批候选信号 + 你定义的『什么是成功』，
它自主跑任务(OODA 7步)、自动沉淀失败/成功模式并可演化出新候选，人审后纳入。

它不绑定某个业务；业务通过 projects/<domain>/<task>/ 的 config + wrapper 接入。

## 2. 最少 4 步跑起来
```
# 1) 拿到仓库 (Python 3.11, git)
git clone <你的仓库> sloth-loop && cd sloth-loop

# 2) 建 venv + 装依赖
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt

# 3) 自检
.venv/Scripts/python sloth_engine/orchestrator.py --doctor

# 4) 跑一次任务
.venv/Scripts/python sloth_engine/orchestrator.py --once     --config sloth_engine/config.yaml --signals sloth_engine/data/signals_seed.json
```
通过标志：doctor 输出无错误；--once 结束后有 report / 状态写入 sloth_engine/data/patterns.db。

## 3. 按「场景」接入模板（创建、不修改引擎）
> 一个场景 = 一个 projects/<domain>/<task>/ 目录，含 config.yaml + wrapper/(data)+ signals。无需改引擎。

| 场景 | 目录示例 | 要做的事 | 成功由谁定义 |
|---|---|---|---|
| 量化回测 | projects/pm/f2-purity/ | wrapper 调你的回测脚本，写 loop_backtest_input/output | 你: success_criteria(trades/win_rate) |
| 文档蒸馏 | projects/book-distill/ | wrapper 解析书籍/文档成结构产物 | 你: 结构门禁 + 语义抽样 |
| 通用任务 | projects/sandbox/（默认 task name） | 任意可脚本化校验的任务 | 你: 产物格式/计数门禁 |

最小模板（可直接 copy）见 docs/PM框架-接入sloth-loop-流程规范.md §3 与 projects/pm/_template/。

## 4. 定义『什么是成功』（核心入口）
在 config 的 task 段写 success_criteria，如：
```yaml
task:
  name: "my-task"
  success_criteria:
    - metric: "trades_count"
      operator: "gt"
      threshold: 0
  scope:
    allow: ["data/", "signals/"]
    deny:  ["production/", ".env"]
```
Loop 每轮按此判定通过/失败，把失败分类进模式库并可持续逼近成功。

## 5. 查询历史任务
```
# 看最近运行
.venv/Scripts/python sloth_engine/orchestrator.py --history
# 看模式库状态
.venv/Scripts/python sloth_engine/orchestrator.py --status
# 看某次运行详情
.venv/Scripts/python sloth_engine/orchestrator.py --inspect runs
.venv/Scripts/python sloth_engine/orchestrator.py --inspect round --round 1
```

## 6. 自主进化（当前【搁置】，仅保留可复用件）
- 第1档信号演化: --evolve 产出候选 -> --rev-candidates --yes 评审纳入
- 第2档自改码门禁: self_modify_gate (patch->沙箱pytest->备份提交)
- 当前因资源约束不实时运行；将来按`<KB_ROOT>/sloth-loop自主进化后续计划-2026-09-02.md`唤醒。

## 7. 自查清单（提交/对外前）
- [ ] --doctor 通过
- [ ] 全量回归: .venv/Scripts/python -m pytest tests sloth_engine/tests -q  (期望 1760 passed / 0 xfailed, coverage 79.49%, fail_under=70)
- [ ] 提交门禁: .venv/Scripts/python scripts/run_gate.py
- [ ] 场景目录 config 的 scope.deny 无敏感路径

## 8. 详细文档入口
| 需要 | 看 |
|---|---|
| 完整介绍与架构 | docs/sloth-loop-项目介绍与规划.md |
| 使用手册 | docs/sloth-loop-USAGE.md |
| 环境搭建 | docs/sloth-loop-DEV-SETUP.md |
| 路线/延后项 | docs/sloth-loop-ROADMAP.md |
| 变更日志 | docs/sloth-loop-CHANGELOG.md |
