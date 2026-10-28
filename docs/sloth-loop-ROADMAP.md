# sloth-loop 后续开发进度与唤醒手册（ROADMAP）

> 本文件是**后续（延后）开发项的唯一待办源头**。后期任何 Agent 接手时，先读本文件
> 了解「当前基线 + 铁律 + 待办 + 触发条件」，再决定做哪些。未经触发条件达到，
> 不要提前推进 gated 项。
> 最后更新：2026-10-28 | 分支 `dev` | 测试 **1760 passed / 0 xfailed / coverage 79.49%**（HEAD `0b8afab`；fail_under=70；单一来源 docs/baseline.json）。
> 历史基线 1113 passed / 2026-10-10、780 passed / 2026-09-06 / HEAD `362e479` 见 docs/sloth-loop-CHANGELOG.md 。本节数字**以实测为准**（冲突以本节为准）。

## 0. 当前基线（实测，接手先核对）

```bash
cd <repo_root>
.venv\Scripts\python.exe -m pytest -p no:cacheprovider --no-cov -q tests/ \
  --ignore=tests/test_p0_2_rerun.py
# 期望：1760 passed / 0 xfailed / coverage 79.49% (fail_under=70)（2026-10-28，HEAD 0b8afab）
git log --oneline -3   # 0b8afab / 7637103 / 16fb7a1
```

- 真实任务接入示例（lh 场景）已沉淀到 lh 知识库（含 pilot 配置模板与生成器）。
- 端到端跑通：`--doctor` 探针 3 trades；`--once` 7/7 OODA、1/1 criteria、provenance 落库。
- 生产发布**未达**门禁（见 CHANGELOG §六），dev-only GREEN。

## 1. 铁律（接手必读）

- 只动 dev 副本 `sloth-loop/`，**不要**碰旧基线 `loop/`（master 47a383b）。
- 回测脚本用仓库内相对路径；运行产物落 `runtime.root`（仓库外）。越界 = fail-closed，不是 bug。
- Pattern 默认证据，Rule 默认审批后控制；**禁止**把 Learn 结果当 Rule 自动改 status。
- 提交 gate 用 `scripts/run_gate.py`（coverage ≥ `fail_under`=70，只升不降）。
- Windows 下中文文件名提交：gate 已强制 UTF-8；提交信息建议用 `git commit -F <文件>`。

## 2. 后续待办清单（含触发条件；gated 项未触发不要抢跑）

### ✅ P0 · fail-closed CI 接入（已交付 2026-10-26，模式 A：pre-receive 服务端门禁）
- **目的**：把本地 `run_gate.py` 从「可绕过」升级为远程不可绕过的 CI（hosted CI 或 pre-receive）。
  同时补 provenance secret/path 扫描（防密钥泄露、防绝对路径污染事件日志）。
- **触发条件**：多人/多机协作提交代码，或准备发布到 live 前。
- **要做**：
  1. 选型（hosted CI / pre-receive 服务端 hook）并接入远程仓库。
  2. CI 运行 `pytest` + coverage（复用 pyproject 门禁，`fail_under` 从 pyproject 读取）。
  3. 加扫描器：扫描 staged 内容中 secrets/keys/`.env` 与完整主机绝对路径。
  4. 失败即拒绝 merge/push。
- **交付物（2026-10-26，commit `310c918`）**：`scripts/content_scan.py`（密钥文件名 / 私钥头 / AWS AK id / 高熵硬编码凭据 / 代码与配置中的家目录路径；对全仓 371 文件实测 0 误报）+ `scripts/push_gate.py`（对每个新 tip 用 `git archive`+`tarfile` 落树 → 内容扫描 → 在推来的树上跑本地门禁；超时 / 无法启动 / 归档越界一律拒绝）+ `scripts/pre-receive` + `scripts/install_push_gate.py`（安装**固定副本**、钉住 `core.hooksPath`、配置 `export`）+ `tests/test_push_gate.py`（28 例，含真实 `git push`）。
- **验收（已达成）**：客户端 `core.hooksPath` 指向空目录（等价于 `--no-verify` / 全新克隆）时，非绿色提交 / 含密钥提交 / 推送内改写 `push_gate.py` 的提交仍被拒；缺 bundle 时 fail-closed 拒绝。
- **剩余（部署动作，非代码）**：在目标接收仓执行 `python scripts/install_push_gate.py --repo <origin>`（一行）；若要 hosted CI 而非 pre-receive，用同一 artifact 包一层即可。事件日志的绝对路径污染由 `tests/test_runtime_artifact_containment.py` 覆盖（本项只扫代码 / 配置域）。
- **依赖**：无（已交付）。

