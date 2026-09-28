# Web：Local Gateway 与 React Figura

> [返回系统总览](../figura-implementation-overview.md)。范围：当前 `src/figura/gateway/`、`src/figura/bootstrap.py`、`frontend/src/api/figura/` 与 `frontend/src/FiguraApp.tsx` 实现；附件和 Panel 源模型归[Sources](sources.md)，Agent 派生清单归[Agent](agent.md)，本篇拥有 Web DTO 与公开路由合同。主规格见 [Gateway](../../openspec/figura/openspec/specs/figura-web-gateway/spec.md) 和 [React Client](../../openspec/figura/openspec/specs/figura-web-client/spec.md)。`connect-figura-web-frontend`、`add-figura-panel-image-tools` 与模块结构调整 change 均已归档。

## 1. 职责与边界

Local Gateway 是 Python 进程内的 HTTP/SSE 边界，不是第二套 Session 或 Run 存储。`bootstrap.py` 负责组装并注入 Runtime、Sources、Agent、Provider 与 Tools；`gateway/application.py` 负责 HTTP 请求处理和安全投影。它把 JSON/图片请求交给 Runtime、Sources 与 ProviderFactory，再把有限的 Session、Run、事件、附件和已提交 Panel DTO 返回给浏览器。Run 创建持久化后由有界 Dispatcher 异步提交给既有 Agent；Gateway handler 不直接请求模型。当前 Registry 提供 `load_image` 和 `decompose_chart_image`；尚无测量和图表生成工具。

React Figura mode 通过 `FiguraClient` 负责 HTTP/SSE，再由 `FiguraWorkspaceApi` 映射到现有工作区协议和共享组件。React 组件不直接访问 Gateway；ChartAgent 与 Mock client 模式仍由其原有客户端提供。此边界目前是本地网页接入，没有 Tauri shell 接入。

```mermaid
flowchart LR
    UI[React Figura mode] -->|FiguraClient| Adapter[FiguraWorkspaceApi]
    Adapter -->|HTTP JSON / SSE| Gateway[Loopback Gateway]
    Gateway -->|Session / Run 读取与创建| Runtime[RunCoordinator / Store]
    Gateway -->|附件操作与图像内容| Sources[Sources services]
    Gateway -->|已提交 Panel 列表| ImageState[Agent RunExecutionState]
    Gateway -->|Panel PNG 内容| Sources
    ImageState -->|Panel metadata 与校验| Sources
    Gateway -->|配置可用性检查| Provider[ProviderFactory]
    Gateway -->|持久 Run 的异步提交| Dispatcher[有界 RunDispatcher]
    Dispatcher -->|execute(session_id, run_id)| Agent[AgentExecutor]
    Agent --> Runtime
    Sources -->|Attachment / Panel metadata| RuntimeDB[(共享 Figura SQLite)]
    Sources -->|私有附件与独立 Panel 图像| Files[(私有文件)]
    Runtime -->|Session / Run / 执行事实| RuntimeDB
    Runtime -->|Session snapshot / RunState / events| Gateway
    Provider -->|ProviderAvailability| Gateway
```

Gateway 只绑定 loopback，并验证浏览器 Origin 白名单。启动时进程环境优先于项目 `.env`；health 只检查本地 Provider 配置，不发送 Provider 请求。敏感配置、原始 endpoint、文件路径、continuation 和执行 payload 不进入公开 DTO。

## 2. 请求与返回流转

