# sloth-loop WebUI 架构设计

> 生成: 2026-10-09 · 既定模式 · 大任务循环
> 参考: DSH apps/web + architect-frontend + architect-plugin + architect-data
> 原则: 一切皆插件 / 前后端分离 / 面板即UI插件 / 零运行时构建

---

## 一、定位

sloth-loop 是一个**独立的 Agent 编排框架**，不依附于任何具体业务项目。

WebUI 的目标：
- 让用户**可视化监控**所有挂载任务的运行状态
- 让用户**操作**规则审批、插件管理、配置切换
- **不替代 CLI**——CLI 是主要操作入口，WebUI 是观测+审批面板

```
sloth-loop CLI (主操作入口)
    ├── orchestrator.py --once / --resume / --loop
    └── webui.py (观测+审批面板)
         ├── /api/* REST (FastAPI)
         └── static/ (vanilla JS, 零构建)
```

---

## 二、架构分层 (对标 architect-frontend FRO-08 六层嵌套)

```
┌────────────────────────────────────────────┐
│ Layer 1: 总览 Dashboard                    │
│  所有任务运行状态 · 核心指标 · 告警摘要      │
├────────────────────────────────────────────┤
│ Layer 2: 项目 Overview                     │
│  单个项目的任务列表 · PatternStore · 进度   │
├────────────────────────────────────────────┤
│ Layer 3: 任务 Run                          │
│  OODA循环 · 信号池 · 回合历史 · 实时事件    │
├────────────────────────────────────────────┤
│ Layer 4: 插件管理                          │
│  Roster · Manifest · 启用/禁用 · 插件市场   │
├────────────────────────────────────────────┤
│ Layer 5: Evolution 进化                    │
│  排除规则 · MentalModels · 压缩模式 · 趋势  │
├────────────────────────────────────────────┤
│ Layer 6: Settings 设置                     │
│  配置 · Profile · Token · Auth             │
└────────────────────────────────────────────┘
```

每层对应一个 hash 路由页面，支持深链直达。

---

## 三、路由设计 (对标 FRO-09 hash路由)

```
#/                          → Layer 1 总览
#/project/<name>            → Layer 2 项目
#/project/<name>/run/<ts>   → Layer 3 任务运行详情
#/plugins                   → Layer 4 插件管理
#/plugins/<id>              → Layer 4 插件详情
#/evolution                 → Layer 5 进化面板
#/settings                  → Layer 6 设置
```

---

## 四、数据流 (对标 FRO-0A 前后端分离)

```
┌──────────────────────────────────────────────────────┐
│ 前端 (static/index.html + vanilla JS)                │
│                                                      │
│  ┌─────────┐  ┌──────────┐  ┌───────────────────┐  │
│  │ Router  │  │ ECharts  │  │ Panel Registry    │  │
│  │ (hash)  │  │ (懒加载) │  │ (ui plugin slots) │  │
│  └────┬────┘  └────┬─────┘  └────────┬──────────┘  │
│       │            │                 │               │
│       └────────────┼─────────────────┘               │
│                    │ fetch() only                    │
└────────────────────┼──────────────────────────────────┘
                     │ HTTP REST + Bearer Token
┌────────────────────┼──────────────────────────────────┐
│ 后端 (webui.py FastAPI)                               │
│                                                      │
│  GET  /api/dashboard    总览摘要                     │
│  GET  /api/projects     项目列表                     │
│  GET  /api/project/<n>  项目详情+runs                │
│  GET  /api/runs         运行历史                     │
│  GET  /api/run/<ts>     单次运行详情                 │
│  GET  /api/rounds       OODA轮次                     │
│  GET  /api/failures     失败模式                     │
│  GET  /api/rules        排除规则                     │
│  GET  /api/plugins      插件列表+状态                 │
│  GET  /api/evolution    进化状态                     │
│  POST /api/rules/<id>/approve  审批规则              │
│  POST /api/rules/<id>/reject   拒绝规则              │
│  POST /api/plugins/<id>/toggle 启停插件              │
│                                                      │
│  数据源: PatternStore(SQLite) + EventLog(JSONL)      │
│          + PluginRegistry + EvolutionBridge          │
└──────────────────────────────────────────────────────┘
```

---

## 五、面板即UI插件 (对标 architect-plugin PLU-01~08)

sloth-loop 已有 `ui` 类型插件（dsh-context / dsh-genui），WebUI 的面板应该走同样的扩展机制：

### 5.1 UI 面板插件的 Manifest 扩展

```json
{
  "id": "panel-dashboard-evolution",
  "type": "ui",
  "entry": "entry.py",
  "extension_points": ["panel"],
  "panel": {
    "title": "Evolution",
    "route": "/evolution",
    "icon": "chart-line",
    "layer": 5,
    "api_endpoints": ["/api/evolution"],
    "component": "templates/evolution-panel.html"
  }
}
```

### 5.2 面板注册流程

```
插件加载 → manifest扫描 → panel扩展点发现
  → webui.py 注册 /api/panel/<id>/data
  → 前端 PanelRegistry 发现 → 渲染到对应 layer
```

### 5.3 核心面板清单

| 面板 | 类型 | Layer | 数据源 | 说明 |
|------|------|:---:|--------|------|
| Dashboard | core | 1 | PatternStore.summary | 总览：任务数/失败数/通过率/进化趋势 |
| ProjectList | core | 2 | projects/ 扫描 | 项目卡片列表 |
| ProjectDetail | core | 2 | project_loader | 单项目 runs+config |
| RunDetail | core | 3 | run_state + event_log | OODA 7步可视化+事件时间线 |
| SignalPool | core | 3 | signal_pool | 信号池状态 |
| PluginManager | core | 4 | PluginRegistry | 插件启停/详情 |
| EvolutionPanel | core | 5 | evolution_bridge | 排除规则/合并/趋势 |
| SettingsPanel | core | 6 | config.yaml | 配置编辑 |
| ContextObserver | plugin | 3 | event_log | 已有 dsh-context |
| TextDashboard | plugin | 1 | render_panel | 已有 dsh-genui |

