# sloth-loop-0927 完整进化路线图

> 生成: 2026-10-09 · 大任务循环三周目
> 来源: Claude Code源码 + DSH插件生态 + Hindsight RAG + Codex 14模块源码
> 状态: 已修复P0+P1(7文件)，待开发P0-P2新功能

---

## 一、已完成项（本轮对话）

### 1.1 架构师skill升级
| 项目 | 进化前 | 进化后 |
|------|:---:|:---:|
| atom数 | 16 | **18** |
| 检查项 | ~128 | **~159** |
| 新增atom | - | architect-context(8条) + architect-rag(8条) |
| 升级atom | - | architect-agent: 8→15条(Claude Code 7条新规) |

### 1.2 sloth-loop-0927 P0+P1缺陷修复
| 文件 | 修复内容 | 检查项 |
|------|---------|:---:|
| `plugins/rag/dsh-rag-kb/entry.py` | _tokenize中文支持+BM25双路检索+token-aware截断+语义去重 | RAG-01/02/06/07/08 |
| `bm25_retrieval.py` | BM25 _tokenize中文支持 | RAG-08 |
| `context_compactor.py` | tool_result_budget(Layer1)+collapse_drain入pipeline | CTX-02/03 |
| `orchestrator.py` | ContextCompactor+ErrorRecoveryLadder集成 | CTX-01+AGE-13/14 |
| `run_loop.py` | run()→iter_loop() thin wrapper+reset_for_new_turn+try/except恢复 | AGE-09/10/13/14 |
| `event_log.py` | SURFACE_EVENT_TYPES+_surface_events分层 | CTX-05 |
| `telemetry.py` | report_token_usage+80%阈值告警 | CTX-07 |
| `mental_model.py` | to_search_context()→RAG集成 | RAG-05 |
| **测试** | 50 passed, 0 failed | |

---

## 二、四系统交叉学习成果

### 2.1 知识来源矩阵

| 系统 | 语言 | 规模 | 核心学习点 | 已注入模块 |
|------|------|------|-----------|-----------|
| **Claude Code** | TypeScript | 闭源泄露 | 单一路径/Async Generator/三段式状态/死亡螺旋/四层压缩+熔断器 | architect-agent |
| **DSH** | TypeScript | 开源 2056TS文件 | cordis微内核/一切皆插件/4路RAG/RRF融合/50+ui面板 | architect-plugin/frontend/rag |
| **Hindsight** | Python+Rust | 开源 v0.10.1 | 4路并行检索/分层记忆/Consolidation/Cross-encoder/MMR | architect-rag |
| **Codex** | Rust | 开源 111 crates | Guardian分层审批/Agent RAII/Compaction三阶段/ContextFragment/Features五阶段 | architect-security/context |

### 2.2 可借鉴设计优先级

| 优先级 | 设计模式 | 来源 | 文件 | 工作量 |
|:---:|---------|------|------|:---:|
| **P0** | ContextFragment trait | Codex context-fragments | 新建 `context_fragment.py` | ~200行 |
| **P0** | Compaction三阶段(提取→摘要→替换) | Codex compact.rs | 改造 `context_compactor.py` | ~150行 |
| **P0** | ToolOrchestrator统一流水线(approval→sandbox→attempt→retry) | Codex tools/orchestrator | 改造 `tool_pipeline.py` | ~200行 |
| **P0** | GuardianLight分层审查(3文件~400行) | Codex guardian | 新建 `guardian/` | ~400行 |
| **P1** | PersistContext分级持久化 | Codex thread-store | 改造 `run_state.py` | ~100行 |
| **P1** | MCP Client解归档+ToolRegistry接入 | Codex MCP | 恢复+改造 `mcp_client.py` | ~100行 |
| **P1** | SkillPolicy门控+SkillDependencies | Codex skills | 改造 `plugin_manifest.py` | ~80行 |
| **P2** | Features五阶段生命周期 | Codex features | 新建 `features.py` | ~150行 |
| **P2** | RAII SpawnReservation | Codex agent/registry | 改造 `sub_agent.py` | ~80行 |
| **P2** | InputQueue唤醒分离(mailbox vs steer) | Codex session | 改造 `sub_agent.py` | ~80行 |

---

## 二·补. 开发完成记录（2026-10-10 大任务循环四周目）

> 承接三周目未完成项，本轮完成 Phase 2 剩余 + Phase 3 全部 + Phase 4 全部，
> 并修复三周目遗留的 4 处回归/语法错误。

