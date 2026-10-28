# cycle-12 场景 C 增量复评 · 19 维覆盖矩阵（条目 10 落地后）（2026-10-22）

> 评估口径：architect-skills 真包（**B 增量 cycle-12 后**：`architect-rag` 检查清单 8→9 含新增 RAG-09；
> `node scripts/validate-contracts.mjs` → 19 atom / 0 错误 / 0 警告；`node tests/run-l1-tests.mjs` → 32 passed）
> 被评对象：sloth-loop（`<WORKSPACE_ROOT>\loop-dev-next`，`dev`，代码 head `26633e3`；基线 **1421 passed / 1 xfailed / 75.13%**，fail_under=70）
> 风险分级口径：`architect-skills/reference/risk-grading-scheme.md`
> 定位：**本轮是"采纳轮"** —— 只落 1 条 adopted（条目 10），矩阵行数与维度分级相对 cycle-10 **不变**；
> 变化仅在 `rag` 维度的检查清单**质量**（8→9）。
> 承上：`docs/design/2026-10-22-cycle10-G56R1-connectivity.md`（该文件为 cycle-10 快照，数字刻意不回填）。

## ① 矩阵（相对 cycle-10 无行级变化）

| 项 | cycle-10 | cycle-12 | 依据 |
|---|---|---|---|
| 矩阵行数 | 19 | 19（不变） | 维度集由 architect-skills atom 定义，本轮无新维度 |
| covered / partial / N/A | 14 / 4 / 1 | 14 / 4 / 1（不变） | 无缺口新闭合、无缺口新增 |
| `rag` 维度检查清单 | 8 条 | **9 条**（+RAG-09） | `architect-rag/contract.json` checklist 8→9 |

**唯一质量变化（条目 10 → `rag`）**：新增 RAG-09「重叠感知的保守文本拼接」—— 包含折叠 + `[min=12,max=400]` 有界
后缀/前缀重叠去除 + 短串（<12 码位）不判包含（相等除外）+ 无命中保守回退（`acc + sep + next`，绝不裁内容）。
loop 侧接线已闭：`sloth_engine/text_merge.py` ← `rag_layers.LayeredMemory._merge_text`（wired，N-1 门禁确认），
`tests/test_text_merge.py`(16 例) 含接线断言。

## ② 仍 partial / N/A 的 6 行（5 partial + 1 N/A，承 cycle-10 §①，本轮无变化）

| # | 维度（atom） | 分级 | 缺口（low 除注明外） |
|---|---|---|---|
| 2 | review（横切 12 层） | partial | 12 层审计台账未成体系 |
| 9 | net（④） | partial | 出站超时/幂等策略未成文 |
| 11 | ops（⑩） | partial | 无容器/编排清单（非目标场景） |
| 13 | cost（⑩） | partial | 接线已通（`quota_probe` → 停止判定），**仍无真实额度源**（N-3） |
| 14 | compliance（⑩） | partial | 合规检查点未纳入 |
| 17 | 性能（⑥主+⑩） | N/A | 无 load-test/benchmark 目录（复检触发：出现 benchmark 目录再评） |

其余 13 行（design / data / test / git / docs / security / observability / frontend / plugin / context / rag / workflow / agent）为 covered。

## ③ 仍未做（如实登记，未绕过 §0.1#6）

- **N-3（承 cycle-10/11）**：真实额度源 + R3（真实模型调用 / 24h soak）—— 需 LLM 挂载主机；下一步 = 文件型探针
  （`LOOP_QUOTA_FILE`，opt-in、可离线测试；接口约定见 status §13.36 D）。
- **N-2 残余（coze I-1..I-4）**：维持 candidate-pending（需真实场景：任意节点图 / 人工闸门 / Redis 依赖）。
- **cycle-12 新 candidate（条目 11/12/13）**：解封条件见 `docs/knowledge-distillation/_INDEX.md` 各条目 ⑦ +
  `docs/design/2026-10-22-cycle12-A-4src-distill.md §⑤`；C6..C10 见同目录 `ISSUES.md`。
- **R2（每项目文件沙箱）**：用户明确裁定**不做**。
- **WebUI / `guardian/risk_assessor.py::llm_review()`**：用户裁定**不动**。
- 低优先：`run_loop.run()` 不可达 `_state_history` 导出；`tool_pipeline` 其余 13 步契约测试。

## ④ 复检命令（GREEN-first）

```powershell
.\.venv\Scripts\python.exe -m pytest tests sloth_engine/tests -q    # 权威门禁：1421 passed / 1 xfailed / 75.13%
.\.venv\Scripts\python.exe scripts\docs_baseline.py               # 文档口径守护
.\.venv\Scripts\python.exe scripts\check_orphan_mechanisms.py     # wired 72 / orphan 0 / stale 0
.\.venv\Scripts\python.exe scripts\run_gate.py --all              # 全量门禁
```