~~### 🔴 P0 · migration sentinel RPO~~ ✅ **已交付（2026-10-26，cycle-38 A，commit `142fb5d`）**
- **目的**：把迁移恢复的 RPO 从「行数代理」升级为「业务时间点」，才能宣称可恢复到某一时刻。
- **交付物**：schema v6 `commit_sentinel(seq, scope, committed_at)` —— 由 SQLite 触发器在 `rounds` / `run_learns` / `failure_patterns` / `success_patterns` / `l2_suggestions` 的 INSERT/UPDATE 上写入，标记由数据库**在同一事务**内产生（任何应用写入路径都绕不过，业务写入回滚后不留标记）；`committed_at` 为 UTC ISO-8601 毫秒精度、字典序可排，`seq` 同毫秒消歧；引入时对既有行**恰好回填一次**，down 只丢弃标记表与触发器、可重放重建（`sloth_engine/migrations/v006_commit_sentinel.py`）。`scripts/migration_rehearsal.py` 在隔离副本上实测业务时间点：记录 backup cutoff → 真实提交 M 笔业务行 → 从 cutoff 备份恢复 → 断言哨兵**恰好等于** cutoff，`rpo.mode = "sentinel_timestamp"`、`verified = true`，输出 `restores_to_cutoff` / `units_lost_on_restore` / `window_ms`；哨兵缺失即 fail-closed（+6 用例）。
- **验收（已达成）**：演练 evidence 给出「恢复到 committed_at ≤ cutoff」的业务时间点；RTO 实测（`rto_ms`）。本机真实库 v5→v6 迁移回填 131 行哨兵、integrity ok、foreign_key_errors 0。
- **诚实作用域**：这是**隔离副本上的演练**，不是生产停写窗口实测；生产 RTO/RPO 仍需按 runbook 在停写窗口复核（见 `docs/sloth-loop-MIGRATION-RECOVERY.md` §四）。
- **依赖**：依赖 fail-closed CI（evidence 校验入 CI）—— 已交付，见本文件上一条。

### ✅ 测试隔离 + 门禁口径（已交付 2026-10-26，cycle-39 A/A2；源自 cycle-38 新鲜副本验证登记）

- **目的**：测试结论不得随机器运行态漂移；门禁的通过消息必须与判定同源。
- **触发条件**：已触发（cycle-38 新鲜副本验证登记两条候选；本轮实测复现并修复）。
- **红证据（实测）**：全新克隆仅 `pytest --collect-only tests/test_v2_p1p2.py` 就写出约 110KB 的 `sloth_engine/data/patterns.db` 进代码树；把一份 v5 旧库放进树后，整套 pytest 在**收集期**直接 ERROR（`RuntimeError: database migration required: v5 -> v6`）。逐文件扫描另发现 4 个同族写入点。`run_gate.py` 判定 `measured + 0.15 >= recorded`，通过行却打印 `coverage 79.35% >= 79.47%`（字面为假）。
- **交付物**：5 个写入点切私有临时库 / 临时配置（`memory.sqlite_path` → tmp）；`test_v2_p1p2.py` 私有临时库 + 确定性种子 + 隔离回归测试；`run_gate.coverage_floor()` 作唯一定义、判定与通过/失败行同口径（+3 用例）。
- **验收（已达成）**：逐文件扫描零创建者；新鲜副本全量在「空库」与「预置 v5 旧库」两场景下均 **1759 passed / 0 xfailed / 79.48%**（cycle-39 快照），仓库树零写入、旧库未被改写；`scripts/run_gate.py --all` → PASS。
- **诚实作用域**：只覆盖 `sloth_engine/data/patterns.db` 这一个耦合点（仓库根 `_data/` / `work_ooda/` / `logs/` 等 gitignore 运行态目录仍会被测试创建，属历史行为）；门禁仍是**本地**软约束（可 `--no-verify` 绕过），强制由 cycle-37 的 pre-receive 承担；0.15pp 宽容保留（本轮只统一口径）。
- **依赖**：无。

