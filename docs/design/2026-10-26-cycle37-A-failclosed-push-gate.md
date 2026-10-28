# cycle-37 A · 能被被约束方关掉的控制不是控制：服务端 fail-closed 推送门禁

- 日期：2026-10-26
- 来源：ROADMAP P0「fail-closed CI」触发条件达成（多人/多机协作提交、准备发布）——把镜头从代码内的门禁抬到仓库边界的门禁
- 提交：cycle-37 A `310c918`（+28 用例）／ B（architect-skills）`aca352b` TES-32 + DOC-23

## 1. 取证方式（先驱动，再结论）

1. 静态：ROADMAP P0 要求「把本地 `run_gate.py` 从可绕过升级为不可绕过的 CI」；实际唯一的执行点是 **pre-commit 钩子**。
2. 探针（三种绕过，都来自被约束方）：`git commit --no-verify` / `git -c core.hooksPath=<别处>` / 全新克隆（无钩子）——任一种都让门禁不运行。
3. 实现服务端半边时暴露的两层同族问题（都由集成测试捕获）：
   - 本机 **全局 `core.hooksPath`** 会把仓库自带 `hooks/pre-receive` **静默替换**——第一次端到端跑，装了钩子却照样推送成功；
   - 钩子 `.` 了配置文件，但变量**只 set 不 export** → 门禁子进程收不到配置，退回默认路径并报「找不到 `<树>/scripts/run_gate.py`」。

| 事实 | 修复前 | 修复后 |
|---|---|---|
| 强制点 | 客户端 pre-commit（可被 `--no-verify` / `hooksPath` / 全新克隆关掉） | 服务端 pre-receive（推送方无开关） |
| 钩子选择 | 受全局 `core.hooksPath` 影响（可能根本不在路径上） | 安装即**钉住**该仓 `core.hooksPath` |
| 配置传递 | 只 set，不 export（子进程收不到） | 配置 `export`，且钩子 `set -a` 兜底 |
| 门禁本体 | 取自工作树（推送方可改写） | **固定副本**（`hooks/loop-push-gate/`），改写被推树无效 |
| 判定内容 | 只跑本地测试 | 内容扫描（密钥 / 家目录路径）+ 在**推来的树**上跑本地门禁 |

## 2. 病根：控制的「开关」在被约束者手里

- 契约是「提交必须绿色」，但执行它的钩子属于**提交方**的运行环境——开关（`--no-verify` / `hooksPath` / 是否安装）全在被约束方手里。
- 「装了钩子」也不等于「会执行」：选择钩子的路径可被上层配置替换；配置即使被读到也可能没传给子进程。**设置 ≠ 生效**。
- 这是 cycle-32~36 的同族延伸：那几轮问「判定对不对（宽/窄）」「缺省往哪走」，本轮问「**谁有权关掉它、它到底跑没跑**」。

## 3. 修复

- **内容扫描**（`scripts/content_scan.py`）：纯函数规则 = 密钥文件名 / 私钥头 / AWS AK id / 高熵硬编码凭据 / 代码与配置中的开发者家目录路径；省略项（泛化绝对路径、长 token 熵）是被**全仓 371 文件实测 0 误报**钉住的决定。
- **服务端 gate**（`scripts/push_gate.py`）：对每个新 tip 用 `git archive` + `tarfile` 落树（纯 Python，无外部 tar；越界 / 链接成员拒绝），先内容扫描，再在推来的树上执行本地门禁（默认 `scripts/run_gate.py --all`）；超时 / 无法启动一律 fail-closed。
- **安装器**（`scripts/install_push_gate.py` + `scripts/pre-receive`）：写入**固定副本**、**钉住 `core.hooksPath`**、`export` 配置、备份已有钩子；`--uninstall` 还原。
- **自证**（`tests/test_push_gate.py`，28 例）：规则正反例 / 对全仓语料 0 误报 / 真实 `git push` 通过与被拒（密钥、red tests-half、**推送内改写 `push_gate.py`**、缺 bundle）/ 安装备份与卸载还原。

## 4. 信任边界（写在代码与文档里，不靠读者推断）

- 钩子、固定副本与配置都在**接收主机**上；推送方不能关闭它们。
- 唯一能削弱检查的是宿主配置 `LOOP_PUSH_GATE_CMD`（tests 半的命令，默认 `scripts/run_gate.py --all`）——它是**接收主机的管理员权限**，不是推送方的开关。
- hosted CI 未接入（无托管远程）：本项交付 **pre-receive** 形态；接入 hosted CI 用同一 artifact 包一层即可。

## 5. B 轮口径（architect-skills）

TES-32 / DOC-23：**能被被约束对象关掉的控制不是控制**——强制点必须在被约束方无权的位置执行；安装时必须固定**选择该控制的开关**（全局 `core.hooksPath` 会静默替换仓库自带钩子）；配置必须真正到达执行点（只设不导出 == 没生效）；控制本体不得取自被约束内容；「已安装」不等于「已生效」，必须有端到端自证（真实动作触发：通过 / 拒绝 / 关闭或改写仍被拒 / 缺失 fail-closed）。文档侧：宣称「已强制 / 已接入」必须写明执行点与信任边界、生效前提与验证方式，未覆盖范围逐条列出。

## 6. 验收

- `pytest tests sloth_engine/tests -q` → 1750 passed / 0 xfailed / **79.42%**（+28 例；新增代码在 `scripts/`，不在覆盖率口径内）
- `scripts/run_gate.py --all` → PASS；`docs_baseline.check() == []`；`scripts/audit_cross_repo_ledger.py` → unexplained 0 / exit 0
- B 侧：`node scripts/validate-contracts.mjs` → 19 atom / 0 错 / 0 警；`node tests/run-l1-tests.mjs` → 32 passed

## 7. 冻结项（不动）

migration sentinel RPO（下一步）；N-3 / R3；coze I-1/I-3/I-4、cycle-12 条目 11/12/13；WebUI / 每项目文件沙箱 / P2 OS 沙箱；`guardian/risk_assessor.py::llm_review()`。
