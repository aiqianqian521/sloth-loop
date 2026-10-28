---
title: "docs/ 文档导航（成品状态）"
author: "sloth-loop（整理）"
url: ""
date: "2026-10-10"
tags: [index, 导航, docs, sloth-loop]
---

# docs/ 文档导航（成品状态）

> 本目录为 **sloth-loop（树懒 Loop）** 的文档区。当前定位：**成品交付 + 观察使用期，暂不开发**。
> 只放"使用/交付这个成品所必需"的文档；研究/知识/外部素材与开发过程稿不在本发布版内
> （原始开发工作区另有备份，不入发布版）。

## 一、上手与使用（按顺序读）

| 文档 | 用途 |
|---|---|
| [sloth-loop-QUICKSTART.md](sloth-loop-QUICKSTART.md) | 5 分钟跑起来：环境自检 / 单轮 OODA / 连续循环 |
| [sloth-loop-USAGE.md](sloth-loop-USAGE.md) | 使用手册：接入真实任务、CLI 全命令、任务接入流程、常见问题 |
| [sloth-loop-DEV-SETUP.md](sloth-loop-DEV-SETUP.md) | 新主机开发环境搭建、跑测试、过提交门禁 |
| [sloth-loop-MIGRATION-RECOVERY.md](sloth-loop-MIGRATION-RECOVERY.md) | 迁移/恢复隔离演练的操作手册与通过条件 |
| [sloth-loop-0927-运行与测试说明.md](sloth-loop-0927-运行与测试说明.md) | 本副本定位说明、运行与测试步骤 |

## 二、项目权威介绍与架构

| 文档 | 用途 |
|---|---|
| [sloth-loop-项目介绍与规划.md](sloth-loop-项目介绍与规划.md) | ⭐ 权威总览入口：全景架构图 + 架构分层 + 任务流程 + 成功判定 + 使用者视角 |
| [sloth-loop-AS-BUILT.md](sloth-loop-AS-BUILT.md) | 唯一 as-built 架构基线：以后扫描/审查先对照本基线 diff |
| [CONTEXT.md](CONTEXT.md) | 领域术语表：Task/Run/Round/Step/Pattern/Rule/Checkpoint/Event 的单一含义 |
| [adr/](adr/) | 架构决策记录（ADR-001 ~ ADR-009） |
| [design/](design/) | 设计文档：任务分解 / 数据架构 / 验证设计 / 演进路线 / WebUI 架构 / [loop-vs-agent-quota-and-boundary.md](design/loop-vs-agent-quota-and-boundary.md) |

## 三、版本、路线与接入规范

| 文档 | 用途 |
|---|---|
| [sloth-loop-CHANGELOG.md](sloth-loop-CHANGELOG.md) | 详细版本与变更说明与生产门禁 |
| [sloth-loop-ROADMAP.md](sloth-loop-ROADMAP.md) | 后续开发进度与唤醒手册：延后项触发条件/待办/执行顺序 |
| [sloth-loop-AI-TEAM-AND-SELF-EVOLUTION.md](sloth-loop-AI-TEAM-AND-SELF-EVOLUTION.md) | 后续扩展（规划，未实现）：AI Team / 蜂群 roster 链 + 自主进化编排层 |
| [sloth-loop-判定外置实践.md](sloth-loop-判定外置实践.md) | 接入补充规范：把「什么算对」写进脚本（真值表 + judge 契约 + 复算/破框） |
| ~~PM框架-接入sloth-loop-流程规范.md~~ | 业务（PM）接入规范 · **本地私有，不随发布**（已 gitignore） |

## 四、发布与质量记录

| 文档 | 用途 |
|---|---|
| [RELEASE.md](RELEASE.md) | 发布与打包规范：干净版本产出、必须包含/排除清单、敏感红线、自检命令 |
| [sloth-loop-0927-regression-and-fixes-2026-09-28.md](sloth-loop-0927-regression-and-fixes-2026-09-28.md) | 2026-09-28 模式三复查的回归问题清单与修复记录 |

## 五、已移出（备份，非成品文档）

以下内容不属于成品运行/使用所需，不在本发布版内（原始开发工作区另有备份）：
- 研究/知识/外部素材：`articles/`、`papers/`、`frameworks/`、`research/`、`deepseek-harness-analysis/`、`deepseek-harness-master/`、`knowledge-distillation/`
- 开发过程稿：DSH 深度对标、C 场景评估、P0/P1/P3 状态与执行日志、开发路线（两版）、破框验证（三份）、自进化补全方案、架构基建规划、图片理解指南、GRAND-LOOP 唤醒指针、GitHub 热门项目开发指南、docs-audit-cleanup

> 如后续要重启开发，需从备份目录按需取回。

## 六、目录纪律

- 只放正式文档；早期快照/过程稿定期归档（见根 `CLAUDE.md` §9）。
- 新增文档前先检索是否已有同主题，能合并就合并（§9.8 单一总账规约）。