### ✅ 测试结论可复现（已交付 2026-10-27，cycle-40 A/A2；源自 cycle-39 新鲜副本验证登记的 0.01pp 残差）

- **目的**：同一份代码在同一台机器上连续两次运行必须给出相同的通过数与覆盖率；登记的基线必须是**可复现的观测**（干净克隆可逐字重现），而不是一个偶然读数。
- **触发条件**：已触发（cycle-39 新鲜副本验证登记「79.47% vs 79.48% 的 1 分支残差」；本轮定位到根因并修复）。
- **红证据（实测，三层漂移）**：① `sloth_engine/tests/_tmp_*` 插件草稿包跨运行残留 → `dsh-mneme` / `dsh-rag-kb` 的 `_ensure` 在「store 已存在 / 缺失」间翻转（90%/88%、70%/69%）；② `run_reporter._archive_raw_io` 最后一级回退直读仓库根 `_data`（热机有、干净克隆无，88%/89%）；③ `sub_agent.AgentRegistry._release` 的循环分支只被线程竞态覆盖 —— 同一命令连跑 6 次，4 次 4 partial、2 次 5 partial（79.48% vs 79.47%）。
- **交付物（commit `74253b4` + `7471e41`）**：`sloth_engine/tests/conftest.py` 会话级 autouse 夹具清理 `_tmp_*`；抽出可注入的 `run_reporter._data_root()`（测试 monkeypatch 到空临时目录）；新增单线程测试直接驱动 `_release` 的三种形状（走过非匹配项 / 首项命中 / 自然耗尽），+1 用例。
- **验收（已达成）**：同一命令连续两次 **1760 passed / 0 xfailed / 79.49%**（4424/670）逐字一致；干净克隆（`git clone` 到空目录后全量）同值、仓库树零写入；`scripts/run_gate.py --all` → PASS。**登记基线由「本机偶发 79.48%」改为「干净克隆可复现 79.49%」。**
- **诚实作用域**：本轮消除的是「测试自身残留 + 并发时序」两类耦合；仓库根 `_data/`、`work_ooda/`、`logs/` 等 gitignore 运行态目录仍会被部分历史测试创建（历史行为，本次未纳入）；`conftest.py` 自身在「干净（无 `_tmp_*`）」与「热机（有 `_tmp_*`）」下命中不同的单条分支，但 partial 计数相同，故总计数不受影响。
- **依赖**：无。

### ✅ 交接入口文档纳入口径守护（已交付 2026-10-27，cycle-41 A；源自打包复核）
- **目的**：新 agent 第一个读的交接入口 `START.md` 也必须引用同一套基线，并被 `docs_baseline` 的手写清单覆盖。
- **触发条件**：已触发（打包复核时发现 `START.md` 两处引用旧基线 1159 / 71.76%，而实际 1760 / 79.49%）。
- **红证据（实测）**：`docs_baseline.check() == []` —— 它**不覆盖** `START.md`（不在 `CHECK_FILES`），于是 `START.md:24` / `START.md:35` 的旧数字（差 601 个用例）长期无人校验；同族：cycle-24 唤醒指针缺口，再外一层。
- **交付物（commit `fc492f0`）**：`START.md` 数字更新；`scripts/docs_baseline.py` 的 `CHECK_FILES` 纳入 `START.md`；`tests/test_gate_self_verification.py` 的作用域 pin 与漂移负控改为覆盖「唤醒指针 + 交接入口」两份入口文档（用例数不变）。
- **验收（已达成）**：`docs_baseline.check() == []`；全量 **1760 passed / 0 xfailed / 79.49%**（口径不变）；`scripts/run_gate.py --all` → PASS。
- **诚实作用域**：本轮只把 `START.md` 这类「交接入口」纳入；其余疑似当前态文档（`sloth_engine/README.md` 的 v3.4 头、`docs/sloth-loop-项目介绍与规划.md`）仍不在清单内，是否属当前态待裁定（已登记候选）。
- **依赖**：无。

