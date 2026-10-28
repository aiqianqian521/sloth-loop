# cycle-36 A · 无门即无 spawn：可选的安全关键依赖必须失败关闭

- 日期：2026-10-26
- 来源：cycle-35 收尾复核（登记只回答了「谁在域内」，没回答「忘记注入怎么办」）——不变量 1（ExecGate 单点出口，F1）
- 提交：cycle-36 A `8c6edb2`（+5 用例）／ B（architect-skills）`e1c5718` TES-31 + DOC-22

## 1. 取证方式（先驱动，再结论）

1. 静态：cycle-35 已把不变量 1 的豁免改成**登记式**（`SPAWN_SANCTIONED` + `SPAWN_OUTSIDE_GATE`），命中的 5 处真绕过被点名。
2. 追问：登记只回答「哪些站点在域内」；若调用方**忘记注入** gate，域内站点会怎么走？逐个回读 → 发现 `else: subprocess.run(...)` 与 `import subprocess as sp` 裸跑。
3. 规模：`backtest_adapter.py` 三处 + `ooda_pipeline.py` 两个 sink = 5 处「无门回退」。
4. 形状：`if x is not None: 安全路径 else: 裸路径` —— 安全关键参数写成「可选」，缺省即不安全路径，门禁变成 opt-in。

| 事实 | 修复前 | 修复后 |
|---|---|---|
| 适配器无门 | `else: subprocess.run(...)` 静默裸跑 | `exec_gate is None` 失败关闭（探针 None / `error_code=exec_gate_required` / legacy 构造期错误） |
| OODA callback / regression | `import subprocess as sp` 裸 spawn | 经 `ExecGate.run`；有 runtime 用它绑门，皆无则拒绝 spawn |
| fitness 回测 | 各自为政 | 接 orchestrator 的门（零参提供者，调用时解析） |
| 测试 / 本地构造门 | 「省掉门就裸跑」 | `runtime_exec.local_exec_gate()` 唯一入口，只构造不 spawn |

## 2. 病根：把「可选」当成「缺省也安全」

- 契约是「ExecGate 是唯一业务 spawn 出口」；`if exec_gate is not None:` 却让缺省走**不安全**的那条路。
- 这是 cycle-32~35 的镜像面：那几轮修的是判定的**宽 / 窄**，本轮修的是**缺省方向**——`None` 必须落在「拒绝」一侧。
- 与 cycle-35 同族但不同层：cycle-35 让「谁受控」成为登记的事实；cycle-36 让「没门怎么办」成为**拒绝**的事实。

## 3. 修复

- **适配器 fail-closed**：删除三处 `else` 分支；`exec_gate is None` 时探针 `return None`、`run_backtest` 返回 `error_code=exec_gate_required`、legacy 返回构造期错误（零 spawn）。
- **OODA 两个 sink 经门**：`_run_callback` / `_verify_regression` 增 `*, exec_gate=None`，有 `runtime` 就用 `ExecGate(runtime)`（同一组合根），皆无则拒绝 spawn（detail 含 fail-closed）；删 `import subprocess as sp`。
- **fitness 接线**：`evolution_bridge` 增 `exec_gate=`（gate 实例或**零参提供者**，调用时解析，避免 overlay 重建 runtime 后钉死旧门）；`evolution_loader` 组合根注入。
- **唯一构造入口**：`runtime_exec.local_exec_gate(root=None, *, project_root=None)` 只构造真门、不 spawn，取代「省掉门就裸跑」的旧习惯。

## 4. 已决定的边界（不「修」）

- 「无门回退」**不保留**。若将来确要为本地方便保留降级，必须作为**显式登记的决定**（文件 + 理由 + 作用对象），且登记须仍命中真站点、失效即报警（TES-31 / DOC-22 口径）。
- 登记粒度仍是**文件 + 理由**（非调用点）：已登记文件内新增 spawn 不会自动报警 —— 新增登记须显式评审。
- `_archive/`（归档）与 `scripts/tmp/`（gitignore 临时脚本）明确在域外。

## 5. B 轮口径（architect-skills）

TES-31 / DOC-22：**安全关键参数 / 依赖缺失时必须 fail-closed**——可选 gate / runtime / 解释器白名单为 None 或未注入时，不得静默退回不安全路径（裸 subprocess / 无门回退 / 跳过校验），必须显式拒绝并给出可核对错误码；任何保留的降级都必须作为**显式登记的决定**（文件 + 理由 + 作用对象）且仍须命中真站点；自证 = 去掉一个真调用点的门必须变红且零 spawn。文档侧：描述「可选依赖 / 可选参数 / 未配置时回退」必须写明**缺省即拒绝**，不得用「可选」掩盖「忘记注入」，并须说明生产组合根在哪里注入。

## 6. 验收

- `pytest tests sloth_engine/tests -q` → 1722 passed / 0 xfailed / **79.42%**（不变量 1 由 xfail 转绿）
- `scripts/run_gate.py --all` → PASS；`docs_baseline.check() == []`；`scripts/audit_cross_repo_ledger.py` → unexplained 0 / exit 0
- B 侧：`node scripts/validate-contracts.mjs` → 19 atom / 0 错 / 0 警；`node tests/run-l1-tests.mjs` → 32 passed

## 7. 冻结项（不动）

N-3 / R3；coze I-1/I-3/I-4、cycle-12 条目 11/12/13；WebUI / 每项目文件沙箱；`guardian/risk_assessor.py::llm_review()`。
