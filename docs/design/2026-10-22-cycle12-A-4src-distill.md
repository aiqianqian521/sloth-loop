# cycle-12 A：四新源蒸馏（WeKnora / cognee / Memori / ADR）（2026-10-22）

> 起点：代码 head `f1a61c7`（基线 1405 passed / 1 xfailed / 75.06%）。
> 本文件记录 step A 的扫描范围、取舍判据、唯一 adopted 条目的落地契约与真值证据。
> 代码提交见 §④；基线刷新为 **1421 / 75.13**。

---

## ① 扫描范围与来源真值

| 源 | 形态/规模 | 解包路径 | 精读子树 |
|---|---|---|---|
| Tencent/WeKnora | Go，1724 `.go`（`internal/` 24 子域） | `<TMP_ROOT>/c12\src\WeKnora` | `internal/searchutil/*`、`internal/storageurl/*`、`internal/storageallowlist/*` |
| topoteretes/cognee | Python，2447 `.py` | `<TMP_ROOT>/c12\src\topoteretes-cognee` | `infrastructure/session/*`、`infrastructure/databases/utils/closing_lru_cache.py` |
| MemoriLabs/Memori | Python + Rust + TS | `<TMP_ROOT>/c12\src\MemoriLabs-Memori` | `memori/memory/augmentation/*`、`search/*`、`integrations/openclaw/src/*` |
| architecture-decision-record | DOC-LEVEL（多语言站点 + 2 skill） | `<TMP_ROOT>/c12\src\architecture-decision-record` | `skills/architecture-decision-record-skill/SKILL.md`、站内 `guide/fitness-functions-*`、`guide/decision-guardrails-*` |

四源均无 `.git`（压缩包快照）→ 阶段0 记 **provisional**（洈1）。
总账：`docs/knowledge-distillation/_INDEX.md` N==M==**14**（adopted 8 / candidate 5 / reference 1）。

## ② 取舍判据（逐条落地）

| 判据 | 结果 |
|---|---|
| 可迁移 **且** loop 真缺口 **且** 能接既有 wired 模块（N-1 门禁） | **adopted**：条目 10（WeKnora 重叠感知保守文本拼接） |
| 可迁移但有同族机制 / 无生产调用点 | **candidate**：条目 11（cognee 水位线）/ 12（Memori 有界延迟批写）/ 13（WeKnora 分数归一化） |
| DOC-LEVEL 证据（洞5） | **reference**：条目 14（ADR 决策治理） |
| 形态不匹配（无落点） | **candidate-pending**：C6..C10 |

**为何只落 1 条 adopted**：N-1 门禁（§13.36）要求新机制必须有**非测试调用方**。四条候选中，
水位线/批写/分数归一化在 loop 侧都没有成立的生产调用点（loop 融合走 RRF；持久化为单事务直写；
checkpoint/resume 已存在），强行落地即为「未接线机制」，会被门禁拦下。故按纪律只落 1 条，其余如实登记。

---

## ③ 条目 10：重叠感知的保守文本拼接（adopted）

### 缺口（反向样本）
loop `rag_layers.LayeredMemory._merge_text` 原实现只做「完全相同去重 + `' ∣ '` 拼接」：
对**包含关系**（A ⊂ B）与**部分重叠**（A 的后缀 == B 的前缀）无能为力 → 观察文本出现截断/重复表述。

### 真值（WeKnora `internal/searchutil/chunkmerge.go`，266 行）
- `:15-45` `JoinChunkContent`：`ContainsChunkContent` 折叠 → `maxOverlap` 被 `defaultSearchSpan` 封顶 →
  由长到短找真实后缀/前缀重叠 → 命中则 `acc + next[overlap:]` → 否则 `acc + separator + next`。
- `:50-58` `ContainsChunkContent`：**极短子串不判包含**（`len([]rune(contained)) >= minOverlapRunes && strings.Contains(...)`）。
- `:87-94` 常量：`minOverlapRunes = 12` / `defaultSearchSpan = 400`（**有界**，防对抗性长文本退化为平方级）。
- `:178-227` `MergeTextChunks`：按 `StartAt`（并列 `ChunkIndex`）稳定排序；间隙/位置缺失走 `gapSep` 拼接不裁剪。

### 取舍
- **不移植** `AppendWithOverlap` / `MergeTextChunks`（依赖 `StartAt`/`EndAt` 位置提示）：loop 调用点无位置坐标，
  无生产调用点不引入（N-1 门禁口径）。
- Go `[]rune` ↔ Python `str`：均为码位序列，等价且无编码截断风险。

### 落地
| 文件 | 内容 |
|---|---|
| `sloth_engine/text_merge.py` | `contains_text` / `join_adjacent` / `merge_texts` + `MIN_OVERLAP_CHARS=12` / `MAX_OVERLAP_CHARS=400` / `DEFAULT_SEPARATOR=" ∣ "` |
| `sloth_engine/rag_layers.py` | `from text_merge import merge_texts`；`_merge_text` → `merge_texts(u.text for u in grp)` |
| `tests/test_text_merge.py` | **16 例**：空/相等/超集子集/短串不判包含/≥min 重叠/<min 重叠/>400 窗口上限/CJK 码位/200KB 对抗输入/幂等/分隔符口径 + **接线断言**（`consolidate` 对超集来源必须折叠） |

### 契约不变量
1. `contains_text`：`len(contained) < 12` 一律不判包含（相等除外）。
2. `join_adjacent`：只在 `[12, 400]` 内去重叠；无命中 → `acc + separator + nxt`（保守，绝不裁内容）。
3. `merge_texts`：折叠结果再喂回自身 = 幂等；空段跳过。
4. 接线：`rag_layers.consolidate` 的观察文本对「超集来源」不含分隔符（= 折叠为超集）。

---

## ④ 验证与基线

```
$ .\.venv\Scripts\python.exe -m pytest tests/test_text_merge.py tests/test_rag_layers.py \
      tests/test_rag_rerank.py tests/test_bm25_retrieval.py -q --no-cov     -> 60 passed
$ .\.venv\Scripts\python.exe scripts\check_orphan_mechanisms.py             -> wired 72 / orphan 0 / stale 0 (exit 0)
$ .\.venv\Scripts\python.exe -m pytest tests sloth_engine/tests -q           -> 1421 passed / 1 xfailed / 75.13%
$ .\.venv\Scripts\python.exe scripts\run_gate.py --all                      -> PASS
```

- 覆盖率：`sloth_engine/text_merge.py` = 34 stmts / 0 miss（**100%**）。
- 全量 1405 → 1421（+16 用例；覆盖率 75.06 → 75.13）。
- 1 warning 为第三方 `StarletteDeprecationWarning`（httpx + `starlette.testclient`），与 cycle-11 基线同源，非本轮引入。

## ⑤ 本轮未做（如实登记，不绕过）
- **I-1..I-4**（coze）、**N-3**（真实额度源 / R3 真实模型 soak）维持原状：无真实场景 / 需 LLM 挂载主机。
- WebUI、`guardian/risk_assessor.py::llm_review()`、R2（每项目文件沙箱）—— 用户裁定不动。
- 低优先：`run_loop.run()` 不可达 `_state_history` 导出、`tool_pipeline` 其余 13 步契约测试。
- 留痕：`work_ooda/20261022-210000-cycle12-A-4src-distill/`（RECORD / ISSUES / AGENT_ERROR_LOG / slices S1,S2）。