### ✅ 当前态文档口径守护扩容（已交付 2026-10-27，cycle-42 A；源自交付包逐文件复核）
- **目的**：把「当前态文档」守护清单补齐——交付前逐文件复核，凡引用同一套基线的入口 / 组件 / 介绍文档，都必须被 `docs_baseline` 的 `CHECK_FILES` 覆盖。
- **触发条件**：已触发（打包复核发现 4 处陈旧基线：`Prompt.md` 头 1282、`QUICKSTART`「700+ / coverage≥64%」、`sloth_engine/README.md` v3.4 头 490、`docs/sloth-loop-项目介绍与规划.md` 1194；另 `AS-BUILT` §158 自相矛盾、`LOOP-ESSENCE` 错21 段编码乱码）。
- **红证据（实测）**：`docs_baseline.check() == []`，同时上述文档与基线 **1760 / 0 xfailed / 79.49%** 不一致——`CHECK_FILES` 这份手写清单未收录它们（cycle-24 唤醒指针 / cycle-41 START.md 的同族，对象再外扩）。
- **交付物（commit `b875f4e`）**：7 份文档数字 / 口径修正（含 1 处编码损坏重建）；`scripts/docs_baseline.py` 的 `CHECK_FILES` **11→14**（+QUICKSTART / +sloth_engine README / +项目介绍）；`tests/test_gate_self_verification.py` 的作用域 pin 与漂移负控由 2 份扩到 5 份（`ENTRY_DOCS`，用例数不变）。
- **验收（已达成）**：`docs_baseline.check() == []`；全量 **1760 passed / 0 xfailed / 79.49%**（口径不变）；`scripts/run_gate.py --all` → PASS。
- **诚实作用域**：① 新增 3 份入口文档须各自承载基线 token 才被守护（故 `sloth_engine/README.md` 头部显式指向 `docs/baseline.json`）；② 历史 / 日期化文档（`docs/design/*`、ADR、CHANGELOG、`docs/flow/2026-09-05-*`、`knowledge-distillation`）刻意不纳入。
- **依赖**：无。

### 🟠 P1 · REST API + Webhook（W4 平台化）
- **目的**：外部系统/脚本通过 HTTP 触发 Loop、查询回测结果/模式库；钉钉/企微通知。
- **触发条件**：出现第 2 个真实多模块任务，或你/团队需要外部驱动 Loop 时。
- **要做**：
  1. 抽象「任务引擎」，config 驱动任意项目（多项目隔离）。
  2. REST 端点：触发 run、查 status/history、读模式库。
  3. Webhook 出站：按 DSH 复检条件触发通知。
  4. 复用 Checkpoint/EventLog/PatternStore 端口，不重复造。
- **验收**：外部 HTTP 可触发一次真实 run 并取回结果；通知到达。
- **依赖**：gated，前置 P1 W2-BOUNDARY-01（Orchestrator per-instance 化，去掉模块级单例锁）。

### 🟡 P2 · AI Team / 蜂群（roster 链）—— 规划，未实现

- **目的**：把「多角色 / 蜂群」从方法论步骤升级为**受控**的编排层能力，同时守住「判定权外置」与「零 LLM」两条底线。
- **触发条件**：L3 有资源，或出现「需要多机并行采集 / 多 item 搭环境」的真实任务（蜂群唯一甜点区）。
- **前置**：判定外置（`success_criteria` + 纯计算 `wrapper`）已就位 —— 本仓已有；无前置代码依赖。
- **要做（全部未实现，详见 `docs/sloth-loop-AI-TEAM-AND-SELF-EVOLUTION.md`）**：
  1. roster 链合并：`subagent_spec.md`（未实施）+ `prompt_registry.py` + `prompt_renderer.py` → `roles.yaml → renderer → spawn → verifier`；
  2. Maker / Checker 隔离落在**工具权限**（Checker 只读模式库 / 禁改库），不靠 prompt 叮嘱；
  3. role / prompt 的 md5 纳入「三轮一致」复算；
  4. `run_gate.py` 增 team gate（独立 verifier 签名 + 证据 `N==M`）；
  5. 每个角色有退出条件；蜂群有可验收的 `success_criteria`。
