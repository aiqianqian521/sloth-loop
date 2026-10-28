# Loop 任务完整拆解模型

> 基于: 用户原始任务"蒸馏 <BOOK_ROOT>\booktest 296本书"
> 方法论: 5W1H + OODA + 两门禁验证 + 蜂群模式
> 日期: 2026-08-19

---

## 一、原始输入

```
将 <BOOK_ROOT>\booktest 目录下的书籍使用 book-to-skill 进行全面蒸馏，放入 Loop 场景来实现。
需要的不是"反复跑同一个检查"，而是驱动脚本从写出来到跑通的过程。
每次 import 失败、编码错误、路径问题被自动捕获记录，下次遇到同类错误直接匹配已有模式。

约束:
  1. 蒸馏的书籍是不是 skill 格式？
  2. 每本书蒸馏后列出 3-5 个验证问题
  3. CIS 书籍需要知识库入口永久调用
  4. 目录结构合理
```

---

## 二、5W1H 发散扫描

### 2.1 Who — 谁受影响、谁决策？

| 维度 | 已知 | 模糊点 | 探索问题 |
|------|------|--------|---------|
| 使用者 | <owner>（Loop 开发者） | 以后是否团队使用？ | 知识库入口设计要考虑多用户吗？ |
| 决策者 | 本人 | — | — |
| 依赖方 | book-to-skill 维护者（virgiliojr94） | 改进是否要提 PR？ | 本地改还是回馈上游？ |

### 2.2 What — 产生什么、边界在哪？

| 维度 | 已知 | 模糊点 | 探索问题 |
|------|------|--------|---------|
| 核心产出 | 每本书: full_text + skill.md + verification.json | skill.md 格式标准由谁定义？ | 需要统一的 skill 模板吗？ |
| 批量产出 | _index.md 知识库索引 | 索引要支持分类/搜索吗？ | 按格式分？按主题分？ |
| 范围边界 | 296 本书全量处理 | pdf 中的图片/表格怎么处理？ | 需不需要 OCR？ |
| 不在范围 | 不修改 book-to-skill 核心逻辑（wrapper 层补偿） | — | — |

### 2.3 Where — 哪个系统/模块？

| 维度 | 已知 | 模糊点 | 探索问题 |
|------|------|--------|---------|
| 输入位置 | `<BOOK_ROOT>\booktest\{pdf,txt}\` | 混在根目录的 epub/mobi | 要不要先整理目录？ |
| Loop 项目位置 | `projects/book-distill/` | — | — |
| 输出位置 | `outputs/success/{书名}/` | 失败的放哪？ | outputs/failed/ |
| book-to-skill 源码 | `<workspace>\master\book-to-skill-master\` | — | — |

### 2.4 When — 时间约束、依赖顺序？

| 维度 | 已知 | 模糊点 | 探索问题 |
|------|------|--------|---------|
| 执行时间 | 296 本书 ~10 分钟 | 大文件 pdf 可能超时 | 单书 timeout 设多少？ |
| 依赖顺序 | 先修 book-to-skill 编码问题 → 再批量蒸馏 | — | — |
| 验证时机 | 每本书蒸馏后立即验证 | 人工抽验什么时候做？ | 批量完成后？ |

### 2.5 Why — 为什么现在解决？

| 维度 | 已知 | 模糊点 | 探索问题 |
|------|------|--------|---------|
| 直接原因 | 有 296 本书需要结构化知识库 | — | — |
| 根本原因 | 人不可能手动蒸馏 296 本书 | — | — |
| 验证价值 | 证明 Loop 能从"跑不通"驱动到"跑通" | — | — |

### 2.6 How — 可行路径？

| 维度 | 已知 | 模糊点 | 探索问题 |
|------|------|--------|---------|
| 方案 A | wrapper 调用 book-to-skill → Loop 驱动 | 已实现 | — |
| 方案 B | 直接改 book-to-skill 命令行接口 | 需要上游接受 | 要不要提 PR？ |

---

## 三、任务拆解（从自然语言到可执行信号）

### 3.1 第 0 层：自然语言 → 理解

```
原始输入: "蒸馏 <BOOK_ROOT>\booktest 书籍"
     │
     ▼  5W1H 扫描
┌──────────────────────────────────────┐
│ Understand:                          │
│   What: 批量提取 296 本书的文本内容    │
│   How:  book-to-skill → Loop wrapper  │
│   Goal: 建立可检索的知识库             │
│   Risk: 中文编码、格式不支持、输出格式  │
└──────────────────────────────────────┘
```

### 3.2 第 1 层：任务 → 信号

```
296 本书 → 296 个信号

