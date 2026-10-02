# Web：Local Gateway 与 React Figura

> 更新日期：2026-10-02。[返回系统总览](../figura-implementation-overview.md)。范围：当前 `src/figura/gateway/`、`src/figura/bootstrap.py`、`frontend/src/api/figura/` 与 `frontend/src/FiguraApp.tsx` 实现；附件和 Panel 源模型归[Sources](sources.md)，Agent 派生清单归[Agent](agent.md)，本篇拥有 Web DTO 与公开路由合同。主规格见 [Gateway](../../openspec/figura/openspec/specs/figura-web-gateway/spec.md) 和 [React Client](../../openspec/figura/openspec/specs/figura-web-client/spec.md)。`connect-figura-web-frontend`、`add-figura-panel-image-tools`、`add-figura-cartesian-chart-measurements`、`add-figura-scoped-chart-observation`、`add-figura-chart-rendering` 与模块结构调整 change 均已归档。

## 1. 职责与边界

Local Gateway 是 Python 进程内的 HTTP/SSE 边界，不是第二套 Session 或 Run 存储。`bootstrap.py` 负责组装并注入 Runtime、Sources、Agent、Provider 与 Tools；`gateway/application.py` 负责 HTTP 请求处理和安全投影。它把 JSON/图片请求交给 Runtime、Sources、Agent 图像读取器与 ProviderFactory，再把有限的 Session、Run、事件、附件、已提交 Panel、ChartFigure 渲染摘要和 Run 工具时间线 DTO 返回给浏览器。Run 创建持久化后由有界 Dispatcher 异步提交给既有 Agent；Gateway handler 不直接请求模型。当前工作树 Gateway Registry 为 `figura-web-v6`，已支持 `render_chart_figure`；PNG 和成功 OCR/测量观察图通过只读内容路由懒加载，测量与渲染仍没有独立前端操作 API。工具时间线是基于 Runtime 已提交 ToolCall、Attempt、Result 事实构造的只读投影，不增加持久表或执行控制入口。

React Figura mode 通过 `FiguraClient` 负责 HTTP/SSE，再由 `FiguraWorkspaceApi` 映射到现有工作区协议和共享组件。React 组件不直接访问 Gateway；ChartAgent 与 Mock client 模式仍由其原有客户端提供。此边界目前是本地网页接入，没有 Tauri shell 接入。

```mermaid
flowchart LR
    UI[React Figura mode] -->|FiguraClient| Adapter[FiguraWorkspaceApi]
    Adapter -->|HTTP JSON / SSE| Gateway[Loopback Gateway]
    Gateway -->|Session / Run 读取、创建与整会话删除| Runtime[RunCoordinator / Store]
    Gateway -->|附件操作与图像内容| Sources[Sources services]
    Gateway -->|已提交 Panel 列表| ImageState[Agent RunExecutionState]
    Gateway -->|Panel / ChartFigure PNG 内容| Sources
    Gateway -->|工具调用事实与派生资源| Timeline[只读工具时间线投影]
    Timeline -->|安全摘要 / 详情| Gateway
    Timeline -->|成功 OCR / 测量的观察图引用| ImageReader[RunExecutionImageReader]
    ImageReader -->|经授权读取| Sources
    ImageState -->|Panel / ChartFigure 渲染事实与校验| Sources
    Gateway --> Deletion[FiguraSessionDeletion]
    Deletion -->|同一事务删除行| Runtime
    Deletion -->|暂存 / 恢复 / 清除文件| Sources
    Gateway -->|配置可用性检查| Provider[ProviderFactory]
    Gateway -->|持久 Run 的异步提交| Dispatcher[有界 RunDispatcher]
    Dispatcher -->|execute(session_id, run_id)| Agent[AgentExecutor]
    Agent --> Runtime
    Sources -->|Attachment / Panel metadata| RuntimeDB[(共享 Figura SQLite)]
    Sources -->|私有附件、独立 Panel 与 ChartFigure PNG| Files[(私有文件)]
    Runtime -->|Session / Run / 执行事实| RuntimeDB
    Runtime -->|Session snapshot / RunState / events| Gateway
    Provider -->|ProviderAvailability| Gateway
```

Gateway 只绑定 loopback，并验证浏览器 Origin 白名单。启动时进程环境优先于项目 `.env`；health 只检查本地 Provider 配置，不发送 Provider 请求。敏感配置、原始 endpoint、文件路径、continuation 和完整执行 payload 不进入公开 DTO；工具详情只返回 allowlist 安全摘要。

## 2. 请求与返回流转

