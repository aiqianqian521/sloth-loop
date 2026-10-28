# corrections/ — Loop 矫正规则库

## 定位

存放从历史测试中提炼的矫正规则。loop 每次执行前读取这些规则，避免重蹈覆辙。

**规则来源**：`<KB_ROOT>/80-量化项目经理/50-测试方法/01-loop学习记录/` 的 3 份纠错记录。

## 文件

| 文件 | 作用 |
|------|------|
| `playbook.json` | 6 条规则定义（人类可读 + 脚本可解析） |
| `pre_check.py` | 前置检查脚本，执行前验证规则 |
| `README.md` | 本文件 |

## 矫正流程

```
                      ┌──────────────────────┐
                      │   loop 执行前          │
                      │   python corrections/ │
                      │   pre_check.py        │
                      └──────────┬───────────┘
                                 │
                    ┌────────────┴────────────┐
                    │ 检查 6 条规则            │
                    │ BLOCK → 阻断执行         │
                    │ WARN  → 提示但允许继续    │
                    └────────────┬────────────┘
                                 │
                    ┌────────────┴────────────┐
                    │ 通过 → 执行 loop         │
                    │ 未通过 → 修→再查→再执行   │
                    └─────────────────────────┘
```

## 命令

```bash
cd <RUNTIME01201>

# 完整检查（loop 执行前）
.venv/Scripts/python.exe sloth_engine/corrections/pre_check.py

# 只检查参数扫描规则
.venv/Scripts/python.exe sloth_engine/corrections/pre_check.py --rule R4 --param-values 5

# 检查五窗口验证
.venv/Scripts/python.exe sloth_engine/corrections/pre_check.py --rule R5 --windows 5 --std 3.5

# 检查 OODA 完整性
.venv/Scripts/python.exe sloth_engine/corrections/pre_check.py --work-dir work_ooda/20260811-my-task
```

## 规则升级

新发现的矫正规则追加到 `playbook.json` 的 `rules` 数组：

```json
{
  "id": "R7",
  "name": "规则名称",
  "check": "on_task_start|on_round_start|on_round_end",
  "severity": "block|warn",
  "trigger": "触发条件",
  "action": "执行动作",
  "error_case": "之前怎么踩坑的"
}
```

## 与知识库的关系

`corrections/playbook.json` 是`<KB_ROOT>/qupm-loop/04-loop-learning-playbook.md` 的**机器可读版本**。两者内容同步——知识库版本供人阅读，corrections 版本供脚本执行。更新时两边都改。