- **验收（将来）**：同一输入下 `roles.yaml` 渲染确定、md5 稳定；team gate 能拒绝「无独立签名」的产物。
- **依赖**：无硬依赖；建议排在自主进化唤醒（§4b）之后。

### 🟡 P2 · OS/network sandbox
- **目的**：把子进程执行从「dev containment」收窄为系统级沙箱（OS/network 约束）。
- **触发条件**：把 Loop 暴露给不可信输入或部署到生产前。
- **要做**：
  1. 在 ExecGate 之上加 OS 沙箱（进程权限/容器化）。
  2. network 策略：默认禁止出网（除非显式允许）。
  3. 文档化信任边界。
- **验收**：逃逸路径/网络越权被系统级拦截（非仅路径断言）。
- **依赖**：无硬依赖，但建议在 fail-closed CI 后做。
~~### 🟡 P2 · WebUI Dashboard（已决策 = 方案 A：FastAPI JSON API + 抽独立静态前端）~~ ✅ **已完成（P2-A）**
- **目的**：网页看板查看回测结果/模式库/运行历史/健康分。
- **触发条件**：你主动想可视化时。用户已明确选**方案 A**。
- **架构选型（2026-09-03 用户拍板）**：后端已是纯 JSON API（`/api/*` 约 15 个路由），保留 FastAPI；把内嵌 HTML/JS 抽成独立静态文件 `sloth_engine/webui/static/index.html` + `app.js`，用 `StaticFiles` 挂载。**同一仓库、零 node 构建工具**；这是"前后端分离"的契约形态但免构建。**不采用**完整 Vue/React（过度设计）与 Streamlit（对交互式规则审批/队列工具是倒退）。
- **要做**：
  1. 把 `webui.py` 内嵌 L224-361 的 HTML/JS 抽到 `sloth_engine/webui/static/`，`index` 路由返回静态 index.html，其余 `/api/*` 不动。
  2. 数据源：JSONL EventLog + SQLite PatternStore（已实现）。
  3. 页面：dashboard / runs / patterns / trace（复用现有 JS 逻辑，白屏已用 `.slice(0,N)` 修复）。
  4. 落地部署路径与鉴权；fastapi/uvicorn 声明进依赖并让 webui 可被单测覆盖（当前 gate 环境缺依赖，coverage 0%，只有静态断言保护）。
- **验收**：浏览器可看运行历史与模式库，且带鉴权；`webui.py` 在单测/coverage 中不再是 0%。
- **依赖**：无硬依赖。
- **遗留关联**：本项的依赖安装与 coverage 化同时解决遗留「webui coverage 0%」。

~~### 🟠 P1 · 测试卫生：修测试污染已提交交付物~~ ✅ **已完成（commit 待记）**
- **修复**：`_write_customer_report` 不再覆盖已跟踪交付物。test_resume_step 加 autouse fixture 阻断 `Orchestrator._write_customer_report` 写成默认任务 reports；test_loop 用隔离 task 名 `_loop-test` + `.gitignore`。全量 734 passed（历史快照），`projects/loop-round/` 零污染。**根因**：`DEFAULT_CONFIG.task.name` 默认值已从 `loop-round` 更名 `sandbox`（config_util / run_once_pipeline fallback / 相关测试 / QUICKSTART 落点 / .gitignore 同步），活动代码零残留 `loop-round`，彻底根治撞交付物目录。commit `a46e044`。

