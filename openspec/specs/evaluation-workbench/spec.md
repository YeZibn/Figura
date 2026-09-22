# evaluation-workbench Specification

## Purpose

为本地 Figura 用户提供一个与普通会话隔离的评测工作台，使独立评测批次、case 诊断、阶段时间线、报告和视觉证据可以通过安全的只读 Gateway 资源在前端被发现和复盘。

## Requirements

### Requirement: Gateway exposes an isolated evaluation catalog

The local Gateway SHALL expose a read-only evaluation catalog backed by the canonical data root's `evaluations/` directory. The catalog SHALL list only valid evaluation bundles and SHALL return bounded metadata including `evaluation_id`, status, provider, model, start/end timestamps, case count, case status counts, and first-failure summaries. Evaluation entries SHALL remain separate from the ordinary `/sessions` collection and SHALL NOT be copied into the default session database.

#### Scenario: User opens the evaluation workspace with existing bundles

- **WHEN** the client requests the evaluation collection
- **THEN** the Gateway returns valid evaluation summaries ordered by most recent update
- **AND** the response contains no absolute local paths, credentials, raw database content, or image bytes

#### Scenario: No evaluations exist

- **WHEN** the canonical data root has no valid evaluation bundle
- **THEN** the Gateway returns an empty evaluation collection with a successful bounded response
- **AND** the ordinary session collection remains unchanged

#### Scenario: Evaluation bundle is running or partial

- **WHEN** an evaluation index reports `running`, `partial`, or `blocked`
- **THEN** the catalog exposes that exact status and the available bounded metadata
- **AND** it does not infer completion or remove already persisted case information

#### Scenario: Evaluation directory is malformed

- **WHEN** an entry below `evaluations/` is missing a valid index, has an unsupported schema, or cannot be read safely
- **THEN** the Gateway excludes it from the normal catalog or returns a bounded diagnostic entry according to the catalog policy
- **AND** it does not expose the malformed path or fail the entire Gateway service

### Requirement: User can inspect an evaluation and its cases

The Gateway SHALL expose read-only detail resources for a selected evaluation and case. A detail response SHALL include the evaluation metadata, case status, session/run references, expected sample metadata, stage timeline, first confirmed failure, bounded summary/diagnostic references, and available report metadata. The response SHALL preserve `not_reached`, `not_observed`, `failed`, and partial states instead of presenting an incomplete run as successful.

#### Scenario: User selects a completed or partial evaluation

- **WHEN** the client requests a valid evaluation detail
- **THEN** the Gateway returns the batch metadata and all available case summaries without requiring the caller to open the evaluation's SQLite database

#### Scenario: User selects one case

- **WHEN** the client requests a valid case belonging to an evaluation
- **THEN** the Gateway returns its run reference, ordered stage states, bounded error summary, report references, and available evidence references
- **AND** an unknown evaluation or case returns a bounded not-found response

#### Scenario: Case history is requested

- **WHEN** the client requests the ordered history for a case with a persisted run
- **THEN** the Gateway returns the same safe run-event envelope and payload semantics used by an ordinary session run, including lifecycle events, tool calls, tool results, visual observations, repair/review events, failures, and recovery events
- **AND** each event preserves its sequence, timestamp, status, and `call_id` when available
- **AND** visual evidence uses stable evaluation-scoped resource references
- **AND** the response does not return the underlying `sessions.db` or local filesystem paths

### Requirement: User can expand bounded read-only run details

The evaluation workspace SHALL provide a read-only run transcript whose grouping and presentation semantics match the ordinary session execution timeline. It SHALL display the complete available sanitized values for user/model-visible messages, tool calls, tool results, measurement-repair details, review state, lifecycle events, errors, recovery state, and evaluation-scoped visual evidence. Safety bounds MAY limit transport size or conceal sensitive content, but a complete persisted result SHALL NOT be replaced by a summary solely because its structured value is deeply nested.

#### Scenario: User expands a tool call and result

- **WHEN** the user expands a tool call or tool result in a selected case's run transcript
- **THEN** the client displays the tool name, call identifier, sanitized arguments, sanitized structured result, status, sequence, timestamp, and related visual evidence using the same grouping semantics as an ordinary session run
- **AND** the user can distinguish the invocation from the returned result without seeing duplicate competing representations of the same tool result