### 本轮新增/修复文件

| 文件 | 类型 | 内容 |
|------|:---:|------|
| `sloth_engine/run_state.py` | FIX+MOD | 修复语法错误(行合并+mojibake)；PersistContext 枚举 + `_flush_sync()`(SQLite WAL checkpoint + fsync)；4 个写方法接入 context 参数 |
| `sloth_engine/features.py` | NEW | Features 五阶段生命周期(UNDEFINED/ENABLED/DISABLED/DEPRECATED/REMOVED) + Feature + FeatureConfigSource + 四级解析(override>env>config>default) |
| `sloth_engine/sub_agent.py` | MOD | SpawnReservation(RAII 槽位) + AgentRegistry(有界并发) + InputQueue(mailbox/steer 双优先级) |
| `sloth_engine/plugin_manifest.py` | MOD | SkillPolicy(auto/explicit/none/inherit) + skill_dependencies 字段 + validate_skill_deps |
| `sloth_engine/tool_registry.py` | FIX | 修复 import(normalize_task_result 来源) + 未知工具 KeyError + params={name,args,kwargs} |
| `sloth_engine/immutable_state.py` | FIX | compute_diff 排除非语义字段(created_at/prev_round_ctx)，消除时序 flake |
| `tests/test_features_and_agents.py` | NEW | 16 测试(features 8 + RAII 4 + InputQueue 1 + SkillPolicy 3) |

### 运行时接入（破框校验后的补缺）

> 破框校验发现：新增模块"存在但未接入运行时"（class present, capability dormant）。
> 本轮补全接入，使能力真正生效。

| 模块 | 接入点 | 机制 |
|------|--------|------|
| Features | `orchestrator.__init__` -> `_build_features()` | 6 个标准 flag 注册+解析+日志；默认映射 enable_ooda/enable_annotation，无 override 时行为不变 |
| ContextFragment | `ContextCompactor.attach_fragment_collector()` + `render_fragments()` | Layer-0 片段渲染 + FragmentBudget 预算裁剪；无 collector 时安全 no-op |
| AgentRegistry | `run_subagents_parallel()` | 有界槽位注册表 + RAII 释放，executor 与 cap 对齐 |
| MCP | `plugin_bootstrap._register_mcp_tools()` | 配置驱动(plugins.mcp.servers)，默认关闭；失败不影响 bootstrap |
| Guardian | `ExecGate._guardian_check()` | （三周目已接入，本轮复核确认） |

### 运行时接入 round 2（破框二轮）

| 模块 | 接入点 | 说明 |
|------|--------|------|
| ErrorRecoveryLadder | `orchestrator.recovery_ladder` | 与 compactor 共享 RecoveryState；prompt_too_long 可驱动 collapse/compact |
| TaskTracker | `orchestrator.task_tracker` | P1-N2 step 级任务追踪，per-run 初始化 |
| ToolOrchestrator | `tool_pipeline.ToolOrchestrator` | 重写为 `ToolRegistry.dispatch` 的薄适配器（原为签名错误的半成品 stub） |

### 去重修复

- `orchestrator.py` 存在 **3× 重复块**（import 3 次 + compactor init 3 次）→ 去重为各 1 次

### 全引擎破框扫描结果

- `.py` 语法错误：**0**
- 重复 3 行块：**0**（去重后）
- 12 个进化模块接入状态：**全部 WIRED**（PermissionMatrix/ReviewSession 经 `from .permission_matrix import` 由 risk_assessor 消费）

### 架构师 skill 三轮复核（18-atom，2026-10-10）

对 sloth-loop-0927 当前状态执行 **18 维度 architect 蜂群复核**（run-pipeline.cjs）：

```
轮次 | findings | critical | high | coverage    | errs | warns
 R1  |    16    |    0     |  0   | 15/1/0/0    |  0   |  0
 R2  |    16    |    0     |  0   | 15/1/0/0    |  0   |  0
 R3  |    16    |    0     |  0   | 15/1/0/0    |  0   |  0
ALL PASS
```

- 结论：**无 Critical/High 阻塞项**；compliance 维度 partial（LICENSE 待确认），其余 covered；frontend/net 维度 N/A（sloth_engine 无对应面）
- 产物：`<PROJECT_ROOT>/docs/architecture-report.md`（180 行）
- fixture：`eval-sloth-loop.json` 刷新为 18-agent 当前态（原为 2026-08-31 的 3-agent 旧版）