~~### 🟡 P2 · run_parallel Windows multiprocessing 并行修复~~ ✅ **已完成（P2-B）**
- **问题（2026-09-03 D8 修复后遗留）**：`orchestrator.run_parallel` 的 `_run_one` 是嵌套闭包，Windows multiprocessing 下无法 pickle（`Can't pickle local object`），无法真实子进程并行。D8 只修了 `_ENGINE` 未定义 NameError，并行仍未落地。
- **触发条件**：需要真正多窗口并行回测时（当前单窗口串行已够用）。
- **要做**：把 `_run_one` 改为模块级可 pickle 函数，或改用 `concurrent.futures.ProcessPoolExecutor` + 顶层 worker，参数通过显式 tuple 传递，避免闭包捕获 `self`。
- **验收**：`run_parallel` 在 Windows 下真实多进程并行多个窗口并返回结果；加对应单测。
- **依赖**：无。工作量 0.5-1d.


## 3. 建议执行顺序（当触发条件满足时）

```
~~fail-closed CI 接入~~ ✅  →  ~~migration sentinel RPO~~ ✅  →  sandbox
                      ↘  REST/Webhook（等第 2 个真实多模块任务）  →  WebUI（按需）
```

## 4. 已在本次会话完成（勿重复）
- ✅ pilot 配置模板化（模板 + 生成器，已随场景移入 lh 知识库）
- ✅ 端到端真实任务接通（doctor/once 跑通、provenance 落库）
- ✅ orchestrator godfile 拆分 / containment / ExecGate / CB 半开 / CI green 门禁
- ✅ ADR + effectiveness/pilot 验证报告入库
- 文档：USAGE / CHANGELOG / DEV-SETUP / MIGRATION-RECOVERY
- ✅ 系统完整性基线 + 报告自动化（--report）、U&Q 条件触发、输入信号 schema 强校验(fail-closed)
- ✅ 自主进化第1档：半自主信号演化（evolution_bridge + evolution_loader + --evolve/--rev-candidates CLI）
- ✅ 自主进化第2档首块：SelfModifyGate 自改码安全门禁原语（patch→沙箱pytest→备份提交/失败丢弃）
- ✅ 架构缺陷修复批次（commit `7ad640a`）：run_id 双写一致/archive 幂等、`--once` 失败退出码、run_once 统一信封、`run_parallel` `_ENGINE`→`_HERE`、WebUI 内嵌 JS 切片白屏修复、WRAPPER_METRICS 白名单对齐。先测后写，新增 14 项测试。
- ✅ P1 测试卫生：`test_resume_step`/`test_loop` 不再把客户完工报告写到 `projects/loop-round/`（隔离 task + autouse fixture + `.gitignore`）。全量 734 passed（历史快照），loop-round 零污染。
- （历史快照：全量回归 734 passed / 1 skipped / 1 xpassed，coverage 70.68%）

- ✅ **P2-A · WebUI 方案 A（静态分离，commit `31caad4`）**：内嵌 HTML/JS 抽到 `sloth_engine/webui/static/index.html`；`webui.py` 挂 `StaticFiles` + 首页 `FileResponse`，`/api/*` 15 路由全保留；fastapi/uvicorn/httpx 入依赖；新增 `tests/test_webui_static.py`（7 项）。`webui.py` 在单测/coverage 中不再是 0%（0% → 已被覆盖）。
- ✅ **P2-B · run_parallel Windows 真实并行（commit `31caad4`）**：嵌套闭包提为模块级 `_parallel_exclusion_check(win, db_path)` + `functools.partial`；Windows 真实多进程并行通过；新增 `tests/test_run_parallel.py`（3 项）；`test_cli_exit_code.py` 过时 D8 断言已更新。
- 全量回归 745 passed / 1 xpassed（历史快照），coverage 71.57%（webui.py 由 0% → 已被覆盖）。
- （P2 拆解与 OODA：docs/sloth-loop-P2-拆解-2026-09-03.md、work_ooda/20260903-p2-decompose-dev/）

- ✅ **WebUI 增强（鉴权/数据隔离/部署 loopback）**：写端点可选 bearer-token 鉴权（env `LOOP_WEBUI_TOKEN` / `--token`；未配置则向后兼容），`_store()` 数据目录可配置（env `LOOP_WEBUI_DATA_DIR` / `--data-dir`，默认 `_HERE/data`），默认 host 改 loopback `127.0.0.1`（显式 `--host` 才对外）。新增 `tests/test_webui_auth_config.py`（10 项，含 env 回退对称性）。全量 755 passed / 1 xpassed（历史快照），coverage 71.91%（webui.py → 72%）。
- （P2-A 鉴权/部署/数据隔离三件套收口；P2 WebUI 框架至此完整可落地。）