---

## 六、前端技术选型 (对标 FRO-05/0B/0C)

| 决策 | 选择 | 理由 |
|------|------|------|
| 框架 | **vanilla JS** | sloth-loop 零运行时依赖，不引入 npm/webpack/vite |
| 路由 | **hash router** | 纯前端，支持刷新+分享还原视图 |
| 图表 | **ECharts CDN** | 懒加载，图表池按需实例化，30s刷新 |
| 虚拟滚动 | **原生 IntersectionObserver** | 大表不卡，无需 Virtuoso |
| 状态管理 | **URL state + fetch cache** | 不引入全局 store（FRO-02按生命周期分层） |
| 三态 | **skeleton/empty/error** | 接口抖动不白屏 (FRO-0C) |
| Auth | **Bearer Token** | 已有机制，webui.py 已实现 |
| 主题 | **CSS Variables 单源** | FRO-07 单源真相 |

---

## 七、开发优先级

### P0 (本周) — 核心路由+面板骨架
1. 前端 hash router + 六层路由骨架
2. Dashboard 总览面板（/api/dashboard 已有）
3. Plugin 列表面板（PluginRegistry 已有）
4. 三态兜底（skeleton/empty/error）

### P1 (下周) — 数据面板+交互
5. Project 详情面板
6. Run 详情面板（OODA 7步可视化）
7. Evolution 面板（排除规则/趋势图）
8. 规则审批交互（approve/reject 已有 API）
9. ECharts 图表集成

### P2 (远期) — 扩展+运维
10. Panel 插件市场（ui-slots 机制）
11. WebSocket 实时推送（事件流）
12. Settings 配置编辑
13. Profile 切换

---

## 八、与 DSH WebUI 的关键差异

| 维度 | DSH WebUI | sloth-loop WebUI |
|------|-----------|----------------|
| 定位 | Coding Agent IDE | 编排框架观测面板 |
| 框架 | 50+ ui-* TS包 + Web Components | 1个 webui.py + vanilla JS |
| 打包 | Vite + npm | 零构建，直接 serve |
| 扩展 | 每个面板是独立 npm 包 | 面板是 ui 类型插件 |
| 复杂度 | 2056 TS文件 | ~15 API + ~5 HTML模板 |
| 插件市场 | dsh-market community | roster + PluginRegistry |

**不抄 DSH UI 的原因**: sloth-loop 不需要 Coding Agent IDE。它需要的是轻量观测面板——能看任务状态、审批规则、管理插件即可。

---

## 九、破框审计检查单 (architect-frontend contract)

| ID | 规则 | 状态 |
|----|------|:---:|
| FRO-01 | 关键用户流程+加载/空/错误/权限四态 | ✅ 设计已覆盖 |
| FRO-02 | 状态按服务器/URL/表单/UI生命周期分层 | ✅ URL state + fetch cache |
| FRO-03 | 组件边界避免隐式依赖 | ✅ 纯 fetch API，无全局 store |
| FRO-04 | 键盘/焦点/语义HTML/对比度/屏幕阅读器 | ⚠️ P2 补充 |
| FRO-05 | LCP/INP/CLS/bundle size/运行时错误 | ✅ 零构建=零bundle |
| FRO-06 | 组件契约测试+关键旅程E2E | ⚠️ P2 补充 |
| FRO-07 | 设计token/主题/版本单源 | ✅ CSS Variables |
| FRO-08 | 数据按六层分层 | ✅ 六层嵌套路由 |
| FRO-09 | hash路由深链直达 | ✅ #/project/<n>/run/<ts> |
| FRO-0A | 前后端分离REST+token鉴权 | ✅ 已有 |
| FRO-0B | 大表虚拟滚动/图表池懒加载 | ⚠️ P1 实现 |
| FRO-0C | 空/加载/错误三态 | ⚠️ P0 实现 |
| FRO-0D | 禁止未来数据 | ✅ N/A (非交易系统) |

| ID | 规则 (architect-plugin) | 状态 |
|----|------------------------|:---:|
| PLU-01 | 新增第三方能力核心改动=0 | ✅ Panel扩展走manifest |
| PLU-02 | Manifest契约 | ✅ plugin_manifest 已有 |
| PLU-03 | 注册vs物化分离 | ✅ lazy=true 机制 |
| PLU-04 | 扩展点明确稳定 | ✅ panel slot 定义 |
| PLU-05 | 插件隔离/纯度门 | ✅ 跨插件import扫描 |
| PLU-06 | 生命周期: 挂载/激活/卸载/热重载 | ✅ PluginHost |
| PLU-07 | 失败隔离不阻塞全局 | ✅ try/except per plugin |
| PLU-08 | Roster配置化mount决策 | ✅ plugin_config.yaml |

## 十、后续进化方向

当 sloth-loop WebUI 的面板超过 5 个时，启动 **Panel Market** 机制：
- 面板从 core 迁移到独立 ui 插件包
- 类似 DSH 的 ui-slots 扩展点
- 第三方可开发面板插件放入 plugins/ui/
- PluginRegistry 自动发现+前端动态渲染

在此之前，保持 core 内置面板（P0/P1 清单），避免过度设计。

---

*基于 architect-frontend + architect-plugin + architect-data 三向校验*
*既定模式 · 破框通过 · 可落地*
