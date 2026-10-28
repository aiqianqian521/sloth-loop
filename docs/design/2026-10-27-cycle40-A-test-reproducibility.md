# cycle-40 A/A2 · 测试结论必须可复现：残留与并发时序都不得决定结果

- 日期：2026-10-27
- 来源：cycle-39「新鲜副本（handoff）验证」登记的残差（干净克隆 79.47% vs 本机 79.48%，差 1 条分支，当时只登记未修）
- 提交：cycle-40 A `74253b4`（+0 用例）／ A2 `7471e41`（+1 用例）／ B（architect-skills）`741eb96` TES-35 + DOC-26

## 1. 取证方式（先驱动，再结论）

1. 重跑基线：干净克隆与本机各跑一遍全量，分数分别为 79.47% / 79.48%，定位到 1 条分支差。
2. 反复跑：**同一条命令**在同一台机器上连跑多次，观察分数。
3. 定位：逐文件 / 逐插件屏蔽，定到冷热不一致的模块与命中点。
4. 反证：清掉残留 / 去掉竞态后重跑，验证分数收敛为单一值。

| 事实 | 修复前 | 修复后 |
|---|---|---|
| 插件草稿目录 `sloth_engine/tests/_tmp_*` | 跨运行残留，`_ensure` 在「已存在 / 缺失」间翻转 | session 级 autouse 夹具逐次清理，每次从同一状态出发 |
| `run_reporter._archive_raw_io` 最后一级回退 | 直读仓库根 `_data`（热机有、干净克隆无） | 抽成可注入的 `_data_root()`，测试指到空临时目录 |
| `AgentRegistry._release` 循环 / if 分支 | 只被线程竞态覆盖（连跑 6 次 4~5 partial） | 新增单线程测试直接驱动三种形状 |
| 登记基线 | 1759 / 79.48%（本机偏现） | 1760 / 79.49%（干净克隆可逐字重现） |

## 2. 病根：结果不由被测系统决定

- **跨运行残留**：测试自己写出的中间产物（插件草稿包）没有被清理，下一次运行读到了上一次的现场——同一份代码在干净机器与热机器上跑出不同结论。
- **环境回退**：生产代码的最后一级回退直读仓库根 `_data`，把「本机碰巧有这个目录」变成了测试输入；干净克隆无此目录，走不同分支。
- **并发时序**：某些分支只在线程竞态下被踩到，于是「覆盖率」取决于调度——不是稳定的观测，而是一场胜负未定的投币。
- 共同病根：登记基线只能是**可复现的观测**，不是一次性读数；「落在容差内」不能掩盖「两次结果不同」。

## 3. 修复

- **A（`74253b4`）**：新建 `sloth_engine/tests/conftest.py`（session 级 autouse 夹具，清理 `_tmp_*`）；`run_reporter` 抽出 `_data_root()`，用例用 `monkeypatch` 把它指到空临时目录。
- **A2（`7471e41`）**：`tests/test_features_and_agents.py` 新增 `test_release_walks_past_a_non_match_and_survives_a_missing_slot`，单线程直接驱动 `_release` 的三种形状。
- **B（`741eb96`）**：`architect-test` 34→35（TES-35）、`architect-docs` 25→26（DOC-26）。

## 4. 证据（实测，逐字一致）

```
# 本机：同一命令连跑两次
pytest tests sloth_engine/tests -q  ->  1760 passed / 0 xfailed / 79.49%  (4424/670)
pytest tests sloth_engine/tests -q  ->  1760 passed / 0 xfailed / 79.49%  (4424/670)

# 干净克隆：空目录
git clone <repo> <fresh>  ->  pytest ...  ->  1760 passed / 79.49%
git -C <fresh> status      ->  仓库树零写入（干净）
```

## 5. 诚实作用域

- 本轮消除的是「测试自身残留 + 并发时序」两类耦合；仓库根 `_data/`、`work_ooda/`、`logs/` 等 gitignore 运行态目录仍会被部分历史测试创建。
- `conftest.py` 自身在「干净」与「热机」下命中不同的单条分支，但 partial 计数相同，不影响总计。
