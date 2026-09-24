## Context

现有真实评测通过 `EvaluationBundle` 将每次运行隔离到
`.chartagent/evaluations/<evaluation_id>/`，其中包含批次索引、summary、diagnostics、独立
`sessions.db`、附件和 run artifacts。默认桌面 Gateway 读取的是 canonical data root 下的普通
`sessions.db`，前端也只通过 `/sessions` 读取普通会话，因此评测记录目前没有可见入口。

本设计依赖现有评测 bundle、Gateway 的本地 loopback 边界、run/history/event 结构和前端已有的
图片预览能力。不引入外部服务或新的持久化数据库。

## Goals / Non-Goals

**Goals:**

- 让默认 Figura Gateway 能以只读方式发现和读取本地评测 bundle。
- 在前端提供与普通会话完全分开的评测列表、case 详情、阶段诊断和证据预览。
- 让运行中的评测可以被发现并安全刷新，评测终态后停止轮询。
- 将报告文字与报告图片分开处理，避免把本地 Markdown 路径暴露给浏览器。
- 保持现有评测数据库隔离、普通 session API 兼容和本地敏感数据边界。

**Non-Goals:**

- 不把评测 session 导入普通 session 数据库。
- 不在评测页启动、重试、继续、修改或删除评测。
- 不实现数值准确率、跨模型对比或通用评测评分平台。
- 不向前端暴露原始 SQLite、provider 原始 payload、API key 或任意本地文件。

## Decisions

### 1. 在默认 Gateway 增加只读评测读取层

新增一个独立的评测读取组件，根目录固定来自 Gateway 已解析的 canonical data root，扫描其
`evaluations/` 子目录。它只读取 `evaluation.json`、`manifest.json`、`summary.*`、
`diagnostics/` 和受控运行材料，不复用普通 session 的写入 API。

对外提供四类资源：

```text
GET /api/v1/evaluations
GET /api/v1/evaluations/:evaluation_id
GET /api/v1/evaluations/:evaluation_id/cases/:case_id
GET /api/v1/evaluations/:evaluation_id/cases/:case_id/history
GET /api/v1/evaluations/:evaluation_id/resources/:resource_id
```

选择独立读取层而不是让前端连接评测运行时的临时 Gateway，原因是评测 Gateway 会在 CLI
结束后关闭，且临时端口不适合作为桌面端稳定的数据入口。选择只读 catalog 而不是将评测
复制成普通 session，原因是两者的生命周期、所有权和清理边界不同。

### 2. 使用受控 DTO 和 evaluation-scoped resource reference

列表和详情接口只返回状态、时间、provider/model、case/run 引用、阶段状态和有限错误摘要。
绝对路径、数据库内容和原始 provider 响应不进入 DTO。

图片和报告资源使用服务端生成或登记的资源 ID，例如：

```text
evaluation_id + case_id + resource_id
```

服务端根据资源 ID 映射到输入附件、visual observation、generated artifact 或
`report-assets/` 中的允许文件。资源解析必须经过：

1. evaluation/case/run 归属校验；
2. 根目录约束和路径穿越检查；
3. 文件存在性和内容哈希/元数据校验；
4. 支持的媒体类型和大小限制校验。

前端扩展现有 `PreviewResource` 联合类型，增加评测资源类型；现有 attachment、observation、
candidate 和 artifact 资源保持原有路径和行为不变。

### 3. 评测 run history 使用只读适配，不暴露数据库

case 详情返回批次索引中的 session/run 关联。用户请求历史时间线时，后端通过评测目录下的
SQLite 历史数据读取器获得事件，再映射为已有前端事件协议和评测资源引用。

前端不需要知道评测数据库位置，也不能通过 run ID 调用普通 `/sessions/:id/runs` 路由读取
评测数据库。读取失败时返回明确的 `evaluation_history_unavailable` 类错误，并保留 case
摘要可见。

### 4. 前端使用独立工作区而不是混入 SessionSidebar

桌面端在现有会话工作区之外增加“评测”模式。评测模式拥有自己的列表和详情状态，不复用
普通会话的 active session、composer、删除确认或 run 提交逻辑。

详情布局分为：

- 批次头部：状态、provider/model、时间和 case 数量；
- case 导航：每个 case 的状态和首个失败阶段；
- 诊断主体：阶段时间线、有限错误、run 引用和报告文字；
- 证据区域：输入、拆分、panel、测量和生成结果图片，调用现有交互式预览。

报告 Markdown 只作为有限文本渲染。Markdown 中的图片不直接解析为本地 URL，而是由后端
返回的 evidence resource 列表单独渲染为图片画廊。

### 5. 运行中批次采用有限轮询

进入评测模式时加载一次列表；选中 `running` 批次后以固定的有界间隔刷新批次和当前 case。
状态变为 `completed`、`partial` 或 `blocked` 时停止轮询。用户离开评测模式、Gateway 不可用
或组件卸载时也停止轮询。

