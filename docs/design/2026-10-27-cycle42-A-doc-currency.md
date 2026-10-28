# cycle-42 A · 当前态文档守护的清单必须随交付面扩大（QUICKSTART / 引擎 README / 项目介绍纳入 CHECK_FILES）

- 日期：2026-10-27
- 来源：交付包 `sloth-loop-new` 的「确保 loop 相关文档 / README 都更新到最新」逐文件复核
- 提交：cycle-42 A `b875f4e`（用例数不变）

## 1. 取证方式（先驱动，再结论）

1. 以 `docs/baseline.json` 为唯一基线（**1760 passed / 0 xfailed / coverage 79.49%**，`fail_under=70`，`head=fc492f0`）。
2. 逐文件比对全部 tracked 文档，实测 5 处与基线不一致（另有 2 处附带问题）。
3. 对照：`docs_baseline.check()` → `[]`（**通过**）。
4. 定位：`docs_baseline.CHECK_FILES` 这份**手写清单**未收录这些文件 —— 清单外 = 无人校验。

| 事实 | 修复前 | 修复后 |
|---|---|---|
| `Prompt.md` 头部基线 | 1282 passed / 1 xfailed / 72.91%（commit ea097b6） | 1760 / 0 / 79.49%（fail_under=70） |
| `docs/sloth-loop-QUICKSTART.md` §7 自查 | 「700+ 全绿, coverage>=64%」，且漏 `sloth_engine/tests` | 1760 / 0 / 79.49% + `fail_under=70`，命令补全 |
| `sloth_engine/README.md` 头 / 汇总 | 「v3.4 \| 测试基线: 490 passed (98.4%)」/「490 passed, 8 failures」 | 标注**历史**并显式指向 `docs/baseline.json`（1760 / 79.49%） |
| `docs/sloth-loop-项目介绍与规划.md` | 4 处 `1194 passed / 1 xfailed / 72.13%` | 1760 / 0 / 79.49%（fail_under=70） |
| `docs/sloth-loop-AS-BUILT.md:158` | 「当前实测 1255 / 1 xfailed / 72.68%」与头部自相矛盾 | 复刷新为 1760 / 0 / 79.49% |
| `CLAUDE.md:49` / `docs/sloth-loop-ROADMAP.md:28` | 「coverage ≥64」 | 「≥ `fail_under`=70」 |
| `docs/LOOP-ESSENCE-AND-LEARNINGS.md` 错21 段 | 编码损坏（非 ASCII 全部替换为 `?`） | 按未损坏标识符忠实重建 |
| `CHECK_FILES` 条目数 | 11 | **14** |
| 全量用例数 | 1760 | 1760（不变） |

## 2. 病根：交付面在扩大，而守护清单是手写的

- `docs_baseline` 的价值来自它的**作用域**：只有列进 `CHECK_FILES` 的文档才被断言。
- cycle-24 漏掉的是唤醒指针 `docs/flow/GRAND-LOOP.md`，cycle-41 漏掉的是交接入口 `START.md`；本轮漏掉的是一整类**交付面文档**：上手清单（QUICKSTART）、组件自述（`sloth_engine/README.md`）、完整介绍（`docs/sloth-loop-项目介绍与规划.md`）。
- 后果同族且更贵：同一套基线在**同一个交付包**里出现了 1282 / 1194 / 490 / 700+ 四个不同旧版本号，而 `check() == []` 始终假绿。
- 附带两类非基线缺陷：`AS-BUILT` 内部自相矛盾（同一文件头 1760 / 正文 1255）；`LOOP-ESSENCE` 错21 段在**入库时**即已编码损坏（`git show 2a1cdd2:…` 同为乱码，无源可恢复）。

## 3. 修复

- **7 份文档**：数字 / 口径修正；`LOOP-ESSENCE` 错21 段按**未损坏**的标识符（`status="ok"` / `run_lock` 6h / `verifier._compare` operator None / `pytest tests sloth_engine/tests`(71.98%) 等）忠实重建。
- **`scripts/docs_baseline.py`**：`CHECK_FILES` 11→14，新增 `docs/sloth-loop-QUICKSTART.md`、`sloth_engine/README.md`、`docs/sloth-loop-项目介绍与规划.md`；中文路径用 `\u` 转义，保持该源码 ASCII。
- **`tests/test_gate_self_verification.py`**：新增 `ENTRY_DOCS`（唤醒指针 + 交接入口 + 3 份新纳入），作用域 pin（`…_covers_the_entry_documents`）与漂移负控（`…_flags_entry_document_drift`）改为逐份断言 —— 均为**改写既有用例**，故口径仍 1760。

## 4. 证据（实测）

```
python -c "import importlib.util as u;s=u.spec_from_file_location('d','scripts/docs_baseline.py');
           d=u.module_from_spec(s);s.loader.exec_module(d);print(len(d.CHECK_FILES), d.check())"
-> 14 []

pytest tests sloth_engine/tests -q  ->  1760 passed / 0 xfailed / 79.49%
run_gate.py --all                 ->  PASS (docs-baseline: OK)
```

## 5. 诚实作用域

- 本轮把三份**交付面文档**纳入；纳入即意味着它们必须各自承载基线 token（故 `sloth_engine/README.md` 头部显式指向 `docs/baseline.json`）。
- 历史 / 日期化文档（`docs/design/*`、ADR、`CHANGELOG`、`docs/flow/2026-09-05-*`、`docs/knowledge-distillation/*`）刻意不纳入。
- `LOOP-ESSENCE` 错21 段为**重建**，非原文恢复（原文已在入库时损坏）；重建只依据该段未损坏的标识符。
- 本轮未做 architect-skills B 轮不变量。
- 交付包问题（copy 打包混入 465 个 gitignored 文件）在同轮修正：改用 `git archive`（跟踪文件）；详见 `RELEASE.md` 与 CHANGELOG。