- ✅ **架构基建图落地（commit `82acaba`）**：`docs/sloth-loop-AS-BUILT.md`（as-built 单点基线 + 15 维覆盖矩阵 + 证据映射）、`docs/sloth-loop-架构基建规划-2026-09-03.md`（结合 architect-skills 的规划 + §八认知上限机制）、`tests/test_contract_invariants.py`（契约不变量层：3 绿守护 + 3 xfail 登记 F1/A2/F6）。
- ✅ **技术细节蒸馏库（2026-09-04）**：`docs/knowledge-distillation/`（README 方法论 + `_TEMPLATE.md` + `_INDEX.md` + 子目录体系 + 首样 `2026-09-03-sloth-loop-self-scan.md`）。机制：外部大量扫描 GitHub 大厂 → 学习 → 蒸馏 → 归类 → 回填 as-built/检查清单/契约不变量（蜂群/ooda/architect-skills 只做已知基线的符合性检查，抬升不了"什么是最好的"的认知上限，全靠本库闭环）。
- 全量回归 758 passed / 3 xfailed / 1 xpassed（历史快照），coverage 70.48-71.99%（契约不变量 6 项加入，未破坏基线，ratchet ok）。

> ⚠ 本节（§4）为**历史里程碑记录**，下方数字为当时快照；**当前基线以 §0 为准**（1760 passed / 0 xfailed / coverage 79.49%）。

## 4b · 自主进化 · 当前【搁置】与唤醒路径

**为什么搁置**：sloth-loop 当前资源受限、不实时运行；自主进化是「运行驱动」能力，
不跑就没有失败/回测数据输入，开发了引擎也只是空转。判定为负债，主动搁置。

**已完成（保留可复用，不动）**：
- 第1档信号演化：EvolutionSignalBridge（产出候选 signal → `--evolve` → `--rev-candidates --yes` 人工评审纳入）
- **自动评审策略（2026-10-10 新增）**：`evolution_review.py` + `EvolutionLoader.auto_review_candidates` + CLI `--auto-review`；
  确定性三态 accept/reject/defer（fitness_threshold / margin_over_incumbent / max_accept_per_round / dedup / param_bounds）
  + shadow evaluation（以信号池 max(fitness) 为基线）。人工 `--yes` 闸门保留为 override。
- 第2档首块：SelfModifyGate（候选 patch → 沙箱 pytest → 门禁通过才备份提交生产；失败丢弃+入失败模式库）

**唤醒路径（将来要跑时，按序，走蜂群+p9+ooda+模拟测试、先测后写）**：
1. 恢复运行条件（资源/调度），跑通 `--once` / `--loop`。
2. 跑 `--evolve` 产生候选，验证数据进演化链路。
3. P1·接线：把 L2 元循环建议自动生成候选 patch → 过 SelfModifyGate（完整反馈式架构自进化）。
4. P2·阶段C：定时调度 + 无人值守 + 全局审计器 + 架构师重审（7×24 全自主）。
5. P3·全局审计 + 架构师视角整体重审 sloth-loop，输出新版规划。

详细背景：docs/self-evolving-assessment-2026-09-02.md、docs/evolution-tier1-implemented-2026-09-02.md、
docs/self-modify-gate-implemented-2026-09-02.md、`<KB_ROOT>/sloth-loop自主进化后续计划-2026-09-02.md`。

## 5. 唤醒（接手后的 3 步）
1. 读 §0 核对基线；验 GREEN。
2. 读 §1 铁律。
3. 读 §2，按**已触发**的项执行；未触发的 gated 项不要抢跑。


> [2026-10-10 文档整理] 本处引用的 `docs/knowledge-distillation/`、`docs/GRAND-LOOP.md`、`docs/research/` 等研究/过程稿已移至 `sloth-loop\docs\_archive-from-0927\` 备份保留；成品 docs/ 仅保留使用/交付所需文档。
