# cycle-15 A/C：14 步工具管线只测了 happy path（A 补契约 + C 19 维增量复评）（2026-10-22）

> 起点：代码 head `915b40a`（基线 1460 passed / 1 xfailed / 75.76%）。本文件记录 step A 的缺口定位与补齐、
> step C 的 19 维增量复评。代码提交 `f9049a7`；基线刷新为 **1485 / 76.11**。
> （文件名沿用 architect-skills `ARCHITECTURE-COVERAGE.md §5` cycle-15 条的引用；内容含 A 与 C 两步。）

---

## ① 缺口（机制存在，但只有 happy path 被验证）

`sloth_engine/tool_pipeline.py::ToolPipeline.execute()` 是 `ToolRegistry.dispatch()` 的**审计版对照**
（对标 Claude Code 的 `checkPermissionsAndCallTool()` 14 步）。但此前只有 `tests/test_step_policy_wiring.py`
覆盖到 step-10（G-5 步异常策略），14 步里：

| 步 | 分支 | 补齐前 |
|---|---|---|
| 1 | tool 查无（含 `registry=None`） | 无测试 |
| 2 | abort（`signal.aborted`） | 无测试 |
| 3 | schema `required` 缺失 / 无 schema / 非 dict params | 无测试 |
| 7 | 前置 hook 发射（含 hook 抛错被吞） | 无测试 |
| 8-9 | 权限拒绝（`blocked`）vs 允许 | 无测试 |
| 10 | 回退（`return_default`）/ throw 上限 / 非 policy 对象 | 无测试 |
| — | 适配器 `ToolOrchestrator`、`create_pipeline` | 无测试 |

模块覆盖率仅 **64%**。两条**安全不变量**因此无人守护：

1. **权限拒绝不得被记为 `completed`**（拒绝路径没断言 → 回归静默）；
2. **短路后不得继续执行后续步**（否则副作用已发生，而审计链"看起来完整"）。

### 反向样本（补齐前实测）
只跑 `tests/test_step_policy_wiring.py`：`tool_pipeline.py` 覆盖率 64%，
未覆盖行 `31, 120->122, 123-128, 134-139, 145->155, 149-154, 165-168, 174-182, 190, 244-246, 254-276, 282`
—— 正是**全部短路分支 + 两个适配器**。

## ② 补齐（step A）

| 文件 | 改动 |
|---|---|
| `tests/test_tool_pipeline_contract.py`（新，25 例） | 逐步契约：step1 查无/registry=None；step2 abort 与未 abort；step3 缺参拒绝 / 满足 / 无 schema 或非 dict 跳过；step7 hook 载荷 + hook 抛错被吞；step8/9 拒绝（两条审计记录、`detail=blocked`）与允许（`detail=no-op`）；happy path 14 步全序；声明的 no-op 步；step10 throw 上限 / `return_default` / 非 policy `TypeError`；`to_dict` 审计形态；`ToolOrchestrator`（扁平 kwargs、args/kwargs 拆分、guardian deny/escalate/allow/error 全 fail-closed、dispatch 失败归一化）；`create_pipeline` 接线（含裸 orchestrator） |

### 契约不变量
1. 每条短路分支的审计步骤集合**恰好止于短路步**（后续步不得出现）。
2. 短路步 `status ∈ {failed, blocked}` 且 `detail` 可判读；终态**不得为 `completed`**。
3. **副作用未发生**（abort / 权限拒绝时 handler 未被调用）。
4. happy path 断言 14 步的**编号与名称全序完整**且全为 `passed`（防某步被静默删除后审计链断档）。
5. step10 三态（throw / `return_default` / 非 policy `TypeError`）各自可辨；`ToolOrchestrator` 对 guardian
   的 deny/escalate/异常**一律 fail-closed**。

## ③ 验证

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_tool_pipeline_contract.py tests/test_step_policy_wiring.py -q   # 36 passed
.\.venv\Scripts\python.exe -m pytest tests sloth_engine/tests -q    # 1485 passed / 1 xfailed / 76.11%
.\.venv\Scripts\python.exe scripts\check_orphan_mechanisms.py      # wired 73 / test_only 15 / exempt 1 / orphan 0 / stale 0
.\.venv\Scripts\python.exe scripts\run_gate.py --all               # PASS
node scripts/validate-contracts.mjs                                # 19 atom / 0 错 / 0 警
node tests/run-l1-tests.mjs                                        # 32 passed
```

- 覆盖率 75.76 → **76.11**；`sloth_engine/tool_pipeline.py` **64% → 99%**（仅剩已生效的 `sys.path` bootstrap 行 `31`）。
- 1 warning 仍为第三方 `StarletteDeprecationWarning`（与既有基线同源，非本轮引入）。

## ④ A 阶段对既有登记项的影响

- 低优先项「`tool_pipeline` 其余 13 步契约测试」→ **本轮闭合**（§13.39 的下一目标登记）。
- 未新增 blocked 项、未绕过任何既有 blocked 项（§0.1#6）。

## ⑤ step C 增量复评（19 维，相对 cycle-14）

> 口径同上轮；本轮 B 增量为 architect-observability **新增 OBS-12**（atom 目录数不变，仍 19）。

| 项 | cycle-14 | cycle-15 | 依据 |
|---|---|---|---|
| 矩阵行数 | 19 | 19（不变） | 无新维度 |
| covered / partial / N/A | 14 / 4 / 1 | 14 / 4 / 1（不变） | 无缺口新闭合、无缺口新增 |
| `observability`（#7）质量 | covered（导出可达 + 真 JSON） | covered（**再进一步：审计覆盖全部短路分支，不只 happy path**） | `tests/test_tool_pipeline_contract.py`(25) |
| `observability` 检查清单 | OBS-01..11 | **OBS-01..12**（+OBS-12） | architect-skills `b2dd73e` |

**仍未做（如实登记，未绕过 §0.1#6）**：N-3 残余（真实厂商额度源）与 R3（真实模型调用 / 24h soak）仍 **blocked**
（需 LLM 挂载主机）；N-2 残余（coze I-1/I-3/I-4）与 cycle-12 条目 11/12/13 维持 candidate-pending；
R2（每项目沙箱）、WebUI、`guardian/risk_assessor.py::llm_review()` 维持用户裁定；
低优先仅剩 `tool_registry.dispatch` 主路径（覆盖率 65%）与 `tool_concurrency`（0%，EXEMPT）。