### 架构师 skill 补充（闭合 §四 盲区）

| 文件 | 改进 |
|------|------|
| `architect-skills/scripts/swarm-to-template.cjs` | skillMap 增加 `scheme` 字段（risk_scheme_ref 透传）|
| `ai-skill-output-template/scripts/render.cjs` | 字段渲染支持 `f2` 次级字段；skill 明细风险行带 scheme |
| `ai-skill-output-template/templates/architect.single-report.json` | `风险分级` 字段增加 `"f2":"scheme"` |

效果：skill 明细从 `风险分级: low` → `风险分级: low (§一④ ...)`，warns 28→0。

### DSH todo/credentials 插件翻译（Task 3）

来源：`998-agent_research_full/deepseek_plugins/main_repo/packages/{todo,credentials}`

| 插件 | 位置 | 类型 | 工具 |
|------|------|:---:|------|
| dsh-todo | `plugins/skill/dsh-todo/` | skill | `todo_write` |
| dsh-credentials | `plugins/memory/dsh-credentials/` | memory | `cred_ref_check` / `cred_info` / `cred_set` / `cred_resolve` |

**dsh-todo 域保留**：whole-list 覆盖写（last-write-wins，条目无需稳定 id）、三态生命周期
（pending/in_progress/completed）、content 去重非空、默认单 active（`allow_parallel_in_progress` 可放开）、
`todos` 投影在 turn/start 清空。

**dsh-credentials 域保留**：ref 文法 `^[A-Za-z_][A-Za-z0-9_]*$`、key 文法 `<scope>/<id>`、
记录 tagged 联合（api-key/grant）、**CredentialInfo 只读值不暴露**、分层解析
env(read-only,wins) > managed(writable) > project/.env > $DSH_HOME/.env、写只落 managed 且锁内 RMW 原子发布。

- roster 新增 2 项；bootstrap 工具数 29→34
- tests: +6（todo 4 + credentials 2）

### 验证结果

```
pytest tests/ -q --no-cov  ->  1061 passed, 1 xfailed  (0 failed)
```

- 回归修复：3 处 tool_pipeline/tool_registry 导入与语义回归 + 1 处 run_state 语法错误
- 破框校验：新代码数据结构级对标 Codex（PersistContext/Features/SpawnReservation/InputQueue/Guardian/SkillPolicy）
- 三周目遗留的 50 测试基线 + 本轮新增 16 测试，全部通过

---

## 三、开发路线图

### Phase 1: 上下文管理升级（P0）
```
目标: 对标Codex的ContextFragment + Compaction三阶段
文件:
  sloth_engine/context_fragment.py    [NEW] ContextFragment trait + markers + ContentItemKind
  sloth_engine/context_compactor.py   [MOD] 集成Compaction三阶段 + PreCompactHook/PostCompactHook
预计: ~350行, 2-3轮既定模式验证
```

### Phase 2: 工具+安全升级（P0）
```
目标: ToolOrchestrator统一流水线 + GuardianLight分层审查
文件:
  sloth_engine/tool_pipeline.py       [MOD] approval→sandbox→attempt→retry
  sloth_engine/guardian/__init__.py   [NEW]
  sloth_engine/guardian/permission_matrix.py [NEW]
  sloth_engine/guardian/review_session.py    [NEW]
  sloth_engine/guardian/risk_assessor.py     [NEW]
预计: ~600行, 3轮既定模式验证
```

### Phase 3: 持久化+集成升级（P1）
```
目标: PersistContext分级持久化 + MCP解归档 + SkillPolicy
文件:
  sloth_engine/run_state.py           [MOD] PersistContext枚举
  sloth_engine/mcp_client.py          [RESTORE] 从_archive恢复+接入ToolRegistry
  sloth_engine/plugin_manifest.py     [MOD] SkillPolicy + SkillDependencies
预计: ~280行, 2轮既定模式验证
```

### Phase 4: 开关+Agent升级（P2）
```
目标: Features五阶段 + RAII SpawnReservation + InputQueue
文件:
  sloth_engine/features.py            [NEW] Feature + Stage + FeatureConfigSource
  sloth_engine/sub_agent.py           [MOD] SpawnReservation + InputQueue
预计: ~310行, 2轮既定模式验证
```

---