不新增 SSE：评测批次的状态变化频率低，轮询足以覆盖本地单用户场景，同时避免再建立一套
与现有 run 事件流不同的实时协议。刷新失败保留最近一次成功快照，并显示可重试的过期状态。

### 6. 兼容当前 bundle 和缺失报告

读取层以现有标准文件为最低可用数据：`evaluation.json`、`summary.json`、
`diagnostics/*.json` 和已有 run artifacts。若发现可选的 `report.md` 与 `report-assets/`，
则额外提供完整报告和图片证据；没有自定义报告时，前端回退到 summary/diagnostic 视图。

这样当前已经生成的评测 bundle 无需迁移即可显示，未来评测是否生成扩展报告也不会阻断基础
诊断浏览。

### 7. 在现有只读运行记录中增加按需的详细展开

现有 `/history` 继续承担轻量级事件时间线的职责；工具调用和工具结果的详细内容不直接塞入
评测列表、case 详情或首次 history 响应，而是在用户展开记录时通过独立的只读 detail 请求加载。
这样保留当前过程视图的响应速度，也避免把完整工具结果误当成普通事件摘要。

详细投影同时参考两类已存在的数据：

- `gateway_run_events` 提供事件顺序、工具调用/结果、`call_id`、状态和视觉观察关联；
- `records` 提供用户输入、模型可见回复和工具消息内容。

两类数据的序号不强行合并，DTO 分别保留 `eventSequence` 与 `recordSequence`，并以时间戳和
`call_id` 建立关联。前端在现有“只读运行记录”中增加折叠详情，而不新增一个顶层 transcript
工作区：

```text
只读运行记录
├── 模型轮次开始
├── 工具调用
│   └── 展开：工具名、call_id、参数
├── 工具结果
│   └── 展开：状态、结构化结果、截断标记
├── 视觉观察
│   └── 通过 resourceId 预览
└── 运行失败
```

详细请求必须继续经过 evaluation/case/run 归属校验。参数和结果使用现有安全投影规则处理：
去除凭据、隐藏 reasoning、绝对路径和二进制内容，限制单条记录与总响应大小，并将已经在
持久化阶段截断的内容原样标记为不可恢复。缺少 `records` 时仍返回事件时间线；缺少某个工具
结果时保留调用记录和失败/不可用状态。

不选择直接开放 SQLite 或将完整 payload 放入 history 的原因是：前者破坏只读资源边界，后者
会让普通时间线变得过重，并混淆 event cursor 与 record cursor。也不重新建立独立 transcript
页面，因为当前运行记录已经是用户理解过程的自然入口。

## Risks / Trade-offs

- **[评测进行中读取 SQLite 时遇到锁或不完整文件]** → 使用只读连接和有界重试；索引尚未可读时返回 `evaluation_not_ready`，列表仍保留批次状态。
- **[报告或运行 artifact 体积过大]** → API 对文本、事件、图片和单次响应设置大小上限；前端按资源单独加载，不把整批原始数据一次性返回。
- **[资源 ID 与普通资源混淆]** → 评测资源引用必须包含 evaluation scope，前端 preview loader 使用独立 resource kind。
- **[恶意或损坏的评测目录]** → 只接受严格格式的 evaluation ID 和 allowlist 文件；单个坏 bundle 不得拖垮 Gateway，也不得暴露解析异常和文件路径。
- **[前端同时维护会话和评测状态增加复杂度]** → 使用明确的工作区模式和独立 client/types，避免把评测分支散落到普通 run 流程。
- **[现有 Markdown 渲染器不支持图片]** → 报告文字和 evidence gallery 分离渲染，图片始终通过受控预览资源加载。
- **[records 与 gateway_run_events 的序号或内容不一致]** → 分别保留两类序号，以 `call_id`、时间戳和可用状态建立软关联；任一来源缺失时降级为另一来源。
- **[详细工具结果造成响应过大]** → 详情按需加载，设置单条和总响应上限，并在前端使用折叠展示。
- **[历史数据已经在持久化阶段截断]** → 不尝试补造内容，向用户显示持久化截断标记；现有可读字段仍正常展示。
- **[详细调试信息扩大敏感数据暴露面]** → 复用安全字段投影，禁止 raw SQLite、provider 私密字段、凭据、绝对路径、隐藏 reasoning 和图片二进制出现在 DTO。

## Migration Plan

1. 增加只读评测读取器和 Gateway API，不修改普通 session 数据库和已有 bundle 文件。
2. 增加前端评测 client、模式切换、列表、详情和资源预览。
3. 用当前 `eval_20260920T024408Z_d4962355` bundle 做手工验证，再用临时 bundle 覆盖空、运行中、完成和部分失败状态。
4. 在现有评测工作台上增加按需运行详情，优先读取当前 bundle 已保存的 events 和 records，不要求历史数据迁移。
5. 保持没有评测目录时的空状态和原有会话工作区行为。
6. 回滚时只移除详细记录 API 与前端展开入口；已有评测目录、普通 session 数据和基础过程时间线无需迁移或删除。