单本书信号结构:
{
  "signal_pattern": "CIS_Debian_Linux_12_Benchmark",  ← 唯一标识
  "market_condition": "pdf",                           ← 格式分类
  "file_path": "<BOOK_ROOT>/booktest/pdf/CIS_...pdf",     ← 物理路径
  "expected_result": "success"                         ← 预期结果（可选）
}
```

**信号扫描脚本**: 遍历 `<BOOK_ROOT>\booktest` 所有子目录，对每个文件生成一条信号记录

### 3.3 第 2 层：信号 → 执行

```
Loop 每轮取 3 个信号 → wrapper.py
                           │
                           ▼
              ┌────────────────────────┐
              │ 1. 编码检测 & 转换      │  ← txt GBK→UTF-8
              │ 2. subprocess 调用      │
              │    Python 3.11 +        │
              │    book_to_skill 1.4     │
              │ 3. 检查输出文件          │  ← full_text.txt > 100B?
              │ 4. 生成 skill.md        │  ← 结构化 skill 格式
              │ 5. 生成 verification     │  ← 3-5 验证问题
              │ 6. 更新 _index.md       │  ← 知识库索引
              └────────────────────────┘
                           │
                           ▼
              返回 {pnl: +1/-1, meta: {...}}
```

### 3.4 第 3 层：执行 → 校验

```
         ┌─────────────────────────────────────┐
         │         五层校验模型                  │
         ├─────┬───────────────────────────────┤
         │ L1  │ 执行完成吗？                    │
         │     │ success_criteria: trades>0      │
         │     │ 由 Loop 框架强制执行             │
         ├─────┼───────────────────────────────┤
         │ L2  │ 有产出吗？                      │
         │     │ full_text.txt 存在且 > 100B     │
         │     │ 由 wrapper 内置检查              │
         ├─────┼───────────────────────────────┤
         │ L3  │ 产出格式对吗？                   │
         │     │ skill.md 有效 frontmatter       │
         │     │ verification.json ≥ 3 问题      │
         │     │ 由 wrapper 内置检查              │
         ├─────┼───────────────────────────────┤
         │ L4  │ 内容正确吗？                     │
         │     │ 编码正确（无乱码）               │
         │     │ 章节检测合理                     │
         │     │ 当前: 人工抽样                   │
         │     │ 理想: verification assertions   │
         ├─────┼───────────────────────────────┤
         │ L5  │ 知识库能用吗？                   │
         │     │ _index.md 可检索                │
         │     │ skill.md 可被 AI 加载           │
         │     │ 由 wrapper 内置检查              │
         └─────┴───────────────────────────────┘
```

### 3.5 第 4 层：校验 → 通过标准

```
单本书通过:
  ✅ L1: trades_count > 0（Loop 框架层）
  ✅ L2: full_text.txt 存在（文件系统层）
  ✅ L3: skill.md + verification.json 已生成（格式层）
  ❌ L4: 内容有无乱码、章节是否合理 → 人工或待 verification 断言

批量通过:
  ✅ success_rate > 95%（当前: 295/296 = 99.7%）
  ✅ _index.md 可索引全部成功书籍
  ✅ failed 书籍有明确失败原因记录

知识库通过:
  ✅ 打开 _index.md 能看到完整目录
  ✅ 点击任意 skill.md 可被 Claude Code 直接加载
  ✅ verification.json 可作为质量检查参考
```

---

## 四、结果正确性检查推理（关键）

### 4.1 问题: 1+1=3 怎么防止？

场景: book-to-skill 蒸馏了一本书，产出了 full_text.txt，但内容是错的（乱码/缺页/章节错位）。Loop 当前会判定为"成功"。

### 4.2 正确性检查的三个维度

```
┌──────────────────────────────────────────────────┐
│              结果正确性 =                          │
│                                                  │
│  结构完整 ✅         内容完整 ⚠️        语义正确 ❌  │
│  (文件存在>100B)     (章节数合理)      (对错判断)   │
│  Loop L1-L2 能做     Loop L3 能做      Loop 做不了  │
│  wrapper 已实现       wrapper 部分做    需要 verification│
└──────────────────────────────────────────────────┘
```

### 4.3 每一层能检查什么、不能检查什么

| 检查层 | 能回答的问题 | 不能回答的问题 |
|--------|------------|-------------|
| L1 执行完成 | "脚本跑了吗？" | "跑出正确结果了吗？" |
| L2 文件存在 | "有输出吗？" | "输出内容完整吗？" |
| L3 格式正确 | "skill.md 格式合法吗？" | "skill.md 内容对吗？" |
| L4 内容正确 | "有没有明显乱码？" | "这本书真的讲了这些吗？" |
| L5 知识库可用 | "索引能查到吗？" | "查到的内容有用吗？" |

### 4.4 L4 内容正确性的现阶段方案

对 book-to-skill 来说，"内容正确"可以近似为:

```
规则 1: 编码健康检查
  if text contains "�" > 1% → 标记为疑似乱码 → FAIL

规则 2: 章节合理性
  if chapters_detected == 0 and pages > 50 → 可能解析失败 → WARN

规则 3: 字数合理性
  if words < file_size_MB * 1000 → 可能提取不完整 → WARN

规则 4: 格式匹配检查
  if format == "pdf" and "pdftotext" not in extraction_method → 提取路径可疑 → WARN