1. **启动本地网页栈**：`npm run dev:figura` 启动 Python Gateway 与 Vite；默认 Gateway 端口为 `8766`，Vite 为 `1421`。Launcher 等待 Figura health 成功后再启动网页，并在退出或启动失败时清理它启动的进程组。只有 Gateway 子进程读取项目 `.env`；Vite 只收到 Figura mode 和 Gateway URL 等前端配置，不继承 `FIGURA_*` 或凭据 endpoint/key 环境值。
2. **读取 Provider 与 Session**：`GET /health` 返回三个 allowlist Provider 的配置可用性及固定 model ID，不探测远端网络。Session 列表使用 Runtime 的 SQL 聚合；创建 Session 后，网页读取 Session 详情以取得消息、附件及 Run 投影。Web DTO 字段见[第 4 节](#4-web-dto-字段)，Runtime 的聚合读取值见[Run Runtime](runtime.md#4-完整模型字段)。
3. **上传、管理及读取分区图像**：浏览器向 Session attachment endpoint 上传原始字节并通过 query 传文件名；Gateway 委托 Sources 做媒体内容验证、大小限制、文件名净化和私有存储。浏览器只能在所属 Session 中列出、预览或删除；已被 Run 引用的附件不能删除。Run 输入保留有序附件 ID，图片字节不进入 Runtime 输入或 Web DTO。Panel 使用独立 Session-scoped list/content 路由；Agent 的 RunExecutionState 根据已提交成功分割结果筛选列表，Sources 提供 metadata 和 PNG 内容；图像读取返回 `image/png` 且不缓存。
4. **创建 Run**：浏览器提交 `text`、有序 `attachmentIds`、allowlist `providerId` 和 `Idempotency-Key`。浏览器不提交 model ID。Gateway 从 Provider allowlist 解析固定 model，Runtime 原子写入 Run、RunInput、初始 Checkpoint、幂等映射和创建事件后，Gateway 将其交给有界 Dispatcher 并返回 `202` Run handle。一个 Session 同时最多一个 running Run；同 key 同 payload 重放返回原 Run，key 冲突或 Session 已有不同 running Run 时返回安全错误。若本地 Dispatcher 暂时满，Run 可能已持久化而请求返回有界 `503`；使用原幂等键重试会复用该 Run 并尝试调度。
5. **执行与恢复**：Dispatcher 当前默认最多 3 个并发 worker、另有 8 个排队槽。Agent 从 Runtime checkpoint 执行，不确定的 Provider attempt 不自动重发，未解决的工具 attempt 不自动 replay。Gateway 启动时按 Session ID 和 Run ordinal 列出所有持久 running Run，再走相同 Dispatcher/Agent 路径；投影只有在 Run 仍 running 且下一动作要求 tool-attempt reconciliation 时才显示 `needs_reconciliation`。
6. **读取历史、Panel 和事件**：Session detail 从一个 Runtime SQLite 读快照生成消息、附件和 Run 投影；前端另调 Panel list route，按 `runId` 将 Panels 放到对应 Run 下，浏览器通过 Session-scoped content URL 懒加载 PNG。Run history 按 `afterSequence` 返回更大的事件序号；SSE 先重放游标后的持久事件，再跟随后续事件，并以 `runId:sequence` 作为事件 ID。终态事件送达后关闭流。前端 RunController 负责历史补读、游标合并和终态收敛；终态后重新加载 Session detail 与 Panel list。

Session Web message projection 与 Agent 的 [Session Memory](memory.md) 分离：前者仅显示每个 Run 的持久用户输入和已接受最终答案；后者还会把模型响应中的工具调用、工具结果投影成完整 Provider 对话，二者均从 Runtime 权威事实读取，但消费者和公开范围不同。

## 3. HTTP 与前端接口

所有 HTTP 路由位于 `/api/v1`。成功 JSON 响应使用 `application/json`；本地服务设置 `Cache-Control: no-store` 与 `X-Content-Type-Options: nosniff`。附件内容响应使用由内容检查确认的媒体类型并禁止缓存。请求体有界，Gateway 错误用 `{ "error": { "code": string, "message": string } }` 返回安全说明。

| 操作 | 请求合同 | 成功返回 | 行为边界 |
|---|---|---|---|
| `GET /health` | 无 | `FiguraHealth` | 配置检查，不做 Provider 网络请求 |
| `GET /sessions` | 无 | `{ sessions: FiguraSessionDto[] }` | 按最近活动降序；不逐 Run hydrate |
| `POST /sessions` | JSON object，`name?: string \| null` | `201 { session: FiguraSessionDto }` | 仅接收 `name`，不创建消息记录 |
| `GET /sessions/{sessionId}` | Session opaque ID | `FiguraSessionDataDto` | 读取同一 Session 的 snapshot |
| `GET /sessions/{sessionId}/panels` | Session opaque ID | `{ panels: FiguraPanelDto[] }` | 只返回对应成功分割结果已提交的 Panel |
| `GET /sessions/{sessionId}/panels/{panelId}/content` | Session 与 Panel opaque ID | 原始 Panel PNG 字节 | `image/png`、`no-store`；跨 Session 读取拒绝 |
| `GET /sessions/{sessionId}/attachments` | Session opaque ID | `{ attachments: FiguraAttachmentDto[] }` | 只返回元数据 |
| `POST /sessions/{sessionId}/attachments?filename=...` | 原始图片字节，恰好一个非空 `filename` query | `201 { attachment: FiguraAttachmentDto }` | Attachment Service 验证文件；不收 JSON 包装 |
| `GET /sessions/{sessionId}/attachments/{attachmentId}/content` | Session 与 attachment opaque ID | 原始已验证图片字节 | 跨 Session 访问不泄露附件是否存在 |
| `DELETE /sessions/{sessionId}/attachments/{attachmentId}` | Session 与 attachment opaque ID | `204` | 被 Run 引用时拒绝删除 |
| `POST /sessions/{sessionId}/runs` | JSON 恰含 `text: string`、`attachmentIds: string[]`、`providerId: FiguraProviderId`；必需 `Idempotency-Key` header | `202 { run: FiguraRunHandleDto }` | Gateway 固定 model ID；Runtime 先持久化，Dispatcher 后执行 |
| `GET /sessions/{sessionId}/runs/{runId}/history?afterSequence=N` | 可选非负整数 `afterSequence`，默认 `0` | `FiguraRunHistoryDto` | 只返回同 Session Run 的安全事件 |
| `GET /sessions/{sessionId}/runs/{runId}/events?afterSequence=N` | 可选非负整数游标，默认 `0` | `text/event-stream` | 按持久事件序号补发和跟随；终态后关闭 |

Gateway 拒绝不在明确白名单中的浏览器 Origin；Origin guard 对无 Origin 的 GET/HEAD 放行，其他无 Origin 请求不作为浏览器写操作放行。当前 API 不提供 Session 删除、Run retry/resume/interruption、评测工作区、测量或生成图表预览接口；Panel 预览使用上表的只读资源接口。

前端接口是 TypeScript 调用合同而非持久模型：`FiguraClient` 封装 HTTP/SSE 与 DTO，`FiguraWorkspaceApi` 将结果映射到兼容工作区协议，组件只调用后者。完整方法形状如下；其中 `Session`、`SessionData`、`Attachment`、`RunHandle`、`RunHistory`、`AgentRunEvent` 和 `RunSubscription` 继续使用现有前端协议类型。

| 接口成员 | TypeScript 合同 | 职责 |
|---|---|---|
| `FiguraClient.baseUrl` | `readonly string` | 本地 Gateway API base URL |
| `FiguraClient.getHealth()` | `Promise<FiguraHealth>` | 读取配置 health |
| `FiguraClient.listSessions()` | `Promise<FiguraSessionDto[]>` | 读取 Session 摘要 |
| `FiguraClient.getSession(sessionId: string)` | `Promise<FiguraSessionDataDto>` | 读取完整 Web Session snapshot |
| `FiguraClient.listPanels(sessionId: string)` | `Promise<FiguraPanelDto[]>` | 列出 Session 中已提交 Panels |
| `FiguraClient.createSession(name: string)` | `Promise<FiguraSessionDto>` | 创建 Session |
| `FiguraClient.listAttachments(sessionId: string)` | `Promise<FiguraAttachmentDto[]>` | 列出 Session 图片元数据 |
| `FiguraClient.uploadAttachment(sessionId: string, file: File)` | `Promise<FiguraAttachmentDto>` | 上传浏览器 `File` 原始字节 |
| `FiguraClient.deleteAttachment(sessionId: string, attachmentId: string)` | `Promise<void>` | 删除未被 Run 引用的图片 |
| `FiguraClient.startRun(sessionId: string, text: string, attachmentIds: string[], providerId: FiguraProviderId, idempotencyKey: string)` | `Promise<FiguraRunHandleDto>` | 提交 Run；固定模型由 Gateway 决定 |
| `FiguraClient.getRunHistory(sessionId: string, runId: string, afterSequence?: number)` | `Promise<FiguraRunHistoryDto>` | 从事件 cursor 读取持久历史 |
| `FiguraClient.subscribeRun(sessionId: string, runId: string, callbacks: { onEvent(event: AgentRunEvent): void; onError(error: Error): void; onComplete(): void }, afterSequence?: number)` | `RunSubscription` | 返回可关闭的 SSE 订阅 |
| `FiguraClient.attachmentContentUrl(sessionId: string, attachmentId: string)` | `string` | 生成 Session-scoped image content URL，不取代 Gateway ownership check |
| `FiguraClient.panelContentUrl(sessionId: string, panelId: string)` | `string` | 生成 Session-scoped Panel PNG URL，读取时由 Gateway 校验 Session 归属 |
| `FiguraWorkspaceApi.health.get()` | `Promise<FiguraHealth>` | 向应用提供 health |
| `FiguraWorkspaceApi.sessions.list()` / `get(sessionId: string)` / `create(name: string)` | `Promise<Session[]>` / `Promise<SessionData>` / `Promise<Session>` | 对应列表、详情与创建，并映射兼容 Session 类型 |
| `FiguraWorkspaceApi.attachments.list(sessionId: string)` / `upload(sessionId: string, file: File)` / `remove(sessionId: string, attachmentId: string)` | `Promise<Attachment[]>` / `Promise<Attachment>` / `Promise<void>` | 对应图片列表、上传、删除并映射 preview URL |
| `FiguraWorkspaceApi.panels.list(sessionId: string)` / `contentUrl(sessionId: string, panelId: string)` | `Promise<FiguraPanelDto[]>` / `string` | 获取 Panel DTO 并构造延迟读取用的 PNG URL；组件通过 Figura workspace callback 展示 |
| `FiguraWorkspaceApi.runs.start(sessionId: string, text: string, attachmentIds: string[], providerId: FiguraProviderId, idempotencyKey: string)` / `history(sessionId: string, runId: string, afterSequence?: number)` / `subscribe(sessionId: string, runId: string, callbacks, afterSequence?: number)` | `Promise<RunHandle>` / `Promise<RunHistory>` / `RunSubscription` | 对应 Run 提交、事件历史和 SSE 订阅；subscribe callbacks 与 `FiguraClient.subscribeRun` 相同 |

实现见 [`client.ts`](../../frontend/src/api/figura/client.ts)、[`workspace.ts`](../../frontend/src/api/figura/workspace.ts) 与 [`types.ts`](../../frontend/src/api/figura/types.ts)。

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

`FiguraRunDto` 是 Session/history 的安全 Run projection；其运行字段来源为 Runtime `Run`，`executionState` 根据 Run status 和 Checkpoint 下一动作计算。写入者为 `web_projection.run_summary`；读者为 workspace timeline 和 run controller。`FiguraRunHandleDto` 是 start 返回的同一投影但省略 `executionState`，有效字段完整列于下表所引用的前 11 行。

| 完整字段路径 | JSON 类型 | 必填/默认 | 含义与约束 | 写入者 → 权威来源 → 读取/公开规则 |
|---|---|---|---|---|
| `FiguraRunDto.runId` | `string` | 必填 | opaque Run ID | run projection → `Run.run_id` → timeline/controller；Session-scoped route 仍校验归属 |
| `FiguraRunDto.sessionId` | `string` | 必填 | 所属 Session opaque ID | run projection → `Run.session_id` → timeline/controller |
| `FiguraRunDto.ordinal` | `number` | 必填 | Session 内从 1 开始的 Run 顺序 | run projection → `Run.ordinal` → timeline 排序 |
| `FiguraRunDto.status` | `'running' \| 'completed' \| 'failed' \| 'interrupted'` | 必填 | 持久 Run 生命周期状态 | run projection → `Run.status` → UI 状态；只有列出的终态/活动态 |
| `FiguraRunDto.provider` | `FiguraProviderId` | 必填 | 创建时固定 Provider | run projection → `Run.provider` → timeline；allowlist 字符串 |
| `FiguraRunDto.model` | `string` | 必填 | 创建时固定 model ID | run projection → `Run.model` → timeline；只读，不接受浏览器修改 |
| `FiguraRunDto.createdAt` | `string` | 必填 | Run 创建 UTC 时间 | run projection → `Run.created_at` → timeline |
| `FiguraRunDto.startedAt` | `string` | 必填 | Agent 开始时间 | run projection → `Run.started_at` → timeline |
| `FiguraRunDto.finishedAt` | `string \| null` | 必填，可空 | 尚未终结时为空 | run projection → `Run.finished_at` → timeline |
| `FiguraRunDto.terminalCode` | `string \| null` | 必填，可空 | 持久安全终态原因码；活动 Run 为空 | run projection → `Run.terminal_code` → UI 安全状态；不含异常堆栈 |
| `FiguraRunDto.terminalMessage` | `string \| null` | 必填，可空 | 可安全显示的终态说明 | run projection → `Run.terminal_message` → UI；无终态时为空 |
| `FiguraRunDto.executionState` | `'active' \| 'needs_reconciliation'` | 必填 | `needs_reconciliation` 当且仅当 Run 仍 running 且 checkpoint action 是 `TOOL_ATTEMPT`；否则为 `active` | `run_summary` → Run + ExecutionCheckpoint → UI reconciliation 状态；纯派生，不写回 Runtime |

`FiguraRunHandleDto = Omit<FiguraRunDto, 'executionState'>` 的完整字段为 `runId`、`sessionId`、`ordinal`、`status`、`provider`、`model`、`createdAt`、`startedAt`、`finishedAt`、`terminalCode`、`terminalMessage`；每字段类型、来源与公开规则与 `FiguraRunDto` 相同。Handle 由 `web_projection.run_handle` 从 `Run` 生成。

### `FiguraEventDto` 与 `FiguraRunHistoryDto`

Event DTO 由 `web_projection.event_projection` 生成，Runtime [`RunStreamEvent`](runtime.md#4-完整模型字段) 是持久事件来源。SSE 的 `id` 行使用 `{runId}:{sequence}`；数据字段不包含执行内容原文。

| 完整字段路径 | JSON 类型 | 必填/默认 | 含义与约束 | 写入者 → 权威来源 → 读取/公开规则 |
|---|---|---|---|---|
| `FiguraEventDto.runId` | `string` | 必填 | 事件所属 Run ID | event projection → RunState.run ID → controller 按 Run 合并 |
| `FiguraEventDto.sequence` | `number` | 必填 | Run 内单调事件序号 | event projection → `RunStreamEvent.event_sequence` → history/SSE cursor |
| `FiguraEventDto.kind` | `string` | 必填；当前仅 `run_created`、`run_completed`、`run_failed`、`run_interrupted` | 生命周期事件 kind | event projection → `RunStreamEvent.event_kind` → UI 更新状态；其值集合见 Runtime 枚举 |
| `FiguraEventDto.timestamp` | `string` | 必填 | 事件创建时间 | event projection → `RunStreamEvent.created_at` → timeline |
| `FiguraEventDto.payload` | `Record<string, unknown>` | 必填 | allowlist payload：created 为 `{ordinal}`，completed 为空对象，failed/interrupted 为 `{terminalCode}` | event projection → Runtime 安全事件 + Run summary → UI；不含 input、模型内容、工具 payload 或 continuation |
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
| HTTP 路由、安全投影、恢复提交 | [Gateway application](../../src/figura/gateway/application.py)、[server / SSE](../../src/figura/gateway/server.py)、[projection](../../src/figura/gateway/web_projection.py)、[dispatcher](../../src/figura/gateway/dispatcher.py) | [Gateway 主规格](../../openspec/figura/openspec/specs/figura-web-gateway/spec.md) |
| React client、Panel gallery 与工作区映射 | [Figura client](../../frontend/src/api/figura/client.ts)、[workspace adapter](../../frontend/src/api/figura/workspace.ts)、[Web DTO types](../../frontend/src/api/figura/types.ts)、[FiguraApp](../../frontend/src/FiguraApp.tsx)、[PanelGallery](../../frontend/src/components/figura/PanelGallery.tsx) | [Web client 主规格](../../openspec/figura/openspec/specs/figura-web-client/spec.md) |
| 本地双进程 Launcher | [dev-figura.mjs](../../frontend/scripts/dev-figura.mjs)、[Gateway entrypoint](../../src/figura/gateway/__main__.py) | [Web client 主规格](../../openspec/figura/openspec/specs/figura-web-client/spec.md) |

Web Gateway 投影运行输入/最终答案、安全生命周期和已提交 Panel metadata；它不能作为 Agent 完整 Memory、Provider 内部响应或工具审计的读取接口。来源证据、持久 ChartSpec、渲染/验证/发布和 Evaluation 的目标状态见[系统总览](../figura-implementation-overview.md#4-规划能力与边界)。
