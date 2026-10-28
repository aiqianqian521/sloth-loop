# RELEASE.md — sloth-loop 发布与打包规范

> 面向维护者：如何从本仓库产出一份**干净、可发布、可交付**的版本。
> 关键原则：**发布版 = 压力测试版 = 交付版，同一个 `git archive` 产物**，不做区分。
> 最后更新：2026-10-14

---

## 0. 一句话流程

```bash
# 1) 工作树 = 希望在包里看到的内容（挂载产物/私有文档由 .gitignore 挡在版本库外）
# 2) 提交
git add -A && git commit -m "release: <版本>"
# 3) 出包（只含 git 跟踪的干净文件）
git archive --format=zip --prefix="sloth-loop-<版本>/" -o sloth-loop_<版本>_release_YYYYMMDD.zip HEAD
# 4) 自检（见 §4）
```

**为什么用 `git archive`**：它只打包 **git 索引里跟踪的文件**，从机制上保证：
- 运行产物（`projects/*/runs/`、`_data/`、`logs/`）不会进包；
- 私有文档（`docs/state/`、`docs/PM框架-*.md`）不会进包；
- 不会再出现「工作目录逐条排除式 zip」导致的**该留未留 / 该排未排**（历史上曾因此漏掉整套 `tests/`）。

---

## 1. 必须随包发布的目录（缺一不可）

| 目录 | 作用 | 交付验证 |
|---|---|---|
| `sloth_engine/` | 引擎主体（OODA/插件/守护者/WebUI/迁移） | `python sloth_engine/orchestrator.py --doctor` → `Verdict: Ready` |
| `sloth_engine/tests/` | 插件系统测试 | `pytest sloth_engine/tests/` |
| `sloth_engine/_archive/` | 归档 legacy 模块，**测试依赖**：`structured_cli.py`、`mcp_client.py`；另有非依赖遗留 `loop_pipeline.py`（cycle-11 归档，被 `backpressure.py`/`circuit_breaker.py`/`run_state.py` 取代） | 被 `tests/test_final_5.py`、`tests/test_runtime_containment.py` 引用 |
| `tests/` | 顶层测试套件（89 个 `test_*.py`） | `pytest tests/` |
| `backtest/` | 契约探针 + 任务适配（`mock_backtest.py` 等） | `--doctor` 依赖它 |
| `scripts/` | 门禁/迁移/路径脚本（`run_gate.py` 等） | `python scripts/run_gate.py` |
| `config/` | 演化/模式 schema 样例 | 存在即可 |
| `agent-prompts/` | Agent 提示词模板 | 存在即可 |
| `docs/` | 使用/设计/ADR 文档 | 存在即可 |
| 根入口 | `README.md` `CLAUDE.md` `RUNBOOK.md` `ONBOARDING.md` `pyproject.toml` `requirements-dev.txt` `.gitignore` | 存在即可 |

---

## 2. 必须排除的内容（由 `.gitignore` 保证，不随版本库）

| 排除项 | 原因 |
|---|---|
| `projects/*`（保留 `projects/pm/_template/`） | 任务运行工作区（`runs/`、`data/` 全是产物） |
| `docs/state/` | sloth-loop 内部开发上下文（WAKEUP/NEXT/IMPROVEMENTS） |
| `docs/PM框架-接入sloth-loop-流程规范.md` | 私有接入规范 |
| `docs/knowledge-distillation/` | 第三方框架蒸馏私有笔记 |
| `docs/sloth-loop-GitHub发布-Runbook-*.md` | 含敏感样例的内部清理 runbook |
| `uv.lock` | 本仓不提供真实锁（空壳已被移除；依赖见 `pyproject.toml` / `requirements-dev.txt`） |
| `*.bak` / `*.bak-*` / `scripts/_archive_sloth_*.py` | 一次性脚本/备份残留 |
| `_scratch_archive_*/`、`.venv/`、`__pycache__/`、`logs/`、`_data/`、`rt/`、`work_ooda/` | 环境/运行产物 |

> 新增排除项时，**改 `.gitignore`**，而不是在打包脚本里写排除逻辑 —— 单一真相源。

---

## 3. 敏感信息红线（发布前必须清零）

发布前对**全部 git 跟踪文件**扫描，以下必须为 0 处真实值（占位符/断言除外）：

