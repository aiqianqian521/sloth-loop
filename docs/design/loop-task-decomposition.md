# Loop 任务执行模型深度分析

> 生成: 2026-08-19 | 基于: book-to-skill 蒸馏 296 本书的完整实战

---

## 一、DSH 怎么做验证？—— 不验证语义正确性

DSH 没有"验证 1+1=2"的机制。它区分的是"工具崩溃"和"工具执行成功"，不区分"结果对"和"结果错"。

| DSH 机制 | 检查内容 | 层面 |
|---------|---------|:--:|
| `validateJsonSchemaValue` | 返回值是否符合 schema 形状 | 结构 |
| Invariant 检查 | seq 单调、turn 嵌套合法、消息配对 | 中继 |
| Sandbox 策略 | 文件操作权限（可写/只读） | 安全 |
| **语义正确性** | **无任何检查** | — |

DSH 完全依赖**模型自身判断**结果是否正确。工具返回什么，模型就收到什么——模型自己决定要不要重试。

### 对比

| | DSH | Loop 当前 | Loop 理想 |
|---|-----|----------|----------|
| 执行完成检查 | ✅ Schema 校验 | ✅ success_criteria | ✅ |
| 结果正确检查 | ❌ 模型自己判断 | ❌ 无 | 🔨 verification 字段 |
| 失败→改进链路 | ✅ Errors and Fixes (上下文) | ✅ IMPROVEMENTS.md (代码建议) | ✅ |

**DSH 和 Loop 都没有"语义验证"。** DSH 靠模型能力弥补，Loop 计划靠 verification 字段弥补。

---

## 二、book-to-skill 任务完整拆解

### 2.1 用户输入了什么

```
将 <BOOK_ROOT>\booktest 目录下的书籍使用 book-to-skill 进行全面蒸馏
```

这是一句**自然语言任务描述**。Loop 需要把它拆解为可执行的信号+执行+验证。

### 2.2 任务拆解过程

```
用户输入: "蒸馏 <BOOK_ROOT>\booktest 的书籍"
    │
    ▼
┌─────────────────────────────────────────────┐
│ 第 1 层: 任务理解 (Understand)               │
│                                              │
│ - What: 用 book-to-skill 提取书籍文本         │
│ - Why: 建立可检索的知识库                     │
│ - Where: 296 本书, txt/pdf/epub/mobi         │
│ - Success: 每本书产出 skill.md + 验证问题      │
└─────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────┐
│ 第 2 层: 信号拆解 (Observe)                  │
│                                              │
│ 296 本书 → 296 个信号                         │
│ 每个信号:                                     │
│   signal_pattern: "{书名}"                   │
│   market_condition: "{格式}"                 │
│   file_path: "{绝对路径}"                    │
│   expected_result: "success" | "failure"     │
└─────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────┐
│ 第 3 层: 执行拆解 (Act)                      │
│                                              │
│ wrapper.py → subprocess → book-to-skill     │
│   1. 编码检测 + 转换 (txt GBK→UTF-8)         │
│   2. 调用 book-to-skill 提取文本             │
│   3. 检查输出: full_text.txt 存在且 > 100B?   │
│   4. 生成 skill.md (结构化格式)              │
│   5. 生成 verification.json (3-5 验证问题)   │
│   6. 更新 _index.md (知识库索引)             │
└─────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────┐
│ 第 4 层: 校验/审核 (Verify)                  │
│                                              │
│ 门禁 1 (success_criteria):                   │
│   trades_count > 0  → 脚本跑了               │
│                                              │
│ 门禁 2 (wrapper 内置, 非 Loop):               │
│   full_text.txt 存在且 > 100B  → 有产出       │
│   skill.md 已生成         → 格式转换完成      │
│   verification.json 已生成 → 验证问题就绪     │
│   _index.md 已更新        → 知识库可检索      │
│                                              │
│ 门禁 3 (人工审核):                            │
│   浏览 skill.md → 内容完整?                   │
│   读 verification.json → 问题合理?            │
│   抽样验证 3-5 问题 → 答案正确?               │
└─────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────┐
│ 第 5 层: 怎么才算通过 (Close)                │
│                                              │
│ ✅ 单本书通过标准:                            │
│   1. full_text.txt > 0 字节                   │
│   2. skill.md 已生成, 含有效 frontmatter      │
│   3. verification.json 含 ≥3 个问题           │
│   4. 文本无明显乱码                            │
│                                              │
│ ✅ 批量通过标准:                              │
│   1. 296 本书全部处理完毕                     │
│   2. success 率 > 95%                        │
│   3. _index.md 可索引全部成功书籍             │
│   4. failed 清单记录到 outputs/failed/        │
│                                              │
│ ❌ 未通过的处置:                              │
│   → IMPROVEMENTS.md 记录缺陷                  │
│   → 修 book-to-skill 源码                    │
│   → Loop 重跑验证                             │
└─────────────────────────────────────────────┘
```

