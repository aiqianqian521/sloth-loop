# cycle-13 A：文件型额度探针（N-3 feasible slice）（2026-10-22）

> 起点：代码 head `a4e1f20`（基线 1421 passed / 1 xfailed / 75.13%）。本文件记录 step A（N-3 可行切片）与
> step C（19 维增量复评）的判据、契约与真值。代码提交 `c7dad2c`；基线刷新为 **1453 / 75.22**。

---

## ① 目标与解封路径（承 §13.36 D）

- N-3 在 cycle-11 登记为 **blocked**（§0.1#6，不绕过）：G-6 的配额停止门已接线，但**真实额度源**需要供应商 SDK / 凭证，
  本机没有；R3（真实模型调用 / 24h soak）同样需要 LLM 挂载主机。
- cycle-11 给出的下一刀建议 = **文件型探针**（`LOOP_QUOTA_FILE`，opt-in、默认关闭、可离线测试）。本轮落地该切片：
  它不需要任何厂商 SDK，也不改变默认行为，是把 N-3 从"完全不可测"推进到"宿主只要写一个 JSON 文件即可闭合"。

## ② 真值：宿主侧接口约定（来自 §13.36 D，本轮的实现依据）

| 项 | 约定 |
|---|---|
| 注入点 | `Orchestrator.quota_probe`（零参 callable；默认 `None` = 行为完全不变） |
| 载荷形状 | `{"primary": {...}, "secondary": {...}}`，字段别名 `usedPercent`/`used_percent`、`resetsAt`/`resets_at`、`windowDurationMins`/`window_duration_minutes` |
| 语义映射 | `quota_window.from_raw`：`usedPercent` 夹取 [0,100]、非法/缺失丢窗、两窗皆废 → `None` |
| 失败契约 | 探针抛错 → `quota_window.resolve_snapshot` 降级（上次已知快照，`degraded=True`；无缓存则 error snapshot），**绝不停机** |
| 停机条件 | 只有 `used_percent >= 100`（`exhausted`）→ 干净停机（`status=ok`、`total_rounds` 不计）；原因显式带 `provider` 与 `next_reset_at` |

## ③ 落地

| 文件 | 内容 |
|---|---|
| `sloth_engine/quota_file_probe.py`（新，50 stmts） | `ENV_FILE`/`ENV_PROVIDER`/`DEFAULT_PROVIDER` + `enabled`/`resolve_path`/`resolve_provider`/`load_payload`/`make_probe`/`install`；**只负责读与解析**，窗口语义映射交给快照层 |
| `sloth_engine/orchestrator.py` | `__init__` 尾部 2 行安装（注释 + `_install_quota_file_probe(self)`）；环境变量未设时默认档逐字节不变 |
| `tests/test_quota_file_probe.py`（新，32 例） | env 门控 / 载荷解析（含 BOM、非对象、坏 JSON、缺文件）/ provider 优先级 / install 与 no-op / fail-soft 交接 / 门禁消费 / **两条端到端 Orchestrator 跑** |

### 契约不变量

1. `LOOP_QUOTA_FILE` 未设 / 空 / 纯空白 → OFF，`quota_probe` 保持 `None`（零行为变化）。
2. 探针每次调用**重新读文件**（不缓存），返回解析后的 dict 原样（窗口映射仍是 `quota_window` 的职责）。
3. provider 标签优先级：`LOOP_QUOTA_PROVIDER` > payload 的 `provider` > `"loop"`；坏载荷只会退回默认标签，不影响安装。
4. 文件缺失 / 非法 JSON / 非对象 → 探针抛错；`resolve_snapshot` 降级，**不抛进主路径、不停机**。
5. 端到端：env 开 + 耗尽载荷 → 第 0 轮干净停机（`status=ok`、`total_rounds=0`、原因含 `provider=file-provider`）；
   env 关 → 3 轮照常、停机原因不含 `Quota`。

## ④ 验证

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_quota_file_probe.py -q --cov-report=term
    # 32 passed；sloth_engine/quota_file_probe.py 50 stmts / 0 miss = 100%
.\.venv\Scripts\python.exe -m pytest tests sloth_engine/tests -q      # 1453 passed / 1 xfailed / 75.22%
.\.venv\Scripts\python.exe scripts\check_orphan_mechanisms.py       # wired 73 / orphan 0 / stale 0 (exit 0)
.\.venv\Scripts\python.exe scripts\run_gate.py --all                # PASS
```

- 全量 1421 → 1453（+32 用例；覆盖率 75.13 → 75.22）；1 warning 仍为第三方 `StarletteDeprecationWarning`（非本轮引入）。
- 门禁佐证：`quota_file_probe` 首次扫描即计入 `wired`（调用方 = 生产代码 `orchestrator.py`），未落入 `test_only` / `orphan`。

## ⑤ step C 增量复评（19 维，相对 cycle-12）

> 口径同 `docs/design/2026-10-22-cycle12-C-19dim-increment.md`；本轮 B 增量为 COS-08 **补强**（非新增 atom）。

| 项 | cycle-12 | cycle-13 | 依据 |
|---|---|---|---|
| 矩阵行数 | 19 | 19（不变） | 无新维度 |
| covered / partial / N/A | 14 / 4 / 1 | 14 / 4 / 1（不变） | 无缺口新闭合、无缺口新增 |
| `cost`（#13）质量 | partial（接线已通、**无真实来源**） | partial（**来源可离线注入**：文件探针；真实厂商源仍 blocked） | `quota_file_probe.py` + 端到端停机用例 |
| `cost` 检查清单 | COS-08 | COS-08 补强（注入面 + opt-in 等价） | architect-skills `90a5287` |

**仍未做（如实登记，未绕过 §0.1#6）**：真实厂商额度源（需凭证）与 R3（真实模型 / 24h soak）仍 **blocked**；
R2（每项目沙箱）、WebUI、`guardian/risk_assessor.py::llm_review()` 维持用户裁定；低优先项
（`run_loop.run()` 不可达 `_state_history` 导出、`tool_pipeline` 其余 13 步契约测试）不变。