```

这些规则可以放到 `verification.assertions` 中，让 Loop 框架统一执行而非每个 wrapper 自己写。

### 4.5 最终答案: 什么才算"通过"

```
任务 "蒸馏 <BOOK_ROOT>\booktest 296本书" 的通过标准:

必须满足 (硬门禁):
  ✅ 296 本书全部处理完毕
  ✅ success_rate > 95%
  ✅ _index.md 可检索全部成功书籍
  ✅ 失败书籍有明确原因记录（写入 outputs/failed/）

应该满足 (软门禁):
  ✅ 每本成功书籍有 skill.md (当前: 290/295)
  ✅ 每本成功书籍有 verification.json ≥ 3 问题 (当前: 290/295)
  ✅ 文本无明显乱码（编码修复后已验证）
  ✅ book-to-skill 源码缺陷已修复（parsers/text.py 编码链）

不要求 (超出范围):
  ❌ 人工验证每本书的内容正确性 (296 本做不到)
  ❌ skill 内容被实际 AI 查询验证过
```

---

## 五、实际执行 vs 理论模型对比

| 步骤 | 理论模型 | 实际执行 | 差距 |
|------|---------|---------|------|
| 任务理解 | OODA Understand | 手动分析 + 5W1H | Loop 自己不做 5W1H |
| 信号拆解 | Observe → 生成信号 | Python 脚本扫描文件系统 | 信号生成靠手工脚本 |
| 执行调度 | Act → batch_size=3 × 100 轮 | 连续模式 cursor 轮转 | batch_size 被默认覆盖 |
| 错误捕获 | Learn → patterns.db | 确实捕获了 mobi/编码错误 | 模式分类粒度粗 |
| 缺陷报告 | _produce_defect_report() | IMPROVEMENTS.md 已生成 | 证据字段有乱码 |
| 验证 | Verify → success_criteria | 只验证了 trades_count>0 | 缺 L2-L4 验证 |
| 闭环 | 改进→重跑→确认 | 手动修编码→重跑通过 | 改进是手动的 |

**结论**: 理论模型覆盖了全链路，但 Loop 框架当前只实现了 L1（执行完成），L2-L4 由 wrapper 补偿，L5 基本到位。verification 字段是填补 L2-L4 缺口的下一步。

---

## 六、OODA 执行流程映射

用户描述的流程: "接收用户问题 → 提问 → 确保理解问题并知道用户目的 → 开始执行 → 最终确认任务完成"

这正是 Loop 的 OODA 7 步循环：

| 用户说的 | OODA 步骤 | Loop 当前实现 | 以 book-distill 为例 |
|---------|----------|-------------|-------------------|
| 接收用户问题 | **U** Understand | `_ensure_understand()` 读 00-purpose.md | "蒸馏 <BOOK_ROOT>\booktest 296本书" |
| 提问 | **Q** Understand & Question | U&Q 交互确认（可选） | "工作区在哪？验证标准是什么？" |
| 确保理解 + 知道目的 | **O1** Observe + **O2** Orient | 加载模式库 → 诊断状态 | 扫描 296 本书 → 分类 pdf/txt/mobi |
| 开始执行 | **D** Decide + **A** Act | 选择策略 → 执行任务 | 每轮 3 本 → wrapper 蒸馏 |
| 确认任务完成 | **V** Verify + **L** Learn + **C** Close | 对比 success_criteria → 记录 → 闭环 | 295/296 成功 → 生成 IMPROVEMENTS |

```
用户输入任务
    │
    ▼
[U] Understand ─── 我理解你要蒸馏 296 本书，对吗？
    │
    ▼
[Q] Question ───── 编码问题怎么处理？输出放哪里？验证标准？
    │
    ▼
[O1] Observe ───── 扫描目录: 284 txt, 10 pdf, 2 epub/mobi
[O2] Orient ────── 核心风险: 中文编码 + mobi 格式
    │
    ▼
[D] Decide ────── 先修编码 → wrapper + book-to-skill → 批量蒸馏
[A] Act ───────── 100 轮 × 3 本 = 295/296 成功
    │
    ▼
[V] Verify ────── success_rate = 99.7% ✓
[L] Learn ─────── +1 failure (mobi) +2 success patterns
[C] Close ─────── 知识库可用，IMPROVEMENTS.md 已生成
```

**当前最弱的一环**：Q（提问）和 V（验证）。Loop 的 Understand 步骤只是读 00-purpose.md 模板，不会主动提问澄清模糊点。Verify 只检查 success_criteria 三元组，不做语义验证。

---

## 七、改进路线图

| 优先级 | 改进项 | 目标 |
|:--:|------|------|
| P0 | `verification.assertions` 字段实现 | L2-L3 从 wrapper 搬到框架 |
| P1 | 编码健康检查规则 | L4 自动判断乱码 |
| P2 | 信号生成自动化 | `loop scan --dir <BOOK_ROOT>\booktest` |
| P3 | 5W1H 引导式任务创建 | `loop init --task "蒸馏书籍"` 交互式引导 |