#### Scenario: User expands conversation content

- **WHEN** a case has persisted user or model-visible conversation records
- **THEN** the client displays those records in chronological relation to the execution transcript
- **AND** missing or truncated conversation records do not hide the available Gateway event transcript or case diagnosis

#### Scenario: Deeply nested chart data is displayed

- **WHEN** a tool result contains nested chart geometry such as bounding boxes, polygons, axes, bars, series, or point coordinates
- **THEN** the client preserves the numeric and structural values available in the persisted safe result
- **AND** the Gateway does not mark those values truncated solely because they exceed a global recursion-depth threshold

#### Scenario: Detail data is truncated or unavailable

- **WHEN** a result was truncated during persistence, exceeds the configured transport limit, or is unavailable in the bundle
- **THEN** the client displays an explicit source and reason such as persistence truncation, detail-resource unavailable, or history gap
- **AND** the client preserves all remaining transcript entries without fabricating missing content or exposing an arbitrary local file as a fallback

#### Scenario: Detailed content crosses a sensitive-data boundary

- **WHEN** an expanded record contains credentials, absolute local paths, hidden reasoning, raw binary data, or unbounded provider payload fields
- **THEN** the Gateway redacts, omits, or replaces those fields with bounded markers before returning the detail
- **AND** the client continues to use evaluation-scoped resource references for images

### Requirement: Evaluation run transcript matches ordinary session trace

The evaluation workspace SHALL render a selected case as a read-only equivalent of the ordinary session user-facing timeline. It SHALL use the same tool-call/result correlation, expandable result behavior, visual-observation attachment behavior, domain-step labels, terminal/error presentation, and technical-lifecycle filtering, while preserving evaluation-specific case, report, and evidence context. Model-start, model-completion, and operation-save events SHALL remain available as persisted history but SHALL NOT be rendered as separate visible transcript rows.

#### Scenario: User reviews a selected case like a normal conversation run

- **WHEN** the user opens a case with a persisted run
- **THEN** the evaluation workspace shows the same flat chronological timeline used by an ordinary run
- **AND** tool calls, tool results, observations, repair events, review events, and terminal events appear in their original meaningful order

#### Scenario: Evaluation hides technical lifecycle noise

- **WHEN** a case history contains model-start, model-completion, or operation-save events
- **THEN** the case timeline does not create separate cards or rows for those events
- **AND** their failure context, when relevant, is surfaced through the associated visible error or terminal step

#### Scenario: Evaluation transcript remains read-only

- **WHEN** the user expands or refreshes an evaluation transcript
- **THEN** the client never submits a new model/tool operation or mutates the evaluation bundle
- **AND** the ordinary session workspace retains its existing run, retry, resume, and interruption behavior

### Requirement: Evaluation uses the runtime compatibility projection

评测工作台 SHALL 对普通 lifecycle/process/legacy 事件使用与普通运行相同的兼容分组、错误字段和去重规则。评测报告可以增加 case 上下文，但不得把同一事件重新解释成另一套顶层时间线。

#### Scenario: Evaluation shows an incomplete run faithfully

- **WHEN** case 在拆解或测量工具阶段失败，且历史中同时存在模型、operation 和 terminal events
- **THEN** case 时间线显示连续过程、失败阶段和终态
- **AND** 不因事件缺少 `unit_id` 而制造大量独立历史卡片或跳过失败上下文

#### Scenario: Evaluation replay matches ordinary run

- **WHEN** 普通运行视图和评测 case 指向同一份 execution history
- **THEN** 两者使用相同的分组、错误分类、顺序和详情引用
- **AND** 评测读取不会重新执行模型、工具或审核

### Requirement: Large sanitized tool results remain retrievable

The evaluation system SHALL support on-demand retrieval of a complete sanitized tool result when the result cannot fit in the ordinary event envelope. The detail resource SHALL be evaluation- and case-scoped, allowlisted, bounded, and independent from raw SQLite or provider payload access. Existing bundles without such a resource SHALL remain readable through their persisted event result and SHALL report unrecoverable truncation explicitly.

#### Scenario: Large result has a detail resource

