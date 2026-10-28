# cycle-35 A · 「受门控 / 已覆盖」必须由登记证明，不是按名字

- 日期：2026-10-26
- 来源：cycle-34 收尾复核（守卫族之外的同族问题）——不变量 1（ExecGate 单点出口，F1）
- 提交：cycle-35 A `eb788b1`（+5 用例）／ B（architect-skills）TES-30 + DOC-21

## 1. 取证方式（先驱动，再结论）

1. 静态：读 `tests/test_contract_invariants.py::_unguarded_spawns`，发现豁免是 `guard_terms & _enclosing_refs` —— **名字级**。
2. 探针：造一个「只把 gate 当参数、只在日志里提一句，然后裸 `subprocess.run`」的函数，喂给 `_enclosing_refs`，
   结果 `{'gate'} & refs` 命中 ⇒ 该站点被豁免。
3. 规模：把名字豁免去掉后重算 `_unguarded_spawns()`，得到 **5 处**（此前 xfail 文案只显示 4 行，其中 3 行是宿主工具）。
4. 取样域：`_PY_FILES` 用 `rglob`，把 gitignore 的 `scripts/tmp/**`（30 处 spawn）算进业务域。

| 事实 | 修复前 | 修复后 |
|---|---|---|
| 名字级豁免 | 「函数提到 gate」即豁免 | 只看**文件是否登记** |
| 违规清单 | 4 行（截断，含 3 处宿主工具） | 5 处真业务绕过，列全 |
| 取样域 | `rglob`（含未跟踪垃圾） | git 跟踪 + 待提交，排除归档 / 临时 |
| mcp 服务端 spawn | 裸 `subprocess.Popen` | `ExecGate.popen`，无 gate 拒绝启动 |

## 2. 病根：判定的对象是「名字」，不是「事实」

- 契约（docstring）说的是「ExecGate 是**唯一**业务 spawn 出口」，判定做的却是「函数里出现过门的名字」。
- 这就是 cycle-32 的同族缺陷（**豁免宽于它豁免的对象**），只是对象从「缺陷引用」换成了「不变量自己」：
  提到 ≠ 经过；而且豁免宽了就会**掩盖**真绕过（5 处业务 spawn 因此长期隐形）。
- 第三个面是**取样域**：用文件系统全量枚举，等于把「本机残留垃圾」当成业务代码——域与声称的域不一致。

## 3. 修复

- **取样域**：`git ls-files --cached --others --exclude-standard sloth_engine scripts`，排除 `_archive` / `tmp` / `_tmp`。
- **登记式允许清单**：`SPAWN_SANCTIONED = {runtime_exec.py: 门实现}`；`SPAWN_OUTSIDE_GATE = {self_modify_gate.py: 自举、scripts/run_gate.py 与 scripts/audit_cross_repo_ledger.py: 宿主工具}`；
  每条登记必须仍命中一个真 spawn 站点，否则 FAIL。
- **报告完整**：xfail 文案给出**条数 + 全部行**。
- **MCP 真接门**：`MCPClient(gate)` → `gate.popen(cmd)`；无 gate 抛错拒绝启动；`plugin_bootstrap` 逐层透传 gate（无 gate 则 MCP 不启用）。

## 4. 已决定的边界（不「修」）

- 登记粒度为**文件 + 理由**（非调用点）：已登记文件内新增 spawn 不会自动报警 —— 因此新增登记必须显式评审。
- `_archive/`（归档）与 `scripts/tmp/`（gitignore 临时脚本）明确在域外。
- 门可选适配器的「无门回退」（`backtest_adapter`）本轮**判定为违规**：契约是单点出口，回退路径就是一个可被未来调用方踩到的裸 spawn。未修 ⇒ 不变量 1 保持 xfail（诚实，不为了让灯变绿而登记它）。

## 5. B 轮口径（architect-skills）

TES-30 / DOC-21：**范围性不变量（单点出口 / 受门控 / 已覆盖）的判定必须由显式登记给出，不得按名字推断**；取样域必须与声称的域一致；每条登记必须仍生效（不可静默腐坏）；违规报告不得截断（条数 + 全部行）；宣称「已受控」的文档必须附可核对证据、写清扫描域并完整列出规模。

## 6. 验收

- `pytest tests sloth_engine/tests -q` → 1717 passed / 1 xfailed / **79.41%**（`tests/test_contract_invariants.py` 15+1 → 20+1）
- `scripts/run_gate.py --all` → PASS；`docs_baseline.check() == []`
- B 侧：`node scripts/validate-contracts.mjs` → 19 atom / 0 错 / 0 警；`node tests/run-l1-tests.mjs` → 32 passed

## 7. 冻结项（不动）

N-3 / R3；coze I-1/I-3/I-4、cycle-12 条目 11/12/13；WebUI / 每项目文件沙箱；`guardian/risk_assessor.py::llm_review()`。