### DSH schedule/jobs/document 三插件翻译 (Task 1, 2026-10-10)

在大任务循环三周目「DSH 插件翻译」线上新增三个真实 DS 插件的 Python 移植
（翻译语义，不复制代码），全部注册为可调度工具并进入 trust roster。

| 插件 | 类型 | 工具 | 域本质（保留点） |
|------|------|------|------------------|
| dsh-schedule | skill | schedule_create / schedule_list / schedule_delete / schedule_due | 四种规则 after/at/every/cron；严格 UTC instant(ms,Z)；every>=60s；cron 400 年上限、边界校验 |
| dsh-jobs | ops | job_submit / job_list / job_read / job_kill | 有界输出环(绝对字节偏移/头部驱逐不移位/非消费式读/UTF-8 安全截尾/gap)；running→terminal 幂等 settle；result 仅交付一次 |
| dsh-document | skill | doc_convert / doc_status / doc_list | 内容身份(sha256(ext\0bytes))共享转换 + 有界 LRU；源准入限流；PDF 输出校验；OfficeToPdfError 分类taxonomy |

文件:
  sloth_engine/plugins/skill/dsh-schedule/{manifest.json,entry.py}
  sloth_engine/plugins/ops/dsh-jobs/{manifest.json,entry.py}
  sloth_engine/plugins/skill/dsh-document/{manifest.json,entry.py}
  sloth_engine/plugin_manifest.py            [MOD] VALID_TYPES += "ops"
  sloth_engine/plugin_config.yaml            [MOD] roster += 3 插件
  tests/test_features_and_agents.py         [MOD] +12 功能测试

验证:
  - registry: 34 → 45 工具；manifest 21/21 有效；plugin_doctor total=0 invalid=0
  - 功能自测: schedule 严格校验/时区归一/cron 边界；jobs 生命周期/幂等/UTF-8 截尾/偏移不回溯；document 去重/分类错误/PDF 校验
  - pytest tests/ 全量: 1077 → 1089 passed, 1 xfailed（无回归）
  - 既定模式三轮: 待执行（见下）

### Hindsight RAG 阶段2/4 + MMR 落地 (Task 2, 2026-10-10)

在既有阶段1(BM25+RRF) 之上，新增零依赖的 `sloth_engine/rag_layers.py`，
对标 999-hindsight-core 的记忆体系（详见 docs/research/rag-comparison-hindsight-vs-loopdev.md）。

| 能力 | 对标 | 实现 |
|------|------|------|
| 实体提取 | Hindsight entity labels | DATE/TIME/PERCENT/MONEY/PATH/ORG/PERSON/TICKER，确定性去重 |
| 三层记忆 | mental_models>observations>raw | LayeredMemory + layer_boost + prefer_observations 去重覆盖 |
| Consolidation | LLM 事实合并 | 相似 raw → observation，保留 provenance(source_ids)，零 LLM |
| MMR 多样性 | Hindsight MMR | λ·rel - (1-λ)·max_sim(已选)，贪心、确定性 |
| 图检索 | Spreading Activation | MemoryGraph 4 类边(自动建边) + 衰减扩散 |
| 统一检索 | recall 栈 | layered_recall = 分层相似 + 图激活 → 合并 → MMR |

接入:
  sloth_engine/rag_layers.py                            [NEW]
  sloth_engine/plugins/rag/dsh-rag-kb/entry.py          [MOD] search() 末尾加 MMR 多样性 pass
  tests/test_rag_layers.py                             [NEW] +13 测试

验证:
  - rag_layers 自测: 实体/consolidation/prefer_observations/层权重/自动建边/衰减扩散/MMR
  - pytest 全量: 1089 → 1102 passed, 1 xfailed（无回归）
  - 三轮一致: 13 passed × 3 轮相同

未做(超出本次范围, 记录待评估):
  - 阶段3 真实 embedding(Ollama/LiteLLM) — 需网络/本地服务, 保持离线优先暂不接
  - LLM 驱动 Consolidation — 成本高, 保留为可选插件方向

### Evolution 候选自动评审策略 (Task 3, 2026-10-10)

原 `evolution_loader.review_candidates()` 必须人工 `--yes` 才纳入候选，
演化闭环无法自主推进。新增**确定性、可解释**的自动评审策略，
使闭环可无人工干预自我推进，同时保留人工闸门作为 override。