- **WHEN** a sanitized tool result exceeds the ordinary event envelope but a registered evaluation detail resource exists
- **THEN** the history event retains its identity, `call_id`, status, sequence, and a detail-resource reference
- **AND** expanding the tool result loads and displays the complete sanitized structured result on demand

#### Scenario: Large result was truncated before a detail resource existed

- **WHEN** a historical result was already truncated during persistence and no complete detail resource is registered
- **THEN** the client displays the persisted preview and an explicit unrecoverable-truncation marker
- **AND** the system does not infer or fabricate the missing fields

#### Scenario: Detail resource is unauthorized or unavailable

- **WHEN** a detail-resource request crosses evaluation/case ownership, points to a missing file, exceeds its resource limit, or uses an unsupported media type
- **THEN** the Gateway returns a bounded unavailable/not-found error
- **AND** the transcript keeps the event identity and shows the remaining run history

### Requirement: Evaluation resources are safe and previewable

The Gateway SHALL serve only allowlisted evaluation resources addressed by opaque or server-issued resource identifiers. Supported resources MAY include the input image, panel crops, visual observations, generated artifacts, report images, and bounded report/diagnostic text. Resource responses SHALL validate evaluation ownership, case/run ownership, media type, file existence, and configured size limits before returning content.

#### Scenario: User previews an available evaluation image

- **WHEN** the client requests an available input, panel, observation, artifact, or report image using its evaluation-scoped resource reference
- **THEN** the Gateway returns the image bytes with a validated supported media type
- **AND** the client can open it through the shared interactive preview without learning its local path

#### Scenario: Resource is missing or unauthorized

- **WHEN** a resource ID is unknown, belongs to another evaluation/case, is missing, changed, oversized, or has an unsupported media type
- **THEN** the Gateway returns a bounded unavailable/not-found error
- **AND** the client does not render a broken preview or fall back to a local path

#### Scenario: Caller attempts path traversal or sensitive-file access

- **WHEN** a request tries to address `..`, an absolute path, `.env`, `sessions.db`, or an unregistered file
- **THEN** the Gateway rejects the request without reading or exposing the target

### Requirement: Desktop client provides an independent evaluation workspace

The desktop client SHALL provide a distinct evaluation navigation mode and SHALL not render evaluation batches as ordinary conversations or sessions. The workspace SHALL include an evaluation list, selected evaluation details, case navigation, status text, stage timeline, failure explanation, report content, and visual evidence previews. Evaluation views SHALL be read-only in this change and SHALL not expose ordinary message composition or session deletion actions as evaluation mutations.

#### Scenario: User switches from sessions to evaluations

- **WHEN** the user activates the evaluation workspace
- **THEN** the client requests the evaluation catalog and displays it separately from the session list
- **AND** switching back to sessions preserves the existing active session state

#### Scenario: User inspects a case

- **WHEN** the user selects a case in an evaluation
- **THEN** the client shows its status, run references, ordered stages, bounded errors, report, and available evidence images
- **AND** technical identifiers remain visible where they help correlate a diagnosis

#### Scenario: Evaluation has no available records

- **WHEN** the evaluation catalog is empty or a selected bundle has no readable cases
- **THEN** the client shows a Simplified Chinese empty or unavailable state with a retry/refresh action
- **AND** the normal session workspace remains usable

### Requirement: Evaluation workspace refreshes safely

The client SHALL provide an explicit refresh action for evaluation data and SHALL poll selected evaluations only while their status is non-terminal, using bounded backoff or a bounded interval. Polling SHALL stop when an evaluation reaches `completed`, `partial`, or `blocked`, when the user leaves the evaluation workspace, or when the Gateway becomes unavailable. Refresh failures SHALL preserve the last readable snapshot and show an explicit stale/unavailable state.

#### Scenario: Running evaluation becomes terminal

- **WHEN** a selected evaluation changes from `running` to a terminal status
- **THEN** the client refreshes the final batch and case details
- **AND** it stops polling without duplicating cases or timeline events

#### Scenario: Gateway is temporarily unavailable

- **WHEN** a catalog or detail refresh cannot reach the local Gateway
- **THEN** the client keeps the last successful evaluation snapshot visible
- **AND** it shows a bounded retryable error instead of clearing the evaluation record

