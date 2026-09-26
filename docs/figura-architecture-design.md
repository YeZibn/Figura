# Figura Architecture v1

> 文档状态：系统设计草案，尚未实现。基线：2026-09-24 的 ChartAgent v1。本文集中说明 Figura 的总体结构、各子系统职责、关键字段及完整流转。

## 1. 背景、范围与设计目标

Figura 延续 ChartAgent 的核心产品流程：用户提交问题和图表附件，Agent 选择工具取得观察和测量证据，组织 ChartSpec，生成图表，并在验证后发布。新系统重新定义状态归属和各组件之间的数据契约。

ChartAgent v1 已覆盖这条产品链路，但运行状态分布在多个相近对象中：

- Agent Memory 的 Run 与 Gateway 的 ManagedRun 都保存运行身份和终态。
- Memory records 与 execution records 保存了形状不同、用途相近的执行内容。
- RunExecutionContext 混合持久数据、恢复字典、临时模型消息、工具 Schema、产物索引与 trace 协作者。
- `artifact_records` 与 `current_output_artifacts` 同时描述产物；自然语言 `pending_action` 容易和恢复游标的 `next_action` 混淆。
- Panel、measurement、generation context、图像状态会复制到 runtime、prompt、timeline 和 API 投影中。

ChartAgent 当前实现的详细事实见 [current-architecture-analysis.md](current-architecture-analysis.md)。Figura 保留产品行为和安全约束，避免复制这些状态重叠。

### 1.1 已确定的项目边界

| 事项 | 约定 |
|---|---|
| ChartAgent v1 | `src/chartagent/` 与现有后端继续服务原有 ChartAgent 会话 |
| Figura 实现 | 新代码放在独立的 `src/figura/` 包 |
| 旧数据 | ChartAgent 会话、附件、运行记录和产物不导入 Figura |
| 存储 | Figura 使用独立 SQLite 和受管文件目录；默认由 `FIGURA_DATA_DIR` 指定，与 `.chartagent/` 分离 |
| 前端 | 继续使用当前 React/Vite 工作区，同时提供 ChartAgent v1 与 Figura；不另建 Figura 前端 |
| 模型与代码 | 模型选择普通分析、证据和修正路径；代码负责来源授权、Schema、执行记录、恢复、验证与发布边界 |

### 1.2 设计目标

- 一个领域事实只有一个权威所有者；history、prompt、timeline、recovery 和 evaluation 都从事实投影。
- Agent 应用层统一创建、推进、终止和恢复 Run；Gateway 只承担传输及 DTO 转换。
- RunExecutionContext 保持精简、只读，提供本次动作需要的运行数据。
- 保留附件理解、panel/measurement、ChartSpec、生成图验证和发布能力。
- 字段、标识符、时间、状态和内部/外部序列有统一含义。

本设计不重做前端、不另建 Figura 前端，也不包含旧数据迁移、任意代码指令级恢复，且不保证 provider 请求只计费一次。Figura 不添加长期双读、双写适配层。

## 2. 总体架构

~~~mermaid
flowchart LR
    UI[当前 React/Vite 工作区<br/>ChartAgent 与 Figura 共用] --> CAC[ChartAgent 前端适配器]
    UI --> FAC[Figura 前端适配器]
    CAC --> OLD[ChartAgent v1]
    FAC --> FIGAPI[Figura Gateway / Application API]
    FIGAPI --> ER[Execution Runtime]
    CLI[Figura CLI] --> ER
    EV[Evaluation Driver<br/>普通 Run 请求] --> ER
    ER <--> AG[Agent Core]
    AG --> MEM[Memory System]
    AG --> PLAN[Planning System]
    ER --> STORE[(Figura SQLite<br/>与 ArtifactStore)]
    MEM --> STORE
    EV -->|只读事实与事件投影| STORE
~~~

箭头表示依赖或数据读取关系。Execution Runtime 是 Run 生命周期与持久化边界；Agent Core 执行模型和工具；Memory System 将已提交事实变成对话与模型上下文；Planning System 定义模型决策所需信息和规则；Evaluation System 通过普通入口运行诊断，再只读分析结果。

| 子系统 | 主要职责 | 自己不拥有的状态 |
|---|---|---|
| Execution Runtime | Session/Run 生命周期、执行事实、checkpoint、事务、恢复、公开事件 | 不维护第二份 Gateway Run 状态或模型消息数组 |
| Agent Core | AgentExecutor、工具、来源校验、证据、ChartSpec、图像验证和发布 | 不拥有独立 Run 生命周期，不保存平行 recovery snapshot |
| Memory System | RunExecutionContext、history、ArtifactIndex 投影、PromptBundle 装配 | 不建立另一份 AgentMemory 事实数据库 |
| Planning System | 模型输入、证据选择/生成约束、预算、GenerationContext 语义 | 不维护强制阶段队列或完整 decision_context 副本 |
| Evaluation System | 诊断样本、隔离批次、时间线、报告与汇总 | 不绕过 Runtime 写 Run，也不把诊断结果写回在线 Agent |

### 2.1 前端复用与后端适配

Figura 后续仍由当前 React/Vite 前端承载，与 ChartAgent v1 共用同一个工作区、应用入口和前端代码库。前端不会拆成两个独立应用，也不会为 Figura 复制一套工作区。Figura 的专属页面或交互需要时，作为现有前端中的新能力加入。

前端复用不改变后端和数据边界：ChartAgent v1 与 Figura 仍是两个独立后端，各自拥有自己的 Session、Run、附件和产物存储；历史数据不导入 Figura。前端通过后端适配器连接目标服务：现有 ChartAgent 调用继续走既有 `ChartAgentClient`、`gatewayClient` 与协议类型，Figura 增加对应的 Figura adapter，连接 Figura Gateway/Application API。两边语义相同的界面能力可以共用前端组件；不同的 Run 生命周期和事件语义留在各自适配器及协议映射内，不为共用 UI 强行合并后端模型。

每个新建的会话都绑定到明确的后端目标。会话详情、历史、附件、Run 操作、SSE 订阅和断线续读均沿用该绑定，不能根据可能重复的 opaque ID 猜测服务目标。共享的是用户界面与可复用的展示组件，不是会话、附件、运行记录或产物数据。

本设计确定“复用当前前端、不另建 Figura 前端”；同一工作区内 Figura 的入口位置和会话创建交互仍可在前端接入阶段决定。

### 2.2 关键组件关系

| 对象 | 生命周期 | 作用 |
|---|---|---|
| `FiguraRuntime` | 进程级 | 组合 settings、repositories、ArtifactStore、provider factory、ToolRegistry、RunCoordinator；不放单次 Run 数据 |
| `RunCoordinator` | 应用服务级 | 唯一 Run 生命周期写入者，负责启动、中断、完成、失败、retry 和显式 resume |
| `AgentExecutor` | 每次执行 | 读取 checkpoint、调用模型或工具、提交对应执行结果 |
| `RunExecutionContext` | 单次 Run 的只读快照 | 给 Agent、Memory 和 Planning 提供当前已授权上下文；不是 checkpoint |
| CLI / Gateway | 请求或进程 adapter | 调用相同 Application API；Gateway 不保存第二份可变状态 |
| Evaluation Driver / Reader | 批次级 / 读取级 | Driver 发起普通 Run；Reader 只读安全投影 |

### 2.3 本文结构