| 类别 | 处理 |
|---|---|
| 私人绝对路径（机器本地盘符 + 私有根：工作区 / 知识库 / 技能仓 / 暂存目录） | 替换为占位符，见下 §3.1（**当前仓库已清零**） |
| 公网 IP / 服务器地址 | 替换为 `<SERVER_IP>` |
| 真实 API key（形如 `sk-sp-<16hex>`） | 替换为 `<YOUR_API_KEY>` |
| 钉钉/IM webhook（`oapi.dingtalk...`） | 替换为 `<WEBHOOK_URL>` |
| 个人用户名/家目录 | 替换为 `<USER_HOME>` / `~` |

> 例外：**守卫断言**属正常，保留——例如 `tests/test_plugin_selfcontained.py` 检测「盘符绝对路径」的断言。
> 它匹配的是**形态** `[A-Za-z]:[\\/]`，本身不含任何真实路径；`tests/test_wake_pointer_chain.py` 的兄弟仓路径与
> `scripts/audit_cross_repo_ledger.py` 的 `DEFAULT_TARGETS` 同理：**派生自本仓位置**，可用环境变量覆盖。

### 3.1 路径占位符约定（发布物零本机路径）

| 占位符 | 含义 |
|---|---|
| `<SLOTH_ROOT>` / `<SLOTH_LOOP>` | 本项目（sloth-loop）仓库根 |
| `<WORKSPACE_ROOT>` | 开发机工作区根（历史上放置 `loop-dev` / `loop-dev-next` / `other_project` / `loop-test-output`） |
| `<SKILL_ROOT>` | 本地技能/评估器仓根（如 architect-skills） |
| `<KB_ROOT>` | 本地知识库根（如 `AGENT_EXECUTION_TEMPLATE.md` 模板） |
| `<TMP_ROOT>` | 临时 / 暂存根 |
| `<DATA_ROOT>` / `<RUNTIME_ROOT>` | 业务运行数据 / 运行态根 |

> 历史档案（`docs/flow/*`、`docs/design/2026-*`）同样只保留「**当时是什么**」的叙事，已按本表占位符化，
> 不再指向任何真实机器目录。名字与沿革的完整叙述见 `docs/HISTORY.md`。

---

## 4. 发布自检（缺一不合格）

解包到临时目录后执行：

```bash
# a) 关键目录齐全
ls tests/ sloth_engine/tests/ backtest/ scripts/ config/ agent-prompts/ docs/

# b) 测试全绿且覆盖率达标（门禁 fail_under=70%）
python -m pytest -q tests/ sloth_engine/tests/

# c) 引擎环境自检
python sloth_engine/orchestrator.py --doctor     # 期望：Verdict: Ready，退出码 0

# d) 隐私扫描（应为 0 处真实泄露）
#    可复用仓库内脚本或自行 grep：[A-Za-z]:[\\/]|runtime2026|runtime01201|sk-sp-|oapi.dingtalk|<公网IP>
```

---

## 5. 已知坑（历史踩过，勿重犯）

| 坑 | 教训 |
|---|---|
| 用「工作目录逐条排除式 zip」 | 排除规则易反向，曾漏掉整套 `tests/` → **一律用 `git archive`** |
| 把 `sloth_engine/_archive/` 当垃圾排掉 | 它是测试依赖（`structured_cli`/`mcp_client`），**必须留 .py** |
| 测试硬编码绝对日期 | 曾用 `2026-10-10` 做 `at` 计划 → 日期一过就失败；**改用运行时相对未来日期** |
| `uv.lock` 空壳（52 字节） | `uv sync --frozen` 形同虚设 → 要么真锁要么不放 |
| `*.py` 带 UTF-8 BOM | 部分工具 `ast.parse` 会失败 → 发布前跑 `sloth_engine/_strip_bom.py` |
| 文档测试基线多口径 | 全仓只保留**一个**基线数字，其余引用它 |

---

## 6. 发布检查清单（Checklist）

- [ ] 工作树已 `git add -A` 且提交（中性作者 `sloth-loop-framework`）
- [ ] `.gitignore` 覆盖 §2 全部排除项
- [ ] §3 敏感扫描 0 处真实泄露
- [ ] `git archive HEAD` 出包，包内无 §2 排除项
- [ ] §4 自检 a~d 全过
- [ ] 备份原 `.gitignore` / 关键文档到 `_sloth-loop_backup_YYYYMMDD/`

---

*本文件只描述"如何打包发布"，不含任何敏感值；敏感扫描规则实现见仓库根 `scripts/`（若存在）或按 §3 表手工 grep。*