| 组件 | 位置 | 职责 |
|------|------|------|
| ReviewPolicy | evolution_review.py | 门槛配置: fitness_threshold / margin_over_incumbent / max_accept_per_round / dedup / param_bounds |
| review_candidates_deterministic | evolution_review.py | 纯函数核心: 三态 accept/reject/defer, 无副作用, 绝不抛 |
| EvolutionLoader.auto_review_candidates | evolution_loader.py | 读候选 → 决策 → accept 写入信号池 + .auto-committed 标记 |
| CLI --auto-review | cli_router.py | 无 --yes 的自动评审入口 |

决策三态 (deterministic):
  accept  — 过全部门槛, 按 fitness 降序纳入 (受 max_accept_per_round 限制)
  reject  — 低 fitness / 重复签名 / 参数越界
  defer   — 边界 (评估失败/提升不足/超轮次上限) → 交人工, 不确定不自动放行

shadow evaluation: 以信号池既有 max(fitness) 为 incumbent 基线, 候选必须
超过 `incumbent + margin_over_incumbent` 才 accept。

文件:
  sloth_engine/evolution_review.py                [NEW]
  sloth_engine/evolution_loader.py                [MOD] auto_review_candidates + review_candidates(auto=)
  sloth_engine/cli_router.py                      [MOD] --auto-review
  tests/test_evolution_review.py                 [NEW] +11 测试

验证:
  - 自测: 三态分类/参数越界/去重/边际提升/确定性排序/签名稳定/空输入/loader端到端
  - pytest 全量: 1102 → 1113 passed, 1 xfailed（无回归）
  - 三轮一致: 11 passed × 3 轮相同

### DSH 插件翻译覆盖表（完整性总账, 2026-10-10）

> 以 998-agent_research_full 的 DSH tool-* 面向为基线, 记录「已翻译 / 部分 / 待译」。
> 接手 Agent 应先读此表, 避免重复翻译或遗漏。

| DSH tool 域 | sloth-loop 承载 | 状态 |
|-------------|--------------|:----:|
| tool-todo | dsh-todo (plugin) | ✅ 已译 |
| tool-schedule | dsh-schedule (plugin) | ✅ 已译 |
| tool-jobs | dsh-jobs (plugin) | ✅ 已译 |
| tool-workflow / tool-ralph | dsh-workflow (plugin) | ✅ 已译 |
| tool-agent-team | dsh-agent-teams (plugin) | ✅ 已译 |
| (credentials) | dsh-credentials (memory plugin) | ✅ 已译 |
| (mneme 记忆) | dsh-mneme (memory plugin) | ✅ 已译 |
| tool-web | dsh-browser + fetch_page/web_search (partial) | 🟡 部分 |
| tool-fs | **dsh-fs (plugin)** — fs_read/write/edit/stat, 路径围栏 | ✅ 已译 |
| tool-fs-search | 仅 list_paths（无 glob/grep 工具面） | ⬜ 待译(判不必要) |
| tool-str-replace-editor | 无 | ⬜ 待译 |
| tool-goal | 无 (goal-round-driver 未译) | ⬜ 待译 |
| tool-ask-user | 无 (user-questions/approval 未译) | ⬜ 待译 |
| tool-lsp | 无 | ⬜ 待译 |
| tool-bash / tool-pwsh | 引擎在 runtime_exec；**无 tool 面** | ⬜ 待译 |
| tool-subagent / tool-subagent-control | 引擎在 sub_agent.py；**无 tool 面** | ⬜ 待译 |
| tool-session-query | 无 (session-log-export 未译) | ⬜ 待译 |
| tool-terminal | 无 | ⬜ 待译 |
| tool-skill / tool-workspace-dependencies | plugin_manifest SkillPolicy 承载；无 tool 面 | 🟡 部分 |
| tool-present (交付物) | 无 | ⬜ 待译 |

统计: 已译 8 · 部分 2 · 待译 8（共 18 域）。
> 2026-10-10 复核: 经必要性评估, 新增翻译 tool-fs (dsh-fs)。其余待译域判定"不该做"(见《DSH 待译域 · 必要性评估》), 主动搁置。

**待译优先级建议**（依据 sloth-loop 运行驱动特性排序, 供后续择机实现）:
1. tool-fs + tool-str-replace-editor（agent 自读写文件是运行基础）
2. tool-bash/pwsh + tool-terminal（命令执行 tool 面, 引擎已存在）
3. tool-subagent（子代理 tool 面, 引擎已存在）
4. tool-ask-user + tool-goal（交互/目标闭环）
5. tool-session-query / tool-lsp / tool-present（场景化）

