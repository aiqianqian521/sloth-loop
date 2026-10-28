# sloth-loop 开发与环境设置（Dev Setup）

> 从零搭建 sloth-loop 开发环境、跑测试、过提交门禁的操作手册。
> 适合新主机 / 新协作者。

## 一、前置条件

- Python 3.11+（本机可用 `py -3.11`）
- Git
- 真实任务运行时（仅接入具体任务时需要）：由 `backtest/runtime_resolver.py` 候选表按主机解析；
  sloth-loop 核心（OODA/回测 mock/模式库/迁移）**不需要**外部运行时即可跑通全套测试与 demo。
- 具体任务的真实数据/市场数据：属于各任务场景本身，随具体任务接入时提供（如有，见对应领域知识库）。

## 二、一次性初始化

```bash
cd <repo_root>

# 1. 虚拟环境（如果用 py 启动器）
py -3.11 -m venv .venv

# 2. 运行依赖（PyYAML 即可；若走 requirements 文件因中文注释触发 GBK 解码错，按包名装）
.venv\Scripts\python.exe -m pip install "PyYAML>=6.0"

# 3. 测试/门禁依赖（可选，做提交门禁才需要）
.venv\Scripts\python.exe -m pip install "pytest==9.1.1" "pytest-cov==7.1.0" "coverage==7.16.0"
.venv\Scripts\python.exe -m pip install "pandas>=2.0"   # 部分 P0 spotcheck 用

# 4.（可选）生成本机 pilot 配置：模板与生成器已随任务场景存放（如 lh 场景见 lh 知识库 loop-接入场景/pilot-lh-template）。核心跑 demo 无需此步。

```

> `requirements.txt` / `requirements-dev.txt` 内含中文注释；Windows 下 `pip install -r` 可能报
> `UnicodeDecodeError: 'gbk' codec`。规避：直接按包名逐一安装（如上）。

## 三、跑测试

```bash
# 全量核心测试（推荐）
.venv\Scripts\python.exe -m pytest -p no:cacheprovider --no-cov -q tests/ sloth_engine/tests/ \
  --ignore=tests/test_p0_2_rerun.py

# 只看某个测试
.venv\Scripts\python.exe -m pytest -q tests/test_loop.py

# 带覆盖率（pyproject 已配 fail_under=70）
.venv\Scripts\python.exe -m pytest -q tests/ sloth_engine/tests/ --ignore=tests/test_p0_2_rerun.py
```

当前基线：**1760 passed / 0 xfailed / coverage 79.49%**（fail_under=70，单一来源 docs/baseline.json）。

## 四、提交门禁（green-umbrella）

```bash
# 直接运行门禁（等价于 pre-commit 里的 Gate）
.venv\Scripts\python.exe scripts/run_gate.py
```

行为：
- 只对改动触碰到 `sloth_engine/`、`tests/`、`scripts/`、`pyproject.toml`、`requirements-dev.txt`
  的提交触发；纯 docs 提交自动 SKIP。
- 缺 pytest/pytest_cov/coverage 时 **fail-closed**（拒绝并提示 bootstrap）。
- coverage 不得低于 pyproject 的 `fail_under`，且相对 HEAD 只升不降（ratchet）。

> 说明：仓库 `.git/hooks/pre-commit` 为机器本地配置，全局 `core.hooksPath` 是
> `<USER_HOME>/.aliyunAKScanHook/hooks`（AK 扫描）。本地 gate 可用 `--no-verify` 绕过，
> 它**不是** fail-closed CI（远程发布仍需另接 CI）。

## 五、提交注意（中文文件名）

- `run_gate.py` 已修复：subprocess 读 git 输出强制 `encoding="utf-8"`，否则中文文件名的
  `git diff --cached --name-only` 会因 GBK 解码失败返回 `stdout=None` 并崩溃。
- 提交信息含中文/特殊字符时建议用 `-F <文件>` 提交，避免 shell 转义问题。

## 六、常见环境问题排查

| 现象 | 原因 | 处理 |
|---|---|---|
| `.venv\Scripts\python` 报 No Python at ... | venv 指向的 Python 已不存在 | 重建 venv（第二节第 1 步） |
| `pip install -r` 报 GBK 编码错 | requirements 含中文注释 | 按包名安装 |
| pytest 收集 3 errors（ImportError） | 主机专属测试找不到外部依赖 | 装 pandas；`test_p0_2_rerun` 用 `--ignore` 或已带 skip 保护 |
| doctor/once 报 ContainmentError | 配置路径越出仓库或 runtime 根 | 用仓库内相对路径（见 USAGE §七） |
| pilot once 产不出交易 | 信号与窗口不匹配 | 检查 `signal_pattern`/`market_condition`/`--max-bars` |