1. **启动本地网页栈**：`npm run dev:figura` 启动 Python Gateway 与 Vite；默认 Gateway 端口为 `8766`，Vite 为 `1421`。Launcher 等待 Figura health 成功后再启动网页，并在退出或启动失败时清理它启动的进程组。只有 Gateway 子进程读取项目 `.env`；Vite 只收到 Figura mode 和 Gateway URL 等前端配置，不继承 `FIGURA_*` 或凭据 endpoint/key 环境值。
2. **读取 Provider 与 Session**：`GET /health` 返回三个 allowlist Provider 的配置可用性及固定 model ID，不探测远端网络。Session 列表使用 Runtime 的 SQL 聚合；创建 Session 后，网页读取 Session 详情以取得消息、附件及 Run 投影。Web DTO 字段见[第 4 节](#4-web-dto-字段)，Runtime 的聚合读取值见[Run Runtime](runtime.md#4-完整模型字段)。
3. **上传、管理及读取分区图像**：浏览器向 Session attachment endpoint 上传原始字节并通过 query 传文件名；Gateway 委托 Sources 做媒体内容验证、大小限制、文件名净化和私有存储。浏览器只能在所属 Session 中列出、预览或删除；已被 Run 引用的附件不能删除。Run 输入保留有序附件 ID，图片字节不进入 Runtime 输入或 Web DTO。Panel 使用独立 Session-scoped list/content 路由；Agent 的 RunExecutionState 根据已提交成功分割结果筛选列表，Sources 提供 metadata 和 PNG 内容；图像读取返回 `image/png` 且不缓存。
4. **创建 Run**：浏览器提交 `text`、有序 `attachmentIds`、allowlist `providerId` 和 `Idempotency-Key`。浏览器不提交 model ID。Gateway 从 Provider allowlist 解析固定 model，Runtime 原子写入 Run、RunInput、初始 Checkpoint、幂等映射和创建事件后，Gateway 将其交给有界 Dispatcher 并返回 `202` Run handle。一个 Session 同时最多一个 running Run；同 key 同 payload 重放返回原 Run，key 冲突或 Session 已有不同 running Run 时返回安全错误。若本地 Dispatcher 暂时满，Run 可能已持久化而请求返回有界 `503`；使用原幂等键重试会复用该 Run 并尝试调度。
5. **执行与恢复**：Dispatcher 当前默认最多 3 个并发 worker、另有 8 个排队槽。Agent 从 Runtime checkpoint 执行，不确定的 Provider attempt 不自动重发，未解决的工具 attempt 不自动 replay。Gateway 启动时按 Session ID 和 Run ordinal 列出所有持久 running Run，再走相同 Dispatcher/Agent 路径；投影只有在 Run 仍 running 且下一动作要求 tool-attempt reconciliation 时才显示 `needs_reconciliation`。
6. **读取历史、工具时间线、图片产物和事件**：Session detail 从一个 Runtime SQLite 读快照生成消息、附件和 Run 投影；前端另调 Panel list route，按 `runId` 将 Panels 放到对应 Run 下，浏览器通过 Session-scoped content URL 懒加载 Panel PNG。Run DTO/history 的 `chartRenders` 只含成功提交的渲染元数据；Gallery 将所有成功预览按渲染所在 Run 分组，并通过 Session/Run/render-call-scoped 内容 URL 懒加载 PNG；每张均能打开大图并下载。展开 Run 时，前端读取时间线列表；展开某一步时再读安全详情，成功 OCR/测量项可通过受授权 URL 查看观察图。Gateway 核对所属 Session、已提交结果和来源引用后才返回 `image/png`。Run history 按 `afterSequence` 返回更大的事件序号；SSE 先重放游标后的持久事件，再跟随后续事件，并以 `runId:sequence` 作为事件 ID。`run_progress` 只携带 Checkpoint revision，前端收到后重新读取时间线。终态事件送达后关闭流。前端 RunController 负责历史补读、游标合并和终态收敛；终态后重新加载 Session detail 与 Panel list。

Session Web message projection 与 Agent 的 [Session Memory](memory.md) 分离：前者仅显示每个 Run 的持久用户输入和已接受最终答案；后者还会把模型响应中的工具调用、工具结果投影成完整 Provider 对话，二者均从 Runtime 权威事实读取，但消费者和公开范围不同。

### 会话删除与恢复

会话侧栏删除按钮先打开确认弹窗；确认后 `FiguraWorkspaceApi.sessions.remove` 调用 `FiguraClient.deleteSession`。删除进行中禁用重复提交，失败保持弹窗并展示安全错误，不预先移除列表。成功后才删除本地列表项；若删除的是当前会话，关闭 RunController、清理待上传附件、选择状态、时间线和预览，再选择原列表相邻会话；删完最后一个则回到空状态。running Run 的拒绝以 Gateway 返回的 `409 session_has_running_run` 为准。

Gateway 的 `FiguraSessionDeletion` 是跨 Runtime/Sources 的协调服务，没有新业务模型或公开删除记录。它在同一个 SQLite 写事务内检查 Session 存在且没有 running Run，然后暂存三类私有图片，开启事务删除授权，依次删除 Runtime 事实、Sources 元数据、Run 与 Session。数据库失败时回滚并恢复图片；提交成功后物理清理暂存树，清理失败可留在不可访问的私有目录等待启动清除。该操作不可撤销，不是软删除，也不提供单 Run 或单事实删除接口。

启动时先初始化各文件服务，再由删除协调器扫描 `session-trash`：Session 仍存在则恢复原路径，已不存在则清除暂存；非法身份、符号链接、恢复碰撞或失败会阻止启动并返回安全 storage error。之后按全部耐久 render 调用清理孤儿渲染文件，最后验证 Panel 内容，再开放服务和恢复 running Run。具体事务归 [Runtime](runtime.md#session-整体删除的提交边界)，文件操作归 [Sources](sources.md#2-内部流转与不变量)。

### 生成图大图查看与 PNG 下载

每个已提交成功渲染都保留独立 Gallery 卡片，不仅展示最新一张。`ChartRenderGallery` 经 `PreviewImage` 将点击、Enter/Space 交给 `FiguraApp` 的统一 `InteractivePreview`，支持放大、缩小、滚动查看、Escape 关闭和焦点返回；预览使用该卡片受授权的 content URL。多子图 Figure 的 PNG 作为整张画布查看，不把子图另算独立 render。PanelGallery 当前仍是普通缩略图，不应把生成图大图功能描述为所有 Sources 图片都已有同样入口。

下载经 `api.runs.chartRenderContent` 获取该 Session/Run/call 的 `Blob`，复用同一只读 PNG endpoint，不新增下载路由或执行工具。client 验证成功 HTTP 状态、`Content-Type=image/png` 与非空 Blob；错误 JSON 转安全 `FiguraClientError`。Gallery 创建临时 object URL 并用净化 Figure 标题生成 `.png` 文件名，空名回退 `figura-chart.png`，处理非法字符、尾部点/空格及设备保留名；触发浏览器下载后释放 URL。卡片独立管理下载中和错误状态，失败可再次点击，预览/下载都不影响 Run 状态或其他产物。

## 3. HTTP 与前端接口

所有 HTTP 路由位于 `/api/v1`。成功 JSON 响应使用 `application/json`；本地服务设置 `Cache-Control: no-store` 与 `X-Content-Type-Options: nosniff`。附件内容响应使用由内容检查确认的媒体类型并禁止缓存；ChartFigure PNG 内容响应使用固定 `image/png` 并禁止缓存。请求体有界，Gateway 错误用 `{ "error": { "code": string, "message": string } }` 返回安全说明。

| 操作 | 请求合同 | 成功返回 | 行为边界 |
|---|---|---|---|
| `GET /health` | 无 | `FiguraHealth` | 配置检查，不做 Provider 网络请求 |
| `GET /sessions` | 无 | `{ sessions: FiguraSessionDto[] }` | 按最近活动降序；不逐 Run hydrate |
| `POST /sessions` | JSON object，`name?: string \| null` | `201 { session: FiguraSessionDto }` | 仅接收 `name`，不创建消息记录 |
| `GET /sessions/{sessionId}` | Session opaque ID | `FiguraSessionDataDto` | 读取同一 Session 的 snapshot |
| `DELETE /sessions/{sessionId}` | Session opaque ID；无请求体 | `204`，无 DTO | 永久删除整个 Session 及其 Run、来源和渲染产物；有 running Run 返回 `409 session_has_running_run`，不存在返回 `404 not_found` |
| `GET /sessions/{sessionId}/panels` | Session opaque ID | `{ panels: FiguraPanelDto[] }` | 只返回对应成功分割结果已提交的 Panel |
| `GET /sessions/{sessionId}/panels/{panelId}/content` | Session 与 Panel opaque ID | 原始 Panel PNG 字节 | `image/png`、`no-store`；跨 Session 读取拒绝 |
| `GET /sessions/{sessionId}/attachments` | Session opaque ID | `{ attachments: FiguraAttachmentDto[] }` | 只返回元数据 |
| `POST /sessions/{sessionId}/attachments?filename=...` | 原始图片字节，恰好一个非空 `filename` query | `201 { attachment: FiguraAttachmentDto }` | Attachment Service 验证文件；不收 JSON 包装 |
| `GET /sessions/{sessionId}/attachments/{attachmentId}/content` | Session 与 attachment opaque ID | 原始已验证图片字节 | 跨 Session 访问不泄露附件是否存在 |
| `DELETE /sessions/{sessionId}/attachments/{attachmentId}` | Session 与 attachment opaque ID | `204` | 被 Run 引用时拒绝删除 |
| `POST /sessions/{sessionId}/runs` | JSON 恰含 `text: string`、`attachmentIds: string[]`、`providerId: FiguraProviderId`；必需 `Idempotency-Key` header | `202 { run: FiguraRunHandleDto }` | Gateway 固定 model ID；Runtime 先持久化，Dispatcher 后执行 |
| `GET /sessions/{sessionId}/runs/{runId}/timeline` | Session 与 Run opaque ID | `FiguraToolTimelineSnapshotDto` | 从已提交工具事实生成步骤摘要，按工具序号排序 |
| `GET /sessions/{sessionId}/runs/{runId}/timeline/{callId}` | Session、Run 与工具调用 ID | `FiguraToolCallDetailDto` | 按需返回安全参数/结果摘要、attempt 摘要和来源；不返回原始参数或结果 |
| `GET /sessions/{sessionId}/runs/{runId}/timeline/{callId}/observation` | Session、Run 与 OCR/测量工具调用 ID | 原始 PNG 字节 | 只允许成功 OCR/测量且能解析授权来源的调用；内存重建观察图，不写入文件，返回 `image/png`、`no-store` |
| `GET /sessions/{sessionId}/runs/{runId}/chart-renders/{callId}/content` | Session、渲染所在 Run 与 `render_chart_figure` call ID | 原始 PNG 字节 | 只允许读取成功提交的同 Session 渲染；校验 PNG 哈希、字节数、尺寸和媒体类型，返回 `image/png`、`no-store` |
| `GET /sessions/{sessionId}/runs/{runId}/history?afterSequence=N` | 可选非负整数 `afterSequence`，默认 `0` | `FiguraRunHistoryDto` | 只返回同 Session Run 的安全事件 |
| `GET /sessions/{sessionId}/runs/{runId}/events?afterSequence=N` | 可选非负整数游标，默认 `0` | `text/event-stream` | 按持久事件序号补发和跟随；终态后关闭 |

Gateway 拒绝不在明确白名单中的浏览器 Origin；Origin guard 对无 Origin 的 GET/HEAD 放行，其他无 Origin 请求不作为浏览器写操作放行。当前 API 已提供 Session 整体删除，不提供 Run retry/resume/interruption、评测工作区、测量或图表渲染操作接口。工具时间线、来源/观察图、Panel 与 ChartFigure PNG 路由均为只读；不存在从网页启动、重试或修改工具调用的接口。

前端接口是 TypeScript 调用合同而非持久模型：`FiguraClient` 封装 HTTP/SSE 与 DTO，`FiguraWorkspaceApi` 将结果映射到兼容工作区协议，组件只调用后者。完整方法形状如下；其中 `Session`、`SessionData`、`Attachment`、`RunHandle`、`RunHistory`、`AgentRunEvent` 和 `RunSubscription` 继续使用现有前端协议类型；ChartRenderSummary 是 Figura Run 投影中的只读摘要。

| 接口成员 | TypeScript 合同 | 职责 |
|---|---|---|
| `FiguraClient.baseUrl` | `readonly string` | 本地 Gateway API base URL |
| `FiguraClient.getHealth()` | `Promise<FiguraHealth>` | 读取配置 health |
| `FiguraClient.listSessions()` | `Promise<FiguraSessionDto[]>` | 读取 Session 摘要 |
| `FiguraClient.getSession(sessionId: string)` | `Promise<FiguraSessionDataDto>` | 读取完整 Web Session snapshot |
| `FiguraClient.listPanels(sessionId: string)` | `Promise<FiguraPanelDto[]>` | 列出 Session 中已提交 Panels |
| `FiguraClient.createSession(name: string)` | `Promise<FiguraSessionDto>` | 创建 Session |
| `FiguraClient.deleteSession(sessionId: string)` | `Promise<void>` | 确认后永久删除整个会话；失败由安全 envelope 返回 |
| `FiguraClient.listAttachments(sessionId: string)` | `Promise<FiguraAttachmentDto[]>` | 列出 Session 图片元数据 |
| `FiguraClient.uploadAttachment(sessionId: string, file: File)` | `Promise<FiguraAttachmentDto>` | 上传浏览器 `File` 原始字节 |
| `FiguraClient.deleteAttachment(sessionId: string, attachmentId: string)` | `Promise<void>` | 删除未被 Run 引用的图片 |
| `FiguraClient.startRun(sessionId: string, text: string, attachmentIds: string[], providerId: FiguraProviderId, idempotencyKey: string)` | `Promise<FiguraRunHandleDto>` | 提交 Run；固定模型由 Gateway 决定 |
| `FiguraClient.getRunHistory(sessionId: string, runId: string, afterSequence?: number)` | `Promise<FiguraRunHistoryDto>` | 从事件 cursor 读取持久历史 |
| `FiguraClient.getRunTimeline(sessionId: string, runId: string)` | `Promise<FiguraToolTimelineSnapshotDto>` | 读取一个 Run 的工具步骤摘要 |
| `FiguraClient.getRunTimelineCall(sessionId: string, runId: string, callId: string)` | `Promise<FiguraToolCallDetailDto>` | 按需读取单个工具调用的安全详情 |
| `FiguraClient.getChartRenderContent(sessionId: string, runId: string, callId: string)` | `Promise<Blob>` | 下载已提交渲染的 PNG；校验 HTTP 成功、媒体类型及非空内容 |
| `FiguraClient.subscribeRun(sessionId: string, runId: string, callbacks: { onEvent(event: AgentRunEvent): void; onError(error: Error): void; onComplete(): void }, afterSequence?: number)` | `RunSubscription` | 返回可关闭的 SSE 订阅 |
| `FiguraClient.attachmentContentUrl(sessionId: string, attachmentId: string)` | `string` | 生成 Session-scoped image content URL，不取代 Gateway ownership check |
| `FiguraClient.chartRenderContentUrl(sessionId: string, runId: string, callId: string)` | `string` | 生成按 Session、渲染 Run 与调用 ID 定位的 PNG 内容 URL；Gateway 仍核对成功事实和摘要 |
| `FiguraClient.panelContentUrl(sessionId: string, panelId: string)` | `string` | 生成 Session-scoped Panel PNG URL，读取时由 Gateway 校验 Session 归属 |
| `FiguraClient.timelineObservationUrl(sessionId: string, runId: string, callId: string)` | `string` | 生成成功 OCR/测量观察图 URL；Gateway 仍校验 Run、工具结果与授权来源 |
| `FiguraWorkspaceApi.health.get()` | `Promise<FiguraHealth>` | 向应用提供 health |
| `FiguraWorkspaceApi.sessions.list()` / `get(sessionId: string)` / `create(name: string)` | `Promise<Session[]>` / `Promise<SessionData>` / `Promise<Session>` | 对应列表、详情与创建，并映射兼容 Session 类型 |
| `FiguraWorkspaceApi.sessions.remove(sessionId: string)` | `Promise<void>` | 委托 client 的会话删除，成功后应用更新选择与列表 |
| `FiguraWorkspaceApi.attachments.list(sessionId: string)` / `upload(sessionId: string, file: File)` / `remove(sessionId: string, attachmentId: string)` | `Promise<Attachment[]>` / `Promise<Attachment>` / `Promise<void>` | 对应图片列表、上传、删除并映射 preview URL |
| `FiguraWorkspaceApi.panels.list(sessionId: string)` / `contentUrl(sessionId: string, panelId: string)` | `Promise<FiguraPanelDto[]>` / `string` | 获取 Panel DTO 并构造延迟读取用的 PNG URL；组件通过 Figura workspace callback 展示 |
| `FiguraWorkspaceApi.runs.start(...)` / `history(...)` / `timeline(...)` / `timelineCall(...)` / `subscribe(...)` | `Promise<RunHandle>` / `Promise<RunHistory>` / `Promise<FiguraToolTimelineSnapshotDto>` / `Promise<FiguraToolCallDetailDto>` / `RunSubscription` | 对应 Run 提交、事件历史、工具时间线摘要/详情读取与 SSE 订阅 |
| `FiguraWorkspaceApi.runs.chartRenderContentUrl(...)` / `timelineObservationUrl(...)` | `string` / `string` | 生成 ChartFigure PNG 或工具观察图的 URL；URL 不代替 Gateway 授权和摘要校验 |
| `FiguraWorkspaceApi.runs.chartRenderContent(sessionId: string, runId: string, callId: string)` | `Promise<Blob>` | 委托 client 二进制读取，供 Gallery 下载使用 |

实现见 [`client.ts`](../../frontend/src/api/figura/client.ts)、[`workspace.ts`](../../frontend/src/api/figura/workspace.ts) 与 [`types.ts`](../../frontend/src/api/figura/types.ts)。 Gallery 位于 [`ChartRenderGallery.tsx`](../../frontend/src/components/figura/ChartRenderGallery.tsx)，由 [`FiguraApp.tsx`](../../frontend/src/FiguraApp.tsx) 按 Run 挂载。

### GatewayResponse

Gateway 内部的一次 HTTP 响应封套，由 `FiguraGatewayApplication` 创建、HTTP server 消费；它本身不作为 JSON DTO 持久化或直接暴露。[定义](../../src/figura/gateway/application.py)。

| 完整字段路径 | 类型 | 必填/默认 | 含义与约束 | 写入者 → 权威位置 → 读取/公开规则 |
|---|---|---|---|---|
| `GatewayResponse.status` | `int` | 必填 | HTTP 响应状态码 | Gateway application → 调用期响应封套 → HTTP server；仅作为状态行公开 |
| `GatewayResponse.headers` | `Mapping[str, str]` | 必填 | 已决定的 HTTP 响应头 | Gateway application → 调用期响应封套 → HTTP server；只发送经过边界规则允许的头 |
| `GatewayResponse.body` | `bytes` | 必填 | 已编码的响应体，可为 JSON、SSE 或受控图片字节 | Gateway application → 调用期响应封套 → HTTP server；由对应路由的媒体类型与授权规则约束 |

## 4. Web DTO 字段

本节是 `frontend/src/api/figura/types.ts` 与 Gateway JSON 的公开 DTO owner。每字段列出 JSON 名、必填状态、投影来源和读取/修订规则。Python 源模型的字段仍由[Runtime](runtime.md#4-完整模型字段)、[Sources 附件与 Panel](sources.md#3-完整模型字段)和[Provider](provider.md#4-完整模型字段)分别拥有；此处不复制它们的源字段表。

### `FiguraProviderId`

字符串联合类型：`'qwen' | 'deepseek' | 'mimo'`。它是前端/Gateway 可选择的 Provider allowlist；固定模型映射见[Provider 边界](provider.md#5-枚举与依据)。浏览器只提交此 ID，不选择模型或发送 Provider 凭据。

### `FiguraProviderAvailability`

由 Gateway health projection 写入；来源为 ProviderFactory 的 `ProviderAvailability`。读取者为 Figura 前端 health/Provider picker；配置可用性可公开，profile、key 和 endpoint 不公开。

| 完整字段路径 | JSON 类型 | 必填/默认 | 含义与约束 | 写入者 → 权威来源 → 读取/公开规则 |
|---|---|---|---|---|
| `FiguraProviderAvailability.providerId` | `FiguraProviderId` | 必填 | Allowlist Provider ID | Gateway health → ProviderFactory → Figura UI；仅三个已声明值 |
| `FiguraProviderAvailability.modelId` | `string` | 必填 | 此 Provider 当前固定模型 ID | Gateway health → ProviderFactory `MODEL_IDS` → UI 显示；浏览器不能回传覆盖 |
| `FiguraProviderAvailability.available` | `boolean` | 必填 | 本地配置与 Provider 策略检查是否可用；不代表远端健康检查 | Gateway health → ProviderFactory 配置检查 → UI 控制可选状态；不发网络请求 |
| `FiguraProviderAvailability.reasonCode` | `'configuration_missing' \| 'invalid_configuration' \| null` | 必填，可空 | 不可用时的有界配置错误码；可用时为 `null` | Gateway health → ProviderFactory availability → UI 安全提示；不含配置值或 endpoint |

### `FiguraHealth`

`GET /health` 固定版本和服务身份，并包含完整 allowlist 可用性列表。写入者为 Gateway application；读取者为 `FiguraClient` 与 `FiguraApp`；不是服务存活以外的远端 Provider 健康承诺。

| 完整字段路径 | JSON 类型 | 必填/默认 | 含义与约束 | 写入者 → 权威来源 → 读取/公开规则 |
|---|---|---|---|---|
| `FiguraHealth.version` | `'v1'` | 必填，固定 | API health schema version | Gateway `_health` → Gateway API version → UI；固定字面值 |
| `FiguraHealth.status` | `'ok'` | 必填，固定 | Gateway 完成本地配置读取 | Gateway `_health` → 当前 health handler → UI；不表示 Provider 网络可达 |
| `FiguraHealth.service` | `'figura'` | 必填，固定 | 服务标识 | Gateway `_health` → Figura Gateway → UI；固定字面值 |
| `FiguraHealth.providers` | `FiguraProviderAvailability[]` | 必填 | Qwen、DeepSeek、MiMo 的本地可用性 | Gateway `_health` → ProviderFactory → UI；元素字段见上方模型 |

### `FiguraSessionDto`

Session summary projection。写入者为 `web_projection.session_summary`；来源字段由 Runtime `Session` 权威，`updatedAt` 还聚合 Run/附件最近活动，`runCount` 由 SessionRepository 查询计算。客户端读取后可映射到旧工作区 Session 形状；DTO 本身只读。

| 完整字段路径 | JSON 类型 | 必填/默认 | 含义与约束 | 写入者 → 权威来源 → 读取/公开规则 |
|---|---|---|---|---|
| `FiguraSessionDto.id` | `string` | 必填 | opaque Session ID | session summary → Runtime `Session.session_id` → client/UI；跨 Session 授权边界 |
| `FiguraSessionDto.name` | `string \| null` | 必填，可空 | 用户给定显示名称 | session summary → Runtime `Session.name` → client/UI；可空 |
| `FiguraSessionDto.createdAt` | `string` | 必填 | UTC 创建时间文本 | session summary → Runtime `Session.created_at` → client/UI；只读 |
| `FiguraSessionDto.updatedAt` | `string` | 必填 | Session 更新、Run 创建/结束和附件创建时间中的最近活动时间 | session summary → SessionRepository 聚合 / snapshot 计算 → client/UI；只读派生值 |
| `FiguraSessionDto.runCount` | `number` | 必填 | Session 持久 Run 数，不含额外 message 记录 | session summary → SessionRepository SQL aggregate / snapshot runStates → client/UI；只读计数 |

### `FiguraAttachmentDto`

Gateway Attachment projection。写入者为 `web_projection.attachment`；源元数据由 [AttachmentMetadata](sources.md#3-完整模型字段) 权威。读者为 FiguraClient 和 workspace adapter；适合公开的文件名/类型/大小/创建时间，不含 Session ID、字节、本机路径或删除状态。

| 完整字段路径 | JSON 类型 | 必填/默认 | 含义与约束 | 写入者 → 权威来源 → 读取/公开规则 |
|---|---|---|---|---|
| `FiguraAttachmentDto.id` | `string` | 必填 | opaque attachment ID | attachment projection → `AttachmentMetadata.attachment_id` → client；内容操作仍需 Session ID |
| `FiguraAttachmentDto.filename` | `string` | 必填 | 已净化文件名 | attachment projection → `AttachmentMetadata.filename` → UI 可展示 |
| `FiguraAttachmentDto.mediaType` | `string` | 必填 | 经图片内容确认的 media type | attachment projection → `AttachmentMetadata.media_type` → 图片预览和展示 |
| `FiguraAttachmentDto.byteCount` | `number` | 必填 | 图片字节数 | attachment projection → `AttachmentMetadata.byte_count` → UI 可展示；不暴露字节 |
| `FiguraAttachmentDto.createdAt` | `string` | 必填 | UTC 创建时间文本 | attachment projection → `AttachmentMetadata.created_at` → UI；只读 |

### `FiguraPanelDto`

Session-scoped Panel metadata projection，由 `web_projection.panel` 从已提交的 `PanelRecord` 创建。客户端独立请求列表；Session detail 不嵌入重复 Panel 数据。字段不含 `sessionId`、路径、图像字节或创建状态；图片由对应 Panel content URL 单独读取。源多边形和持久字段见[PanelRecord](sources.md#3-完整模型字段)。

| 完整字段路径 | JSON 类型 | 必填/默认 | 含义与约束 | 写入者 → 权威来源 → 读取/公开规则 |
|---|---|---|---|---|
| `FiguraPanelDto.panelId` | `string` | 必填 | opaque Panel ID | `web_projection.panel` → `PanelRecord.panel_id` → client/UI key；Session-scoped 内容读取仍检查归属 |
| `FiguraPanelDto.runId` | `string` | 必填 | 产生该 Panel 的 Run ID | projection → `PanelRecord.run_id` → workspace 在所属 Run 下分组；不授权单独内容访问 |
| `FiguraPanelDto.sourceAttachmentId` | `string` | 必填 | 被切分的来源 Attachment ID | projection → `PanelRecord.source_attachment_id` → UI 显示来源引用 |
| `FiguraPanelDto.name` | `string` | 必填 | Panel 显示名 | projection → `PanelRecord.name` → 标题和图像 alt；只读 |
| `FiguraPanelDto.points` | `{ x: number, y: number }[]` | 必填 | 原图归一化 0–1000 多边形点；保持分割输入顺序 | projection → `PanelRecord.points` → Web client；坐标定义见 Sources，不在网页端修改 |

### `FiguraSessionDataDto`

Session detail 顶层响应。写入者为 `web_projection.session_snapshot`；其 nested contracts 分别由本 Web DTO 专题、[Attachment](sources.md#3-完整模型字段)和[Runtime](runtime.md#4-完整模型字段)拥有。客户端读取后映射为工作区 SessionData；字段本身是当前 snapshot，不支持原位修订。

| 完整字段路径 | JSON 类型 | 必填/默认 | 含义与约束 | 写入者 → 权威来源 → 读取/公开规则 |
|---|---|---|---|---|
| `FiguraSessionDataDto.session` | `FiguraSessionDto` | 必填 | 当前 Session summary；字段见本节对应 DTO | session snapshot projection → Runtime `SessionSnapshot.session` 与聚合值 → workspace adapter/UI；只读 |
| `FiguraSessionDataDto.messages` | `FiguraMessageDto[]` | 必填 | 所有 Run 输入及存在的 accepted final answer；按 Run ordinal 排列，单个 Run 中输入在答案前 | session snapshot projection → ordered Runtime RunState records → Conversation；不含 tool/model intermediate history |
| `FiguraSessionDataDto.attachments` | `FiguraAttachmentDto[]` | 必填 | 当前 Session 所保留附件的元数据列表 | session snapshot projection → `SessionSnapshot.attachments` → Attachment panel；不含 image bytes |
| `FiguraSessionDataDto.runs` | `FiguraRunDto[]` | 必填 | 当前 Session 全部 Run，按 ordinal 升序 | session snapshot projection → `SessionSnapshot.run_states` → Run timeline；保留活动及终态 Run |

### `FiguraMessageDto`

Session 详情的用户可见对话投影，不是 Agent Session Memory。由 `web_projection.session_snapshot` 写入；来源为 Run 的 `RunInput` 和已接受 `FinalAnswerFact` 引用的 `ModelResponseFact`。读取者是 Conversation UI；只读，不把中间模型响应和工具消息公开。

| 完整字段路径 | JSON 类型 | 必填/默认 | 含义与约束 | 写入者 → 权威来源 → 读取/公开规则 |
|---|---|---|---|---|
| `FiguraMessageDto.id` | `string` | 必填 | 确定性身份 `${runId}:user` 或 `${runId}:assistant` | session snapshot projection → Run ID 与角色 → Conversation key；不独立持久化 |
| `FiguraMessageDto.runId` | `string` | 必填 | 所属 Run opaque ID | session snapshot projection → `Run.run_id` → Conversation 来源关联 |
| `FiguraMessageDto.kind` | `'user' \| 'assistant'` | 必填 | user 输入或 accepted final answer；不包含工具角色 | session snapshot projection → `RunInput` / `FinalAnswerFact` → Conversation；只有两种值 |
| `FiguraMessageDto.text` | `string` | 必填 | 原始用户文本或被最终接受的助手文本 | session snapshot projection → `RunInput.text` / `ModelResponseFact.assistant_content` → Conversation；非终态中间 assistant response 不公开 |
| `FiguraMessageDto.timestamp` | `string` | 必填 | user input record 或 final answer record 的创建时间 | session snapshot projection → 对应 ExecutionRecord `created_at` → Conversation；UTC 文本 |
| `FiguraMessageDto.attachmentIds` | `string[]` | 仅 user message 有非空列表时存在 | 用户输入引用的附件 ID，保持提交顺序 | session snapshot projection → `RunInput.attachment_ids` → user message attachment mapping；空列表字段省略，assistant 不带该字段 |

### `FiguraRunDto` 与 `FiguraRunHandleDto`

`FiguraRunDto` 是 Session/history 的安全 Run projection；其运行字段来源为 Runtime `Run`，`executionState` 根据 Run status 和 Checkpoint 下一动作计算，`chartRenders` 则来自 Agent 对已提交渲染事实的安全投影。写入者为 `web_projection.run_summary`；读者为 workspace timeline 和 run controller。`FiguraRunHandleDto` 是 start 返回的基础运行投影，省略 `executionState` 和 `chartRenders`；其字段见本表中这两项之外的字段行。

| 完整字段路径 | JSON 类型 | 必填/默认 | 含义与约束 | 写入者 → 权威来源 → 读取/公开规则 |
|---|---|---|---|---|
| `FiguraRunDto.runId` | `string` | 必填 | opaque Run ID | run projection → `Run.run_id` → timeline/controller；Session-scoped route 仍校验归属 |
| `FiguraRunDto.sessionId` | `string` | 必填 | 所属 Session opaque ID | run projection → `Run.session_id` → timeline/controller |
| `FiguraRunDto.ordinal` | `number` | 必填 | Session 内从 1 开始的 Run 顺序 | run projection → `Run.ordinal` → timeline 排序 |
| `FiguraRunDto.status` | `'running' \| 'completed' \| 'failed' \| 'interrupted'` | 必填 | 持久 Run 生命周期状态 | run projection → `Run.status` → UI 状态；只有列出的终态/活动态 |
| `FiguraRunDto.provider` | `FiguraProviderId` | 必填 | 创建时固定 Provider | run projection → `Run.provider` → timeline；allowlist 字符串 |
| `FiguraRunDto.model` | `string` | 必填 | 创建时固定 model ID | run projection → `Run.model` → timeline；只读，不接受浏览器修改 |
| `FiguraRunDto.createdAt` | `string` | 必填 | Run 创建 UTC 时间 | run projection → `Run.created_at` → timeline |
| `FiguraRunDto.startedAt` | `string` | 必填 | Run 创建时的开始时间；当前与 createdAt 相同，不是首个 Provider 调用时刻 | run projection → `Run.started_at` → timeline |
| `FiguraRunDto.finishedAt` | `string \| null` | 必填，可空 | 尚未终结时为空 | run projection → `Run.finished_at` → timeline |
| `FiguraRunDto.terminalCode` | `string \| null` | 必填，可空 | 持久安全终态原因码；活动 Run 为空 | run projection → `Run.terminal_code` → UI 安全状态；不含异常堆栈 |
| `FiguraRunDto.terminalMessage` | `string \| null` | 必填，可空 | 安全终态说明，包括本地 prepare 拒绝的白名单中文原因 | run projection → `Run.terminal_message` → UI；无终态时为空，不含原始 SDK 错误或私有续接 |
| `FiguraRunDto.executionState` | `'active' \| 'needs_reconciliation'` | 必填 | `needs_reconciliation` 当且仅当 Run 仍 running 且 checkpoint action 是 `TOOL_ATTEMPT`；否则为 `active` | `run_summary` → Run + ExecutionCheckpoint → UI reconciliation 状态；纯派生，不写回 Runtime |
| `FiguraRunDto.chartRenders` | `ChartRenderSummary[]` | 必填 | 当前 Run 成功提交的渲染摘要；无成功渲染时为空数组 | `run_summary` → Agent 资源目录的成功 ChartRenderContent 与被引用 ChartFigureContent → React Gallery；PNG 字节另走受授权路由 |

`FiguraRunHandleDto = Omit<FiguraRunDto, 'executionState' | 'chartRenders'>` 的完整字段为 `runId`、`sessionId`、`ordinal`、`status`、`provider`、`model`、`createdAt`、`startedAt`、`finishedAt`、`terminalCode`、`terminalMessage`；每字段类型、来源与公开规则与 `FiguraRunDto` 相同。Handle 由 `web_projection.run_handle` 从 `Run` 生成。

### `ChartRenderSummary`

`FiguraRunDto.chartRenders` 和 `FiguraRunHistoryDto.run.chartRenders` 中的已成功渲染摘要，由 `web_projection.chart_render_summaries` 查询 Agent 资源目录的 `chart_render` 与 `chart_figure` 两类资源构造。数组按渲染发生顺序排列，归属于发起渲染工具调用的 Run；图片字节不在 DTO 中，前端需要时使用 `FiguraClient.chartRenderContentUrl` 懒加载。失败渲染不出现在 Web DTO。

| 完整字段路径 | JSON 类型 | 必填/默认 | 含义与约束 | 写入者 → 权威来源 → 读取/公开规则 |
|---|---|---|---|---|
| `ChartRenderSummary.callId` | `string` | 必填 | 发起 `render_chart_figure` 的 call ID，也是渲染文件内容路径键 | `chart_render_summaries` → `ToolResourceRef.call_id` 的 ChartRenderContent → Gallery key 与受授权 PNG URL |
| `ChartRenderSummary.figureRef` | object | 必填；恰含 `runId`、`callId` | 已接受 Figure 的来源引用 | `chart_render_summaries` → `ChartRenderContent.figure_ref` → 展示/一致性检查；不直接授权内容读取 |
| `ChartRenderSummary.figureRef.runId` | `string` | 必填 | Figure assembly 来源 Run ID | `ToolResourceRef.run_id` → Gallery 元信息 |
| `ChartRenderSummary.figureRef.callId` | `string` | 必填 | Figure assembly 调用 ID | `ToolResourceRef.call_id` → Gallery 元信息 |
| `ChartRenderSummary.figureTitle` | `string` | 必填 | 被渲染 Figure 标题，可为空 | `chart_render_summaries` → 同 Session 已接受 `ChartFigureContent.result.figure.title` → figcaption 与图片 alt |
| `ChartRenderSummary.figureDigest` | `string` | 必填；64 位小写十六进制 | 被渲染 Figure 的 canonical digest | 成功 ToolResultFact.result → `ChartRenderContent.result` → 安全 Run DTO |
| `ChartRenderSummary.imageSha256` | `string` | 必填；64 位小写十六进制 | PNG 内容 SHA-256，Gateway 读取文件时校验 | 成功 ToolResultFact.result → `ChartRenderContent.result` → Web 内容路由完整性核验 |
| `ChartRenderSummary.mediaType` | `'image/png'` | 必填；固定值 | 媒体类型 | 成功 ToolResultFact.result → `ChartRenderContent.result` → 图片路由 Content-Type |
| `ChartRenderSummary.byteCount` | `number` | 必填；1–`MAX_IMAGE_BYTES` | PNG 精确字节数 | 成功 ToolResultFact.result → `ChartRenderContent.result` → 读取时与文件长度比较 |
| `ChartRenderSummary.width` | `number` | 必填；1–1280 | PNG 像素宽度 | 成功 ToolResultFact.result → `ChartRenderContent.result` → 读取时与图片解码尺寸比较 |
| `ChartRenderSummary.height` | `number` | 必填；1–1962 | PNG 像素高度 | 成功 ToolResultFact.result → `ChartRenderContent.result` → 读取时与图片解码尺寸比较 |

### Tool Timeline DTO

这些 DTO 只由本 Web 边界拥有。Gateway 按当前 Run 的持久 ToolCall、Attempt、Result 事实生成它们；不建立时间线数据库表。快照列表按 `toolSequence` 排序，详情按 UI 展开动作懒加载。摘要经过 allowlist 与长度限制，不返回原始参数、工具结果、图片字节或 Provider 内容。工具字段本身仍由[Runtime](runtime.md#4-完整模型字段)拥有，资源引用与观察图读取规则见[Agent](agent.md#4-runexecutionstate-资源合同与完整字段)。

`FiguraToolTimelineStatus` 的值与判定如下：`completed` 表示已提交成功结果，`failed` 表示已提交失败结果，`pending` 表示 Run 仍运行且尚无 attempt，`running` 表示 attempt 已开始且 Dispatcher 仍拥有该 Run，`needs_reconciliation` 表示 Run 仍运行但 Dispatcher 不拥有它，`unknown` 表示 Run 已终态但 attempt 没有结果，`not_started` 表示 Run 已终态且该调用从未开始。该状态只描述持久事实和当前 Dispatcher 所有权，不推断工具结果。

| 完整字段路径 | JSON 类型 | 必填/默认 | 含义与约束 | 写入者 → 权威来源 → 读取/公开规则 |
|---|---|---|---|---|
| `FiguraToolTimelineSnapshotDto.runId` | `string` | 必填 | 此快照所属 Run 的 opaque ID | `run_timeline` → Runtime `RunState.run` → UI 按 Run 展示；Session-scoped 路由校验归属 |
| `FiguraToolTimelineSnapshotDto.steps` | `FiguraToolTimelineStepDto[]` | 必填 | 此 Run 的工具调用步骤，按 `toolSequence` 升序 | `run_timeline` → RunState 已提交 ToolCall/Attempt/Result facts → 时间线列表；没有调用时为空数组 |
| `FiguraToolTimelineStepDto.callId` | `string` | 必填 | 当前逻辑工具调用 ID | `run_timeline` → `ToolCallFact.call_id` → detail 路由键；opaque ID |
| `FiguraToolTimelineStepDto.toolSequence` | `number` | 必填；正整数 | Run 内工具调用的持久顺序 | `run_timeline` → ToolCall `ToolExecutionFact.tool_sequence` → 步骤排序 |
| `FiguraToolTimelineStepDto.toolName` | `string` | 必填 | 工具注册名 | `run_timeline` → `ToolCallFact.tool_name` → UI 标签；未识别名称安全回显为名称文本 |
| `FiguraToolTimelineStepDto.createdAt` | `string` | 必填 | 工具调用创建时间，UTC 文本 | `run_timeline` → ToolCall fact `created_at` → UI 时间线 |
| `FiguraToolTimelineStepDto.updatedAt` | `string` | 必填 | 最近相关事实时间：结果、最新 attempt 或调用本身，依次回退 | `run_timeline` → 对应 RunState facts → UI 更新时间 |
| `FiguraToolTimelineStepDto.status` | `FiguraToolTimelineStatus` | 必填 | 基于已提交 attempt/result 与 Dispatcher 所有权计算的状态，含义见上方 | `run_timeline` → Run status、tool facts、`dispatcher.owns` → UI 状态标签；不是额外持久字段 |
| `FiguraToolTimelineStepDto.summary` | `string` | 必填；最多 180 字符 | 工具名称与有限结果摘要；结果内容不原样复制 | `run_timeline` → allowlist `_step_summary` → 时间线卡片 |
| `FiguraToolCallDetailDto.runId` | `string` | 必填 | 所属 Run opaque ID | `tool_call_detail` → Runtime `RunState.run` → UI 展开详情 |
| `FiguraToolCallDetailDto.callId` | `string` | 必填 | 工具调用 ID | `tool_call_detail` → `ToolCallFact.call_id` → 与步骤匹配 |
| `FiguraToolCallDetailDto.toolName` | `string` | 必填 | 工具注册名 | `tool_call_detail` → `ToolCallFact.tool_name` → UI 标签 |
| `FiguraToolCallDetailDto.status` | `FiguraToolTimelineStatus` | 必填 | 该调用的当前安全状态；判定规则见上方 | `tool_call_detail` → Runtime facts 与 Dispatcher ownership → UI 状态标签 |
| `FiguraToolCallDetailDto.createdAt` | `string` | 必填 | 工具调用创建时间，UTC 文本 | `tool_call_detail` → ToolCall fact `created_at` → UI 展开详情 |
| `FiguraToolCallDetailDto.updatedAt` | `string` | 必填 | 最近相关事实时间，UTC 文本 | `tool_call_detail` → 结果、最新 attempt 或 ToolCall fact `created_at` → UI 展开详情 |
| `FiguraToolCallDetailDto.argumentSummary` | `string` | 可选；识别工具时返回 | allowlist 生成的人类可读输入摘要，不含原始 JSON | `tool_call_detail` → ToolCall 参数与安全来源元数据 → UI；unknown tool 不返回 |
| `FiguraToolCallDetailDto.resultSummary` | `string` | 可选；识别工具时返回 | 已提交结果摘要；无结果时为“尚无已提交结果”，不含原始 JSON | `tool_call_detail` → ToolResultFact → UI；unknown tool 不返回 |
| `FiguraToolCallDetailDto.attempts` | `FiguraToolAttemptDto[]` | 可选；识别工具时返回 | 此逻辑调用的 attempt 摘要，保持事实顺序 | `tool_call_detail` → 对应 `ToolAttemptStartedFact` 与结果 → UI；unknown tool 不返回 |
| `FiguraToolCallDetailDto.errorSummary` | `string \| null` | 可选；识别工具时返回 | allowlist 安全错误摘要；无已提交错误时为 `null` | `tool_call_detail` → ToolResultFact.error code 安全映射 → UI；不包含原始异常 |
| `FiguraToolCallDetailDto.source` | `FiguraToolTimelineSourceDto \| null` | 可选；识别工具时返回 | 可解析来源时提供 Attachment/Panel 标识；不授权图像访问 | `tool_call_detail` → 输入引用与 Agent RunExecutionState → UI 显示来源；内容仍走 Session-scoped URL |
| `FiguraToolCallDetailDto.observationAvailable` | `boolean` | 可选；识别工具时返回 | 是否存在成功且来源可解析的 OCR/测量观察图 | `tool_call_detail` → 成功 ToolResultFact 与 OCR/Measurement resource → UI 是否显示预览 |
| `FiguraToolAttemptDto.attemptNumber` | `number` | 必填；正整数 | 同一逻辑调用中的 attempt 序号 | `tool_call_detail` → `ToolAttemptStartedFact.attempt_number` → UI attempt 列表 |
| `FiguraToolAttemptDto.startedAt` | `string` | 必填 | attempt 开始时间，UTC 文本 | `tool_call_detail` → Attempt fact `created_at` → UI 时间线 |
| `FiguraToolAttemptDto.finishedAt` | `string \| null` | 必填，可空 | 有匹配结果时为结果时间；否则为空 | `tool_call_detail` → 与 attempt 匹配的 ToolResultFact → UI attempt 状态 |
| `FiguraToolAttemptDto.status` | `'running' \| 'completed' \| 'failed' \| 'unknown'` | 必填 | 匹配结果成功/失败时为对应终态；没有结果时为 `running`；已提交结果属于其他 attempt 时为 `unknown` | `tool_call_detail` → Attempt 与 Result facts → UI 状态；不启动恢复动作 |
| `FiguraToolAttemptDto.errorSummary` | `string \| null` | 必填，可空 | 此 attempt 已知失败时的安全错误摘要 | `tool_call_detail` → 匹配的 ToolResultFact.error 安全映射 → UI；不含异常原文 |
| `FiguraToolTimelineSourceDto.kind` | `'attachment' \| 'panel'` | 必填 | 来源资源种类 | `tool_call_detail` → Agent `ImageResourceRef` → UI 选择正确的 Session-scoped 图片 URL |
| `FiguraToolTimelineSourceDto.id` | `string` | 必填 | 来源 Attachment 或 Panel opaque ID | `tool_call_detail` → RunExecutionState 来源引用 → UI 构造内容 URL；服务端仍校验归属 |
| `FiguraToolTimelineSourceDto.name` | `string` | 必填；最多 96 字符 | 已净化 Attachment filename 或 Panel name | `tool_call_detail` → AttachmentContent / PanelContent → UI 来源标签 |

未知工具名仍出现在步骤列表中；其详情只返回 `runId`、`callId`、`toolName`、`status`、`createdAt`、`updatedAt` 六个基础字段，避免把未经审核的输入/结果摘要公开。观察图仅支持成功的 `extract_text` 与四类测量调用；URL 不取代 Gateway 对同 Session、成功结果和来源资源的核验。

前端的 `FiguraToolTimelineStepViewModel` 是纯展示派生值，不是 API DTO 或持久模型。其基础字段完整继承 [`FiguraToolTimelineStepDto`](#tool-timeline-dto)，并添加 `id: string`（`runId:callId` 合并身份）、`label: string`（已知工具的本地化标签，未知工具回显 `toolName`）和 `statusLabel: string`（本地化状态标签）；由 `domain/figura/timeline.ts` 映射，`ToolTimeline` 消费。

### `FiguraEventDto` 与 `FiguraRunHistoryDto`

Event DTO 由 `web_projection.event_projection` 生成，Runtime [`RunStreamEvent`](runtime.md#4-完整模型字段) 是持久事件来源。SSE 的 `id` 行使用 `{runId}:{sequence}`；数据字段不包含执行内容原文。

| 完整字段路径 | JSON 类型 | 必填/默认 | 含义与约束 | 写入者 → 权威来源 → 读取/公开规则 |
|---|---|---|---|---|
| `FiguraEventDto.runId` | `string` | 必填 | 事件所属 Run ID | event projection → RunState.run ID → controller 按 Run 合并 |
| `FiguraEventDto.sequence` | `number` | 必填 | Run 内单调事件序号 | event projection → `RunStreamEvent.event_sequence` → history/SSE cursor |
| `FiguraEventDto.kind` | `string` | 必填；`run_created`、`run_progress`、`run_completed`、`run_failed`、`run_interrupted` | 生命周期或安全进度事件 kind | event projection → `RunStreamEvent.event_kind` → UI 更新 Run 或刷新工具时间线；其值集合见 Runtime 枚举 |
| `FiguraEventDto.timestamp` | `string` | 必填 | 事件创建时间 | event projection → `RunStreamEvent.created_at` → timeline |
| `FiguraEventDto.payload` | `Record<string, unknown>` | 必填 | allowlist payload：created 为 `{ordinal}`，progress 为 `{checkpointRevision}`，completed 为空对象，failed/interrupted 为 `{terminalCode}`；progress revision 为正整数 | event projection → Runtime 安全事件 + Run summary → UI；不含 input、模型内容、工具 payload 或 continuation |
| `FiguraRunHistoryDto.run` | `FiguraRunDto` | 必填 | 与历史一起返回的安全 Run summary | `run_history` → RunState → timeline；字段见上方 `FiguraRunDto` |
| `FiguraRunHistoryDto.events` | `FiguraEventDto[]` | 必填 | `sequence > afterSequence` 的事件，保持升序 | `run_history` → RunState.events → RunController merge；当前实现保留全部持久事件 |
| `FiguraRunHistoryDto.historyGap` | `boolean` | 必填；当前固定 `false` | 当前实现不剪裁事件历史，因此不会报告 history gap | `run_history` → 当前全量 Runtime event list → RunController；若未来改成有界保留需同步合同 |

### 错误响应与 `FiguraClientError`

Gateway 错误 envelope 由 application 生成，客户端把它转换成 `FiguraClientError`。浏览器仅读取安全 message；网络断开时 client 用 HTTP status `0` 和 `gateway_unavailable`/`gateway_stream_unavailable` 表达无 HTTP 响应。

| 完整字段路径 | JSON/运行时类型 | 必填/默认 | 含义与约束 | 写入者 → 权威来源 → 读取/公开规则 |
|---|---|---|---|---|
| `ErrorEnvelope.error` | `{ code: string, message: string }` | 必填 | 安全错误对象 | Gateway `_error` → 当前请求处理结果 → client 转换；不含 traceback 或本地配置 |
| `ErrorEnvelope.error.code` | `string` | 必填 | 有界错误标识 | Gateway error mapping → RunError / Gateway 边界类别 → UI 错误映射 |
| `ErrorEnvelope.error.message` | `string` | 必填 | 可展示的简短错误文本 | Gateway safe message → 当前请求结果 → UI；不含 secret、原始 endpoint 或路径 |
| `FiguraClientError.code` | `string` | 必填 | envelope code 或安全 client 网络/协议错误码 | `FiguraClient.request` / SSE handler → HTTP 结果或传输状态 → `toUserMessage`；无响应时用本地定义值 |
| `FiguraClientError.status` | `number` | 必填 | HTTP status；无响应时为 `0` | `FiguraClient.request` / SSE handler → Fetch/EventSource 结果 → UI 错误处理 |
| `FiguraClientError.message` | `string` | 必填 | 可展示错误说明，继承 `Error.message` | Client 从 envelope 或本地映射创建 → 前端错误映射；不附带原始异常 |
| `FiguraClientError.name` | `'FiguraClientError'` | 必填，固定 | 标识该前端错误类 | `FiguraClientError` constructor → 固定类名 → 前端错误诊断；不含服务端细节 |

## 5. 实现与规格索引

| 边界 | 当前代码 | 规格 |
|---|---|---|
| HTTP 路由、安全投影、恢复提交 | [Gateway application](../../src/figura/gateway/application.py)、[server / SSE](../../src/figura/gateway/server.py)、[projection](../../src/figura/gateway/web_projection.py)、[dispatcher](../../src/figura/gateway/dispatcher.py)、[删除协调](../../src/figura/gateway/session_deletion.py) | [Gateway 主规格](../../openspec/figura/openspec/specs/figura-web-gateway/spec.md) |
| React client、Panel gallery、Run tool timeline 与工作区映射 | [Figura client](../../frontend/src/api/figura/client.ts)、[workspace adapter](../../frontend/src/api/figura/workspace.ts)、[Web DTO types](../../frontend/src/api/figura/types.ts)、[FiguraApp](../../frontend/src/FiguraApp.tsx)、[PanelGallery](../../frontend/src/components/figura/PanelGallery.tsx)、[生成图 Gallery](../../frontend/src/components/figura/ChartRenderGallery.tsx)、[共享大图预览](../../frontend/src/components/preview.tsx)、[ToolTimeline](../../frontend/src/components/figura/ToolTimeline.tsx)、[timeline view model](../../frontend/src/domain/figura/timeline.ts)、[safe projection](../../src/figura/gateway/timeline_projection.py) | [Web client 主规格](../../openspec/figura/openspec/specs/figura-web-client/spec.md)、[Gateway 主规格](../../openspec/figura/openspec/specs/figura-web-gateway/spec.md) |
| 本地双进程 Launcher | [dev-figura.mjs](../../frontend/scripts/dev-figura.mjs)、[Gateway entrypoint](../../src/figura/gateway/__main__.py) | [Web client 主规格](../../openspec/figura/openspec/specs/figura-web-client/spec.md) |

Web Gateway 投影运行输入/最终答案、安全生命周期、已提交 Panel metadata 和有限的工具时间线摘要；它不能作为 Agent 完整 Memory、Provider 内部响应或工具审计的读取接口。截至 2026-10-02，工具时间线、Session 删除及生成图大图/下载相关 change 均已归档，OpenSpec CLI 未列出活动 change。PNG 渲染和预览已实现；来源证据、独立持久 ChartSpec、验证/发布和 Evaluation 的目标状态见[系统总览](../figura-implementation-overview.md#4-规划能力与边界)。
