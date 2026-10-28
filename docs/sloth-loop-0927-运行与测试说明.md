# sloth-loop-0927 · 框架副本运行与测试说明

> 版本：2026-09-27 · 本目录为 sloth-loop 框架「纯代码副本」，**不含任何挂载任务**。
> 副本来源：`<repo_root>`（复制框架主体，排除 `projects/` 挂载任务、`work_ooda/`、`logs/`、`_archive/`、`.venv` 等运行时/环境目录）。

## 一、本目录定位

- **保留**：sloth_engine（核心引擎 + 全量插件体系）、backtest、config、agent-prompts、scripts、tests、docs、根级文档。
- **不含**：任何 pm-*/book-distill/error-loop 等挂载任务；不含 `.venv` 虚拟环境（刻意隔离）。
- **运行时目录**（`_data`/`logs`/`work_ooda`/`projects` 等由 loop 运行自动创建，gitignored）。

## 二、如何用它跑 / 测（借助源 sloth-loop 的 venv）

本目录未配 venv，但可用源 sloth-loop 的 Python 虚拟环境直接指向本目录代码：

```powershell
$vpy = "<repo_root>\.venv\Scripts\python.exe"
$t   = "<repo_root>"
Push-Location $t          # 必须在目标目录 cwd 下运行（config 相对路径）

# 1) 环境自检
& $vpy "$t\sloth_engine\orchestrator.py" --doctor

# 2) 跑一轮完整 OODA 闭环
& $vpy "$t\sloth_engine\orchestrator.py" --once

# 3) 完整回归测试（780 用例，约 9~10 分钟）
& $vpy -m pytest tests -q --no-cov

# 4) 提交门禁
& $vpy scripts\run_gate.py
Pop-Location
```

## 三、独立自包含部署（可选）

如需本目录完全独立运行，新建 venv：

```powershell
cd <repo_root>
py -3.11 -m venv .venv
.venv\Scripts\pip install "PyYAML>=6.0"   # 核心仅需标准库 + PyYAML
.venv\Scripts\pip install fastapi uvicorn  # 仅 WebUI 需要
```

## 四、本次验证记录（2026-09-27，经由源 venv）

| 验证项 | 结果 |
|--------|------|
| `mock_backtest.py` 独立运行 | ✅ 通过（exit 0，正常输出 JSON） |
| `orchestrator.py --doctor` 环境自检 | ✅ Verdict: Ready，契约探针 1 trades |
| `orchestrator.py --once` OODA 7 步闭环 | ✅ Verify 1/1 passed，产出 STATE + run 快照 + 客户报告 |
| `pytest tests --no-cov` 完整回归 | ✅ **779 passed / 1 skipped / 1 xfailed，exit 0**（562s） |
| 测试全量收集 | ✅ 780 tests collected（补充归档模块后无 collection error） |
| 关键入口文件完整性 | ✅ 13 项全存在 |

## 五、发现并修复的缺口

完整回归首次运行时，`tests/test_runtime_containment.py` 收集失败：
`ModuleNotFoundError: No module named 'structured_cli'`。

- **原因**：该测试显式将 `sloth_engine/_archive` 加入 sys.path，依赖其中归档的遗留模块 `structured_cli.py`（以及 `mcp_client.py`）；而框架复制时排除了 `_archive` 目录。
- **处置**：将源 `sloth_engine/_archive\structured_cli.py`、`mcp_client.py` 补回本目录同路径，恢复测试可收集，完整回归通过。
- **经验**：复制框架时应保留 `sloth_engine/_archive` 中**被测试引用的归档模块**（虽为遗留代码，但测试契约依赖它）。

## 六、目录纪律提醒

遵循源 `CLAUDE.md §9`：临时脚本**唯一合法落点 = `scripts/tmp/`**（gitignored，用完即删）；根目录为 allowlist 制，禁止散落 `.bak`、散落日志、临时 `.py`。

---
本说明由既定模式（完整回归 → 发现缺口 → 修复 → 复测）生成并落盘。