| 章节 | 范围 |
|---|---|
| [Execution Runtime Design](#4-execution-runtime-design) | Run、ExecutionRecord、Checkpoint、恢复、事务与 DTO |
| [Agent Core Design](#5-agent-core-design) | 工具、Panel、测量、ChartSpec、验证和发布 |
| [Memory System Design](#6-memory-system-design) | 上下文、对话历史、产物索引、提示词装配 |
| [Planning System Design](#7-planning-system-design) | 决策输入、GenerationContext、预算和门槛 |
| [Evaluation System Design](#8-evaluation-system-design) | 样本、批次、诊断时间线和报告 |

## 3. 命名体系、数据所有权与字段落位

本章是全文的数据字典入口。后续章节出现的字段都必须归属于这里登记的对象，或在对象的详细字段表中声明为嵌套字段。字段第一次出现时使用完整路径，例如 `ExecutionCheckpoint.next_action.action_kind`；后文可以在上下文明确时简写为 `next_action`。不允许只写一个字段名而没有说明它属于哪个对象。

### 3.1 名称层级

Figura 按“持久事实、运行控制、派生读模型、单次调用对象、对外协议”区分名字。它们不是同一类对象，不能都命名成 `State`、`Context` 或 `Event`。

~~~text
持久领域对象：Session、Attachment、Run
持久执行事实：ExecutionRecord[]
持久推进控制：ExecutionCheckpoint
可重建读模型：RunExecutionContext、ArtifactIndex、ConversationHistory、DiagnosticTimeline
单次调用对象：ToolExecutionContext、PromptBundle、ModelRequest
对外协议投影：RunSummary、RunStreamEvent、RunResumeAvailability
进程组件：FiguraRuntime → RunCoordinator → AgentExecutor
~~~

权威流转关系：

~~~mermaid
flowchart LR
    INPUT[请求与授权附件] --> RC[RunCoordinator]
    RC --> RUN[(Run)]
    RC --> REC[(ExecutionRecord)]
    RC --> CP[(ExecutionCheckpoint)]
    RC --> EV[(RunStreamEvent)]
    REC --> VIEW[可重建读模型]
    CP --> VIEW
    VIEW --> CTX[RunExecutionContext]
    CTX --> AG[AgentExecutor]
    AG --> PROVIDER[Provider / Tool]
    PROVIDER --> REC
    REC --> INDEX[ArtifactIndex / ConversationHistory / Timeline]
    RUN --> DTO[RunSummary / RunResumeAvailability]
    EV --> CLIENT[Gateway SSE]
~~~

`ExecutionRecord` 是事实日志；`ExecutionCheckpoint` 是与事实日志原子更新的推进点；`RunExecutionContext` 是每一步从 Run、记录、来源和配置重建的临时视图。Checkpoint 不复制 messages 或完整业务状态，也不取代 Run 的生命周期状态。模型轮次和预算计数由有效执行记录派生，不另存一个可漂移计数。Read model 和 DTO 均可重建，不反向成为事实来源。

### 3.2 权威对象与字段存储目录

#### 跨章节共用引用和值对象

以下类型供多个模块共用。它们定义字段形状和定位语义；实体身份仍归属各自的持久事实，不因引用而复制完整对象。

| 对象及字段路径 | 类型/约束 | 存储与用途 |
|---|---|---|
| AttachmentRef.attachment_id | Attachment ID，必填 | 引用附件实体 |
| AttachmentRef.content_sha256 | SHA-256，必填 | 将引用绑定到确切上传字节；读取时与 Attachment 当前 hash 比较 |
| PanelRef.panel_id | Panel ID，必填 | 引用逻辑 Panel |
| PanelRef.revision | 正整数，必填 | 锁定不可变 PanelRecord 修订 |
| PanelRef.attachment_id | Attachment ID，必填 | 锁定原始图像归属 |
| PanelRef.attachment_content_sha256 | SHA-256，必填 | 锁定该 Panel 修订分析的原图字节 |
| SourceRef.source_kind | attachment / panel，必填 | 判别来源引用联合类型 |
| SourceRef.attachment | AttachmentRef，仅 source_kind=attachment 时必填 | 引用原图附件 |
| SourceRef.panel | PanelRef，仅 source_kind=panel 时必填 | 引用 panel 修订 |
| ArtifactRef.ref_kind | managed_blob / staged_chart / published_artifact，必填 | 受控资源种类，不表示文件系统路径 |
| ArtifactRef.ref_id | 不透明字符串，必填 | 受控应用层 locator；是否可读取仍由 Session/Run 权限校验 |
| ChartObjectRef.object_kind | chart_spec / chart_figure / chart_spec_collection，必填 | 区分可提交给 render_chart 的图表对象种类；不是文件引用 |
| ChartObjectRef.object_id | 对应领域对象 ID，必填 | 精确指向已提交 ChartSpec、ChartFigure 或 ChartSpecCollection |
| Warning.code | 受控字符串，必填 | 稳定机器可识别警告类别 |
| Warning.severity | info / warning，必填 | 展示严重程度；不是 Run 终态 |
| Warning.message | 有界文本，必填 | 经脱敏的用户可读解释 |
| Warning.object_path | 字段路径，可空 | 指向受影响的结构化字段，不包含任意本机路径 |
| Scope / Target / Quality | 由 ToolDefinition 对应工具的版本化 parameters/result Schema 定义 | 每个工具的 scope、测量目标和质量语义都必须在该工具合同内明确；不设含义不清的全局自由 JSON |

SourceRef 只引用附件或 panel；EvidenceRef 是独立的证据事实身份，不作为 SourceRef 的递归 variant。AttachmentRef/PanelRef 中的 hash 和 revision 是引用绑定条件，不能用同名但当前已变化的资源悄悄替换。工具专用 Scope/Target/Quality 若新增字段，必须登记在对应 ToolDefinition Schema 与 tool_result payload 版本下，不得作为未声明自由键透传。

下表说明每类字段的唯一权威位置。各章节继续解释字段含义、可空条件和校验规则。SQLite 字段可以通过列或版本化 JSON 表示；即使物理 schema 归一化实现不同，逻辑所有权不得改变。

| 对象及字段路径 | 权威位置 / 持久化 | 创建或更新者 | 读取者与对外边界 |
|---|---|---|---|
| `Session`: `session_id`、`name`、`created_at`、`updated_at` | `sessions` 表；Session 元数据 | Session application service；更新名称时更新 `updated_at` | Session 查询和 `SessionSummary`；Run/Attachment 只引用 `session_id`，不重复保存会话元数据 |
| `Attachment`: `attachment_id`、`session_id`、`filename`、`media_type`、`byte_count`、`content_sha256`、`storage_key`、`status`、`deleted_at`、`created_at` | 元数据在 `attachments` 表；原始文件在 Figura `ArtifactStore`；`storage_key` 仅内部存在 | Attachment application service；删除先改 metadata status，再按保留策略清理文件 | 来源授权与工具读取；公开 DTO 可显示安全元数据，禁止暴露 `storage_key` 或文件字节 |
| `Run`: `run_id`, `session_id`, `ordinal`, `input_record_id`, `status`, `provider`, `model`, `prompt_bundle_version`, `tool_registry_version`, `verification_policy_version`, `execution_policy_version`, `execution_limits`, `parent_run_id`, `parent_record_sequence`, `continuation_kind`, `lifecycle timestamps`, `terminal fields`, `final_record_id` | `runs` 表；Run 生命周期、运行版本和冻结限额的唯一来源 | Agent application layer 的 `RunCoordinator` 唯一写入状态变迁 | `RunSummary`、恢复资格计算、查询；Gateway 不保存可变副本 |
| `RunInput`: `text`、`attachment_ids`、`requested_provider`、`requested_model`、`schema_version` | `ExecutionRecord.payload`，且该记录的 `record_kind=input`；只写一次 | 请求校验后由 `RunCoordinator` 写入；图片字节只留在 Attachment store | `RunExecutionContext`、ConversationHistoryReader；公开查询按权限投影，不能把输入另存成第二份 Run 字段 |
| `ExecutionRecord`: `record_id`、`run_id`、`record_sequence`、`record_kind`、`work_key`、`payload`、`created_at` | `run_execution_records` 表；按 Run 有序追加，不原地改写 | `RunCoordinator` 提交初始/终态事实；Agent 经 Runtime commit port 提交模型、工具、验证和发布事实 | 恢复、历史、ArtifactIndex、评测 reader；私有 payload 不直接进入 SSE |
| `ExecutionCheckpoint`: `run_id`、`last_committed_record_sequence`、`next_action`、`schema_version`、`updated_at` | `run_execution_checkpoints` 表；每个 Run 一份最新检查点，与新记录在同一事务更新 | Runtime 的执行提交服务；不由 Gateway 或 Memory 单独更新 | AgentExecutor、显式 resume 校验、RunResumeAvailability；只公开最小 `checkpoint_id`，不公开私有动作 payload |
| `RunStreamEvent`: `run_id`、`event_sequence`、`event_kind`、`payload`、`created_at` | `run_stream_events` 表兼作可重放事件日志/outbox；每个 Run 独立序号 | RunCoordinator/Runtime 在事实提交事务中创建安全事件；Gateway 只投递 | SSE、客户端时间线和 Evaluation Reader；payload 受白名单、长度和脱敏规则限制 |
| `RunIdempotency`: `session_id`、`idempotency_key_digest`、`request_fingerprint`、`run_id`、`created_at`、`expires_at` | `run_idempotency` 表；仅保存键摘要和请求指纹，不保存重复请求正文 | `RunCoordinator` 创建 Run 的同一事务写入 | 重复请求查找和冲突检测；不进入提示词或公开事件 |
| `ExecutionPolicy` | 版本化进程配置；定义 model_steps_limit、chart_attempts_limit、provider_retry_limit | FiguraRuntime 启动时解析；Run 创建时将版本与限额快照固定到 Run | RunCoordinator、BudgetSnapshot builder；不直接注入模型 |
| `ToolRegistry` | FiguraRuntime 进程配置；registry_version、definitions_by_name、allowed_tool_names[] | 版本化代码与权限策略组装；Run 创建后版本固定 | PromptAssembler、AgentExecutor；本 Run 只使用授权工具子集 |
| `ToolDefinition` | 进程级不可变 `ToolRegistry`；含 `name`、`summary`、`prompt_guidance`、模型输入 `parameters`、内部 `result_schema` / `result_schema_version`、内部 `handler`、`display_name`、`group`、`budget_category`、`replay_effect` | FiguraRuntime 根据版本化代码/配置组装；运行期间不可变 | 已授权工具的摘要/指导和参数 Schema 进入 ModelRequest；`handler`、凭证和实现细节绝不对模型/客户端公开 |
| `Observation`、`EvidenceRef`、`PanelRecord`、`MeasurementAttempt`、`ChartSpec`、`ChartFigure` | 逻辑事实在对应 `ExecutionRecord.payload` 的类型化子对象中；超出内嵌上限的结构化内容以 `payload_ref` 指向 `ArtifactStore` 中的版本化 JSON blob | AgentExecutor 调用工具后提交；Panel/Chart 新版本追加新记录，不覆盖已提交版本 | PanelReadModel、ArtifactIndex、PromptAssembler、guard；只投影有界摘要，完整内容按 ID/ref 读取 |
| `ArtifactManifest` | `artifact_manifests` 表；登记受管 JSON blob/生成图文件及 ArtifactStore locator | ArtifactStore application service；文件原子落盘后登记 | ArtifactRef resolver、StagedChartManifest、授权读取；`storage_key` 永不外露 |
| `StagedChartManifest` | `staged_chart_manifests` 表；持有图像 manifest 与 ChartSpec/来源/生成操作的绑定 | staging service；与图像 ArtifactManifest 及对应 render tool_result ExecutionRecord 同一 DB 事务 | Verifier、Promotion、授权预览；不复制图像字节或底层 locator |
| `VerificationResult`、`PublishedArtifact` | 分别作为 `record_kind=verification_result`、`record_kind=promotion_result` 的 `ExecutionRecord.payload` 子对象；不是独立可变状态表 | Verifier 结果由 Runtime 提交；Promotion 由 Runtime 复核并幂等提交 | ArtifactIndex、最终回答 guard、RunSummary/安全 DTO 的受限投影 |
| `RunExecutionContext`、`SourceAuthorizationScope`、`ArtifactIndex`、`ConversationHistory`、`BudgetSnapshot` | 内存中的可重建读模型；不作为权威数据库行 | Memory/read-model builders 从 Run、ExecutionRecord、Checkpoint、Attachment 和 manifest 构建 | AgentExecutor、Planning、PromptAssembler；只有白名单字段摘要进入模型提示词 |
| `ToolExecutionContext`、`PromptBundle`、`ModelRequest`、`HistoryMessage[]` | 一次工具/模型调用的临时对象；历史消息从 ExecutionRecord 重建，不单独持久化 | AgentExecutor、Memory System 和 Provider adapter | 当前 handler/provider；日志仅写经过脱敏的诊断信息 |
| `RunSummary`、`RunResumeAvailability`、`RunStreamEventDto`、`RunStreamGapNoticeDto` | Gateway 协议投影；不构成第二份业务状态 | DTO mapper 从权威对象/安全事件转换 | 当前共享前端、CLI；`RunResumeAvailability` 是计算结果，不是 Run status |
| `EvaluationManifest` | 受控评测 asset root 下的版本化 JSON 文件 | 评测调用方提供；Driver 先校验再运行 | EvaluationDriver；只含相对资源路径、hash 和期望提示 |
| `EvaluationBatch`、`EvaluationCase` | 隔离评测目录中的 `evaluation.sqlite3` 元数据；每个 batch 的 Run 数据另存在其独立 runtime root | EvaluationDriver 创建/推进 case 元数据 | EvaluationReader、报告生成；不写回在线用户 Run |
| `DiagnosticTimeline`、`DiagnosticReport` | 从评测 Run 事实生成；JSON/Markdown 报告放在该 batch 的 `reports/`，报告路径由 `report_ref` 定位 | EvaluationReader | 评测 UI/CLI；报告是诊断投影，不是在线 Agent 的权威事实 |

`ArtifactStore` 保存受管文件字节；`ArtifactManifest` 是文件元数据行；`StagedChartManifest` 将一张生成图的文件元数据绑定到 ChartSpec 和来源；`ArtifactIndex` 是面向 Agent/Memory 的可重建索引；`PublishedArtifact` 是验证后正式交付的领域身份。它们分别负责字节、存储定位、暂存图业务关联、查询索引和正式发布，不互相替代。附件自身的 metadata 仍归 attachments 表。

### 3.3 临时对象与派生字段

| 对象/字段 | 从哪里派生 | 何时创建 | 是否持久化/注入模型 |
|---|---|---|---|
| `RunSnapshot` | `Run` 行中本次调用需要的身份、状态和配置字段 | 每次创建 RunExecutionContext 时 | 不单独保存；按字段白名单进入 PromptBundle |
| `SourceAuthorizationScope` | `RunInput.attachment_ids`、Attachment 所有权/状态/hash、PanelReadModel 的 panel revision | 每次动作前重新校验 | 不持久化；只列已授权来源和可用 panel 摘要给模型 |
| `ArtifactIndex` | 当前有效 record 前缀、父 Run 固定前缀、manifest、验证和发布事实 | 每次上下文构建或查询缓存未命中时 | 不持久化；提示词只拿摘要，guard 查询完整索引 |
| `ConversationHistory` / `HistoryMessage[]` | 完成的历史 Run 和当前 Run 的 ExecutionRecord 顺序 | 每次模型请求前 | 不单独保存；以原角色消息发送给 Provider |
| `BudgetSnapshot` | Run execution config、策略限制和已提交 `model_response` 数与 budget_category=chart_attempt 的 ToolCall 数 | 每次动作前 | 不持久化；模型看到 remaining 值，Runtime 执行前再次硬校验 |
| `ToolExecutionContext` | `NextAction`、已校验 tool call 参数、SourceAuthorizationScope、取消令牌 | 每次执行单个 handler 前 | 不持久化；只传当前 handler |
| `RunExecutionContext` | RunSnapshot、ExecutionCheckpoint、授权来源、ArtifactIndex、BudgetSnapshot 和运行中的取消请求 | 每次模型决策或工具动作前 | 不持久化；Agent/Memory/Planning 消费，PromptAssembler 按字段投影 |
| `PromptBundle` / `ModelRequest` | Prompt assets、RunExecutionContext、ToolDefinition 和 ConversationHistory | 每次 provider 请求前 | 不作为 Run 字段保存；可另记版本号和脱敏诊断摘要 |
| `RunResumeAvailability` | Run 终态、ExecutionCheckpoint、来源完整性和 `replay_effect` 校验 | API 查询或用户请求 resume 时 | 不持久化；只输出 `can_resume`、`checkpoint_id` 和有界原因码 |
| `PanelReadModel`、`DiagnosticTimeline` | PanelRecord/Observation/MeasurementAttempt、ExecutionRecord 与 RunStreamEvent | 查询/评测时 | 可丢弃重建；不得成为原始事实来源 |

### 3.4 跨模块字段命名规则

| 语义 | 规范 | 示例与边界 |
|---|---|---|
| 对象路径 | 新字段首次出现必须写 `Object.field`；嵌套字段写完整路径 | `ExecutionCheckpoint.next_action.action_kind`、`RunInput.attachment_ids` |
| 身份 | `*_id` 是 Figura 内实体身份 | `run_id`、`record_id`、`panel_id`、`artifact_id` |
| 跨对象/存储引用 | `*_ref` 是受控 locator 或不可变资源引用，不等同于实体主键 | `staged_ref`、`verification_ref`、`payload_ref`；路径和 `storage_key` 不对外 |
| 顺序号 | 不同序列使用有语义的名字，不共用泛化 `sequence` | `record_sequence`、`event_sequence`、`ordinal`；Run内记录号与SSE事件号永不互换 |
| 判别字段 | 每种联合类型都用类型限定字段名 | `record_kind`、`action_kind`、`event_kind`、`artifact_kind`；不在整个系统盲目替换成 `type` |
| 生命周期 | `status` 只描述对象自身状态，不用 `kind` 表达终态 | Run.status 与 VerificationResult.status 各有自己的枚举 |
| 行为选择 | `mode` 表示策略模式；`role` 表示参与者/图表面板角色；`source` 表示用户可读来源名称 | 与 `status`、`*_kind` 分开 |
| 内容校验 | 原始文件字节使用 `*_sha256`；规范化 JSON/Schema 的一致性校验使用 `*_digest` | `content_sha256`、`image_sha256`、`chart_spec_digest` |
| 时间 | 持久时间统一 UTC aware datetime；API 输出 ISO 8601 UTC | `created_at`、`finished_at`，不存本地时区字符串 |
| 可空与派生 | nullable、可选、默认值、计算方式都必须在字段表标明 | `final_record_id` 仅在终态存在；`root_run_id` 由 lineage 派生，不默认持久化 |

工具请求的 `requested_scope` 只保留在对应 ToolCall.arguments 中，`effective_scope` 是工具实际执行范围（未指定子范围时为完整 source_ref），`observation_scope` 是结果实际观察到的范围；`RunExecutionContext.authorized_source_scope` 是代码允许访问的来源上限，`GenerationContext.selected_source_scope` 是生成时用于覆盖评估的候选来源集合。`ChartSpec.provenance.source_refs` 是图表实际数据来源，`provenance.evidence_refs` 是实际支撑图表的证据。



## 4. Execution Runtime Design

### 职责与边界

Execution Runtime 接收一个用户请求，将它表示为一个 `Run`，按已提交的 `ExecutionCheckpoint` 推进动作，并让每个对外可见结果对应可重建的执行事实。Run 的状态由 Agent 应用层的 `RunCoordinator` 统一写入。CLI、Gateway 和 Evaluation Driver 都调用同一 Application API。

| 组件 | 生命周期 | 职责 |
|---|---|---|
| `FiguraRuntime` | 进程级 | 组合配置、repositories、ArtifactStore、provider factory、不可变 ToolRegistry 和 RunCoordinator；不保存某个 Run 的消息或 panel |
| `RunCoordinator` | 应用服务 | 创建、启动、中断、完成、失败、retry 与显式 resume；唯一写入 Run 生命周期 |
| `AgentExecutor` | 一次执行调用 | 根据 checkpoint 请求模型或调用工具，提交执行结果；不保留第二份 Run 状态 |
| `RunContextFactory` | 每次动作前 | 从已提交事实和授权来源构建只读 RunExecutionContext，详见 Memory System Design |
| Gateway/CLI adapter | 请求级 | 协议校验、安全 DTO 转换和事件传输；不持有可变 ManagedRun |

### 身份与生命周期模型

#### Session 与 Attachment

`Session` 是可继续对话的持久边界，`Run` 是一次 Agent 执行；一个 Session 可有多个 Run。Session 的权威字段只在 `sessions` 行中。当前活跃 Run、附件清单和 panel 清单都是查询结果，不作为 Session 的重复字段保存。

| 字段路径 | 类型与可空性 | 含义及写入规则 |
|---|---|---|
| `Session.session_id` | 不透明字符串，必填 | 创建时生成，所有 Session 子对象使用它归属，不在客户端重新解释 |
| `Session.name` | 有界字符串，可空 | 用户可见名称；更新名称只改本字段与 `updated_at` |
| `Session.created_at`、`Session.updated_at` | UTC 时间，必填 | 创建和最后一次 Session 元数据变更时间 |

`Attachment` 的 metadata 在 `attachments` 表，文件内容存 `ArtifactStore`。`storage_key` 是 metadata 指向内部文件的定位值，不是 API 标识。

| 字段路径 | 类型与可空性 | 含义及写入规则 |
|---|---|---|
| `Attachment.attachment_id`、`Attachment.session_id` | 不透明 ID，必填 | 附件身份及所属会话；上传入口校验两者绑定 |
| `Attachment.filename` | 安全展示字符串，必填 | 清洗后的展示名，不作为本机路径 |
| `Attachment.media_type`、`Attachment.byte_count` | MIME 字符串、非负整数，必填 | 通过上传校验后记录；下载/读取时再次验证资源内容 |
| `Attachment.content_sha256` | 64 位十六进制摘要，必填 | 上传字节的内容指纹；工具执行前用于校验来源未变化 |
| `Attachment.storage_key` | 内部 locator，必填 | ArtifactStore 内部文件定位；禁止进入 DTO、prompt、RunStreamEvent 和评测报告 |
| `Attachment.status`、`Attachment.deleted_at` | 状态必填、删除时间可空 | `active` 可被新 Run 授权；`deleted` 立即拒绝新读取；物理清理按保留策略执行 |
| `Attachment.created_at` | UTC 时间，必填 | 接收文件时生成 |

上传顺序是：校验请求大小/MIME → 原子写文件 → 计算 `content_sha256` → 写 metadata → 返回安全 Attachment DTO。删除先将 status 改为 `deleted` 并记录时间；历史 ExecutionRecord 保留原来源引用用于审计，但不代表旧附件仍可重新读取。物理清理期限属于保留策略，清理前必须检查所有有效 manifest/ref。

#### Run 与 RunInput

Run 行保存生命周期和本次实际执行配置；用户原始文字、附件 ID 和用户请求的模型选择不复制进 Run 行，放在初始 `ExecutionRecord.payload` 的 `RunInput` 对象中。

| 字段路径 | 类型与可空性 | 含义及写入规则 |
|---|---|---|
| `Run.run_id`、`Run.session_id` | 不透明 ID，必填 | Run 身份和所属 Session；创建后不可变 |
| `Run.ordinal` | 正整数，必填 | Session 内创建顺序，由 `RunCoordinator` 分配 |
| `Run.input_record_id` | ExecutionRecord ID，必填 | 指向唯一的 `record_kind=input` 记录；子 Run 沿 lineage 引用原输入，不复制正文 |
| `Run.status` | `running` / `completed` / `failed` / `interrupted`，必填 | 唯一生命周期状态，由 RunCoordinator 在状态变迁事务中更新 |
| `Run.provider`、`Run.model` | 字符串，必填 | 最终实际采用的 provider/model；区别于 RunInput 里可选的请求值 |
| `Run.prompt_bundle_version`、`Run.tool_registry_version`、`Run.verification_policy_version`、`Run.execution_policy_version` | 不透明版本字符串，必填 | 固定本 Run 的 prompt、工具、执行限额策略和发布校验策略版本，供审计/评测对比；运行中不变 |
| `Run.execution_limits.model_steps_limit`、`Run.execution_limits.chart_attempts_limit` | 非负整数，必填 | Run 创建时从 execution_policy_version 解析并冻结的模型决策步与图表渲染尝试上限；本 Run 不可变 |
| `Run.execution_limits.provider_retry_limit` | 非负整数，必填 | Provider adapter 在 Run 创建时冻结的传输重试上限；不计入 model_steps_used |
| `Run.parent_run_id` | Run ID，可空 | retry/resume child 的直接父 Run；普通首个 Run 为空 |
| `Run.parent_record_sequence` | 正整数，可空 | 只对 resume 固定父 Run 的已提交记录前缀；必须与 `parent_run_id` 同时出现，retry 不继承记录前缀 |
| `Run.continuation_kind` | `retry` / `resume`，可空 | child Run 的创建方式；root Run 为空 |
| `Run.created_at`、`Run.started_at`、`Run.finished_at` | UTC 时间；后两者按生命周期可空 | 接受请求、开始 AgentExecutor、进入终态的时间 |
| `Run.terminal_code`、`Run.terminal_message` | 有界字符串，终态时按原因可空 | 面向日志/安全 DTO 的终态原因；不得包含 provider 私有内容或敏感路径 |
| `Run.final_record_id` | ExecutionRecord ID，完成时必填，其他状态为空 | 指向 `record_kind=final_answer` 的权威答复/审核事实，不复制答复正文 |

`RunInput` 位于初始 `ExecutionRecord.payload`：

| 字段路径 | 类型与可空性 | 含义及写入规则 |
|---|---|---|
| `RunInput.text` | UTF-8 文本，必填；允许空字符串但 attachment_ids 至少一项 | 用户原始文字；图片/多模态内容通过附件引用表达，不把字节或任意多模态 JSON 混入 text |
| `RunInput.attachment_ids` | 有序 Attachment ID 列表，默认空 | 用户本次明确附加的新资源或从同一 Session 选择的既有资源；写入时验证 Session 归属和 active 状态 |
| `RunInput.requested_provider`、`RunInput.requested_model` | 字符串，可空 | 用户/客户端请求的选项；解析后实际值写 `Run.provider/model` |
| `RunInput.schema_version` | 正整数，必填 | 输入 payload 结构版本，历史记录解析时据此升级/拒绝 |

`root_run_id` 可以由 `Run.parent_run_id` 链推导；仅在查询性能确有需要时作为可重建索引物化，不成为第二个 lineage 权威字段。`RunSummary` 从 Run 行映射；`RunResumeAvailability` 还要检查 checkpoint、父前缀、附件 hash 与副作用策略，不能只看 `Run.status`。

~~~text
请求被接受 → running ──→ completed
                    ├──→ failed
                    └──→ interrupted
~~~

Run 创建成功后对外为 `running`。终态不可原地重开；retry 和 resume 都创建新的 child Run，保留原 Run 的终态与事件。

### 执行记录与检查点

#### ExecutionRecord

`ExecutionRecord` 是 Run 内唯一有序、只追加的执行事实日志。每个已提交的模型回复、工具结果、验证结论和发布结论都有自己的记录。对话、ArtifactIndex、诊断时间线和恢复前缀都是从它派生的读模型，不反向改写记录。

| 字段路径 | 类型与可空性 | 含义及写入规则 |
|---|---|---|
| `ExecutionRecord.record_id` | 不透明 ID，必填 | 单条事实的永久身份；不可复用 |
| `ExecutionRecord.run_id` | Run ID，必填 | 所属 Run；resume 子 Run 的记录只属于子 Run，父事实通过 Run lineage 读取 |
| `ExecutionRecord.record_sequence` | 正整数，必填 | Run 内从 1 递增；同一 Run 不可重复；子 Run 从 1 开始 |
| `ExecutionRecord.record_kind` | 受限枚举，必填 | 区分 `input`、`model_response`、`tool_result`、`verification_result`、`promotion_result`、`final_answer` 六类 payload |
| `ExecutionRecord.work_key` | 有界稳定字符串，可空 | 仅对需要去重/对账的动作填写；由 run/响应记录/tool call/动作/输出序号确定，结果提交时原样写入 |
| `ExecutionRecord.payload` | 对应 record_kind 的版本化对象，必填 | 小型字段内嵌 JSON；大型结构以该 payload 内的 `payload_ref` 引用 ArtifactStore，不保留重复副本 |
| `ExecutionRecord.created_at` | UTC 时间，必填 | 事实提交时由 Runtime 生成；不使用 provider 时间作为排序依据 |

`ExecutionRecord.payload` 的判别结构如下；每类的路径均从 `ExecutionRecord.payload` 开始：

| `record_kind` | payload 字段 | 来源与用途 |
|---|---|---|
| `input` | `text`、`attachment_ids`、可选 `requested_provider` / `requested_model`、`schema_version` | 原始用户请求；记录后不可编辑 |
| `model_response` | `assistant_content`、有序 `tool_calls[]`、可选 `provider_response_id`、可选 `continuation_payload_ref` | Provider 返回的结构化 assistant 内容和精确 tool call；私有 continuation 只放受控 ref，不能进入 prompt/事件 |
| `tool_result` | `call_id`、`tool_name`、`outcome`、成功时的 `result` 或失败时的 `error`、`schema_version` | 通用外层只标识调用和结果；来源、范围、证据、产物等领域字段属于对应类型化 result |
| `verification_result` | `verification_result` 对象 | 对应精确 `staged_ref`、图像/ChartSpec digest、验证 policy 和结论 |
| `promotion_result` | `published_artifact` 对象 | 对应已验证暂存图的正式发布身份；按 work_key 幂等 |
| `final_answer` | `response_record_id`、`artifact_refs`、`guard_version` | 精确指向通过 guard 的模型回复并记录回答可声明的正式产物；正文只在 model_response 中保存一次 |

`tool_result` 使用下列互斥结构；result/error 的内部字段由 ToolDefinition.result_schema_version 约束：

| 字段路径 | 类型/可空性 | 规则 |
|---|---|---|
| `ExecutionRecord.payload.call_id` | 当前模型响应内不透明字符串，必填 | 与对应 ToolCall.call_id 相同 |
| `ExecutionRecord.payload.tool_name` | ToolDefinition 名称，必填 | 与被调用工具一致 |
| `ExecutionRecord.payload.outcome` | succeeded / failed，必填 | 决定下方只允许 result 或 error 之一 |
| `ExecutionRecord.payload.result` | 工具专属类型化对象，outcome=succeeded 时必填 | Observation、MeasurementAttempt、ChartSpec 等由对应工具 Schema 定义；无领域数据的成功结果使用显式空结果对象 |
| `ExecutionRecord.payload.error` | ToolExecutionError，outcome=failed 时必填 | 只含有界安全诊断，不含堆栈、密钥或原始 provider 响应 |
| `ExecutionRecord.payload.schema_version` | 正整数，必填 | 版本化外层 envelope；具体 result/error Schema 版本由固定 ToolDefinition 标识 |

`ToolExecutionError` 位于失败 tool_result 的 error 字段：

| 字段路径 | 类型/可空性 | 含义 |
|---|---|---|
| `ToolExecutionError.code` | 受控错误码，必填 | 稳定机器可判别错误类别 |
| `ToolExecutionError.message` | 有界脱敏文本，必填 | 面向 Agent 的可恢复诊断 |
| `ToolExecutionError.retryable` | bool，必填 | 是否允许 Agent 再次提出调用；Runtime 仍执行预算/副作用门槛 |
| `ToolExecutionError.field_path` | Schema 字段路径，可空 | 参数或结果校验失败时指出字段；不能包含任意本机路径 |
| ToolExecutionError.issues[] | ToolIssue[]，可空，最多 32 项 | 多字段 Schema/ChartSpec 校验问题；顺序稳定 |
| ToolIssue.code | 受控错误码，必填 | 可机器识别的具体失败类型 |
| ToolIssue.field_path | 相对 JSON 字段路径，必填 | 指向被拒绝的输入字段，不包含本机路径 |
| ToolIssue.message | 有界脱敏文本，必填 | 可供 Agent 修正本次输入的说明 |


`work_key` 必须在调用可能产生副作用之前确定。它绑定产生操作的 `response_record_id`、`call_id`、`operation_name` 和多输出时的 `output_ordinal`；重放/恢复重新计算必须得到相同值。同参数的两次独立用户调用不能共用 key。最终结果记录持久化这个 key，供提交前崩溃后的去重或对账。

#### ExecutionCheckpoint

`ExecutionCheckpoint` 是每个 Run 当前唯一的持久执行推进点。它不是 Run 生命周期，也不是完整状态快照。权威恢复事实仍在 ExecutionRecord；checkpoint 只说明已提交到哪条本 Run 记录，以及下一项协议动作是什么。模型轮次从已提交的 model_response 记录计数，不单独保存在 checkpoint。

| 字段路径 | 类型与可空性 | 含义及写入规则 |
|---|---|---|
| `ExecutionCheckpoint.run_id` | Run ID，主键，必填 | 每个 Run 恰有一个最新 checkpoint |
| `ExecutionCheckpoint.schema_version` | 正整数，必填 | checkpoint JSON/列结构的版本 |
| `ExecutionCheckpoint.last_committed_record_sequence` | 非负整数，必填 | 本 Run 已提交记录的最大 `record_sequence`；读取前缀不得超过此值 |
| `ExecutionCheckpoint.next_action` | `NextAction` 或 null | 下一步唯一允许的协议动作；终态后为 null，失败/中断时可保留待恢复动作 |
| `ExecutionCheckpoint.updated_at` | UTC 时间，必填 | 最近一次与记录一起提交的时间 |

父 Run 和固定父前缀只存于 `Run.parent_run_id`、`Run.parent_record_sequence`，checkpoint 不复制 lineage。`checkpoint_id` 是对 checkpoint 当前版本的稳定不透明标识，由 Runtime 依据其有效内容生成；不另建 ID 权威字段。恢复请求携带该 ID 作为并发校验条件，若 checkpoint 已前进则拒绝过期请求。

`NextAction` 只存在于 `ExecutionCheckpoint.next_action`，是由 `action_kind` 判别的联合类型。只有对应 variant 才允许其引用字段：

| `action_kind` | 必须字段 | Runtime 解释 |
|---|---|---|
| `model` | 无 | 从 Context/Prompt 重建请求并调用 Provider |
| `tool` | `response_record_id`、`call_id` | 执行指定模型回复中的单个调用；若同一响应还有其他 calls，Runtime 从 model_response.tool_calls 与已提交 tool_result 事实选出下一条，不在 checkpoint 复制调用列表 |
| `verify` | `staged_ref` | 对精确暂存图和 manifest 运行验证 |
| `promote` | `staged_ref`、`verification_ref` | 复核对应通过结论并幂等发布 |
| `final` | `response_record_id` | 对已提交模型回复运行最终答案 guard |

不适用的引用字段必须缺省，不能以 null/空字符串构造伪引用。Checkpoint 不保存完整 messages、待执行工具列表、测量 session、ArtifactIndex 或自然语言 `pending_action`。显式 resume 是否允许还要校验来源和副作用策略；checkpoint 存在不等于 Run 一定可恢复。

#### RunStreamEvent

`RunStreamEvent` 是客户端可见事件流的一条安全投影，不是执行事实，也不是 Agent 恢复依据。

| 字段路径 | 类型与可空性 | 含义及写入规则 |
|---|---|---|
| `RunStreamEvent.run_id` | Run ID，必填 | 所属 Run |
| `RunStreamEvent.event_sequence` | 正整数，必填 | 每个 Run 的公开事件序号，和 `ExecutionRecord.record_sequence` 独立递增 |
| `RunStreamEvent.event_kind` | 受限枚举，必填 | `run_created`、`run_started`、`tool_started`、`tool_completed`、`artifact_staged`、`verification_completed`、`artifact_published`、`run_completed`、`run_failed`、`run_interrupted` |
| `RunStreamEvent.payload` | 各 event_kind 对应的有界对象 | 仅含展示/重连所需白名单字段，不含用户原文、图片字节、reasoning、provider 原始回复和本机路径 |
| `RunStreamEvent.created_at` | UTC 时间，必填 | Runtime 创建安全事件的时间 |

事件 ID 由 run_id:event_sequence 组成；SSE 续读参数为 after_event_sequence。持久 RunStreamEvent 在同一事务提交到 run_stream_events 后由 Gateway 投递；断线只影响投递，不取消 Run。读取历史时若发现事件保留窗口造成缺口，Gateway 另外发出非持久化 RunStreamGapNoticeDto，不伪装成 Runtime event_kind，也不修改执行事实。

RunStreamGapNoticeDto 字段如下：

| 字段路径 | 类型/可空性 | 含义 |
|---|---|---|
| RunStreamGapNoticeDto.run_id | Run ID，必填 | 所属 Run |
| RunStreamGapNoticeDto.after_event_sequence | 非负整数，必填 | 客户端原续读位置 |
| RunStreamGapNoticeDto.first_available_event_sequence | 正整数，可空 | 当前仍可读的最早事件；为空表示无事件可补 |
| RunStreamGapNoticeDto.reason_code | history_gap，必填 | 固定的缺口原因 |
| RunStreamGapNoticeDto.created_at | UTC 时间，必填 | Gateway 生成提示的时间 |

RunStreamEvent.payload 按 event_kind 使用固定 variant；下表字段均为该 variant 的必填字段，run_started 使用空对象：

| event_kind | payload 字段路径 | 来源与安全限制 |
|---|---|---|
| run_created | RunStreamEvent.payload.session_id、ordinal | Run 创建事实；不包含 RunInput.text |
| run_started | 空对象 | 时间由 RunStreamEvent.created_at 表达 |
| tool_started | RunStreamEvent.payload.call_id、display_name | ToolCall 身份与 ToolDefinition.display_name；不含参数 |
| tool_completed | RunStreamEvent.payload.call_id、display_name、outcome | outcome 为 succeeded 或 failed；不含工具原始结果 |
| artifact_staged | RunStreamEvent.payload.staged_ref、display_name、width、height | 受权预览使用的安全展示信息 |
| verification_completed | RunStreamEvent.payload.staged_ref、verification_status | verification_status 与 VerificationResult.status 一致 |
| artifact_published | RunStreamEvent.payload.artifact_id、staged_ref | 发布事实的 opaque refs |
| run_completed | RunStreamEvent.payload.final_artifact_refs[] | 只列最终已发布 ArtifactRef |
| run_failed / run_interrupted | RunStreamEvent.payload.terminal_code | 受控终态原因码，不包含模型原文 |

各 variant 不重复顶层 run_id/event_sequence/created_at，也不包含原始工具结果。

### 提交顺序

~~~mermaid
sequenceDiagram
    participant C as CLI/Gateway
    participant R as RunCoordinator
    participant A as AgentExecutor
    participant PRT as Runtime Commit Port
    participant S as Figura SQLite
    participant P as Provider/Tool
    C->>R: create(session_id, RunCreateRequest, idempotency key)
    R->>S: 同一事务提交 Run + input ExecutionRecord + checkpoint + RunStreamEvent
    R-->>C: RunAccepted
    R->>A: execute(run_id)
    A->>PRT: 读取 checkpoint 与有效 record 前缀
    PRT->>S: 加载权威执行数据
    PRT-->>A: RunExecutionContext + ModelRequest inputs
    A->>P: 模型请求或下一工具动作
    P-->>A: 响应/结果
    A->>PRT: 提交类型化结果与下一动作
    PRT->>S: 同一事务提交 ExecutionRecord + ExecutionCheckpoint + 安全事件
    A-->>R: 最终结果或失败/中断
    R->>PRT: 提交终态
    PRT->>S: 同一事务提交终态字段与 terminal RunStreamEvent
~~~

创建事务还保存请求幂等映射。模型、工具、验证和发布动作先通过 Runtime Commit Port 原子提交事实、下一 checkpoint 和安全事件，再向客户端报告完成。完成事务将 `Run.final_record_id`、`Run.status=completed`、清空后的 `ExecutionCheckpoint.next_action` 和终态 RunStreamEvent 一次写入；失败或中断则由 RunCoordinator 发起同一事务。AgentExecutor 不直接更新 SQLite，也不直接写 Run.status。

### 恢复与副作用

| 操作 | Run 身份与执行前缀 | 规则 |
|---|---|---|
| Reconnect | 同一个 Run | 只补偿事件；不会重复 Agent 请求 |
| Interrupt | 同一个 Run 变为 interrupted | 设置 cancellation token，在安全边界停止新动作；断开 SSE 本身不取消执行 |
| Retry | 新 child Run | 引用原始 RunInput，从头执行，不继承父产物前缀 |
| Resume | 新 child Run | 固定父 `parent_record_sequence`，验证 lineage、来源、产物与 replay contract 后继续 |

Resume 子 Run 的本地 `ExecutionCheckpoint.last_committed_record_sequence` 从自己的第一条新记录开始计数。子 Run 通过 `Run.parent_run_id` 和 `Run.parent_record_sequence` 固定父前缀；从该前缀读取的每条父记录都必须不超过父 Run 对应 checkpoint。子 Run 的 `NextAction` 只引用已验证记录/资源的 ID/ref，不复制父记录。普通 Session 历史不会自动把失败/中断 Run 混入新请求。

已提交的模型、工具、验证、发布和最终答复事实按 record identity 复用。未提交的只读/计算工具可重跑；本地写入按 `work_key` 对账；无法核对的外部副作用阻止自动重放。Provider/VLM 未提交请求只有显式 resume 后才能重发，可能再次计费或产生不同结果。工具在 ToolDefinition 声明 `replay_safe`、`idempotent_local_write` 或 `reconcile_required`，不增加一份通用 OperationJournal。

### 存储与公开协议

Figura SQLite 负责 `sessions`、`attachments`、`runs`、`run_idempotency`、`run_execution_records`、`run_execution_checkpoints`、`run_stream_events`、`artifact_manifests` 和 `staged_chart_manifests`。ArtifactStore 保存图片和超限结构化 JSON 的字节。先原子写文件并计算 digest，再在 SQLite 事务中写 ArtifactManifest、可选 StagedChartManifest、ExecutionRecord、ExecutionCheckpoint 与 RunStreamEvent；DB 与文件系统不能共用事务，因此数据库提交失败时文件保持 unpublished，由清理器按 Figura 存储根和引用检查清理孤儿。ExecutionRecord、ExecutionCheckpoint、Run 生命周期和 RunStreamEvent 必须在同一 SQLite transaction 内提交。

Gateway 只做协议校验和 DTO 映射，不持有第二份 Run 状态。主要对外对象如下：

| DTO / Request | 字段 | 映射与安全边界 |
|---|---|---|
| `RunCreateRequest` | `text`、`attachmentIds`、可选 `requestedProvider` / `requestedModel` | 归一化后形成 `RunInput`；幂等键走请求 header，不混入用户正文 |
| `RunAccepted` | `runId`、`sessionId`、`status`、`eventSequence` | 创建事务已提交后的响应；`eventSequence` 为最后已提交公开事件序号 |
| `RunSummary` | `runId`、`sessionId`、`ordinal`、`status`、`provider`、`model`、`parentRunId`、`continuationKind`、`createdAt`、`startedAt`、`finishedAt`、`terminalCode`、`finalArtifactIds` | 从 Run 与已审核发布事实派生；不传数据库内部字段、私有 payload 或 cancellation token |
| `RunResumeAvailability` | `canResume`、可选 `checkpointId`、可选 `reasonCode` | 由 Run、checkpoint、来源引用和 replay_effect 校验即时计算；不保存、不引入第二种 Run status；不公开 `next_action` |
| `RunStreamEventDto` | `runId`、`eventSequence`、`eventKind`、有界 `payload`、`createdAt` | 对应持久安全事件；客户端只使用 `afterEventSequence` 续读 |
| `RunStreamGapNoticeDto` | `runId`、`afterEventSequence`、可选 `firstAvailableEventSequence`、`reasonCode`、`createdAt` | Gateway 读取事件时检测到缺口后合成；不持久化、不占用 eventSequence |
| `ResumeRequest` | `parentRunId`、`checkpointId`、幂等键 | 要求显式用户动作；校验 checkpointId 与当前 checkpoint 一致后创建 child Run；幂等键通过请求头传递 |
| `RetryRequest` | `parentRunId`、可选请求模型覆盖、幂等键 | 引用父 Run 的原始 RunInput，创建从头执行的 child Run，不复制正文或复用父 checkpoint；幂等键通过请求头传递 |

RunResumeAvailability 是查询时重算的 DTO：canResume=true 时必须带 checkpointId 且省略 reasonCode；canResume=false 时省略 checkpointId，并使用一个 reasonCode：run_not_terminal、checkpoint_missing、checkpoint_stale、source_unavailable、replay_not_safe 或 unsupported_version。它不更改 Run.status，也不泄露 next_action 内容。

所有 ID/ref 对调用方不透明。HTTP/SSE 不公开 `storage_key`、ExecutionRecord 私有 payload、完整 checkpoint JSON、provider 原始回复、reasoning、原始图片字节或无界工具结果。字段公开与否以 DTO 表为准，而不是因为某字段存在于内部对象就自动公开。

### 与其他专题的接口

- Agent Core 提交模型、工具与图表事实；Runtime 保证顺序、事务、终态和恢复。
- Memory System 根据已提交前缀构建 Context、历史和 Prompt；Runtime 不持有第二份 messages。
- Planning System 读取预算与来源，选择工具和产物路线；Runtime 只校验并执行 checkpoint 指向的动作。
- Evaluation System 以普通请求入口创建评测 Run，并通过安全、只读投影分析结果。

## 5. Agent Core Design

### 执行职责与边界

Agent Core 的唯一执行组件名为 `AgentExecutor`。它从 Execution Runtime 取得当前 `ExecutionCheckpoint.next_action`，从 Memory System 取得该步所需的只读上下文与模型输入，然后调用 Provider、工具、验证器或发布服务。每一步产出的事实交给 Runtime Commit Port 原子提交；AgentExecutor 不直接写数据库、不自行改变 Run 生命周期，也不把历史结果积累在长期可变列表中。

| 对象/组件 | 所属层 | 生命周期 | 所有权与用途 |
|---|---|---|---|
| `AgentExecutor` | Agent Core | 单次推进调用 | 执行 checkpoint 指定动作；无权创建第二份 Run 状态 |
| `ToolRegistry` | Runtime 组合根 | 进程级不可变版本 | 持有已注册 ToolDefinition；创建 Run 后版本固定 |
| `ToolDefinition` | Agent 工具合同 | 注册表生命周期 | 同一份定义提供模型可读说明、Provider Schema、内部 handler 和重放策略 |
| `ToolExecutionContext` | Agent Core | 单次 handler 调用 | 携带已校验的调用身份、来源与取消信号；不持久化 |
| `SourceAuthorizationScope` | Memory 派生读模型 | 每次动作重建 | 列出本 Run 当前获准使用的附件和 panel 版本；不代表模型已经选择使用 |
| `Observation` / `EvidenceRef` / `PanelRecord` / `MeasurementAttempt` | Agent 领域事实 | 不可变，写入后追加新版本 | 记录工具观察、可追溯证据、panel 分析和一次测量结果 |
| `ChartSpec` / `ChartFigure` | Agent 图表领域事实 | 不可变 | 描述单图或复合图的数据、来源和生成取舍 |
| `StagedChartManifest` | Runtime Artifact Store 边界 | 暂存图生命周期 | 绑定不可变图像文件、图表规格、来源和生成操作 |
| `VerificationResult` / `PublishedArtifact` | Runtime 图表发布事实 | 不可变 | 分别记录验证结论与通过验证后的正式发布身份 |

~~~mermaid
flowchart LR
    CP[ExecutionCheckpoint.next_action] --> AG[AgentExecutor]
    CTX[RunExecutionContext] --> AG
    AG -->|model| PROVIDER[Provider]
    AG -->|tool| REGISTRY[ToolRegistry / handler]
    REGISTRY --> FACTS[Observation / Evidence / Panel / Measurement / ChartSpec]
    AG -->|verify| VERIFY[Verifier]
    AG -->|promote| PROMOTE[Promotion]
    FACTS --> PORT[Runtime Commit Port]
    VERIFY --> PORT
    PROMOTE --> PORT
    PORT --> REC[ExecutionRecord + next checkpoint]
~~~

### ToolDefinition 与工具调用

ToolRegistry 是 FiguraRuntime 组合的进程级不可变对象：ToolRegistry.registry_version 是必填版本字符串，ToolRegistry.definitions_by_name 是以 ToolDefinition.name 为键的只读映射，ToolRegistry.allowed_tool_names[] 是同一版本内授权策略计算出的可用工具子集。Run.tool_registry_version 锁定定义和授权策略；运行期间不可替换。PromptBundle.dynamic_tool_instructions 与 ModelRequest.tools 只投影 allowed_tool_names 中的工具。

`ToolDefinition` 是注册表中的不可变定义；对应字段在配置/代码构建的注册表对象中，不写入每个 Run。`Run.tool_registry_version` 记录实际使用的注册表版本。Provider 原生工具 Schema 和动态说明由此对象投影，避免同名工具的文案、参数与执行实现各自维护。

| 字段路径 | 类型/可空性 | 所属位置与用途 | 边界 |
|---|---|---|---|
| `ToolDefinition.name` | 稳定字符串，必填 | ToolRegistry 唯一键；对应模型 tool call 的名称 | 创建 Run 后不变；模型可见 |
| `ToolDefinition.summary` | 最多 160 字符，必填 | 一句说明工具解决什么问题；进入 Provider 原生工具 Schema 的 description | 模型可见；不承载授权事实 |
| `ToolDefinition.prompt_guidance` | 最多 640 字符，必填 | 更详细说明适用时机、选择理由和不可替代限制；进入动态 ToolInstruction | 模型可见；不重复参数 JSON Schema，不承载授权事实 |
| `ToolDefinition.parameters` | JSON Schema，必填 | Provider 原生参数 Schema；校验模型返回参数 | 模型可见；handler 执行前再次校验 |
| `ToolDefinition.handler` | callable，必填 | Python 进程内的实际执行函数 | 仅 Runtime/AgentExecutor 可见 |
| `ToolDefinition.display_name` | 有界文本，必填 | 面向用户的安全展示名称 | 可进入 UI 投影；不用于协议分派 |
| `ToolDefinition.group` | 受控字符串，必填 | UI/产品侧工具分组 | 不决定执行权限 |
| `ToolDefinition.budget_category` | none / chart_attempt，必填 | 由固定 registry version 标识是否消耗图表渲染预算；不复用 group | BudgetSnapshot 按此字段统计 chart ToolCall |
| `ToolDefinition.replay_effect` | `replay_safe` / `idempotent_local_write` / `reconcile_required` | 重放策略声明 | 每个工具必须声明；未知副作用默认阻止自动重放 |
| `ToolDefinition.result_schema` | 版本化 JSON Schema，必填 | 描述成功 tool_result.payload.result 的类型化结构 | 仅 Runtime 校验；不作为 API 原生工具参数 |
| `ToolDefinition.result_schema_version` | 稳定版本字符串，必填 | 锁定该工具的结果 Schema 版本 | 由 Run.tool_registry_version 间接固定；与外层 envelope schema_version 分开 |

ToolDefinition.summary 供 Provider 原生 Schema 做短描述，ToolDefinition.prompt_guidance 供动态 developer 区域说明何时调用及其边界；两段文字来自同一固定 ToolDefinition，职责不重叠。ToolDefinition.parameters 只定义模型可传入什么；ToolDefinition.result_schema 只定义 handler 成功时 Runtime 能接收什么。两种 Schema 与两段说明都由固定 ToolRegistry 版本冻结，不能从提示词文字推导，也不能由模型自行扩展。执行失败走 ExecutionRecord.tool_result.error，不伪装成成功 result。

#### Figura v1 主 Agent 工具清单

默认图表分析注册表包含下表九个模型可调用工具。每个 Run 锁定 Run.tool_registry_version 和 ToolRegistry.allowed_tool_names[]；Provider 请求只公布授权子集中的工具。工具名、参数名、枚举值都来自同一个 ToolDefinition。此处列出的是 Figura 面向主 Agent 的产品工具，不包括内部 Runtime 服务。

来源观察工具共用以下输入约定：

| 参数字段 | 类型/要求 | 归属与校验 |
|---|---|---|
| source_ref | SourceRef，必填；attachment 或 panel 分支 | 从当前 RunExecutionContext.authorized_source_scope 中选择；服务端重验 session、附件状态/hash 与 panel revision |
| observation_scope.coordinate_space | panel_norm / panel_px / source_px，可选 | 有 panel 时默认 panel_norm；坐标必须落在精确 source_ref 内 |
| observation_scope.include[] / exclude[] | ScopeRegion[]，可空 | 每项必须且只能指定 bbox 或 polygon；不能通过区域字段切换 attachment/panel |
| observation_scope.objectives[] | 受控观察目标数组，可空 | labels、axes、legend、baseline、series、categories、values 等；只缩小本次观察任务 |
| observation_scope.reason | 有界文本，可空 | 给 Agent 的选择理由；作为数据处理，不构成授权指令 |
| measurement_target.parent_attempt_id | MeasurementAttempt ID，定向补充时必填 | 必须与本次 source_ref 完全同源 |
| measurement_target.evidence_refs[] | EvidenceRef ID[]，可选 | 只能引用 parent_attempt_id 已产生的候选 |
| measurement_target.mode | include / exclude，定向补充时必填 | 明确本次要补测或排除的候选 |
| measurement_target.fields[] | 有界字段名数组，可选 | category、value、series、baseline 等；不接受可执行表达式 |
| measurement_target.region | ScopeRegion，可选 | 无法用已有证据引用定位时提供，仍受原 source_ref 限制 |
| measurement_target.reason | 有界文本，定向补充时必填 | 解释主动补充原因；warning 本身不会自动发起重测 |
| layout_observation_id | Observation ID，可空 | 必须指向同一 source_ref 下 observation_kind=layout 且 accepted_for_measurement=true 的已提交结果 |
| observation_scope | ObservationScope，可空 | 首次观察的目标范围；缺省表示完整 source_ref |
| measurement_target | MeasurementTarget，可空 | 仅在模型基于既有 MeasurementAttempt 主动补测时提供 |
| ObservationScope 与 MeasurementTarget | 互斥 | 若提供 measurement_target，必须省略 observation_scope；避免两个目标范围相交/冲突 |


ScopeRegion 的完整结构是 role（受控几何提示，可空）、label（有界提示文本，可空）、bbox（四数 left/top/width/height）或 polygon（3..32 个点，每点为 x/y 二元组）。bbox 与 polygon 必须且只能有一个。归一化坐标限制在 0..1；像素坐标必须位于 Attachment/Panel 实际宽高内。attachment、panel、revision、hash 和坐标原点从 source_ref 确定，不在每个 region 冗余传入。

LayoutHint 是 inspect_chart_layout 的严格结构化可选参数，未知字段一律拒绝：

| LayoutHint 字段 | 类型/约束 | 解释 |
|---|---|---|
| LayoutHint.measurement_frame.bbox_norm | 归一化矩形，可空 | 图表实际绘图区在 source_ref 中的位置 |
| LayoutHint.axes.x.points_norm / y.points_norm | 两个归一化端点，可空 | 对应轴的方向和范围线索；不接受单端点 |
| LayoutHint.orientation | horizontal / vertical / rotated / unknown，可空 | 图表相对方向候选 |
| LayoutHint.coordinate_system | cartesian / polar / unknown，可空 | 坐标系统候选 |
| LayoutHint.annotation_regions[] | ScopeRegion[]，可空 | 标签、图例或注释的可能区域 |
| LayoutHint.polar_region | 中心点与半径的归一化对象，可空 | 饼图/极坐标绘图区候选 |
| LayoutHint.reason | 有界文本，可空 | 解释该提示依据；不构成证据结论 |

decompose_chart_image.regions[] 的每项字段为 proposal_id（可选短 ID）、name（必填有界文本）、bbox_norm（必填归一化矩形）、role（chart / kpi_card / legend / text_block / unknown）、chart_type（bar / line / pie / scatter / unknown）与 confidence（可选 0..1）。regions 最多 32 项；max_panels 在 1..32；crop_padding 在 0..0.08。模型提出的 bbox 是待校验假设，越界、过小或重叠区域由工具返回 warnings，不得静默扩张或覆盖其它附件。

| ToolDefinition.name | 分组与何时调用 | 模型参数契约 | 成功结果契约 | 副作用、预算与禁区 |
|---|---|---|---|---|
| decompose_chart_image | chart-observation；一张附件含多个图表、卡片或视觉区域时，建立可复用 PanelRecord | attachment_id 必填；可选 regions[]（name、bbox_norm、role、chart_type、confidence）、segmentation_mode（auto / deterministic / sam）、max_panels、crop_padding | 有序 PanelRecord[]；每项给出 panel_ref、source_bbox、analysis_scope、confidence、warnings；crop/preview 通过 ArtifactRef 引用 | idempotent_local_write；最多 32 panels。SAM 仅显式 opt-in。只拆分和定位，不提取数值；不得接受本地路径 |
| inspect_chart_layout | chart-observation；方向、轴、绘图区或旋转不清楚时可选调用 | source_ref 必填；可选 chart_type、结构化 layout_hint | observation_kind=layout 的 Observation；payload 给出 accepted / rejected / fallback、布局字段、证据、warnings | replay_safe；不消耗 chart_attempt。只提供布局假设，不是数值提取器或其他工具的强制前置步骤 |
| extract_text | chart-observation；需要标题、刻度、图例、注释或印刷值时 | source_ref 必填；可选 observation_scope | observation_kind=text 的 Observation；text_spans[] 含 text、bbox、confidence 和稳定 evidence ref；叠加预览通过 ArtifactRef | replay_safe；OCR 是有置信度的候选证据，不自动成为标签真值 |
| measure_bars | chart-observation；二维柱体几何或柱高/长度证据 | source_ref 必填；可选 layout_observation_id、observation_scope、measurement_target | MeasurementAttempt；包括柱多边形、类别/系列候选、零基线、方向、标定、confidence、quality、warnings 和 evidence_refs | replay_safe；3D、强透视、遮挡或缺少标定时不得声称精确值 |
| extract_line_series | chart-observation；清晰二维折线和系列轨迹 | 与测量传感器共用 source_ref、layout_observation_id、observation_scope、measurement_target | MeasurementAttempt；包括绘图区、坐标标定、轨迹/点位、系列候选、confidence、quality、warnings 和 evidence_refs | replay_safe；无法标定的轨迹只保留像素证据 |
| extract_pie_slices | chart-observation；普通二维饼图的扇区和相对比例 | 与测量传感器共用 source_ref、layout_observation_id、observation_scope、measurement_target | MeasurementAttempt；包括扇区几何、角度/比例候选、类别/图例关联、confidence、quality、warnings 和 evidence_refs | replay_safe；donut、爆炸、嵌套、3D 或透视图不得按完整平面饼图解释 |
| extract_scatter_points | chart-observation；二维散点标记、相对位置及可证实坐标 | 与测量传感器共用 source_ref、layout_observation_id、observation_scope、measurement_target | MeasurementAttempt；包括点几何、系列候选、x/y 标定、重叠/密度/离群线索、confidence、quality、warnings 和 evidence_refs | replay_safe；标定不足时只返回像素位置 |
| assemble_spec | chart-spec；用户要求结构化图表、重绘、转换、摘要或合成数据时 | output_kind 必填（chart_spec / chart_figure / chart_spec_collection）；`spec_input` 必填，按 output_kind 匹配版本化 Draft Schema；`GenerationContext.mode` 决定 provenance 条件校验；运行 ID、对象 ID 和时间由 Runtime 填入 | 成功时返回 ChartObjectRef 和已校验对象摘要；Runtime 将 Draft 规范化为不可变领域对象后与 tool_result 一起持久化；失败返回带字段路径 issues 的 ToolExecutionError | replay_safe；只组装/校验，不渲染、不验证图片、不发布，也不代替 Agent 选择证据；不得把 synthesize 标成来源重建 |
| render_chart | chart-generation；结构化图表完成且用户请求或任务需要图像输出时 | chart_object_ref 必填；width、height 可选（默认 1200×800，最大 2400×1600，图像字节上限 10 MiB）；对象必须来自当前有效 ArtifactIndex；若其 Provenance 含 SourceRef，Runtime 再逐项检查授权 | 返回一个或多个 staged_ref、尺寸、digest 和有界预览引用；字节在 ArtifactStore，业务绑定在 StagedChartManifest | idempotent_local_write，budget_category=chart_attempt；一次调用计一个 chart attempt，子图数量另受集合上限约束；只暂存，不宣称通过或发布 |

四个测量工具共用 source_ref、layout_observation_id、observation_scope 和 measurement_target 的字段语义；单个工具 Schema 可收窄适用范围，不能改变公共字段含义。只有主 Agent 看到当前结果后再次显式发起调用，才会执行 measurement_target；warning 不自动重测。generation_context 不作为观察工具的平行副本；它只存于 ChartSpec/ChartFigure，MeasurementAttempt 不复制整段生成计划。

`assemble_spec` 的 `ToolCall.arguments.spec_input` 是一次调用内的 Draft，不持久化，也不出现在后续 Context。ChartSpecDraft 的字段名仍为 `metadata`、`dataset`、`axes`、`provenance` 与 `generation_context`，只是嵌套值分别使用 ProvenanceDraft、GenerationContextDraft；ChartFigureDraft 提供局部子图 Draft、布局及整体 `generation_context`；ChartSpecCollectionDraft 提供有序 ChartFigureDraft[]。Draft 使用 `draft_key` 在本次对象内部关联子图和布局：ChartFigureDraft.draft_key 在同一 Collection Draft 内唯一，ChartSpecDraft.draft_key 在同一 Figure Draft 内唯一；单个顶层对象的 draft_key 可省略。所有 draft_key 仅在该次调用内有效。Draft 不含服务端身份字段和时间字段：`chart_spec_id`、`figure_id`、`collection_id`、`ChartFigureItem.chart_id`、各对象的 `schema_version`、`GenerationContext.created_at` 与 `Provenance.input_record_id` 均由 Runtime 分配或绑定后写入持久对象。`InputDataRefDraft` 只提交 `start_offset`、`end_offset`、`quoted_text` 和 `target_paths[]`；Runtime 从当前 Run 绑定 input_record_id，并验证区间、原文逐字匹配和目标路径。`target_paths[]` 相对各自 ChartSpecDraft 的 dataset，使用 JSON Pointer 语法。ToolDefinition.parameters 描述 Draft Schema，ToolDefinition.result_schema 描述成功返回的 ChartObjectRef 与摘要；二者不得共用同一 Schema 名称。

| Draft 对象/字段路径 | 类型/可空性 | 所在位置与规则 |
|---|---|---|
| ToolCall.arguments.output_kind | chart_spec / chart_figure / chart_spec_collection，必填 | 决定 `spec_input` 使用的 Draft variant |
| ToolCall.arguments.spec_input | 对应 Draft 对象，必填 | 只在当前 ToolCall.arguments 内；Runtime 校验并转换为持久领域对象 |
| ChartSpecDraft.metadata / dataset / axes | ChartMetadata / DataPoint[] / Axis[] | output_kind=chart_spec 时使用；metadata、dataset 必填，axes 按 ChartSpec 与 chart_type 约束可空或必填 |
| ChartSpecDraft.provenance | ProvenanceDraft，必填 | 对应持久 ChartSpec.provenance；模型只提供来源证据与变换声明，input_record_id 由 Runtime 绑定 |
| ChartSpecDraft.generation_context | GenerationContextDraft，必填 | 对应持久 ChartSpec.generation_context；模型提供 mode、data_origin、scope、coverage、选择理由和目标摘要 |
| ChartSpecDraft.draft_key | 有界字符串；作为 Figure 子图时必填 | 同一 Figure Draft 内唯一；单 ChartSpec 顶层可以省略 |
| ChartFigureDraft.draft_key | 有界字符串；嵌套在 Collection Draft 时必填 | 仅用于同一次 Collection Draft 内关联；顶层 ChartFigure 可省略；不成为 figure_id |
| ChartFigureDraft.charts[] | ChartSpecDraft[]，非空 | 子图各自提供数据和本地图表语境；必须满足 Figure mode/data_origin 一致性规则 |
| ChartFigureDraft.layout | Layout，必填 | 使用 LayoutItemDraft[]；其中 `chart_key` 替代持久 LayoutItem.chart_id，规范化时映射到对应 chart_id |
| ChartFigureDraft.generation_context | GenerationContextDraft，必填 | 对应持久 ChartFigure.generation_context，记录组合图整体目标与覆盖；mode/data_origin 必须与所有子图一致 |
| LayoutItemDraft.chart_key | 当前 Figure 内 ChartSpecDraft.draft_key，必填 | 不可跨 Figure 引用；规范化后映射到 Runtime 分配的 ChartFigureItem.chart_id |
| ChartSpecCollectionDraft.figures[] | ChartFigureDraft[]，非空且有序 | Collection 的顺序就是最终展示顺序；不同 Figure 可以有不同 mode/data_origin |
| ChartSpecDraft.provenance.source_refs[] / evidence_refs[] | SourceRef[] / EvidenceRef ID[] | 是否为空由 ChartSpecDraft.generation_context.mode 决定；引用必须已存在且通过授权检查 |
| ChartSpecDraft.provenance.input_data_refs[] | InputDataRefDraft[] | `data_origin=user_provided_data` 时必须为非空；其他取值时必须为空 |
| ChartSpecDraft.provenance.transformations[] | Transformation[]，可空 | 仅 source-linked 模式可提供；结构与持久 Transformation 一致，每项的输入 EvidenceRef 必须属于同一 provenance.evidence_refs |
| InputDataRefDraft.start_offset / end_offset | 非负整数，必填 | 以 Unicode code point 计数，定位当前 RunInput.text 的半开区间 |
| InputDataRefDraft.quoted_text | 有界字符串，必填 | 必须与输入区间逐字相等 |
| InputDataRefDraft.target_paths[] | ChartSpecDraft.dataset JSON Pointer[]，至少一项 | 指向该原文片段直接提供的类别或数值字段；覆盖该 Draft 中所有直接来自用户输入的数据字段 |
| ChartSpecDraft.generation_context.mode / data_origin | 受控枚举，必填 | 必须满足上方模式校验表 |
| ChartSpecDraft.generation_context.selected_source_scope[] | SourceRef[]，按 mode 条件必填 | 必须是 Runtime 当前授权来源的子集 |
| ChartSpecDraft.generation_context.coverage | Coverage，必填 | 与下方持久 Coverage 使用相同字段；Runtime 规范化后写入，GenerationContext.schema_version/created_at 由 Runtime 写入 |

默认 Run 不注册通用文件系统工具。ChartAgent v1 的 read_file、list_dir、parse_json、read_json_file 不带入 Figura 主 Agent：用户附件必须经 Attachment API 授权，不让模型提供任意本地路径。extract_text 仅读取经 SourceRef resolver 授权的图像；内部 JSON 解析、文件读写与图像解码属于 handler/ArtifactStore 实现能力，不是模型工具。

以下能力是 Runtime/Agent 内部服务，不出现在 ModelRequest.tools，也不生成模型 ToolCall：ExecutionRecord/Checkpoint 提交、取消/恢复、来源授权校验、ArtifactRef resolve、ChartSpec Schema 校验、图像安全解码、确定性/视觉验证、promotion、最终回答 guard。模型通过下一次 RunExecutionContext 与 ArtifactIndex 看到已提交结果；不能直接请求把 fail 改为 pass 或伪造 PublishedArtifact。

一次 model_response 可包含多个 ToolCall；AgentExecutor 按 Provider 返回顺序逐个验证和执行，绝不并行写入同一 Run。每个 call_id 都有独立 ToolExecutionContext 与 tool_result，Runtime 每次提交后推进 checkpoint；此前响应中的后续调用仍按原 arguments 执行，不把新事实偷偷合并成新参数。若后续调用依赖前一个结果才可确定的 ID/ref，Schema/来源校验失败后返回工具错误，Agent 在下一模型轮次基于已提交事实重新提出调用。只有这一轮所有既有 ToolCall 均完成后，checkpoint 才回到 model action。

参数在调用前按 ToolDefinition.parameters 校验，再核对 source_ref、attachment/panel/evidence 的 Session 归属、hash/revision、work_key 和预算。成功 result 按 ToolDefinition.result_schema 校验。Schema/权限/执行失败都会形成与 call_id 配对的 ToolExecutionError；Runtime 不会把异常文本、堆栈或文件路径原样暴露给模型。tool result 完整提交后才成为后续 Context 与 HistoryMessage 的输入。



`ToolCall` 是模型响应中的一次工具调用，物理上位于 `ExecutionRecord.payload.tool_calls[]`：

| 字段路径 | 类型/可空性 | 含义 |
|---|---|---|
| `ToolCall.call_id` | 当前模型响应内不透明字符串，必填 | 将模型请求、工具结果和 checkpoint 精确关联 |
| `ToolCall.name` | 工具名，必填 | 必须命中本 Run 固定版本的 ToolRegistry |
| `ToolCall.arguments` | JSON 对象，必填 | 未信任输入；Schema、引用归属和授权范围均在执行前校验 |

`ToolExecutionContext` 只存在于当前 handler 调用栈，完整字段如下：

| 字段路径 | 类型/可空性 | 来源与写入时机 | 用途/可见范围 |
|---|---|---|---|
| `ToolExecutionContext.run_id` | Run ID，必填 | ExecutionCheckpoint 对应 Run | 执行归属；handler 可见 |
| `ToolExecutionContext.response_record_id` | Record ID，必填 | checkpoint 的 tool NextAction | 原始 assistant 响应的权威位置 |
| `ToolExecutionContext.call_id` | 字符串，必填 | 指定 ToolCall.call_id | 当前调用身份 |
| `ToolExecutionContext.tool_name` | 字符串，必填 | 已校验 ToolCall.name | 匹配固定 ToolDefinition |
| `ToolExecutionContext.arguments` | 校验后的 JSON 对象，必填 | ToolCall.arguments | 只含通过 schema 与授权检查的参数 |
| `ToolExecutionContext.source_refs` | SourceRef[]，可空 | 从参数解析并验证 Attachment/Panel/Evidence 引用 | 限定 handler 可读取的输入；不允许自行扩权 |
| `ToolExecutionContext.work_key` | 不透明字符串，可空 | 对需去重/对账的副作用按 Runtime 规则生成 | 重试时稳定；不暴露给模型 |
| `ToolExecutionContext.cancellation_token` | 进程内取消令牌，必填 | RunCoordinator 的当前运行句柄 | handler 在安全边界协作取消；不序列化、不持久化 |

工具结果持久化在 `ExecutionRecord.payload` 的 `record_kind=tool_result` variant 中，不保存 ToolExecutionContext 或取消令牌。通用外层只记录 call_id、tool_name、outcome 和版本化 result/error；`requested_scope` 等请求字段留在对应的 ToolCall.arguments，`effective_scope`、`observation_scope`、source refs 和 artifact refs 由 Observation、MeasurementAttempt 或其他具体 result 类型承载。这样结果结构不会再复制一份通用来源/范围字段。工具收到的参数即使带有 attachment_id、panel_id 或 evidence_id，也必须核对 Session 归属、授权清单、对象版本与来源内容摘要，不能仅凭不透明 ID 通过校验。

### 授权来源、Observation、Evidence 与 Panel

`SourceAuthorizationScope` 是代码可访问来源的只读清单，字段来自 RunInput、AttachmentRepository 与 PanelReadModel；它不含“当前选中 panel”，也不含模型的最终数据选择。

| 字段路径 | 类型/可空性 | 来源与语义 |
|---|---|---|
| `SourceAuthorizationScope.session_id` | Session ID，必填 | 固定本次来源授权边界 |
| `SourceAuthorizationScope.authorized_attachment_refs[]` | AttachmentRef[]，可空 | RunInput 指定且仍 active 的附件；每项绑定 attachment_id 与上传字节 content_sha256 |
| `SourceAuthorizationScope.available_panel_refs[]` | PanelRef[]，可空 | 当前仍可读取的 panel 版本；每项绑定 panel_id、revision、attachment_id 和 attachment_content_sha256 |

该清单每次动作前重新校验。授权附件表示“可以读取”，不表示已被模型选中；可用 panel 表示“可供选择”，不等于本次工具目标。工具参数中的 `requested_scope` 表达请求，tool result 中的 `effective_scope` 表达实际处理范围，`observation_scope` 表达结果实际观察范围，ChartSpec 的 `provenance.evidence_refs` 才表示真正支撑图表的数据依据。

工具领域事实均放在产生它们的 `ExecutionRecord.payload.result` 类型化对象中；超出内嵌限制的完整结构化内容写入 ArtifactStore JSON blob，以同一对象中的 `payload_ref` 定位。

| 对象及字段路径 | 类型/可空性 | 含义、来源与约束 |
|---|---|---|
| `Observation.observation_id` | 不透明 ID，必填 | 一次观察结果身份 |
| `Observation.observation_kind` | text / layout / visual，必填 | 区分 OCR 文字、布局提示或其他一次性观察；测量使用 MeasurementAttempt |
| `Observation.tool_name` | ToolDefinition 名称，必填 | 实际产生观察的工具 |
| `Observation.source_refs[]` | SourceRef[]，至少一项 | 本次读取的已授权来源及固定版本 |
| `Observation.evidence_refs[]` | EvidenceRef ID[]，可空 | 由本次观察生成且可被后续 ChartSpec 明确引用的证据身份 |
| `Observation.effective_scope` | Scope 对象，必填 | 工具实际处理的范围；必须位于授权来源范围内 |
| `Observation.observation_scope` | Scope 对象，必填 | 工具结果确实覆盖的观察范围；可能比请求或实际处理范围更窄 |
| `Observation.summary` | 有界文本，必填 | 可用于后续决策的简要观察；不作为权威数值数据 |
| `Observation.warnings[]` | Warning[]，可空 | OCR 置信度低、布局假设退回等有界质量提示 |
| `Observation.payload_ref` | ArtifactRef，可空 | 仅当完整观察超出 ExecutionRecord 内嵌上限时存在 |
| `Observation.preview_ref` | ArtifactRef，可空 | OCR/layout 的安全视觉叠加图；不替代 observation 数据 |
| `Observation.created_at` | UTC 时间，必填 | Runtime 提交事实时生成 |
| `EvidenceRef.evidence_id` | 不透明 ID，必填 | 可被 ChartSpec 引用的证据身份 |
| EvidenceRef.display_ref | 当前 Observation/MeasurementAttempt 内唯一的短标签，可空 | 便于模型阅读的 B1/S1/P1/C1 等局部显示名；不跨 Attempt 充当实体身份 |
| EvidenceRef.evidence_kind | 受控 evidence kind，必填 | text_span、bar_geometry、line_series/line_point、pie_sector、scatter_point 或 layout_fact |
| EvidenceRef.summary | 有界文本，必填 | 描述该候选事实；不是业务结论 |
| EvidenceRef.confidence | 0..1 数值，可空 | 对该证据提取质量的估计，不是统计置信区间 |
| EvidenceRef.payload | 当前 EvidenceRef Schema 的有界类型化对象，可空 | 小型值内嵌；具体字段由 evidence_kind 判别 |

| `EvidenceRef.source_refs[]` | SourceRef[]，至少一项 | 证据的附件/panel 来源绑定 |
| `EvidenceRef.origin_run_id` | Run ID，必填 | 产生该证据的原 Run |
| `EvidenceRef.origin_record_id` | Record ID，必填 | 产生该证据的 ExecutionRecord |
| `EvidenceRef.attempt_id` | MeasurementAttempt ID，可空 | 证据若来自测量，则指向对应 attempt |
| `EvidenceRef.payload_ref` | ArtifactRef，可空 | 完整证据值超出内嵌限制时的定位引用 |
EvidenceRef.payload 与 EvidenceRef.payload_ref 必须且只能出现一个；大几何数组和预览存入 ArtifactStore，payload_ref 指向它。payload 的固定 variant 字段如下：

| evidence_kind | EvidenceRef.payload 字段 | 值的来源 |
|---|---|---|
| text_span | text、bbox、可选 language、OCR confidence | extract_text；bbox 为 source_ref 坐标系内的像素框 |
| bar_geometry | polygon、orientation、baseline_ref、category_candidate、series_candidate、pixel_extent、可选 calibrated_value | measure_bars；基线与分类不确定时保留 warning，不强行赋值 |
| line_series / line_point | series_candidate、point_order、pixel_points[]、可选 calibrated_points[]、plot_frame_ref | extract_line_series；pixel_points 是几何事实，calibrated_points 只有通过轴标定后才存在 |
| pie_sector | center、radius、start_angle、end_angle、可选 ratio、category_candidate、legend_ref | extract_pie_slices；ratio 只有几何质量达到工具阈值时提供 |
| scatter_point | pixel_position、series_candidate、可选 calibrated_x / calibrated_y、plot_frame_ref | extract_scatter_points；未标定坐标不得输出语义 x/y |
| layout_fact | measurement_frame、axis_endpoints、orientation、coordinate_system、accepted_for_measurement | inspect_chart_layout；模型 hint 与工具校验结果分开保存 |


| `PanelRecord.panel_id` | 不透明 ID，必填 | Panel 的逻辑身份；不同修订共享此 ID |
| `PanelRecord.session_id` | Session ID，必填 | 所属会话，必须与附件归属一致 |
| `PanelRecord.attachment_id` | Attachment ID，必填 | 原始图像来源 |
| `PanelRecord.attachment_content_sha256` | 64 位十六进制摘要，必填 | 固定 panel 分析所基于的图像字节版本 |
| `PanelRecord.revision` | 正整数，必填 | 同一 panel_id 下单调递增的不可变修订号 |
| `PanelRecord.name` / `slug` | 有界展示文本 / 稳定短标识，必填 | 人类可读名称与内部可引用名称；slug 不替代 panel_id |
| `PanelRecord.role` / `chart_type` | 受控角色 / 可空图表类型 | Panel 的分析角色及识别出的图表类型 |
| `PanelRecord.source_bbox` | 归一化矩形，可空 | 原图坐标中的区域；x/y/width/height 均在 0..1 且边界有效 |
| `PanelRecord.crop_ref` | ArtifactRef，可空 | 如需持久化 crop/预览则指向受管图像 blob；原图 bbox 仍是来源真值 |
| `PanelRecord.analysis_scope` | Scope 对象，必填 | 此 PanelRecord 覆盖的分析范围 |
| `PanelRecord.confidence` | 0..1 数值，可空 | 工具对结构识别结果的置信度，不是统计置信区间 |
| `PanelRecord.warnings[]` | 有界 Warning[]，可空 | 识别歧义或质量限制；不改写来源授权 |
| `PanelRecord.evidence_refs[]` | EvidenceRef ID[]，可空 | 支持 panel 分析的明确证据引用 |
| `PanelRecord.origin_run_id` / `origin_record_id` | Run ID / Record ID，必填 | 创建本修订的执行来源 |
| `PanelRecord.supersedes_panel_id` | Panel ID，可空 | 仅新逻辑 panel 取代旧 panel 时填写；普通 revision 不改变 panel_id |
| `PanelRecord.schema_version` | 正整数，必填 | PanelRecord JSON 结构版本 |
| `PanelRecord.created_at` | UTC 时间，必填 | 对应 ExecutionRecord 提交时间 |

PanelReadModel 是查询投影，从已提交 PanelRecord 中按 panel_id/revision 选择当前可用版本；不另存权威 `status`。它在查询时重建，不持久化；PanelRecord 的每个版本仍由原 ExecutionRecord 保存。

| 字段路径 | 类型/可空性 | 含义与来源 |
|---|---|---|
| PanelReadModel.panels[] | 有序 PanelReadModelEntry[]，可空 | 当前 Session 中可按权限提供给 Run 的 panel 摘要 |
| PanelReadModelEntry.panel_ref | PanelRef，必填 | 精确绑定 panel_id、revision 与附件 hash |
| PanelReadModelEntry.name / slug | 安全文本 / 稳定短标识，必填 | 展示和模型引用名 |
| PanelReadModelEntry.role / chart_type | 受控角色 / 字符串，可空 | 从选定 PanelRecord 修订投影 |
| PanelReadModelEntry.summary | 有界文本，必填 | 只读分析摘要，不作为数据真值 |
| PanelReadModelEntry.warnings[] | Warning[]，可空 | 来源事实中的有界警告 |

若来源 hash 已变化、附件已删除或 panel 的来源绑定不匹配，工具必须拒绝读取。Panel 的新修订通过新 ExecutionRecord 追加，不覆盖旧版本。

### MeasurementAttempt

`MeasurementAttempt` 表示一次不可变测量调用结果，位于该次 `tool_result` 中；不存在独立的“当前测量 session”字段或队列。

| 字段路径 | 类型/可空性 | 含义与规则 |
|---|---|---|
| `MeasurementAttempt.attempt_id` | 不透明 ID，必填 | 此次测量身份 |
| MeasurementAttempt.sensor_kind | bars / line_series / pie_slices / scatter_points，必填 | 对应具体测量结果 Schema variant |
| `MeasurementAttempt.run_id` | Run ID，必填 | 实际执行测量的 Run；可能与被引用证据的 origin_run_id 不同 |
| `MeasurementAttempt.tool_name` | ToolDefinition 名称，必填 | 实际使用的测量工具 |
| `MeasurementAttempt.source_refs[]` | SourceRef[]，至少一项 | 精确来源及版本 |
| `MeasurementAttempt.parent_attempt_id` | Attempt ID，可空 | 聚焦重测或基于前次结果继续时指向父 attempt |
| `MeasurementAttempt.effective_scope` | Scope 对象，必填 | 工具实际处理的范围 |
| `MeasurementAttempt.observation_scope` | Scope 对象，必填 | 工具实际成功观察/测量到的范围 |
| `MeasurementAttempt.target` | 版本化 Target 对象，必填 | 要测量的对象、系列或区域 |
| `MeasurementAttempt.target_fingerprint` | 稳定 digest，必填 | 用于确认跨 attempt 的目标是否相同；不替代来源绑定 |
| `MeasurementAttempt.quality` | MeasurementQuality，必填 | 完整度、精度或局部质量状态；需携带明确语义，不能只用无单位分数 |
| `MeasurementAttempt.warnings[]` | 有界 Warning[]，可空 | 质量警告和缺失情况 |
| `MeasurementAttempt.preview_ref` | ArtifactRef，可空 | 几何叠加图的授权预览；不作为测量结论 |
| `MeasurementAttempt.series_metadata` | SeriesMetadata，可空 | 工具提供的来源序列映射；大对象可使用 payload_ref |
| `MeasurementAttempt.evidence_refs[]` | EvidenceRef[]，可空 | 此结果产出的证据；引用后仍须由 ChartSpec.provenance 明确选择 |
| `MeasurementAttempt.created_at` | UTC 时间，必填 | Runtime 提交事实时生成 |

模型可比较多个 attempt、继续测量、选择部分证据或停止。工具负责返回可核对事实和局部质量；是否采用由模型决定，并以 ChartSpec.provenance 落实。不存在 `measurement_decision_required` 状态或独立待办队列。

### ChartSpec 与 ChartFigure

ChartSpec、ChartFigure 和 ChartSpecCollection 是不可变业务对象，逻辑数据位于相应 `ExecutionRecord.payload.result`；大对象可以改由唯一 ArtifactRef 保存。ArtifactIndex 只保留索引字段，不复制完整图表。

`ChartSpec.provenance` 是 ChartSpec 内的嵌套对象，不单独持久化。Runtime 自动写入 `input_record_id`；模型只提交待校验的来源引用、用户输入片段映射与变换说明。来源字段是否必填由 `GenerationContext.mode` 和 `GenerationContext.data_origin` 决定，不能用空数组绕过相应模式的要求。

| 对象及字段路径 | 类型/可空性 | 含义与约束 |
|---|---|---|
| `DataPoint.category` | 字符串，可空 | 分类/横轴标签；按 chart_type 与 x 二选一或使用 Schema 规定形式 |
| `DataPoint.value` | 数值或受限文本，可空 | 单值图表的数据值 |
| `DataPoint.x` / `DataPoint.y` | 数值或受限类别值 / 数值，可空 | 二维图的坐标；需要时两者按类型共同必填 |
| `DataPoint.series` | 有界字符串，可空 | 系列标识；同一 dataset 内含义稳定 |
| `DataPoint.confidence` | 0..1 数值，可空 | 点级数据质量提示，不自动表示统计置信区间 |
| `ChartMetadata.chart_type` | 受控图表类型，必填 | 规定 dataset 与 axes 的解释/校验方式 |
| `ChartMetadata.title` | 有界文本，必填 | 图表标题 |
| `ChartMetadata.source` | 有界展示文本，可空 | 面向读者的来源说明；不能替代 provenance |
| `ChartMetadata.note` | 有界文本，可空 | 解释单位、限制或必要注释 |
| `ChartSpec.chart_spec_id` | 不透明 ID，必填 | 单图规格身份 |
| `ChartSpec.schema_version` | 正整数，必填 | ChartSpec 结构版本 |
| `ChartSpec.metadata` | ChartMetadata，必填 | 图表语义与展示元数据 |
| `ChartSpec.dataset[]` | 有序 DataPoint[]，非空 | 图中实际绘制的数据；所有点需通过 chart_type 对应约束 |
| `ChartSpec.axes` | Axis[]，可空 | 轴名、单位、尺度和范围；图表类型要求时必填 |
| `ChartSpec.provenance` | Provenance，必填 | 图表数据来源的机器可校验关联；是 ChartSpec 内嵌对象，不另存 |
| `ChartSpec.provenance.input_record_id` | Record ID，必填 | Runtime 自动绑定当前 Run 的唯一 RunInput 记录，说明图表来自哪个用户请求；模型不得指定其他 Run 的记录 |
| `ChartSpec.provenance.evidence_refs[]` | EvidenceRef ID[]，按 mode 条件必填 | reconstruct / transform / summarize 必须引用实际使用的图像观察或测量证据；synthesize 必须为空 |
| `ChartSpec.provenance.source_refs[]` | SourceRef[]，按 mode 条件必填 | source-linked 模式绑定数据的原始附件/Panel 来源，并覆盖所选证据的来源；synthesize 必须为空 |
| `ChartSpec.provenance.input_data_refs[]` | InputDataRef[]，按 data_origin 条件必填 | synthesize 使用用户在当前 RunInput 文本中明确给出的数值时，记录原文片段到 ChartSpec 数据字段的映射；纯模型示例数据必须为空 |
| `ChartSpec.provenance.transformations[]` | Transformation[]，可空 | source-linked 图表对原数据实际执行的聚合、筛选、单位换算等；synthesize 不记录来源变换 |
| `ChartSpec.generation_context` | GenerationContext，必填 | 本图的数据选择、覆盖和生成目标，字段在 Planning 章节定义 |
| `ChartFigure.figure_id` | 不透明 ID，必填 | 复合图/整张图身份 |
| `ChartFigure.source` | 有界展示文本，可空 | 整体来源标签，不能替代子 ChartSpec provenance |
| `ChartFigure.layout` | 版本化 Layout 对象，必填 | 子图排列、顺序和比例；仅表达布局事实 |
| `ChartFigure.charts[]` | 有序 ChartFigureItem[]，至少一项 | 子图集合，顺序影响最终展示 |
| `ChartFigure.generation_context` | GenerationContext，必填 | 复合图整体取舍、覆盖与布局目标的唯一位置 |
| `ChartFigureItem.chart_id` | 不透明 ID，必填 | 此 Figure 内单张子图身份 |
| `ChartFigureItem.spec` | ChartSpec，必填 | 子图完整规格；其 chart_spec_id 必须唯一 |
| `ChartFigureItem.title` | 有界文本，可空 | Figure 中的局部展示标题；缺省时使用 ChartSpec.metadata.title |
| `ChartSpecCollection.collection_id` | 不透明 ID，必填 | 一组图表集合身份 |
| `ChartSpecCollection.figures[]` | 有序 Figure[]，非空 | 多图输出及其展示顺序 |

ChartSpec 的下列嵌套类型由 ChartSpec.schema_version 统一版本化，字段归属于相应 ChartSpec/ChartFigure，不单独持久化：

| 嵌套对象及字段路径 | 类型/可空性 | 所属与约束 |
|---|---|---|
| Axis.axis_role | x / y / color / size，必填 | 轴/视觉通道类别；同一 chart_spec_id 下同角色按 Schema 限制数量 |
| Axis.label | 有界字符串，必填 | 读者可见轴名 |
| Axis.unit | 有界字符串，可空 | 该轴数值的单位；数据与单位换算需一致 |
| Axis.scale | linear / logarithmic / categorical / date，必填 | 轴的解释尺度；数值要求按 chart_type 校验 |
| Axis.minimum / maximum | 数值或类别边界，可空 | 明确显示范围；minimum 不得大于 maximum |
| Axis.tick_format | 有界格式标识，可空 | 安全、有限的显示格式，不接受任意可执行表达式 |
| Transformation.transformation_kind | filter / aggregate / normalize / convert_unit / sort / other，必填 | 说明数据变换类别 |
| Transformation.input_evidence_refs[] | EvidenceRef ID[]，至少一项 | 变换的来源证据 |
| Transformation.parameters | 版本化 JSON 对象，必填 | 具体变换参数；其 schema 随 transformation_kind 版本化 |
| Transformation.output_summary | 有界文本，必填 | 解释输出变化；不代替数值数据 |
| InputDataRef.input_record_id | Record ID，必填 | 必须等于同一 ChartSpec.provenance.input_record_id；只允许引用当前 RunInput |
| InputDataRef.start_offset / end_offset | Unicode code point 偏移，必填 | 在 RunInput.text 中定位半开区间 `[start_offset, end_offset)`；必须满足 `0 <= start < end <= text.length` |
| InputDataRef.quoted_text | 有界原文片段，必填 | 必须与 RunInput.text 对应区间逐字相等；不能用模型改写后的摘要代替原文 |
| InputDataRef.target_paths[] | ChartSpec JSON Pointer[]，至少一项 | 指向由该原文片段提供的 dataset 字段；路径必须可解析，且不得指向 metadata 或 provenance |
| Layout.layout_kind | grid，首版必填 | ChartFigure 子图布局模型；不在首版接受自由 CSS/任意坐标脚本 |
| Layout.rows / columns | 正整数，必填 | 网格大小 |
| Layout.items[] | LayoutItem[]，与 ChartFigure.charts 一一对应 | 每个子图的展示位置 |
| LayoutItem.chart_id | ChartFigureItem.chart_id，必填 | 绑定布局项与子图 |
| LayoutItem.row / column | 从 0 开始的非负整数，必填 | 网格起点；必须位于 rows/columns 范围内 |
| LayoutItem.row_span / column_span | 正整数，必填 | 占据的网格跨度；不得越界或与其他子图冲突 |
| LayoutItem.aspect_ratio | 正数，可空 | 子图宽高比提示 |
| MeasurementQuality.quality_status | usable / partial / unusable，必填 | 对一次测量结果的可用性判断，不是 Run status |
| MeasurementQuality.confidence | 0..1 数值，可空 | 工具对测量读数可靠性的估计，不解释为统计置信区间 |
| MeasurementQuality.issues[] | MeasurementIssue[]，可空 | 影响测量的可核对问题 |
| MeasurementIssue.code / severity / message | 受控码 / info-warning-error / 有界文本，必填 | 问题分类、程度和说明；error 表示结果不应被直接采用 |
| SeriesMetadata.series[] | SourceSeries[]，可空 | 测量工具检测到的源序列清单；具体来源字段依照 Planning 的 SourceSeries 定义 |
| VerificationIssue.code / severity / message | 受控码 / info-warning-error / 有界文本，必填 | 一条验证问题的类型、程度和安全说明 |
| VerificationIssue.object_path | 字段路径，可空 | 指向 ChartSpec/Manifest 中被检查的字段 |
| VerificationIssue.evidence_refs[] | EvidenceRef ID[]，可空 | 支撑该问题结论的证据引用 |

MeasurementAttempt.target、MeasurementAttempt.series_metadata 与各工具的 Scope 结构属于具体 ToolDefinition 的 schema 子对象。它们必须在 tool_registry_version 下可解析；工具专属字段不能未经声明直接进入 ExecutionRecord。Schema 校验失败应返回有界、带字段路径的类型化错误。

Schema 校验器负责根据 chart_type、dataset、axes 和 Layout 检查结构合法性；字段组合和允许的图表类型属于版本化 ChartSpec Schema。source 展示文本、selection_basis 摘要及用户原话都不能代替证据引用。ChartFigure.generation_context 与子图 ChartSpec.generation_context 分别记录整体和局部取舍，二者字段形状一致、覆盖对象不同。

### ArtifactManifest 与 StagedChartManifest 的文件关系

一个受管 blob 有且只有一条 ArtifactManifest 元数据记录；逻辑 payload_ref 指向该记录。附件有独立的 Attachment 元数据，不重复登记为这里的 ArtifactManifest。 OCR overlay、Panel crop、Measurement overlay 和生成图像字节均可使用 ArtifactManifest.resource_kind=chart_image；只有生成图才另有 StagedChartManifest。生成图使用两层元数据：ArtifactManifest 解释如何读取字节，StagedChartManifest 解释这些字节属于哪次生成、对应哪份图表规格和来源。

| 字段路径 | 类型/可空性 | 权威位置与规则 |
|---|---|---|
| ArtifactManifest.manifest_id | 不透明 ID，必填 | artifact_manifests 主键，也是 ArtifactRef.ref_kind=managed_blob 时的 ref_id |
| ArtifactManifest.resource_kind | structured_json / chart_image，必填 | 受管文件用途；附件不使用此表 |
| ArtifactManifest.run_id / session_id | Run ID / Session ID，必填 | 文件的安全归属 |
| ArtifactManifest.storage_key | 内部 locator，必填 | ArtifactStore 的文件定位值；只由 resolver 使用 |
| ArtifactManifest.content_sha256 | 64 位十六进制 hash，必填 | 文件原始字节摘要；生成图该值等同所关联的 image_sha256 |
| ArtifactManifest.media_type | 受控 MIME，必填 | 文件格式 |
| ArtifactManifest.byte_count | 正整数，必填 | 文件字节数 |
| ArtifactManifest.storage_status | available / deleted，必填 | 文件能否读取；不表示验证/发布状态 |
| ArtifactManifest.created_at / deleted_at | UTC 时间；deleted_at 可空 | 文件元数据创建和物理清理时间 |

StagedChartManifest.image_manifest_id 是 ArtifactManifest.manifest_id 的外键。StagedChartManifest.staged_ref 是 ref_kind=staged_chart 的 ArtifactRef；其 ref_id 对应 staged_chart_manifests 行。PublishedArtifact.artifact_id 是 ref_kind=published_artifact 的 ArtifactRef.ref_id。三种 ref_kind 表示不同授权/业务状态，不可以直接互换；最终发布不复制图像字节，只建立正式领域身份并引用同一 staged 图。

### 暂存、验证与发布

图像生成按 staged → verify → promote 推进。每一步是不同的权威对象，并使用不同的标识；暂存引用不是正式产物 ID。

| 对象/字段路径 | 类型/可空性 | 存储与含义 |
|---|---|---|
| `StagedChartManifest.staged_ref` | 不透明 ArtifactRef，必填 | 精确暂存图的定位引用；公开预览需要另行授权 |
| `StagedChartManifest.run_id` / `session_id` | Run ID / Session ID，必填 | 资源归属；Runtime 验证 owner |
| `StagedChartManifest.work_key` | 稳定不透明键，必填 | 渲染副作用幂等/对账身份 |
| `StagedChartManifest.tool_call_id` | Call ID，必填 | 对应发起图像生成的模型调用 |
| `StagedChartManifest.output_ordinal` | 非负整数，必填 | 同一调用多张输出中的稳定序号 |
| `StagedChartManifest.image_manifest_id` | ArtifactManifest ID，必填 | 指向存有图像字节、image_sha256、media_type 与 byte_count 的唯一文件元数据行 |
| `StagedChartManifest.width` / `height` | 正整数，必填 | 解码并核对后的图像尺寸 |
| `StagedChartManifest.chart_spec_id` / `chart_spec_digest` | ID / 规范化 JSON digest，必填 | 绑定图像对应的精确图表规格 |
| `StagedChartManifest.source_refs[]` | SourceRef[]；source-linked 至少一项，synthesize 为空 | 从精确 ChartSpec.provenance.source_refs 派生并绑定图表视觉来源；不从提示文字另行拼装 |
| `StagedChartManifest.generation_context_digest` | digest，必填 | 绑定对应 GenerationContext 内容；Manifest 不复制其全文 |
| `StagedChartManifest.figure_id`、`collection_id`、`child_chart_id` | ID，可空 | 复合输出存在时保留父子图关系；单图无关字段缺省 |
| `StagedChartManifest.schema_version` / `created_at` | 正整数 / UTC 时间，必填 | Manifest 结构版本与暂存提交时间 |

通用 ArtifactManifest 元数据在 `artifact_manifests` 表；图表业务绑定在 `staged_chart_manifests` 表；图像字节在 ArtifactStore。ArtifactManifest.storage_key 仅用于内部读取，不能进入 API、提示词或报告。图像原子落盘并校验 hash 后，将 ArtifactManifest、StagedChartManifest 与对应 render tool_result ExecutionRecord 在同一 SQLite 事务提交；DB 事务失败时文件保持 unpublished，由同一 Figura root 内的清理器按引用检查后处理。

`VerificationResult` 以 `record_kind=verification_result` 追加到 ExecutionRecord：

| 字段路径 | 类型/可空性 | 含义与约束 |
|---|---|---|
| `VerificationResult.verification_ref` | 不透明 Ref，必填 | 一次不可变验证结论的身份 |
| `VerificationResult.staged_ref` | StagedChartManifest Ref，必填 | 绑定被检查的精确图像 |
| `VerificationResult.status` | `pass` / `pass_with_warning` / `fail` / `unavailable` | 验证总结果；unavailable 不得视为通过 |
| `VerificationResult.image_sha256` | digest，必填 | 核对的图像字节版本 |
| `VerificationResult.chart_spec_digest` | digest，必填 | 核对的 ChartSpec 版本 |
| `VerificationResult.source_refs_digest` | digest，必填 | 核对来源绑定 |
| `VerificationResult.policy_version` | 版本字符串，必填 | 实际使用的 verifier policy |
| `VerificationResult.issues[]` | 有界 VerificationIssue[]，可空 | code、severity、message 与可选对象路径；必须对应可核对检查 |
| `VerificationResult.repair_hint` | 有界文本，可空 | 给模型的修正建议，不自动发起下一工具调用 |
| `VerificationResult.created_at` | UTC 时间，必填 | Runtime 提交时生成 |

确定性检查总是执行；需要来源语义核对时，Verifier 可调用无工具的 VLM。source-linked 图表按授权检查来源图像；synthesize 不传源图像，只检查生成图自身结构、可读性与其声明的示例/用户输入数据映射。`VerificationResult.source_refs_digest` 始终是必填值，按规范化排序后的来源集合计算；source-free 时对空集合 `[]` 计算 digest。结论绑定精确图像、ChartSpec、来源集合和 policy，不可套用于另一张图。

`PublishedArtifact` 作为 `record_kind=promotion_result` 的 payload 子对象追加：

| 字段路径 | 类型/可空性 | 含义 |
|---|---|---|
| `PublishedArtifact.artifact_id` | 不透明 ID，必填 | 正式发布的下载/引用身份 |
| `PublishedArtifact.staged_ref` | Staged Ref，必填 | 原始暂存图 |
| `PublishedArtifact.verification_ref` | Verification Ref，必填 | 必须对应可发布的 pass 或经策略允许的 pass_with_warning |
| `PublishedArtifact.run_id` / `session_id` | Run ID / Session ID，必填 | 发布归属和授权边界 |
| `PublishedArtifact.published_at` | UTC 时间，必填 | Promotion 成功提交时间 |

Promotion 重新验证 Manifest owner、digest、来源和验证策略后才提交 PublishedArtifact；幂等键只由对应 ExecutionRecord.work_key 持有，不在 PublishedArtifact 重复保存。失败或 unavailable 的图可以在明确授权下作为暂存图预览，但不能成为正式交付。多图 collection 中每个 child chart 分别验证、发布，并保留 collection/figure/chart 关系。

最终回答 guard 对比当前有效执行前缀中所有生成图声明与已发布 PublishedArtifact 的完整集合。Prompt 中被裁剪的 ArtifactIndex 摘要只辅助模型理解，不能充当 guard 的校验数据。

### 一次模型轮次与模块位置

1. AgentExecutor 读取 ExecutionCheckpoint；仅当 `next_action.action_kind=model` 时才创建新的 ModelRequest。
2. Memory System 组装 PromptBundle、HistoryMessage[] 与本 Run ToolRegistry 生成的原生工具 Schema。
3. Provider 响应先由 Runtime 提交为完整 model_response ExecutionRecord，并将精确的下一动作写入同一事务的 ExecutionCheckpoint。
4. 如有 tool call，checkpoint 保存 response_record_id 与 call_id；AgentExecutor 校验后执行对应 handler，提交 tool_result 与下一 checkpoint。
5. ChartSpec 经渲染暂存、验证和发布；每个阶段都提交独立事实并由 checkpoint 指向下一步。
6. 模型最终回复进入 final-answer guard；只有 RunCoordinator 能将 Run 置为 completed 并原子提交终态事实。

Agent Core 可报告类型化失败或中断意图，但不改写 Run 生命周期。建议模块为 `figura.agent.executor`、`figura.tools.registry`、`figura.domain.sources`、`figura.domain.evidence`、`figura.domain.charts` 与 `figura.domain.artifacts`；模块路径是实现组织建议，不创建额外状态对象。
## 6. Memory System Design

### 基本原则与边界

Memory System 不建立第二份 AgentMemory 事实库，也不接管 Run 生命周期。它是从 Runtime 权威事实构建的读模型与模型输入装配层。持久事实分别归属 Run、ExecutionRecord、ExecutionCheckpoint、Attachment、ArtifactManifest 和图表领域记录；Memory 生成的 Context、Index、History 和 PromptBundle 都可丢弃并重建。

| 名称 | 对象类别 | 持久化 | 主要消费者 |
|---|---|---|---|
| RunExecutionContext | 当前 Run 的结构化运行读模型 | 否 | AgentExecutor、Planning、PromptAssembler |
| ArtifactIndex | 观察、证据、图表和生成图的只读索引 | 否 | AgentExecutor、PromptAssembler、final-answer guard |
| ConversationHistory | 从提交记录构造的历史消息序列 | 否 | ModelRequest builder |
| PromptBundle | 当前请求的静态职责与动态状态投影 | 否 | Provider adapter |
| HistoryMessage[] | 一次请求的对话协议消息 | 否 | Provider adapter |
| ModelRequest | 一次 Provider 调用的完整应用层输入 | 否 | Provider client |

RunExecutionContext 与 ConversationHistory 不合并：前者描述当前执行身份、授权和可用事实；后者保留用户与助手实际说过什么以及工具调用往返。PromptBundle 不是新的状态所有者，而是把 Context 与 ArtifactIndex 的白名单字段整理成模型可读文本/JSON。

~~~mermaid
flowchart LR
    RUN[Run + ExecutionCheckpoint] --> FACTORY[RunContextFactory]
    REC[ExecutionRecord 前缀] --> FACTORY
    ATT[Attachment + PanelReadModel] --> FACTORY
    MAN[ArtifactManifest] --> FACTORY
    FACTORY --> CTX[RunExecutionContext]
    REC --> HIST[ConversationHistoryReader]
    CTX --> INDEX[ArtifactIndex]
    CTX --> PROMPT[PromptAssembler]
    INDEX --> PROMPT
    HIST --> REQ[ModelRequest]
    PROMPT --> REQ
    TOOLS[本 Run 固定 ToolRegistry] --> REQ
~~~

### RunExecutionContext 的定义与字段

每次模型决策或工具动作前，RunContextFactory 从 Run、当前 ExecutionCheckpoint、RunInput、Attachment、有效 ExecutionRecord 前缀、manifest 和运行取消信号构建一个不可变快照。任何动作提交事实并推进 checkpoint 后，下一步重新构建新 Context，不在旧对象上增量改写。

~~~python
@dataclass(frozen=True)
class RunExecutionContext:
    run: RunSnapshot
    checkpoint: ExecutionCheckpoint
    authorized_source_scope: SourceAuthorizationScope
    artifact_index: ArtifactIndex
    budget: BudgetSnapshot
    interruption_requested: bool
~~~

| 字段路径 | 类型/可空性 | 权威来源与构建时机 | 消费者及是否注入模型 |
|---|---|---|---|
| RunExecutionContext.run | RunSnapshot，必填 | 从 Run 行白名单字段投影；每次 Context 构建读取 | PromptAssembler 仅投影 run_id、session_id、status、provider/model 和必要 lineage 摘要 |
| RunExecutionContext.checkpoint | ExecutionCheckpoint，必填 | ExecutionRepository 当前 checkpoint；读取时核对 record 前缀 | AgentExecutor 选择下一动作；整个 checkpoint、next_action 均不进 PromptBundle |
| RunExecutionContext.authorized_source_scope | SourceAuthorizationScope，必填 | RunInput.attachment_ids、Attachment 当前状态/hash 与 PanelReadModel；每次动作前重校验 | 工具授权检查；Prompt 只获得获准附件与可用 panel 的有界摘要 |
| RunExecutionContext.artifact_index | ArtifactIndex，必填 | 当前有效执行前缀与受管 manifest 的派生索引 | Agent/Planning 消费；Prompt 仅获得有限摘要，guard 查询完整索引 |
| RunExecutionContext.budget | BudgetSnapshot，必填 | Run 的不可变 execution_limits 与已提交执行事实计数 | Prompt 显示 remaining 摘要；Runtime 在执行前硬校验 |
| RunExecutionContext.interruption_requested | bool，必填 | 当前 RunCoordinator 控制句柄/cancellation token 的只读快照 | AgentExecutor 在安全边界停止；不进入 prompt、不持久化到记录 |

RunExecutionContext 不含数据库连接、Repository、Provider client、handler、EventEmitter 或完整附件字节。它只保存当步决策需要的结构化视图。checkpoint 里的唯一下一动作是协议控制事实，不代表模型应当看到或自行重写的计划。

`RunSnapshot` 是 Context 内嵌的只读 Run 投影，不是另一张表：

| 字段路径 | 类型/可空性 | 来源与含义 |
|---|---|---|
| RunSnapshot.run_id / session_id | ID，必填 | 对应 Run 行身份与所属 Session |
| RunSnapshot.status | Run 状态枚举，必填 | running、completed、failed 或 interrupted；只读 |
| RunSnapshot.provider / model | 字符串，必填 | 本 Run 实际选定模型 |
| RunSnapshot.parent_run_id / continuation_kind | ID / 枚举，可空 | 若是 retry/resume child 则用于解释 lineage |
| RunSnapshot.created_at / started_at | UTC 时间，按阶段可空 | 运行时间摘要；不是上下文历史 |
| RunSnapshot.prompt_bundle_version / tool_registry_version / verification_policy_version / execution_policy_version | 字符串，必填 | 本次 Run 锁定的策略版本 |

Context 中缺省的内容有意保留在对应 owner：原始文本在 RunInput/HistoryMessage，附件字节在 ArtifactStore，图表全文在其 chart record/blob，恢复控制只在 ExecutionCheckpoint，生命周期变更只由 RunCoordinator 写入。

### ArtifactIndex 的定义与字段

ArtifactIndex 是从有效 ExecutionRecord 前缀、父 Run 固定前缀、ArtifactManifest、StagedChartManifest、VerificationResult 和 PublishedArtifact 重建的类型化只读索引。它既不是 ArtifactStore，也不是可变 artifact_records 列表。完整引用集合用于校验；PromptAssembler 从中另建有界展示投影。

每个 ArtifactIndex 条目拥有以下公共字段：

| 字段路径 | 类型/可空性 | 来源与含义 |
|---|---|---|
| ArtifactIndexEntry.artifact_kind | 受控枚举，必填 | observation、panel、measurement、chart_spec、chart_figure、chart_spec_collection 或 generated_chart |
| ArtifactIndexEntry.origin_run_id | Run ID，必填 | 创建该事实的 Run |
| ArtifactIndexEntry.origin_record_id | Record ID，必填 | 首次声明该事实的权威 ExecutionRecord |
| ArtifactIndexEntry.source_refs[] | SourceRef[]，可空 | 可追溯来源；不同 artifact_kind 按领域约束设置 |
| ArtifactIndexEntry.summary | 有界文本，可空 | 面向 Agent 决策和 Prompt 的安全摘要，不是完整事实 |
| ArtifactIndexEntry.payload_ref | ArtifactRef，可空 | 完整对象位于 ArtifactStore blob 时的定位值 |
| ArtifactIndexEntry.created_at | UTC 时间，必填 | 源事实创建时间 |

条目按 artifact_kind 添加对应身份和阶段引用，不用通用 artifact_id 混淆领域实体 ID：

| artifact_kind | 条目特有字段 | 来源 |
|---|---|---|
| observation | observation_id、observation_kind、observation_scope、可选 preview_ref | Observation |
| panel | panel_id、revision、attachment_id、attachment_content_sha256、可选 crop_ref | PanelRecord |
| measurement | attempt_id、evidence_refs、quality、可选 preview_ref | MeasurementAttempt |
| chart_spec | chart_spec_id、provenance_evidence_refs、generation_context_summary(mode/data_origin/goal/coverage) | ChartSpec；common source_refs 从 provenance.source_refs 派生 |
| chart_figure | figure_id、child_chart_ids、generation_context_summary(mode/data_origin/goal/coverage) | ChartFigure；common source_refs 是子图来源去重并集 |
| chart_spec_collection | collection_id、figure_ids、各 Figure 的 generation_context_summary | ChartSpecCollection 与所含 Figure；common source_refs 是 Figure 来源去重并集 |
| generated_chart | staged_ref、可选 verification_ref、可选 PublishedArtifact.artifact_id、collection/figure/chart 关联、派生 publish_status | Manifest、VerificationResult、PublishedArtifact |

generated_chart 条目的 publish_status 是从权威阶段事实推导的展示状态，不单独写入。它可区分 staged、verified、published、verification_failed、verification_unavailable；该状态不能替代 VerificationResult.status 或 PublishedArtifact 是否存在。

ArtifactIndex 按当前 Run 的有效执行前缀与经授权父前缀限定范围。Session 中已有 panel 可以作为可读来源，但不因此成为本轮新生成的产物。显式 resume 可读取固定且校验通过的父 ExecutionRecord 前缀；retry 只读取原始 RunInput，不继承父生成图。最终回答 guard 查询完整条目及 manifest 事实，不能依赖被裁剪的模型摘要。

因此旧概念 artifact_records 与 current_output_artifacts 不再对应两份维护中的状态：
- 所有已观察、测量、图表和生成图事实由 ArtifactIndex 统一索引。
- “本次正式输出”是从当前有效前缀筛选存在 PublishedArtifact 的 generated_chart 条目所得的查询结果。
- 图片字节仍由 ArtifactStore 保存；领域事实仍由 ExecutionRecord/ArtifactManifest 保存；ArtifactIndex 可以删除并重建。

完整 GenerationContext 留在 ChartSpec 或 ChartFigure 上；ArtifactIndex 仅携带 ID、digest 或有界摘要，不复制完整 GenerationContext。不存在另一份平行 decision_context。

### ConversationHistory 与 HistoryMessage

ConversationHistoryReader 根据已提交 ExecutionRecord 与 RunInput 构造本次 Provider 调用所需消息。历史消息不从提示词文本逆向解析，也不单独存储。每个 HistoryMessage 都能追溯到源记录；裁剪可影响普通历史输入长度，但不能影响恢复所需的执行事实。

| 字段路径 | 类型/可空性 | 含义与生成规则 |
|---|---|---|
| HistoryMessage.role | user / assistant / tool，必填 | 保留原始对话协议角色 |
| HistoryMessage.source_run_id | Run ID，必填 | 消息来源 Run |
| HistoryMessage.source_record_id | Record ID，必填 | 原始输入、model_response 或 tool_result 记录 |
| HistoryMessage.record_sequence | 正整数，必填 | 在其来源 Run 内的事实顺序 |
| HistoryMessage.content[] | 有序 HistoryContentBlock[]，可空 | 文本及受控多模态引用；assistant tool call 消息可以无文本内容 |
| HistoryMessage.tool_calls[] | HistoryToolCall[]，assistant 消息可空 | 保留模型返回的调用顺序与参数 |
| HistoryMessage.tool_call_id | 字符串，tool 角色必填 | 精确匹配之前 assistant 的 ToolCall.call_id |

HistoryContentBlock 使用 content_kind 判别：
- text：携带受控长度的 text；用户原文按隐私策略保存在 RunInput 记录中，投影时不改写语义。
- image_ref：携带 AttachmentRef 或授权 ArtifactRef；只传资源引用，不将图片字节放入 HistoryMessage JSON。
- 其他多模态块仅在 Provider adapter 明确支持且拥有稳定序列化 Schema 后增加，不使用任意自由 JSON。

HistoryToolCall 包含 call_id、name 和 arguments，源自 model_response.tool_calls[]；其 tool reply 必须有同一 call_id 的 tool_result 记录。Provider 要求将工具回复转为文本/JSON 时，由 adapter 根据 tool_result 做有界序列化，不能把工具结果伪装成 user/assistant 消息。

当前对话消息构建顺序：
1. 读取同一 Session 中此前正常完成且符合产品历史策略的 Run 对话块。
2. 按当前 Run 的 ExecutionRecord.record_sequence 追加已提交前缀；RunInput.input_record_id 只产生一条 user 消息。
3. 保留 assistant 消息、tool_calls 和相匹配的 tool 消息的原始先后关系；不构造孤立 tool 回复。
4. final_answer 指向的响应仍来自相应 model_response 事实；不再保存第二份可变答复正文。
5. 在 provider token 预算内对旧的完整 Run 对话块裁剪或摘要；当前 Run 协议往返不得裁成无法匹配的残片。
6. 失败/中断 Run 默认不自动并入下一次普通请求；显式 resume 按固定父前缀读取，retry 从父 RunInput 重建新对话，不继承父执行工具往返。

普通历史摘要是可重建输入优化；Checkpoint、ExecutionRecord 才是精确恢复来源。RunStreamEvent 是安全客户端投影，不代替对话记录。

### PromptBundle 与 ModelRequest

每次 Provider 调用新建 PromptBundle 和 ModelRequest。两者都不持久化为 Run 状态；Run 只保存使用的版本号和必要的脱敏诊断元数据。四类静态职责、动态工具说明、当前 Runtime 状态和产物/证据索引全部按本节规定的对象来源投影。

| 字段路径 | 类型/可空性 | 来源与用途 |
|---|---|---|
| PromptBundle.prompt_bundle_version | 不透明版本字符串，必填 | 与 Run.prompt_bundle_version 一致 |
| PromptBundle.static_duties[] | 有序 PromptSection[]，必填 | 四份静态职责资产，按固定顺序装配 |
| `PromptBundle.dynamic_tool_instructions[]` | 有序 ToolInstruction[]，可空 | 当前 ToolRegistry 版本内已授权工具的模型可读说明 |
| PromptBundle.runtime_state | 有界 JSON 投影，必填 | RunExecutionContext.run、authorized_source_scope 和 budget 的字段白名单；panel 摘要通过 available_panel_refs 与同一 Context.artifact_index 的 panel 条目关联生成 |
| PromptBundle.artifact_evidence_index | 有界 JSON 投影，可空 | RunExecutionContext.artifact_index 的安全摘要 |
| PromptSection.section_name | agent_role / evidence_rules / workflow / response_rules，必填 | 固定职责段落名，用来校验四类内容齐全 |
| PromptSection.asset_version | 版本字符串，必填 | 单个 asset 版本；并入 bundle version |
| PromptSection.content | UTF-8 文本，必填 | 静态职责说明 |
| ToolInstruction.tool_name | ToolDefinition.name，必填 | 对应 API Schema 名称 |
| ToolInstruction.prompt_guidance | ToolDefinition.prompt_guidance，必填 | 同一 ToolDefinition 的动态可读适用时机和限制 |

PromptBundle 的 runtime_state 只保留模型决策需要的 Run 身份/状态、已获授权附件/可用 panel 摘要和剩余预算；不能包含 database locator、Attachment.storage_key、cancellation token、完整 ExecutionCheckpoint、next_action、RunInput 隐私字段之外的服务端数据或 provider 内部字段。artifact_evidence_index 是有界目录投影，具体条目和截断策略由 ArtifactIndex 投影器实现；不得将摘要当成 final-answer guard 数据。

ModelRequest 是 Provider adapter 的输入 DTO：

| 字段路径 | 类型/可空性 | 来源与用途 |
|---|---|---|
| ModelRequest.provider | Provider ID，必填 | Run 实际配置 |
| ModelRequest.model | 模型名，必填 | Run 实际配置 |
| ModelRequest.prompt_bundle | PromptBundle，必填 | 系统/开发者职责与动态状态上下文 |
| ModelRequest.messages[] | HistoryMessage[]，必填 | 从 ConversationHistoryReader 构造 |
| ModelRequest.tools[] | ProviderToolSchema[]，可空 | 从同一 ToolDefinition 的 summary 与 parameters 生成；只含本次已授权工具 |
| ModelRequest.provider_options | 版本化有限配置对象，可空 | 温度、输出上限等经配置批准的请求选项；不记录密钥 |

ProviderToolSchema 是 ProviderAdapter 的临时协议 DTO，不持久化：

| 字段路径 | 类型/可空性 | 唯一来源与限制 |
|---|---|---|
| ProviderToolSchema.name | 稳定工具名，必填 | ToolDefinition.name |
| ProviderToolSchema.description | 最多 160 字符，必填 | ToolDefinition.summary；短说明可重复工具名，但不复制动态 guidance |
| ProviderToolSchema.parameters | 对象 JSON Schema，必填 | ToolDefinition.parameters 的 Provider 兼容投影；属性名、required、enum、约束不能被 Adapter 静默放宽 |
| ProviderToolSchema.strict | 可选 Provider 能力标志 | 由 ProviderAdapter capability 决定；不改变领域 Schema 和服务端二次校验 |



Provider adapter 负责把 PromptBundle 映射到 Provider 的 system/developer 通道，把 HistoryMessage[] 映射到原生 messages，把 tools 映射到 Provider 原生 Schema 参数。当前用户文字与图像引用作为 user 消息进入对话历史，不拼接为静态系统提示。验证器如使用 VLM，另建无工具的 VerificationRequest 和专用验证 prompt，不复用主 Agent 完整 ModelRequest。

### 提示词四类内容的来源表

| 提示词内容 | 唯一权威来源 | ModelRequest 中的位置 | 是否在 RunExecutionContext |
|---|---|---|---|
| 四份静态职责提示：Agent 角色、证据规则、工作方式、回答边界 | 版本化 prompt assets；建议 agent.md、evidence.md、workflow.md、response.md | PromptBundle.static_duties，映射到 system/developer | 否；只记录 bundle version |
| 动态工具说明 | 已授权 ToolDefinition | PromptBundle.dynamic_tool_instructions，映射到 system/developer | 否；注册表是来源 |
| 当前 Runtime 状态 | RunExecutionContext.run、authorized_source_scope、budget 白名单投影 | PromptBundle.runtime_state，映射到 system/developer | 是，结构化原数据在 Context |
| 产物与证据索引 | RunExecutionContext.artifact_index 白名单摘要 | PromptBundle.artifact_evidence_index，映射到 system/developer | 是，完整可重建索引在 Context |
| 对话历史 | ConversationHistoryReader | ModelRequest.messages 原角色序列 | 否；Context 不保存 messages |
| API 原生工具 Schema | 同一 ToolDefinition.parameters | ModelRequest.tools | 否；由本 Run 固定 ToolRegistry 投影 |

静态职责和动态工具说明是文本提示；API Schema 是 Provider 协议参数；当前 Runtime 状态和产物索引是动态投影；对话历史是独立 messages。它们在一次 ModelRequest 中共同送入模型，但来源和持久化位置不同。用户文本、OCR、图片内容与工具返回自由文本都是不可信输入，不能覆盖静态职责、来源授权或发布事实。提示摘要允许裁剪，Runtime 校验不得裁剪权威来源。

### 主 Agent Prompt 资产与静态职责

与 ChartAgent v1 的差异：当前旧 loader 把静态职责、动态工具说明、runtime 与 artifacts 合并成一个 system 字符串；tools.md 还会把参数名和完整 JSON Schema 再打印一遍，同时 Provider 请求另传 native tools。Figura 保留四份职责资产和动态三层信息，但明确 system/developer/messages/native tools 四个协议位置；动态工具说明使用 ToolDefinition.prompt_guidance，原生 Schema 使用短 summary 和 parameters，完整参数 Schema 只在 ModelRequest.tools 出现一次。旧资产可作内容参考，不由 Figura 运行时直接加载或共享版本号。

Figura 的提示词资产属于新包，不直接引用 ChartAgent v1 的动态运行时 JSON。建议目录固定为 src/figura/prompting/assets/：

| 资产路径 | PromptSection.section_name | 唯一职责 | 必须覆盖的规则 | 不应放入 |
|---|---|---|---|---|
| static/agent.md | agent_role | 定义 Figura 主 Agent 身份、用户目标和决策边界 | 简体中文回复；模型选择普通分析、工具、澄清或停止；代码只执行、校验和提交；只调用本次 ModelRequest.tools 中存在的工具 | 当前 Run 状态、工具清单副本、具体 measurement 结果 |
| static/evidence.md | evidence_rules | 定义来源、观察、证据和不确定性纪律 | SourceRef/EvidenceRef 含义；OCR、几何、模型观察都是候选证据而非自动真值；reconstruct / transform / summarize 必须引用真实来源证据；synthesize 必须声明 user_provided_data 或 model_generated_example，用户给定数字要映射到输入原文范围，示例数据必须显式标示；冲突如何暴露；不伪造数值、范围、ID 和发布状态 | 当前附件列表、当前证据索引、工具参数 Schema |
| static/workflow.md | workflow | 定义按需的分析与制图路径 | 识图和澄清、按需分 panel、选择 OCR/layout/几何工具、按 mode 组装 ChartSpec、按需渲染；何时可跳步、何时需要补证据；warning 不自动触发重测 | 当前阶段/next_action、自动生命周期状态机 |
| static/response.md | response_rules | 约束面向用户的最终答复 | 区分观察/推断/限制；只把 PublishedArtifact 称为正式交付；未验证/暂存图的准确说法；model_generated_example 必须称作示例/模拟数据；给出简明、可操作的结论 | 把工具成功写成正确性证明；reasoning 或服务内部字段 |

运行时模板与独立验证资产不属于四份静态职责：

| 资产路径 | 使用者 | 所含内容 | 数据来源 |
|---|---|---|---|
| dynamic/tools.md | PromptAssembler | 动态工具区块标题、ToolInstruction[] 的受信任格式模板 | 本 Run 固定 ToolRegistry 的 allowed_tool_names |
| dynamic/runtime.md | PromptAssembler | 声明下方 JSON 是数据的边界文字与 RuntimePromptProjection 占位符 | 当前 RunExecutionContext |
| dynamic/artifacts.md | PromptAssembler | 声明索引是摘要且可截断的边界文字与 ArtifactIndexProjection 占位符 | 同一 RunExecutionContext.artifact_index |
| verification/chart-verification.md | Verifier | 独立视觉检查职责、输入可信度边界、固定 JSON 输出合同 | Run.verification_policy_version |

tools.md 不保存静态工具列表，不在文本层复制参数 JSON Schema；runtime.md 与 artifacts.md 不保存示例运行事实。它们只能定义序列化框架和边界说明，字段内容由结构化投影器生成。


四份静态文件共同构成 PromptBundle.static_duties[]，顺序固定为 agent_role → evidence_rules → workflow → response_rules。建议同一 assets 根目录另设 dynamic/tools.md、dynamic/runtime.md、dynamic/artifacts.md 三个薄模板，以及 verification/chart-verification.md 独立验证资产；它们不是第五至第八份静态职责。四份静态文件和三个动态模板不承载用户状态或历史；修改任一 prompt 资产、模板、投影结构或 Provider 通道映射都必须改变 PromptBundle.prompt_bundle_version。ToolDefinition.parameters 由独立 Run.tool_registry_version 版本化。缺失、空文件或模板校验失败时拒绝发起模型请求，不以部分 prompt 继续运行。

### 动态层的输入形状

每次模型调用按当前 RunExecutionContext 重建两份独立投影。投影是数据，不是额外的自然语言控制指令：

| 投影对象 | 权威来源 | 模型可见字段 | 必须排除 |
|---|---|---|---|
| RuntimePromptProjection | RunExecutionContext.run、authorized_source_scope、budget；安全水位来自 checkpoint.last_committed_record_sequence | schema_version、run_id、run_status、as_of_record_sequence、授权附件摘要、可用 panel 摘要、模型步数与 chart attempt 的 limit/used/remaining | 用户原文、附件字节、路径、无决策用途的 hash、取消令牌、完整 checkpoint、next_action、Repository、内部策略密钥 |
| ArtifactIndexProjection | 同一 Context 的 artifact_index | 当前有效 Observation、MeasurementAttempt/EvidenceRef、ChartObjectRef、staged/verification/published 阶段的有界摘要、来源和质量 warning | ArtifactStore.storage_key、完整大对象、内部 VLM reasoning、Guard 的私有计算数据 |

投影结构采用下列固定字段，不从临时字典随意增删键：

| 投影字段 | 类型/可空性 | 唯一来源 |
|---|---|---|
| RuntimePromptProjection.schema_version | 正整数，必填 | RuntimePromptProjection Schema 版本 |
| RuntimePromptProjection.run_id | Run ID，必填 | RunExecutionContext.run.run_id |
| RuntimePromptProjection.run_status | Run 状态枚举，必填 | RunExecutionContext.run.status；通常为 running |
| RuntimePromptProjection.as_of_record_sequence | 非负整数，必填 | RunExecutionContext.checkpoint.last_committed_record_sequence；只表示提示快照水位 |
| RuntimePromptProjection.authorized_sources.attachment_refs[] | AttachmentPromptEntry[]，可空 | RunExecutionContext.authorized_source_scope.authorized_attachment_refs[] |
| AttachmentPromptEntry.attachment_id | Attachment ID，必填 | AttachmentRef.attachment_id |
| AttachmentPromptEntry.display_name / media_type | 安全文本 / MIME，必填 | Attachment 元数据的白名单字段；不传 storage_key、完整路径或原始 hash |
| AttachmentPromptEntry.width / height | 正整数，可空 | 已解析图像尺寸；不代表图像内容已分析 |
| RuntimePromptProjection.authorized_sources.panel_refs[] | PanelPromptRef[]，可空 | RunExecutionContext.authorized_source_scope.available_panel_refs[] 的安全投影；只列可选身份，不传 hash 或 panel 摘要 |
| PanelPromptRef.panel_id / revision / attachment_id | Panel ID / 正整数 / Attachment ID，必填 | 唯一定位当前授权的 panel 修订；hash 仅在服务端校验 |
| RuntimePromptProjection.budget.model_steps | BudgetPromptEntry，必填 | RunExecutionContext.budget |
| RuntimePromptProjection.budget.chart_attempts | BudgetPromptEntry，必填 | RunExecutionContext.budget |
| BudgetPromptEntry.used / limit / remaining | 非负整数，必填 | 对应 BudgetSnapshot；remaining 为派生值，Runtime 执行前仍重新校验 |

ArtifactIndexProjection 是不同对象，至少含 schema_version、as_of_record_sequence、entries[]、truncated、omitted_entry_count。entries[] 每项保留 artifact_kind、源对象 ID/ref、origin_record_id、必要的 source_refs、有界 summary/warnings；再按 artifact_kind 使用前表定义的 variant 字段。as_of_record_sequence 必须与 RuntimePromptProjection 水位相同，否则 PromptAssembler 丢弃旧投影并重建，不混合不同执行前缀。

主 Agent 可见的动态 JSON 形状示例（值为占位符，不代表当前运行状态）：

~~~json
{
  "runtime_state": {
    "schema_version": 1,
    "run_id": "run_opaque",
    "run_status": "running",
    "as_of_record_sequence": 12,
    "authorized_sources": {
      "attachment_refs": [
        {
          "attachment_id": "attachment_opaque",
          "display_name": "sales-chart.png",
          "media_type": "image/png",
          "width": 1600,
          "height": 900
        }
      ],
      "panel_refs": [
        {
          "panel_id": "panel_opaque",
          "revision": 1,
          "attachment_id": "attachment_opaque"
        }
      ]
    },
    "budget": {
      "model_steps": {"used": 2, "limit": 12, "remaining": 10},
      "chart_attempts": {"used": 0, "limit": 3, "remaining": 3}
    }
  },
  "artifact_evidence_index": {
    "schema_version": 1,
    "as_of_record_sequence": 12,
    "truncated": false,
    "omitted_entry_count": 0,
    "entries": [
      {
        "artifact_kind": "measurement",
        "attempt_id": "attempt_opaque",
        "source_refs": ["panel_opaque@1"],
        "quality": "partial",
        "evidence_refs": [
          {
            "evidence_id": "evidence_opaque",
            "display_ref": "B1",
            "evidence_kind": "bar_geometry",
            "summary": "一个柱体候选，标签关联不确定"
          }
        ]
      }
    ]
  }
}
~~~

工具 arguments 中的 attachment_id、panel_ref 与 evidence_id 必须从这些有效投影或当前对话中出现的已提交结果引用；Provider 不可依赖显示名、摘要或示例字段值推导权限。完整 content_sha256 只由 Runtime 在服务端授权比较；Prompt 投影不暴露它。


授权附件条目的模型可见形状限定为 attachment_id、安全显示名、media_type、宽高（若已知）与可选 summary；显示名视为不可信数据并 JSON 转义。RuntimePromptProjection 只列授权 PanelRef[] 身份；Panel 的安全 name/slug、role、chart_type、summary 与 warnings 只在 ArtifactIndexProjection.panel 条目中展开。两个投影可以共享 panel_ref 作为连接键，不重复 panel 描述字段。Prompt 不提供一个需同步维护的 selected_panel_id；当前工具选择保留在 ToolCall.arguments，授权 inventory 仅说明“允许使用什么”。

ArtifactIndexProjection 按以下 variant 编码，不使用含义模糊的自由字段包：

| artifact_kind | Prompt 摘要字段 | 用途 |
|---|---|---|
| observation | observation_id、observation_kind、source_refs、summary、warnings、payload_ref、preview_ref | 指出已发生的 OCR/layout/视觉观察 |
| measurement | attempt_id、tool_name、source_refs、effective_scope、observation_scope、quality、warnings、evidence_refs | 让 Agent 选取或忽略候选证据 |
| panel | panel_ref、name、role、chart_type、summary、warnings | 复用有效 PanelRecord 和局部来源 |
| chart_spec / chart_figure / chart_spec_collection | ChartObjectRef、source_refs、GenerationContext 的 mode/data_origin/goal_summary/coverage 摘要、verification 关联 | 后续精确引用或渲染已提交图表对象；source-free synthesize 的 source_refs 为空且仍保留 data_origin |
| generated_chart | staged_ref、verification_ref/status、artifact_id（已发布时）、图表关联 | 区分暂存、验证失败/不可用和正式发布 |

Prompt 中的索引是有界、可截断的导航摘要；实际证据在相应 HistoryMessage/tool_result 或可解析 ArtifactRef 中。索引被截断时必须附 truncated=true 与遗漏计数，不能因此声称没有相关证据。最终答案 guard 使用完整 ArtifactIndex/发布事实，不读取此摘要。current_output_artifacts 不作为另一份 Context/Prompt 字段；正式输出是从当前有效前缀筛出存在 PublishedArtifact 的 generated_chart 条目。

### 单次主 Agent 请求的精确组装顺序

~~~mermaid
flowchart TD
    STATIC[四份静态职责资产<br/>固定顺序] --> BUNDLE[PromptBundle]
    TOOLDESC[授权 ToolDefinition.prompt_guidance] --> DYNAMIC[动态开发者上下文]
    CONTEXT[RunExecutionContext<br/>白名单 RuntimePromptProjection] --> DYNAMIC
    INDEX[同一 Context.artifact_index<br/>ArtifactIndexProjection] --> DYNAMIC
    DYNAMIC --> BUNDLE
    HIST[ConversationHistory<br/>user / assistant / tool 消息] --> REQ[ModelRequest]
    BUNDLE --> REQ
    SCHEMA[ToolDefinition.summary 与 parameters<br/>Provider 原生 tools Schema] --> REQ
    REQ --> MODEL[主 Agent Provider]
~~~

装配顺序和角色固定如下：

1. PromptBundle.static_duties[] → Provider system/instructions 通道；按四职责顺序。
2. dynamic_tool_instructions[]、runtime_state、artifact_evidence_index → Provider developer/context 通道；内部顺序为工具说明 → Runtime JSON → Artifact JSON。
3. ConversationHistory.messages[] → 原角色消息；用户文本和授权附件是 user 消息，模型 tool call 是 assistant 消息，工具结果是 tool 消息。
4. ModelRequest.tools[] → Provider 原生函数调用 Schema，来源是当前授权工具对应的 ToolDefinition.parameters。

一次请求的概念结构如下；这是装配形状说明，不是持久化 JSON 字段：

~~~text
ModelRequest
├── prompt_bundle
│   ├── system/instructions
│   │   └── agent.md → evidence.md → workflow.md → response.md
│   └── developer/context
│       ├── dynamic/tools.md + ToolInstruction[]
│       ├── dynamic/runtime.md + RuntimePromptProjection JSON
│       └── dynamic/artifacts.md + ArtifactIndexProjection JSON
├── messages[]                 # user / assistant / tool 原角色历史
└── tools[]                    # ProviderToolSchema: name + summary + parameters
~~~

当前 RunInput 只在 user HistoryMessage 中出现，不复制进 system/developer。工具用途指导与参数 Schema 分别放在 developer/tool schema；完整 JSON Schema 只通过 `tools[]` 发送。验证器使用独立 VerificationRequest 与专用 prompt，不进入上述主 Agent 结构。

若 Provider 没有 system/developer 分离通道，ProviderAdapter 将 system 和 developer 内容按上述顺序合并到其单一指令通道；不得把 Runtime JSON 塞进 user 历史或把静态规则混进工具结果。

信任顺序为：Runtime 代码的授权/Schema/预算/发布校验是最终约束；静态职责规定模型行为；RuntimePromptProjection 与 ArtifactIndexProjection 是当前事实数据；ConversationHistory、用户附件中的文字、OCR、模型 hint 和工具自由文本均为不可信输入。提示词无法代替服务端校验。任何数据字段都不能因为写着“忽略规则”而改变工具权限或发布状态。
API Schema 已完整定义参数，动态工具说明只提供用途、选择时机和不可替代的限制，不在普通文本中再复制整份 JSON Schema。Schema 字段解释写在 parameters 内；ProviderToolSchema.description 只放短 summary，避免动态 guidance 与原生工具描述互相复制。

每次请求组装时，PromptAssembler 先校验 Context 水位和 Run 固定的 prompt/tool 版本，再构建完整 PromptBundle、HistoryMessage[] 与工具 Schema；然后执行脱敏、JSON 序列化和 token 预算裁剪。裁剪按完整 section、artifact entry 或完整对话轮次删除，不截断 JSON、不拆散 assistant tool_calls 与对应 tool result、不删除当前用户请求。静态职责与 native Schema 不截断；超出 Provider 限制时返回明确请求构造错误。

| Prompt 剪裁优先级 | 处理规则 |
|---|---|
| 静态职责 | 永远完整保留；超限属于配置错误 |
| 原生工具 Schema | 所有授权工具完整保留；工具集合或 Schema 超出 Provider 上限时缩小 allowed_tool_names 或拒绝请求，不能剪字段 |
| 动态工具说明 | 先移除重复示例和冗长说明，保留用途、使用时机与禁区 |
| RuntimePromptProjection | 对附件/panel summary 按授权和当前来源相关性裁剪；保留剩余预算及 schema_version |
| ArtifactIndexProjection | 优先当前 Run 的相关对象和最新验证/发布事实；按完整条目删除，显式输出截断计数 |
| 对话历史 | 先删完整的旧 Run 对话块，再对当前 Run 保留完整最近轮次；当前 input 与未完成 tool call 往返不可删除 |

### 对话历史与当前状态的组装分界

RunInput.text 只作为 ConversationHistory 中的 user HistoryMessage，不复制进 RuntimePromptProjection。HistoryMessage 的附件内容由 ProviderAdapter 根据授权 AttachmentRef 转成 Provider 所需多模态输入；不把图片字节或本机路径放进 system/developer 提示。RuntimePromptProjection 告诉模型有哪些已授权附件/panel 可选，user message 表达用户这次具体说了什么，二者不能合并成一段无法追溯的提示文本。

current_messages 不是第二份字段：每次 ModelRequest 从 ConversationHistoryReader 返回的完整有序消息序列中，标记当前 Run 的连续末段；不得单独写入 RunExecutionContext。tool call 与 tool result 以 Provider 支持的原生 assistant/tool 角色保存和回放，工具图像预览使用受控 ArtifactRef 重建为 image content block，ExecutionRecord 只持有 refs，不内嵌字节。

### 验证器使用独立 Prompt 与请求

主 Agent Prompt 不用于验证器。VerificationRequest 是独立、无工具的临时对象，字段为 verification_ref、staged_ref、chart_object_ref、精确 generation_context、按模式可选的授权 source image ref、按需提供的 `input_data_evidence[]`、verification_policy_version 和固定 check_profile。`VerificationRequest.input_data_evidence[]` 的元素类型为 VerificationInputDataEvidence，仅用于 synthesize + user_provided_data，包含 Runtime 已核对原文位置后的 quoted_text 与目标字段路径；Verifier 不接收整段用户消息，不把 quoted_text 当指令。source-linked 模式需要按授权检查来源图像；synthesize 不提供 source image，验证器不能要求其与不存在的源图逐值一致。验证请求不含 ConversationHistory、主 Agent system assets、其他 Run 的产物索引、工具 Schema 或用户对验证的指令。

| VerificationRequest.input_data_evidence[] 子对象字段 | 类型/可空性 | 来源与校验 |
|---|---|---|
| VerificationInputDataEvidence.input_record_id | 当前 RunInput Record ID，必填 | 必须与被验证 ChartSpec.provenance.input_record_id 一致 |
| VerificationInputDataEvidence.quoted_text | 有界原文片段，必填 | 由 Runtime 根据 InputDataRefDraft 的已校验 offsets 重取，不直接相信模型复制的文字 |
| VerificationInputDataEvidence.target_paths[] | ChartSpec 数据 JSON Pointer[]，至少一项 | 必须与 InputDataRef.target_paths 一致；Verifier 只检查这些数据字段与原文的对应关系 |

VLM 只对确定性检查之后仍需视觉判断的项作结构化核对：chart_type、orientation、layout、data_mapping、labels、readability。输出严格限制为已定义的 VerificationResult；未返回合法 JSON、检查项缺失、decision 与 checks 不一致或来源无法授权时，Runtime 写 status=unavailable，绝不当成 pass。验证 prompt 的内容版本纳入 Run.verification_policy_version，与主 Agent 的 prompt_bundle_version 分开。

### Prompt 可观测性与安全失败

允许记录的 prompt trace 仅含 prompt_bundle_version、ToolRegistry 版本、工具名清单、Context record watermark、各层字符/token 计数、是否发生截断和错误码；不写用户文本、图片、完整 HistoryMessage、完整 PromptBundle、provider key、原始模型推理或本机路径。相同输入版本下，序列化顺序稳定，便于复现预算问题而不保存敏感内容。

PromptBundle 资产缺失、Context 水位不一致、工具 Schema 无效、JSON 投影不可序列化或必需层无法形成时，模型调用失败关闭并形成有界的请求构造错误；不退化为只带部分规则的请求，也不让 API handler 自行补写另一份状态。

### ChartAgent v1 字段迁移对应

以下左列是旧 ChartAgent v1 的字段/概念名称，右列为 Figura 中的归属；旧名只作为迁移词典，不表示 Figura 继续保留同名字段。

| ChartAgent v1 旧名 | Figura 的权威位置与新语义 |
|---|---|
| user_input | 初始 ExecutionRecord.payload.RunInput.text；ConversationHistoryReader 将其投影为 user HistoryMessage |
| messages / current_messages | 从 ExecutionRecord 重建的 HistoryMessage[]；不放入 RunExecutionContext |
| recovery、pending_recovery_calls | ExecutionCheckpoint 的 typed next_action、已提交前缀与 Run lineage；不保存动态恢复字典 |
| tools | 进程级 ToolRegistry；工具说明、Schema、handler、replay_effect 同属 ToolDefinition |
| emitter | Gateway/CLI 的安全事件投递 adapter；不属于 Context |
| layout_contexts / measurement_sessions | PanelRecord、Observation、MeasurementAttempt 的不可变事实和 ArtifactIndex 引用 |
| artifact_records / current_output_artifacts | 一个派生 ArtifactIndex；正式输出按 PublishedArtifact 存在与有效前缀查询 |
| visual_references | Observation/EvidenceRef 及其受控 ArtifactRef |
| selected_panel_id | 当前 ToolCall.arguments 中显式 panel_id；Context 只列 available_panel_refs |
| current_tool_name | 当前 ToolCall.name 或最近已提交 tool_result.tool_name 的只读投影；不作为 Context 持久状态 |
| pending_action | 迁为 ExecutionCheckpoint.next_action 的 typed union；不再使用自然语言自由字段 |
| max_layout_contexts | Prompt/PanelReadModel 的实现配置；不属于 Context 权威业务字段 |
| generation_context / decision_context | GenerationContext 仅在对应 ChartSpec/ChartFigure；不另存完整 decision_context |

Memory 建议模块为 figura.memory.context、figura.memory.artifact_index、figura.memory.history 和 figura.prompting.assembler。它们只读 Runtime 权威事实，不得写入另一份 AgentMemory 或与 Run 同步维护的列表。
## 7. Planning System Design

### 规划的含义与数据边界

Planning System 表达“主 Agent 如何基于当前事实选择下一步”，不创建独立的持久 Plan、phase 队列、decision_context 大对象或第二套预算计数器。一次决策的结构化输入来自 RunExecutionContext、ArtifactIndex、HistoryMessage[]、ToolDefinition 和已提交验证事实；模型输出的 tool call、ChartSpec 或回答进入 ExecutionRecord。图表生成时的取舍写入 ChartSpec/ChartFigure 上的 GenerationContext。

| 决策输入 | 权威来源 | Planning 如何使用 |
|---|---|---|
| 用户目标与对话上下文 | ConversationHistoryReader 输出的 HistoryMessage[] | 理解当前请求；不复制进 PlanningState |
| 当前 Run 和模型配置 | RunExecutionContext.run | 解释本次会话与实际运行配置 |
| 可访问来源 | RunExecutionContext.authorized_source_scope | 代码许可的上限；不代表已被选择 |
| 已有观察、测量、图表和生成结果 | RunExecutionContext.artifact_index 的有界模型投影 | 判断已有事实和可复用结果 |
| 当前可用工具 | 当前 Run 固定版本 ToolRegistry | 模型选择工具；Runtime 仍校验 Schema 和授权 |
| 剩余预算 | RunExecutionContext.budget | 模型参考剩余量；Runtime 硬性拒绝越限动作 |
| 图表验证反馈 | 有效前缀中的 VerificationResult.issues 与 repair_hint | 可供模型修正；repair_hint 本身不执行工具 |

Planning 不直接写 Run、checkpoint、ArtifactIndex 或 Timeline。它将请求发给 AgentExecutor；AgentExecutor 执行并提交后，Memory System 再从新事实构建 Context。没有额外的可变 planning state 需要与 Run 同步。

~~~mermaid
flowchart TD
    HIST[用户目标与历史消息] --> DECIDE[主 Agent 选择下一动作]
    SCOPE[授权来源上限] --> DECIDE
    INDEX[已有观察/测量/图表索引] --> DECIDE
    TOOLS[已授权工具 Schema] --> DECIDE
    BUDGET[剩余预算] --> DECIDE
    DECIDE --> OBS[观察或 panel 分解]
    DECIDE --> MEASURE[测量或聚焦重测]
    DECIDE --> SPEC[组织 ChartSpec]
    DECIDE --> ANSWER[直接回答]
    OBS --> RECORD[提交 ExecutionRecord]
    MEASURE --> RECORD
    SPEC --> RECORD
    RECORD --> CONTEXT[重建 Context 与 ArtifactIndex]
    CONTEXT --> DECIDE
    SPEC --> RENDER[渲染并暂存]
    RENDER --> VERIFY[验证]
    VERIFY -->|按策略通过| PUBLISH[正式发布]
    VERIFY -->|未通过/需修正| DECIDE
    PUBLISH --> ANSWER
~~~

上述分支是可选择的工作方式，不是每个 Run 必须顺序通过的固定阶段。模型可以跳过无关步骤、沿用可访问的已有证据、继续测量或结束。代码负责保证引用合法、范围授权、结构 Schema、预算、来源绑定、验证和发布门槛；不能替模型虚构数据或替它选择证据。

### 来源选择和 GenerationContext

`GenerationContext` 是生成结果的领域说明，完整内容仅存放在对应的 ChartSpec 或 ChartFigure 字段中。它记录“图表生成时选择了什么范围、覆盖程度如何、作出了哪些取舍”，不复制到 Run、ExecutionCheckpoint、ArtifactIndex 或 Manifest。单张 ChartSpec 必须有自己的 GenerationContext；存在复合 ChartFigure 时，Figure 层也必须有一个整体 GenerationContext，分别解释整体覆盖和布局取舍。

`GenerationContext.selected_source_scope` 与来源字段的关系如下：
- RunExecutionContext.authorized_source_scope 是代码允许读取的来源上限。
- GenerationContext.selected_source_scope 是生成时纳入评估/覆盖判断的候选视觉来源集合，必须是授权范围内的 SourceRef[]；SourceRef 只表示附件或 Panel，不表示用户文字输入。
- ChartSpec.provenance.source_refs 是图表实际数据来源；ChartSpec.provenance.evidence_refs 是实际用于图表的具体证据。
- selected_source_scope 可以比 provenance.source_refs 更宽，因为它说明覆盖评估的候选集合；它不能引用未授权来源。provenance.source_refs 必须属于 selected_source_scope，每条 evidence_ref 的 source_refs 也必须属于该集合；selected_source_scope 不替代 provenance，也不能宣称未使用来源支撑图中数据。
- GenerationContext.coverage.basis_source_refs 必须来自 selected_source_scope；它定义完整/部分覆盖的分母范围。
- `reconstruct`、`transform` 和 `summarize` 是 source-linked 模式，必须引用图像/Panel 来源和实际使用的 EvidenceRef。`synthesize` 是不基于图像/Panel 的 source-free 模式；它可使用 RunInput 明确给出的数值，或按用户要求创建示例数据，但必须通过 `data_origin` 区分这两种来源。
- `Coverage.basis_source_refs` 是覆盖率的实际分母，`GenerationContext.selected_source_scope` 是生成时纳入考虑的候选来源；两者不等价。`basis=full_source` 时二者必须相同；`basis=requested_subset` 时未纳入分母的候选来源必须逐项进入 `Coverage.omitted_source_refs` 并说明原因。

| 字段路径 | 类型/可空性 | 精确位置、来源与语义 |
|---|---|---|
| ChartSpec.generation_context / ChartFigure.generation_context | GenerationContext；均必填 | 不可变图表对象内嵌，或由该对象内唯一结构化 payload_ref 引用；不另存完整副本 |
| GenerationContext.schema_version | 正整数，必填 | GenerationContext JSON 结构版本 |
| GenerationContext.mode | reconstruct / transform / summarize / synthesize，必填 | 图表意图；枚举随 GenerationContext.schema_version 固定，禁止额外 custom 值 |
| GenerationContext.data_origin | visual_source / user_provided_data / model_generated_example，必填 | 前三种 mode 必须是 visual_source；synthesize 必须在后两者中选一个 |
| GenerationContext.selected_source_scope[] | SourceRef[]；source-linked 至少一项，synthesize 为空 | 纳入覆盖评估的授权附件/Panel 集合；每项锁定附件或 Panel 版本；具体采用的数据另由 ChartSpec.provenance 引用 |
| GenerationContext.coverage | Coverage，必填 | 对来源数据的覆盖结论；source-free synthesize 使用 not_applicable / not_assessable，见下方字段 |
| GenerationContext.selection_basis | 有界文本，必填 | source-linked 时解释来源/系列/展示选择；synthesize 时解释用户数据映射或示例数据意图；仅是说明，不是授权或来源真值 |
| GenerationContext.goal_summary | 有界文本，必填 | 从用户目标提炼的本图生成目标；不能替代对话原文 |
| GenerationContext.created_at | UTC 时间，必填 | 对应图表事实提交时由 Runtime 写入 |

模式校验规则：

| mode | data_origin | SourceRef / EvidenceRef | Coverage | 可用数据来源与约束 |
|---|---|---|---|---|
| reconstruct | visual_source | `selected_source_scope`、`provenance.source_refs`、`provenance.evidence_refs` 均非空；证据来源必须被两个来源集合覆盖 | 默认 `basis=full_source`；用户明确要求局部重绘时可用 `requested_subset`；数据不足时只能标 partial / not_assessable | 从授权图像观察或测量中重建；不得把模型猜测写成测量事实 |
| transform | visual_source | 同 source-linked 校验 | 通常 `basis=requested_subset`；所有未呈现系列须记录省略原因 | 对来源图表数据作用户要求的筛选、聚合、换算或展示变换 |
| summarize | visual_source | 同 source-linked 校验 | 按所选来源评估，可完整或部分；覆盖不能评估时标 not_assessable | 用图表概括来源数据；摘要范围需在 selection_basis 与 coverage 中说明 |
| synthesize | user_provided_data | `selected_source_scope`、`provenance.source_refs`、`provenance.evidence_refs` 均为空；`input_data_refs` 非空且逐项映射用户原文数值 | `basis=not_applicable`、来源系列和覆盖来源为空、`status=not_assessable` | 将 RunInput 明确给出的数字制图；输入片段只证明数字来自哪段用户文字，不证明其外部真实性 |
| synthesize | model_generated_example | 所有视觉来源、EvidenceRef 与 `input_data_refs` 均为空 | `basis=not_applicable`、来源系列和覆盖来源为空、`status=not_assessable` | 仅用户明确要求示例/模拟数据时允许；Metadata.note 和最终答复必须标明数据为示例或模拟，不得表述为观测事实 |

`ChartSpec.provenance.input_record_id` 对所有模式都由 Runtime 绑定到当前 RunInput；它只关联生成目标，不替代 source-linked 的 EvidenceRef，也不替代 `user_provided_data` 模式的原文片段映射。InputDataRefDraft 必须覆盖 ChartSpec.dataset 中所有直接取自用户输入的类别和数值字段；每个 target_path 指向具体 JSON Pointer，例如 `/dataset/0/value`。V1 只支持从当前 RunInput.text 原样提取并直接制图，不支持跨轮次查找用户以前发过的数值，也不支持把原文未提供的数字混入 `user_provided_data`。需要引用旧轮输入时，用户须在当前请求重述，或后续另行定义跨 Run 的 UserInputRef 与授权规则。

Coverage 位于 GenerationContext.coverage；ChartFigure 不另设第二个独立 coverage 字段。其字段精确定义如下：

| 字段路径 | 类型/可空性 | 含义与校验 |
|---|---|---|
| Coverage.basis | full_source / requested_subset / not_applicable，必填 | 完整来源、用户指定子集，或无视觉来源；synthesize 必须为 not_applicable |
| Coverage.basis_source_refs[] | SourceRef[]；source-linked 至少一项，synthesize 为空 | 覆盖判断的视觉来源集合；必须是 GenerationContext.selected_source_scope 的子集 |
| Coverage.omitted_source_refs[] | OmittedSource[]；可空，synthesize 为空 | selected_source_scope 中未纳入 Coverage.basis_source_refs 的来源及省略原因 |
| OmittedSource.source_ref | SourceRef，必填 | 被排除出覆盖分母的精确授权来源 |
| OmittedSource.reason | 有界文本，必填 | 说明用户所选子集或排除理由；不能将未分析来源描述为已观察 |
| Coverage.source_series[] | SourceSeries[]；synthesize 为空 | 从 basis 来源识别出的可比较系列；没有系列概念时为空 |
| SourceSeries.series_key | 有界字符串，必填 | 在此 GenerationContext 中稳定标识一条来源系列 |
| SourceSeries.source_refs[] | SourceRef[]，至少一项 | 该系列来自哪些具体来源 |
| SourceSeries.point_count | 非负整数，可空 | 识别到的源数据点数量；未知时缺省 |
| Coverage.represented_series[] | series_key[]；synthesize 为空 | ChartSpec.dataset 中实际呈现的源系列 |
| Coverage.intentionally_omitted_series[] | OmittedSeries[]；synthesize 为空 | 有意未展示的源系列及理由 |
| OmittedSeries.series_key | SourceSeries.series_key，必填 | 被省略系列 |
| OmittedSeries.reason | 有界文本，必填 | 省略的可解释原因；不能用作伪造来源依据 |
| Coverage.status | complete / partial / not_assessable，必填 | source-linked 时基于 basis_source_refs 与系列对应关系得出；synthesize 固定 not_assessable |
| Coverage.assessment_note | 有界文本，可空 | 无法自动判定或存在边界时说明限制 |

Coverage.status 的判定规则：
- complete：相对于明确的 Coverage.basis，所有可识别数据系列和数据点均由图表表示；complete 不等于覆盖所有授权附件。
- partial：basis 内存在没有呈现的数据；是否在 intentionally_omitted_series 中给出原因不会把 partial 改成 complete。
- not_assessable：源数据无法可靠枚举、映射或比较；不得表述为 complete。
- 没有 series 概念时，应按 ChartSpec Schema 能验证的源数据单位评估；若不能验证则使用 not_assessable。
- 当 `Coverage.basis=full_source` 时，`basis_source_refs` 必须等于 `GenerationContext.selected_source_scope` 且 `omitted_source_refs` 为空。
- 当 `Coverage.basis=requested_subset` 时，`basis_source_refs` 必须是 selected_source_scope 的非空子集；两者差集必须与 `omitted_source_refs` 一一对应，不能默默丢弃来源。status 只评估 basis 内数据；显式省略的来源不进入分母。
- 当 `Coverage.basis=not_applicable` 时，`basis_source_refs`、`omitted_source_refs`、`source_series`、`represented_series` 和 `intentionally_omitted_series` 必须全部为空，`status` 必须是 `not_assessable`。此状态不是失败，而是说明没有视觉来源覆盖率可评估。

ChartFigure.generation_context.coverage 说明复合输出整体范围；每个 ChartFigureItem.spec.generation_context.coverage 说明对应子图。Figure 与其全部子 ChartSpec 的 `mode` 和 `data_origin` 必须一致，避免一个 Figure 同时把 source-linked 与 source-free 数据包装成同一来源口径；需要混合来源类别时，拆成 ChartSpecCollection 中的多个 Figure。父 Figure 的覆盖范围是子图来源/系列范围的去重并集，每个子图仍单独保留 Provenance。ChartFigure 不另设平行的 coverage 或 provenance 字段。ArtifactIndex、Timeline 和 Prompt 只生成一次有界摘要；读取完整内容时通过 chart_spec_id/figure_id 解析权威图表对象。

### BudgetSnapshot 与停止条件

RunExecutionContext.budget 是从 Run 创建时冻结的执行限额和有效记录前缀推导出的读模型，不是可变计数器。Run.execution_limits 保存本 Run 的确切限额；BudgetSnapshot 只呈现 used、limit、remaining 和计数依据。

| 字段路径 | 类型/可空性 | 来源与计数规则 |
|---|---|---|
| Run.execution_limits.model_steps_limit | 非负整数，必填 | Run 创建时从 ExecutionPolicy 解析并冻结；整个 Run 不变 |
| Run.execution_limits.chart_attempts_limit | 非负整数，必填 | Run 创建时从 ExecutionPolicy 解析并冻结；整个 Run 不变 |
| BudgetSnapshot.as_of_record_sequence | 非负整数，必填 | 此快照纳入的当前 Run 最大有效 ExecutionRecord 序号 |
| BudgetSnapshot.model_steps_used | 非负整数，必填 | 当前有效前缀中已提交 model_response 记录数；表示可恢复模型决策步，不等于账单请求数 |
| BudgetSnapshot.model_steps_limit | 非负整数，必填 | 复制 Run.execution_limits.model_steps_limit 的不可变值 |
| BudgetSnapshot.model_steps_remaining | 非负整数，派生 | max(limit - used, 0)；不单独存储 |
| BudgetSnapshot.chart_attempts_used | 非负整数，必填 | 当前前缀中 budget_category=chart_attempt 的 ToolCall 数；ToolCall 随 model_response 先提交，所以失败或待执行调用也计入 |
| BudgetSnapshot.chart_attempts_limit | 非负整数，必填 | 复制 Run.execution_limits.chart_attempts_limit 的不可变值 |
| BudgetSnapshot.chart_attempts_remaining | 非负整数，派生 | max(limit - used, 0)；不单独存储 |

模型用 remaining 值决定是否继续；Runtime 在创建新 model action 或执行图表渲染 tool call 前按相同前缀再次校验。Provider adapter 自身的网络重试次数/账单请求数属于独立传输策略，不冒充模型决策步。预算耗尽时 Agent 应返回明确的未完成说明，不得声称未发布的图已正式交付。Verifier 的 repair_hint 不会自动触发修复；必须由模型产生新的、显式的下一动作。

### 决策归属与可追溯性

| 决策事项 | 选择者 | 必须通过的程序校验 | 权威事实位置 |
|---|---|---|---|
| 选择工具与当前 panel | 主 Agent | Tool Schema、Session/attachment/panel 授权、来源 hash/revision | model_response ToolCall + tool_result |
| 选择或重测候选证据 | 主 Agent | source_refs、scope、工具质量和 evidence 身份 | MeasurementAttempt / EvidenceRef |
| 选择实际图表数据 | 主 Agent | ChartSpec schema、来源授权、provenance 引用解析 | ChartSpec.provenance |
| 说明选择与覆盖取舍 | 主 Agent | selected_source_scope 在授权范围内；coverage 结构与事实一致 | ChartSpec/ChartFigure.generation_context |
| 修正失败图或停止 | 主 Agent | checkpoint、剩余预算、验证结论与发布状态 | model_response、VerificationResult、ExecutionCheckpoint |
| 声称已交付图 | 主 Agent 提出 | final-answer guard 精确核对有效前缀中 PublishedArtifact | final_answer + PublishedArtifact |

“为什么做出这个决策”的 UI/诊断摘要由 HistoryMessage、ToolCall、ChartSpec.generation_context 和 VerificationResult 投影；它们复用已有事实，不创建一份同步维护的 PlanningDecision 或完整 PlanningState。恢复只依赖 Runtime ExecutionCheckpoint 与有效记录，不依赖自然语言 pending_action。

本设计不引入持久的多步 Plan 对象。如果后续产品需要用户可编辑的计划、跨 Run 任务图或计划审批，再单独定义 Plan 的身份、版本、所有者、修改规则与恢复语义，不把临时 JSON 塞入 RunExecutionContext。
## 8. Evaluation System Design

### 两个评测组件的职责

Evaluation 由 Driver 和 Reader 两个组件组成。Driver 使用与普通客户端相同的 Application API 创建评测 Run；Reader 对已提交执行数据只读，生成诊断时间线和报告。报告不是 Agent 的新状态，也不会写回 Run。

| 组件 | 允许操作 | 禁止边界 |
|---|---|---|
| EvaluationDriver | 读取并校验 EvaluationManifest；创建隔离 batch；通过普通上传与 Run API 执行每个 case；记录 case 与 Run 引用 | 不直接改 Run/ExecutionRecord/Checkpoint 表；不绕过权限、工具、验证或发布流程 |
| EvaluationReader | 读取 batch 元数据、RunSummary、安全 RunStreamEvent、授权 ExecutionRecord/Artifact 投影；构建时间线和指标 | 只读；查看或刷新报告不得再次执行 Agent |
| ReportWriter | 将 Reader 结果写入 batch reports/ 下的 JSON 与 Markdown | 不修改源 Run；不嵌入私有 prompt、图片字节或 Provider 原始响应 |

每个 batch 使用独立 FiguraRuntime 存储根；Run、附件和产物仍走同一 Runtime 代码。隔离根只能由 EvaluationDriver 创建和持有，报告/API 只返回 opaque report_ref，不向客户端暴露绝对路径。评测资源不得与日常用户 Session 混用。

### EvaluationManifest 与样本字段

EvaluationManifest 是只读、版本化 JSON 文件，保存在受控 asset root。其字段由评测调用方提供；Driver 加载后校验 canonical manifest digest、路径、大小、数量及敏感数据规则。Manifest 不存绝对工作站路径，不允许符号链接逃逸 asset root。

| 字段路径 | 类型/可空性 | 存储位置与语义 |
|---|---|---|
| EvaluationManifest.schema_version | 正整数，必填 | manifest 文件根字段；定义结构版本 |
| EvaluationManifest.manifest_id | 稳定字符串，必填 | 样本集逻辑身份；不同版本可共享 ID |
| EvaluationManifest.samples[] | 有序 EvaluationSample[]，至少一项 | 样本顺序固定；每个 case 一次 Run |
| EvaluationManifest.manifest_digest | SHA-256 digest，派生 | canonical JSON 去除该字段后计算；写入 EvaluationBatch 以固定输入版本 |
| EvaluationSample.case_id | 稳定字符串，必填 | manifest 内 case 主键；一个 manifest 中唯一 |
| EvaluationSample.asset_ref | 相对路径，必填 | 相对受控 asset root 的图表图片路径；不可有绝对路径、.. 或 root 外 symlink |
| EvaluationSample.asset_sha256 | 64 位十六进制 hash，必填 | Driver 在运行前核对实际文件字节 |
| EvaluationSample.expected_panel_count | 非负整数，可空 | 有人工/可靠真值时的 panel 数；为空表示不可计算匹配率 |
| EvaluationSample.expected_panels[] | ExpectedPanelHint[]，可空 | 有 panel 级标注时提供；不完整标注不能冒充全量真值 |
| ExpectedPanelHint.name | 有界文本，必填 | 可用于 name 归一化对比的 panel 提示 |
| ExpectedPanelHint.chart_type | 受控字符串，可空 | 标注了类型时比较 |
| ExpectedPanelHint.role | 受控字符串，可空 | 标注了 panel 角色时比较 |
| ExpectedPanelHint.bbox_norm | 归一化矩形，可空 | x/y/width/height 在 0..1；用于空间匹配，不含原始图像数据 |

asset_ref 是定位信息；asset_sha256 才是样本身份的内容校验值。Driver 上传前核对 hash，Run 的 Attachment 再生成自己的 attachment_id/content_sha256，二者必须一致。EvaluationSample.case_id 不直接作为全局 Run ID 或 Attachment ID。

### EvaluationBatch 与 EvaluationCase

Batch 是一次完整评测运行及其固定配置快照。元数据持久化在评测控制目录的 evaluation.sqlite3；实际运行数据保存在 batch 自己的 FiguraRuntime root。

| 字段路径 | 类型/可空性 | 存储与语义 |
|---|---|---|
| EvaluationBatch.batch_id | 不透明 ID，必填 | batch 全局身份；不使用模糊的 evaluation_id |
| EvaluationBatch.schema_version | 正整数，必填 | 批次元数据结构版本 |
| EvaluationBatch.manifest_id / manifest_digest | 字符串 / digest，必填 | 精确指向样本集身份与字节版本 |
| EvaluationBatch.provider / model | 字符串，必填 | 实际用于此批次的 Provider/model |
| EvaluationBatch.prompt_bundle_version | 版本字符串，必填 | 主 Agent 静态 prompt bundle |
| EvaluationBatch.tool_registry_version | 版本字符串，必填 | 运行期工具合同版本 |
| EvaluationBatch.execution_policy_version | 版本字符串，必填 | 模型/图表限额和重试规则版本 |
| EvaluationBatch.verification_policy_version | 版本字符串，必填 | 生成图验证规则版本 |
| EvaluationBatch.runtime_root_id | 内部 opaque ID，必填 | 与 batch 绑定的隔离 Runtime root；真实路径只保留在服务端配置 |
| EvaluationBatch.status | created / running / completed / completed_with_errors / failed / cancelled | batch 生命周期；不等同任何 case Run.status |
| EvaluationBatch.case_count | 非负整数，必填 | manifest 中样本数，创建时冻结 |
| EvaluationBatch.started_at / finished_at | UTC 时间，可空 | 批次开始和所有 case 处理结束时间 |
| EvaluationBatch.created_at | UTC 时间，必填 | batch 元数据创建时间 |

EvaluationCase 在 evaluation.sqlite3 中按 (batch_id, case_id) 唯一；同一个 case 要重新跑时创建新 batch，不能覆盖旧 case。

| 字段路径 | 类型/可空性 | 存储与语义 |
|---|---|---|
| EvaluationCase.batch_id / case_id | ID / manifest case key，必填 | 复合主键，固定样本归属 |
| EvaluationCase.case_ordinal | 正整数，必填 | case 在 manifest.samples[] 中的顺序 |
| EvaluationCase.asset_sha256 | digest，必填 | 本次评测已核对的样本 hash |
| EvaluationCase.session_id / run_id | ID，可空 | 普通 Runtime 入口成功创建资源后填写 |
| EvaluationCase.status | queued / running / observed_terminal / observation_timed_out / setup_failed | Case 处理状态；diagnostic timeout 不会把仍 running 的 Run 改成 failed |
| EvaluationCase.report_ref | opaque ReportRef，可空 | Reader 已生成报告后填写；精确包含 report_id 与 report_version 的逻辑引用，不含本机路径 |
| EvaluationCase.error_code / error_summary | 受控码 / 有界脱敏文本，可空 | setup_failed 或 Reader 错误时记录；禁止私密 Provider 响应 |
| EvaluationCase.created_at / started_at / finished_at | UTC 时间，按状态可空 | case 排队、实际执行和 Driver/Reader 停止观察时间 |

Batch 的版本字段记录本次实际生效的配置。无法还原或读取到的版本必须标记 unknown/error；不允许根据当前默认配置补猜历史值。EvaluationBatch 不复制完整 Run payload 或 ArtifactIndex。Batch 状态迁移为 created → running → completed / completed_with_errors / failed / cancelled；completed 表示所有 case 均有可读终态结果，completed_with_errors 表示已结束但存在 setup/diagnostic 错误，failed 表示 Driver 无法继续批次，cancelled 表示调用方显式取消。状态只由 EvaluationDriver 写入。

### DiagnosticTimeline 的字段和状态

DiagnosticTimeline 是 EvaluationReader 从 RunSummary、ExecutionRecord、RunStreamEvent、manifest 与受限 artifact refs 构造的只读诊断投影。Timeline 阶段是报告词汇，不是 Runtime 强制执行的 phase 状态机。

| 字段路径 | 类型/可空性 | 含义 |
|---|---|---|
| DiagnosticTimeline.schema_version | 正整数，必填 | 时间线 JSON 结构版本 |
| DiagnosticTimeline.batch_id / case_id / run_id | ID，run_id 在 Run 创建前可空 | 与唯一评测 case 和被观察 Run 绑定 |
| DiagnosticTimeline.protocol_status | complete / partial / gapped / unavailable | 当前可读取的执行事实与公开事件完整性 |
| DiagnosticTimeline.history_gap | bool，必填 | Reader 是否发现记录序列或事件序列缺口 |
| DiagnosticTimeline.phases[] | DiagnosticPhase[]，固定有序展示 | 分阶段读模型，不驱动 Run |
| DiagnosticTimeline.anomalies[] | DiagnosticAnomaly[]，可空 | 不一致、缺失引用或安全协议异常 |
| DiagnosticTimeline.first_failure | FailureReference，可空 | 第一处可确认失败；不可确认时缺省而非推断 |
| DiagnosticTimeline.final_references[] | ArtifactRef[]，其中 ref_kind=published_artifact，可空 | Reader 验证后确认的正式发布引用 |

DiagnosticPhase.phase_name 的首版词汇为 input、model、decomposition、panel_handoff、measurement、assembly、render、verification、publication。每个阶段对象字段如下：

| 字段路径 | 类型/可空性 | 含义与来源 |
|---|---|---|
| DiagnosticPhase.phase_name | 受控枚举，必填 | 上述诊断分类；并非 Run.status |
| DiagnosticPhase.status | completed / failed / not_reached / not_observed / observed_in_progress | 依据本阶段能核验的事实确定；Reader 观察超时时可为 observed_in_progress |
| DiagnosticPhase.record_sequences[] | 非负整数[]，可空 | 仅 ExecutionRecord.record_sequence；不能装 RunStreamEvent 序号 |
| DiagnosticPhase.event_sequences[] | 非负整数[]，可空 | 仅 RunStreamEvent.event_sequence；不能装 record sequence |
| DiagnosticPhase.panel_ids[] / attempt_ids[] / observation_ids[] | ID[]，可空 | 相关领域对象引用 |
| DiagnosticPhase.artifact_refs[] | ArtifactRef[]，可空 | Manifest、staged、verification 或 published 引用 |
| DiagnosticPhase.notes[] / errors[] | 有界摘要数组，可空 | 经过脱敏和长度限制的解释或错误分类 |

状态判定必须保守：
- completed：有成功提交的事实支撑；
- failed：有明确终态或对应事实证明动作失败；
- not_reached：执行前置事实表明流程尚未到达此阶段；
- not_observed：当前数据没有足够证据判断阶段是否发生；
- observed_in_progress：观察时 Run 仍处于 running，或 Reader 等待超时，但没有失败事实。

FailureReference 字段为 source_kind（execution_record / run_stream_event，必填）、record_sequence（source_kind=execution_record 时必填）、event_sequence（source_kind=run_stream_event 时必填）、failure_code（受控字符串，必填）和 summary（有界脱敏文本，必填）；两种 sequence 必须且只能出现一种。DiagnosticAnomaly 字段为 anomaly_code（受控字符串，必填）、source_refs[]（至少一项执行事实定位或 ArtifactRef）、severity（info / warning / error）和 description（有界脱敏文本）；它说明读取到的不一致，不自动宣判 Run 失败。

### DiagnosticReport 与批次指标

每个已处理 case 最多生成一份当前 Report；旧报告版本不得原地覆写，重生成时递增 report_version 并使用新 ref。

| 字段路径 | 类型/可空性 | 存储位置与含义 |
|---|---|---|
| DiagnosticReport.report_id | 不透明 ID，必填 | 一次不可变报告版本的身份 |
| DiagnosticReport.report_version | 正整数，必填 | 同 case 重生成时递增 |
| DiagnosticReport.batch_id / case_id / run_id | ID，run_id 可空 | 固定报告归属 |
| DiagnosticReport.manifest_digest / asset_sha256 | digest，按资源可空 | 固定样本集和单样本版本 |
| DiagnosticReport.run_summary | SafeRunSummary，可空 | 字段为 run_id、status、provider、model、terminal_code、created_at、started_at、finished_at、record_count、event_count；按权限可空 |
| DiagnosticReport.timeline | DiagnosticTimeline，必填 | 结构化诊断事实 |
| DiagnosticReport.metrics | CaseMetrics，必填 | 只包含有真值且方法适用的可计算指标 |
| DiagnosticReport.created_at | UTC 时间，必填 | Reader 完成此报告版本的时间 |
| EvaluationCase.report_ref | opaque ReportRef，可空 | 指向报告 JSON 与 Markdown 的逻辑资源身份，不存本机绝对路径 |

报告文件放在隔离 batch 根下的 reports/，内部按 batch_id/case_id/report_version 命名；report_ref 是 API locator，不是公开文件系统路径。JSON 是机器读取权威表示，Markdown 是由同一 JSON 生成的可读视图，二者不得独立维护不同结果。

CaseMetrics 是 DiagnosticReport.metrics 内的只读结果对象；字段为 schema_version（正整数）、metrics[]（有序 MetricResult[]）和 evaluated_at（UTC 时间）。每个 MetricResult 的字段是 metric_name（受控枚举）、value（数值，可空）、numerator（非负数值，可空）、denominator（非负数值，可空）、metric_status（computed / partial / not_assessable / not_applicable）、method_version（不透明版本，必填）和 note（有界说明，可空）。当 metric_status 不是 computed 时 value 必须为空；计算比例时保留 numerator/denominator，不只保留四舍五入结果：
- panel_count_match 只有 expected_panel_count 存在、Reader 确认 panel 检出完整时才有可判定结果。
- expected_panel_recall/precision 只有标注定义了可比较 panel 集合、匹配方法版本明确时才计算。
- chart_spec_validity 来自 schema validator 的已提交事实，不等同图表正确性。
- verification_pass_rate 按有 verification_result 的图统计；unavailable 需单独计数，不纳入 pass。
- published_chart_count 只统计存在正式 PublishedArtifact 的图，不统计 staged/refused 结果。
- failure_phase_distribution 依赖可确认的 FailureReference；not_observed 不并入 failed。

批次聚合保留分母和未观察数。无真值、真值不完整或读取缺口时输出 not_assessable/partial，而不是猜测准确率、召回率或失败阶段。

### Driver 与 Reader 流程

~~~mermaid
sequenceDiagram
    participant M as EvaluationManifest
    participant D as EvaluationDriver
    participant R as FiguraRuntime
    participant Q as EvaluationReader
    participant O as Evaluation Store / ReportWriter
    M->>D: samples、asset_ref、asset_sha256
    D->>D: 校验路径、hash、配置并创建 batch 与隔离 root
    loop 每个 EvaluationCase
        D->>R: 普通附件上传和 RunCreateRequest
        R-->>D: session_id / run_id
        D->>O: 持久化 case 引用和状态
        Q->>R: 读取安全事件、提交事实和产物投影
        Q->>O: 写不可变 DiagnosticReport 版本
    end
    Q->>O: 汇总 case metrics 与 batch 结果
~~~

Driver 创建 Run 是执行；Reader 查看报告是只读。Reader 超时只更新 EvaluationCase.status=observation_timed_out，不得改 Runtime Run.status。重新执行相同 manifest case 时创建新的 batch，避免覆盖原有记录与报告。

### 隐私和完整性边界

- EvaluationManifest 只能引用受控 asset root 内的相对文件；读取时解析符号链接并重新验证 root containment 与 SHA-256。
- 报告和 UI 资源采用明确白名单投影并限制深度、长度、数量；不包含 API key、token、reasoning、绝对本机路径、完整 prompt、Provider 原始响应或图片字节。
- Evaluation root、artifact storage_key 和本地文件路径仅由服务端内部解析；客户端使用 batch_id、case_id、report_ref 等 opaque protocol 值。
- Reader 校验 batch/case/Run/session/manifest 的归属关系；资源损坏、记录断档或事件缺失都要表达成 protocol_status/anomaly，而不是改写原始 Run。
- Evaluation 只消费已提交数据；不能将测量、ChartSpec、验证或报告结论写回线上用户 Run，也不替 Agent 决定下一步。

建议模块为 figura.evaluation.manifest、figura.evaluation.driver、figura.evaluation.reader、figura.evaluation.timeline 和 figura.evaluation.report。Runtime root 与评测控制 metadata/report 目录均由 batch_id 隔离；前端是否提供评测 UI 留给接口设计阶段，本章只定义数据和读取契约。
## 9. 端到端数据流

### 新 Run 到最终回答

1. Client、CLI 或 Evaluation Driver 提交文字、附件 ID、可选模型和幂等键。Gateway adapter 校验协议及请求大小。
2. RunCoordinator 校验 session 与附件授权，在一个事务中创建 Run、input ExecutionRecord、初始 checkpoint、幂等映射和 run-created event。
3. AgentExecutor 读取已提交前缀；Memory System 构造 RunExecutionContext、PromptBundle、角色化历史消息与原生工具 Schema。
4. Provider 返回后，先提交完整 model_response 和 next_action。存在工具调用时，checkpoint 指向精确 response_record_id/call_id；无工具调用时进入 final-answer guard。
5. 工具执行前校验参数、attachment/panel、scope 和副作用策略。tool_result、checkpoint 与安全事件同事务提交。
6. Agent 根据新 Context 继续决策。ChartSpec 经渲染暂存后，依次验证和发布；每一步都写入可恢复事实。
7. Final-answer guard 核对回答声明与正式 artifact refs。final_answer、清空后的 checkpoint、Run.completed 和终态 outbox event 同一事务提交。
8. Gateway 投影 Run 和安全事件；Evaluation Reader 从相同的已提交事实构建时间线和报告。

### 附件、证据和生成图

~~~mermaid
flowchart LR
    UP[上传附件] --> ATT[Attachment ID + hash]
    ATT --> SCOPE[授权 attachment/panel scope]
    SCOPE --> OBS[Observation]
    OBS --> PANEL[PanelRecord]
    OBS --> MEAS[MeasurementAttempt]
    OBS --> EVIDENCE[Evidence refs]
    PANEL --> EVIDENCE
    MEAS --> EVIDENCE
    EVIDENCE --> SPEC[ChartSpec.provenance]
    USERDATA[RunInput.text 中明确提供的数字] --> INPUTREF[InputDataRefDraft 原文片段映射]
    INPUTREF --> SPEC
    SAMPLE[用户要求示例/模拟数据] --> SYNTH[GenerationContext.data_origin=model_generated_example]
    SYNTH --> SPEC
    SPEC --> GC[ChartSpec.generation_context]
    SPEC --> RENDER[渲染与暂存]
    RENDER --> FILE[ArtifactStore bytes]
    FILE --> AM[ArtifactManifest]
    AM --> MANIFEST[StagedChartManifest]
    GC -. digest/ref .-> MANIFEST
    MANIFEST --> VERIFY[VerificationResult]
    VERIFY --> PROMOTE[幂等 Promotion]
    PROMOTE --> OUTPUT[PublishedArtifact]
~~~

source-linked 模式下，测量是候选证据；只有 ChartSpec.provenance.evidence_refs 明确列出的证据才支持该图的来源声明。synthesize 模式不声明图像来源，用户提供的数值通过 InputDataRefDraft 回链到 RunInput 文本，模型生成的数据必须显式标为示例/模拟。Verification 绑定精确图像、ChartSpec digest、来源集合（可为空）和 policy；通过后才可 Promotion。用户可授权预览暂存图，正式答复只把已发布 artifact_id 描述为交付产物。

### 模型输入与恢复的关系

`ModelRequest = PromptBundle + HistoryMessage[] + 原生工具 Schema`。PromptBundle 的四类上下文由 RunExecutionContext、ArtifactIndex 和 ToolDefinition 投影；对话历史从 ExecutionRecord 按 user/assistant/tool 原角色构建。checkpoint.next_action 不注入模型，history 摘要不用于精确恢复，RunStreamEvent 不代替执行事实。

Reconnect 续读同一 Run 的事件；retry 从原始 input 创建新的 child Run；resume 只在用户显式请求并通过 parent checkpoint、来源引用和 replay contract 校验后创建 child Run。原 Run 的状态与记录不回写。

## 10. 持久化边界与主要风险

SQLite 保存 sessions、attachments 元数据、runs、run_idempotency、run_execution_records、run_execution_checkpoints、run_stream_events、artifact_manifests 和 staged_chart_manifests。图片等 blob 在独立 ArtifactStore。下列写入必须原子：

| 写入动作 | 同一 SQLite transaction 的内容 |
|---|---|
| 新 Run | Run + input record + checkpoint + idempotency + created event |
| Agent 步骤 | execution fact + next checkpoint + 安全 event/outbox |
| 完成 Run | final_answer + terminal Run state + final checkpoint + terminal event |
| 中断或失败 | 唯一终态 + checkpoint + terminal event |
| 生成文件 | blob 先原子落盘；随后在 SQLite 同一事务写 ArtifactManifest、对应 StagedChartManifest（如为图像）、render tool_result execution fact、checkpoint 与 event；校验 digest |

| 风险 | 处理方式 |
|---|---|
| 私有执行内容泄露到 API 或 trace | ExecutionRecord 和公开投影分开；Gateway 只序列化白名单字段 |
| ExecutionRecord、checkpoint、event 不一致 | 同一事务提交事实、游标和 outbox event |
| blob 与数据库无法共用事务 | 原子文件落盘、manifest digest 校验、只清理 Figura root 内无 manifest 的孤儿 |
| resume 重发 provider 请求 | 只允许用户显式 resume 未提交请求；可能重复计费，已提交响应复用 |
| 来源内容变化但 ID 未变 | 校验 attachment hash、panel revision 和 exact source binding |
| Run 状态重新出现多个 owner | RunCoordinator 唯一生命周期写入；Gateway 不持有可变副本 |
| 评测数据污染用户会话 | Evaluation batch 使用独立 Runtime storage root |

## 11. 建议实施顺序

1. 定义 Session、Run、ExecutionRecord、ExecutionCheckpoint 与事务边界；先实现 Run 创建、中断、终态提交和恢复读取。
2. 定义固定版本的 ToolRegistry、ToolDefinition 参数/结果 Schema、来源引用与 ToolExecutionError；注册本稿明确的九个图表工具，排除通用本地文件工具。
3. 实现 RunContextFactory、ArtifactIndex、ConversationHistoryReader 和 PromptAssembler；落实四份静态职责、三个动态模板、Context 派生 Runtime/Artifact 投影、Provider 原生 Schema 映射与独立验证 Prompt。
4. 实现附件授权、PanelRecord、Observation、EvidenceRef、MeasurementAttempt 和五类图表证据 payload，再逐个接入拆 panel、OCR、布局和四种测量工具。
5. 实现 ChartSpec / ChartFigure / ChartSpecCollection 组装与校验，随后接入 ChartObjectRef → render_chart → StagedChartManifest → VerificationResult → PublishedArtifact。
6. 暴露 Figura CLI/本地 Gateway 与隔离 Evaluation Driver/Reader；确认 DTO、事件和 Run 生命周期共用同一应用服务。
7. 在当前 React/Vite 工作区增加 Figura 前端适配器，使一个前端同时连接 ChartAgent v1 与 Figura；验证会话目标绑定和数据隔离。

## 12. 待确认事项

- Figura 首阶段 CLI 命令、Gateway 端口与 API 路由前缀。
- 四份静态职责 prompt 的最终逐句文案与评审；文件职责、路径分层和装配顺序已在本稿固定。
- 用户删除附件后，图片字节的保留期限和物理清理时机。
- 在现有工作区中，Figura 入口应采用何种导航和会话创建交互。
- Provider 具体版本对原生工具 Schema 的能力差异；Adapter 必须报告不兼容，不能静默放宽参数校验。
- 若未来需要用户可编辑的多步计划，应另行讨论持久 Plan 对象的身份、版本和恢复语义；本版不预置 Plan 队列。

本文先作为一份完整的架构评审稿。字段和边界确认后，再决定如何拆出规格和实现任务。