### Requirement: Reports and evidence remain separate from raw storage

The evaluation workspace SHALL render bounded Markdown/JSON summaries through safe client presentation and SHALL present report images through evaluation resource references rather than interpreting local Markdown file paths as browser URLs. Raw SQLite databases, unbounded provider payloads, credentials, and unrestricted report file contents SHALL remain unavailable to the client.

#### Scenario: Report contains image evidence

- **WHEN** a case has a Markdown report and registered report images
- **THEN** the client renders the report text and an evidence gallery using authorized resource references
- **AND** opening an image preserves its case and evaluation context

#### Scenario: Report is absent or truncated

- **WHEN** a bundle has no custom report or a report exceeds the bounded display limit
- **THEN** the client falls back to the standard summary/diagnostic view and indicates the report limitation
- **AND** it does not expose arbitrary files from the evaluation directory

### Requirement: Evaluation traces reuse the unified review presentation

评测工作区 SHALL 以只读方式复用普通运行的审核记录、门禁状态和证据引用，完整展示测量审核与生成图审核的开始、阻塞、修复、重试和最终结果，不得把中间审核过程压缩成单一成功或失败标签。

#### Scenario: Evaluation shows both review domains
- **WHEN** 一个评测同时包含测量审核和生成图审核
- **THEN** case 时间线分别显示两个审核 subject，同时使用统一的状态和阻塞语义
- **AND** 用户可以展开查看各自的问题、证据和下一步动作

#### Scenario: Evaluation preserves a blocked outcome
- **WHEN** 审核失败、修复耗尽或候选未发布
- **THEN** 评测记录明确显示阻塞原因和未完成阶段
- **AND** 报告不得把该 case 标记为完整成功

#### Scenario: Evaluation remains read-only
- **WHEN** 用户在评测工作区查看审核记录
- **THEN** 客户端只读取已保存的审核事件和资源
- **AND** 展开详情、刷新或预览不得重新触发测量、审核或发布动作

### Requirement: Evaluation cases use the shared decision timeline projector

评测工作台 SHALL 使用与普通运行相同的 decision unit、phase、transition 去重和 review cycle 投影。评测批次可以增加 case、expected result 和报告上下文，但不得为 timeline 另定义一套事件解释。

#### Scenario: Evaluation transcript matches an ordinary run

- **WHEN** 普通运行和评测 case 指向等价的 execution history
- **THEN** 两者显示相同的测量、证据、assemble、review、repair 和 publication 顺序
- **AND** 评测界面不会额外制造审核或工具步骤

#### Scenario: Evaluation remains read-only

- **WHEN** 用户展开或刷新 case timeline
- **THEN** 客户端只读取已保存的 timeline projection inputs 和安全资源
- **AND** 不重新执行测量、装配、VLM review 或发布

### Requirement: Evaluation timeline preserves unresolved and blocked decisions

评测 case SHALL 保留 pending、abandoned、failed、blocked、partial 和 not_reached 等决策状态，并显示当前 unit 的 reason、next action 和第一失败引用。任何中间摘要不得把未发布候选标记为完整成功。

#### Scenario: Focus application has no follow-up observation

- **WHEN** case 在 focused measurement applied 后中断或没有 observation
- **THEN** 评测时间线显示未完成的 measurement unit 和 interruption/absence reason
- **AND** case 不得被报告为已完成生成

#### Scenario: Review repair is exhausted

- **WHEN** candidate review 的 repair budget 用尽
- **THEN** case 显示父 candidate、最后 attempt、repair kind 和 blocked/unpublished 终态
- **AND** 报告保留已经产生的证据和失败诊断

### Requirement: Evaluation expands the same safe evidence details

评测工作台 SHALL 使用与普通运行相同的工具 call/result、decision、review sub-check 和 visual resource 关联规则。展开详情时 SHALL 保留 bounded structured values、sequence 和安全资源引用，不得通过本地路径或原始数据库补全内容。

#### Scenario: User expands a discarded evidence decision

- **WHEN** 用户展开一个 case 的 evidence decision
- **THEN** UI 显示 attempt、selected/discarded refs、basis 和后续 assemble 关系
- **AND** 原始 observation 仍然可追溯且未被摘要覆盖
