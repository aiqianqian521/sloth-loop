# ONBOARDING — 把其他工作接入 sloth-loop（Agent 读取即用版）

> 本文档是**唯一入口**：在任意其他目录运行 agent 时，让它先读本文件，它就知道怎么把某项工作接入 `sloth-loop` 自进化引擎。自包含，不依赖其他文档。
> 目标仓库：`<repo_root>`（工作目录 = 该仓库根）。

---

## 一、核心认知（先读，别跳）

- **Loop 是编排器，不是计算器**。它调用你写的 `wrapper.py` 跑你的算法，把你跑出的结果当作交易/任务结果做失败/成功学习。你（agent）负责写 wrapper，Loop 负责循环与积累经验。
- **任务 = 一个可独立跑、可判定成败的最小单位** = 一条 `config.yaml` + 一份信号 + 一个 `wrapper.py`。
- **接入 = 建一个 `projects/<domain>/<task>/` 目录**，含以上三件套。Loop 反复跑它。
- **落盘契约（§9.4/§9.5/§9.6 强制）**：报告落 `projects/<domain>/<task>/reports/<日期>/REPORT.md`；运行产物只写 `runtime.root`（仓库外）；临时脚本只放 `scripts/tmp/`（用完即删）。

---

## 二、前置校验（每台新主机必做一次）

```powershell
cd <repo_root>
.\venv\Scripts\python.exe -m pytest -p no:cacheprovider --no-cov -q tests\ sloth_engine\tests\ --ignore=tests\test_p0_2_rerun.py
```
期望输出：`1760 passed, 0 xfailed`（无 skipped；fail_under=70，coverage 79.49%）。**不通过先修环境，不要开始接入。**

---

## 三、选择接入域（domain 分组）

| 域 | 用途 | 路径 |
|---|---|---|
| `pm` | 量化 PM 任务（回测/过滤/裁决/止盈止损场景） | `projects/pm/<task>-<YYYYMMDD>-000000/`（task 子任务带时间戳，见 §9.7） |
| `arch` | 架构/评审类任务 | `projects/arch/<task>-<YYYYMMDD>-000000/` |
| `distill` | 文档/知识蒸馏任务 | `projects/distill/<task>-<YYYYMMDD>-000000/` |
| `loop` | loop 引擎自身基准/用例 | `projects/loop/<task>-<YYYYMMDD>-000000/` |
| 其他 | 各类通用工作 | `projects/<新域名>/<task>-<YYYYMMDD>-000000/` |

> 铁律：任何非 pm/arch/distill/loop 的工作请新建**语义化上层目录名**（如 `projects/news/`、`projects/ops/`、`projects/tools/`），**禁散落 `projects/` 顶层**。

---

## 四、生成任务骨架（三件套）

### 方式（推荐）：手动建立三件套
在 `sloth_engine/` 下为任务建目录（如 `work_ooda/<task>/`），放三件套：
- `config.yaml`：见 §5.1，`runtime.root` 填仓库外运行根 `<RUNTIME_ROOT>/<task>`，`backtest.script` 指向同目录 `wrapper.py`；
- `wrapper.py`：读 `--input`（signals）跑算法，产出 success_criteria 需要的 metric（见 §5.2）；
- `signals.json`：种子/候选信号（见 §5.3）。
手动把 `<task>`、`<RUNTIME_ROOT>` 占位符换成真实值即可。

---

## 五、改三件套（写你的真实逻辑）

### 5.1 config.yaml
| 字段 | 要求 |
|---|---|
| `runtime.root` | 每任务独立运行根（仓库外，例 `<RUNTIME_ROOT>/<task>`），勿共用 || `loop.signals` | 必须在 `runtime.root` 内（containment 强制） |
| `backtest.script` | 仓库内相对路径 `projects/<domain>/<task>-<YYYYMMDD-HHMMSS>/wrapper.py` |
| `task.name` | 唯一（= `<task>-<YYYYMMDD-HHMMSS>`，与时间戳目录名一致，见 §9.7） |
| `task.success_criteria` | **至少 3 条**；operator 仅 `gt/gte/lt/lte/eq/ne`；threshold 数值 |
| `task.scope.allow/deny` | 白/黑名单，禁 secrets/production/.env |

### 5.2 wrapper.py（你写的核心）
- 读 `--input`（signals）→ 跑你的算法 → 产出 trades/metrics 输出
- 必须输出 config 里 `success_criteria` 用到的那些 metric（如 trades_count / win_rate / …）
- 只读输入、产出结果，不碰 live/生产数据

### 5.3 signals.json
- 种子信号 / 候选列表 / 待校验输入

---

## 六、运行验证（在 `sloth_engine/` 目录下）

```powershell
cd <repo_root>\sloth_engine
python orchestrator.py --config ../projects/<domain>/<task>-<YYYYMMDD-HHMMSS>/config.yaml --once
```
通过 = OODA 7 步 Verify 达标（exit 0）+ `success_criteria` 全部满足。

---

## 七、排查（接入失败时）
- runtime/信号路径→ 检查 config 里 `runtime.root` 与 `loop.signals` 是否一致、signal 是否已复制到 runtime root
- 找不到运行时/数据 → 检查 `runtime_resolver.py` 候选表，把本机实际路径写进去
- wrapper 外部依赖失败 → 该任务标 `blocked`，先做其他任务，如实报
- 容器/子进程 CreateProcess 267 → 用进程内装配（参考 `projects/pm/pm-with-plugins/`）

---

## 八、三遍验证 + 证据落盘（验收标准）

1. 同一任务 `--once` 跑 **3 遍**，指标/产物一致（确定性 md5 一致）
2. 证据：`projects/<domain>/<task>/reports/<日期>/REPORT.md` + runtime 产物
3. KB 归档：结论 → `<KB_ROOT>/02_项目/<域>/`（PM 放 `02_项目/<Q_PROJECT>/PM/`）
4. `docs/state/WAKEUP.md` + `docs/state/NEXT.md` 固定锚追加该本轮结果（2026-10-14 由根目录归位）

---

## 九、铁律（违反即回退）

1. **Loop 只跑测试不发明**：接入 = 把你的算法写进 wrapper 让 Loop 循环跑，**不在 loop 里发明新算法**。
2. **每任务独立 runtime root**，勿共用。
3. **可逆**：mv 不删，接入失败可回退。
4. **containment**：signals/产物 runtime root 内；config scope 白名单；禁 secrets。
5. **落盘契约**：报告 `projects/<domain>/<task>/reports/`，产物 runtime.root 外，临时脚本 `scripts/tmp/` 用完即删。
6. **三遍一致** 才算验收通过。
7. **万物接入 loop**= 每次接入 = 一个可循环的 loop-runnable 项目 + RC 记录。

---

## 十、接入后总检查清单（照打勾）

- [ ] pytest 基线通过（§二）
- [ ] 域分组正确：`projects/<domain>/<task>/`（§三）
- [ ] 三件套就位：config.yaml + signals + wrapper.py（§四/§五）
- [ ] `runtime.root` 独立、`loop.signals` 在 root 内（§五）
- [ ] `success_criteria ≥3` 且 operator/threshold 合法（§五）
- [ ] wrapper 输出 criteria 对应的所有 metric（§五）
- [ ] `orchestrator.py --once` exit 0 + criteria 全满足（§六）
- [ ] 同一任务跑 3 遍一致（§八）
- [ ] 报告在 `reports/<日期>/REPORT.md`；产物在 runtime.root；无散落（§九）
- [ ] WAKEUP/NEXT 锚已追加（§八）