### 2.3 执行过程中的错误分类

| 错误类型 | 发现方式 | 处置 | Loop 学习 |
|---------|---------|------|----------|
| mobi 格式不支持 | 第 1 轮 Act 失败 | 自动排除 mobi 信号 | +1 failure pattern |
| txt GBK 编码失败 | 第 1-2 轮 Act 失败 | 修 book-to-skill 源码 | +1 IMPROVEMENTS issue |
| 输出检测逻辑缺陷 | wrapper 调试发现 | 修 wrapper 源码 | 手工 |
| 循环 cursor 重置 | 日志观察发现 | 用连续模式 | 手工 |
| budget 限制过早停止 | 日志观察发现 | 修 config | 手工 |

### 2.4 完整执行时间线

```
14:29  Doctor 通过 (Contract probe: 1 trade)
14:30  R1: 3 本书, +1 failure (mobi), +2 success (pdf)
14:31  R2: 3 本书, 编码修复生效
15:02  改进 wrapper: +skill.md +verification +_index
15:11  R1-R10: 编码修复后, txt 全部通过
15:47  bugfix: cursor 不重置, 用连续模式
15:53  bugfix: budget max_rounds 20→200
16:06  100 轮完成: 295/296 本蒸馏成功 (9.2 分钟)
17:01  book-to-skill 源码改进验证通过
```

---

## 三、关键设计经验

### 3.1 Loop 能做什么，不能做什么

| 能 | 不能 |
|----|------|
| 批量执行 296 个任务 | 自己写蒸馏逻辑 |
| 自动分类成功/失败 | 判断"蒸馏质量好不好" |
| 记录失败模式并去重 | 自动修 book-to-skill 源码 |
| 生成 IMPROVEMENTS.md | 应用改进（需人工） |
| 维护知识库索引 | 验证语义正确性（待实现） |

### 3.2 任务的"通过"标准是分层的

```
L1: 执行完了吗?      → success_criteria   (Loop 框架)
L2: 有产出吗?        → wrapper 输出检查     (wrapper 内置)
L3: 产出格式对吗?    → skill.md/verify.json (wrapper 内置)
L4: 内容正确吗?      → 人工抽样验证         (人)
L5: 知识库能用吗?    → _index.md 可检索     (wrapper 内置)
```

Loop 框架只负责 L1。L2-L5 要么在 wrapper 里实现，要么靠人工。**这正是 verification 字段要解决的问题——把 L2-L4 的检查从 wrapper 代码搬到框架配置层，让所有任务都能复用。**

### 3.3 蜂群模式在这个场景的应用

如果 book-to-skill 有 verification 字段：

```yaml
verification:
  mode: "swarm"
  assertions:
    - type: "exists"     # 文件存在
      field: "outputs/success/{book}/full_text.txt"
    - type: "min_size"   # 文件不为空
      field: "outputs/success/{book}/full_text.txt"
      threshold: 100
    - type: "exists"     # skill 格式已生成
      field: "outputs/success/{book}/skill.md"
    - type: "schema"     # verification.json 有效
      field: "outputs/success/{book}/verification.json"
      schema: "verification_schema.json"
```

3 个验证器并行检查，任意一个失败则整本书标记为"验证未通过"→ 写入 IMPROVEMENTS.md。

---

## 四、总结

**用户给 Loop 一个任务时，真正发生的是 5 层拆解**：

```
自然语言任务
  → 信号拆解 (每本书一个信号)
    → 执行拆解 (wrapper + book-to-skill 调用链)
      → 校验拆解 (L1-L5 五层门禁)
        → 通过标准 (单本 + 批量 + 知识库可用)
```

**当前最缺的一环**：校验（Verify）太依赖 wrapper 代码和人工。`verification` 字段的目标是把校验逻辑从"每个任务的 wrapper 里写着"搬到"Loop 框架统一管理"——所有任务共享同一套验证表达方式。