### DSH 待译域 · 必要性评估（2026-10-10, 既定模式）

> 评估前提: sloth-loop-0927 的定位是 **CLI 驱动的自进化回测编排框架**（OODA 7 步,
> 确定性编排, **无 LLM client / 无模型驱动的 agent loop**）。因此 model-facing 工具
> 的消费者是"内部流水线 (tool_pipeline)", 而非外部大模型。这是判断"是否需要翻译"的关键。

评估结论（必要性 × 成本 × 风险）:

| 域 | sloth-loop 已有等价物 | 必要性 | 结论 |
|----|--------------------|:------:|------|
| tool-fs (read/write/edit) | 无 | 🟡 中 | **建议译**（受控路径读写, 供编排/自改性场景） |
| tool-str-replace-editor | 无 | 🟢 低 | 暂不译（与 tool-fs 重叠, 二选一） |
| tool-fs-search (glob/grep) | 无 | 🟢 低 | 暂不译（编排无需模型式检索） |
| tool-bash/pwsh | ExecGate 引擎已有 | 🟡 中 | **可选译**（高风险, 需 Guardian 完整门控） |
| tool-subagent | sub_agent.py 引擎已有 | 🟢 低 | 暂不译（编排已内部并行, 无模型递归委托） |
| tool-goal | 无 (OODA 本身即目标闭环) | 🟢 低 | 暂不译（loop 的 rounds 已是 goal 语义） |
| tool-ask-user | 无 (CLI --yes 即人工闸门) | 🟢 低 | 暂不译（无交互式 agent 消费者） |
| tool-session-query | event_log.py 已有事件 | 🟢 低 | 暂不译（可后续作为审计工具） |
| tool-terminal | 无 | 🟢 低 | 暂不译（回测编排无需持久终端） |
| tool-lsp | 无 | 🟢 低 | 暂不译（非代码导航场景） |
| tool-present | 无 (reporter 已产出 REPORT.md) | 🟢 低 | 暂不译（交付物已由 reporter 覆盖） |

**总判定**: 9 域中 **仅 1 域 (tool-fs) 明确建议翻译**, tool-bash 列为可选。
其余 7 域对 sloth-loop-0927 当前定位 **无实际价值**, 主动搁置 (非能力缺失, 而是
"不该做"——完整复刻 DSH 通用工具面会偏离 sloth-loop 的编排框架定位)。

**为什么只译 tool-fs**:
  - 自进化/自修改场景需要"受控路径下的读写"能力 (读配置、写候选、改产物);
  - 现有 `list_paths`/`resolve_path` 只读不写, 是真实缺口;
  - 实现成本低 (纯 stdlib pathlib + 路径围栏), 风险可控 (复用 runtime.assert_under)。

**为什么其余不译**:
  - 无 LLM/agent loop ⇒ 缺 model-facing 工具的消费者;
  - 已有引擎 (ExecGate/sub_agent/event_log) 覆盖了编排所需;
  - 盲目翻译会引入安全面 (bash/terminal) 且无收益。

## 四、架构师skill待补充盲区

| 盲区 | 严重度 | 建议 |
|------|:---:|------|
| architect-security缺Guardian模式 | high | 补充分层审批矩阵+审查Token预算+异步决策 |
| 缺Compaction专项评估维度 | high | architct-context需扩展：三阶段+Pre/PostHook |
| 缺Feature flag治理维度 | medium | 可选新增architect-features或并入architect-config |

---

## 五、验证标准

每轮开发完成后执行：
1. `pytest tests/ -x -q --no-cov` — 全量测试不降级
2. `python -c "from orchestrator import Orchestrator"` — 导入不报错
3. 破框检查：新代码是否与四系统参考一致（数据结构级别核对）
4. 既定模式三轮：修复→验证→回归→确认一致

---

*基于: Claude Code / DSH / Hindsight / Codex 四系统交叉学习*
*大任务循环三周目落盘*

> [2026-10-10 文档整理] 本处引用的 `docs/knowledge-distillation/`、`docs/GRAND-LOOP.md`、`docs/research/` 等研究/过程稿已移至 `sloth-loop\docs\_archive-from-0927\` 备份保留；成品 docs/ 仅保留使用/交付所需文档。
