# desktop-client Specification

## Purpose

Provide a local desktop workspace for ChartAgent where users can inspect sessions, conversations, attachments, and execution details through a consistent React interface hosted by Tauri.

## Requirements

### Requirement: Desktop client starts into the ChartAgent workspace

The desktop client SHALL open a local Figura workspace with clear session, conversation, and attachment areas. The workspace SHALL establish a consistent visual hierarchy in which the active conversation is primary, session navigation and attachments are secondary, and run state remains visible. It SHALL be usable without provider credentials when running with mock data.

#### Scenario: Workspace opens offline

- **WHEN** the user starts the desktop client without a configured provider or backend
- **THEN** the workspace opens with mock content or an explicit empty state instead of failing to render, and the visible product identity is Figura

#### Scenario: Narrow window remains usable

- **WHEN** the desktop window is resized to a narrow width
- **THEN** the primary conversation, input controls, session navigation, and attachment content remain readable with no major panel content overlapping

### Requirement: User-facing client content is Simplified Chinese

All user-visible interface labels, mock session names, sample messages, prompts, loading text, empty states, error messages, and interaction feedback SHALL use Simplified Chinese and SHALL use Figura as the primary product name. Technical identifiers, protocol fields, file formats, and tool names MAY remain in English when needed for accuracy, but they SHALL NOT replace the Figura product identity in user-facing branding.

#### Scenario: Chinese workspace copy

- **WHEN** the desktop client renders its workspace in mock mode
- **THEN** visible labels, example content, status feedback, and product-facing copy are presented in Simplified Chinese and identify the product as Figura

#### Scenario: Technical identifiers remain recognizable

- **WHEN** the UI displays a tool name, attachment ID, protocol field, or technical runtime identifier
- **THEN** it preserves the original identifier such as `load_image`, `att_...`, `React`, `Tauri`, or `chartagent` rather than translating the identifier itself

### Requirement: Workspace provides a clear visual hierarchy

The desktop workspace SHALL visually distinguish the session navigation, primary conversation, attachment inspection, user input, execution details, visual observations, and service status. The primary answer and current user request SHALL remain easier to scan than raw tool details, and state distinctions SHALL not depend on color alone.

#### Scenario: Major workspace regions are distinguishable

- **WHEN** a session is loaded with messages and attachments
- **THEN** the user can identify the active session, primary conversation, attachment area, input area, and service state without relying on hidden navigation or ambiguous borders

#### Scenario: Answer remains primary during execution

- **WHEN** a conversation contains tool calls, tool results, or visual observations
- **THEN** the assistant answer and user request remain visually prominent while execution details remain available in a subordinate, expandable presentation

#### Scenario: Run states are understandable

- **WHEN** a run is connecting, running, completed, failed, or unavailable
- **THEN** the workspace presents the state with text and a distinguishable visual treatment, and the state does not cause surrounding content to shift unpredictably

### Requirement: Workspace interaction affordances are consistent and accessible

Interactive controls SHALL use consistent sizing, focus treatment, labels, and familiar iconography across session navigation, message execution details, attachment actions, dialogs, and message submission. Essential actions SHALL remain discoverable without depending exclusively on pointer hover.

#### Scenario: Controls remain discoverable on narrow or touch-oriented layouts

- **WHEN** the workspace is viewed at a narrow width or without hover input
- **THEN** essential session, attachment, dialog, and message actions remain visible or keyboard accessible and their text or accessible labels fit within their controls

#### Scenario: Focused controls are identifiable

- **WHEN** the user navigates the workspace with a keyboard and focuses an interactive control
- **THEN** the focused control has a visible focus treatment and its accessible name describes the action in Simplified Chinese or preserves a necessary technical identifier

### Requirement: User can inspect and switch sessions

The workspace SHALL display available sessions, identify the active session, allow the user to select another session or request a new session, and expose an explicit delete action for each session. Deletion SHALL require confirmation and SHALL keep the workspace in a valid empty or neighboring-session state after success.

#### Scenario: Active session is visible

- **WHEN** the workspace has loaded session data
- **THEN** the session list shows the active session with a distinct selected state and the conversation reflects that session

#### Scenario: User switches sessions

- **WHEN** the user selects another session
- **THEN** the active state changes and the conversation and attachment panels update to the selected session's data

#### Scenario: User starts a new session

- **WHEN** the user activates the new-session action and confirms a name
- **THEN** the new session becomes active with an empty or starter conversation and no stale attachment selection

#### Scenario: User deletes a session

- **WHEN** the user confirms deletion of an idle session
- **THEN** the client removes it from the list, selects a deterministic remaining session or shows the empty workspace, and clears stale run and attachment state

#### Scenario: Session deletion is rejected

- **WHEN** the Gateway reports that the session is busy or unavailable
- **THEN** the client keeps the session visible and shows bounded Simplified Chinese recovery feedback

### Requirement: User can inspect a conversation

The conversation area SHALL render each completed or active Agent run as one
distinct chronological item containing, in order, the user request, its
expandable execution process, and its final result. Final Agent answers SHALL
be rendered as safe Markdown inside the final result area. Generated chart
artifacts SHALL be presented with the final result rather than as a duplicate
ordinary execution-timeline card, while the execution process SHALL retain a
compact event indicating that the chart was generated. The client SHALL use
the canonical run identifier returned by the Gateway to associate the user
request, assistant answer, execution events, and generated artifacts. New
server-backed runs SHALL NOT leave their user request or assistant answer in
the unassociated-message fallback merely because different layers generated
different local identifiers. The client SHALL preserve genuinely
unassociated legacy messages through a compatible fallback presentation.

#### Scenario: Conversation renders one Run in stable order

- **WHEN** a session contains a user request, an associated run, execution
  events, and a final answer
- **THEN** the UI renders one chronological Run item with the user request
  first, the expandable execution process second, and the final result last
- **AND** opening or closing the process does not change message order or lose
  any event

#### Scenario: Gateway Run identity associates the conversation

- **WHEN** the Gateway accepts a message and returns a Run identifier
- **THEN** the persisted user request, assistant answer, Run summary, and
  execution history use that same canonical identifier for association
- **AND** the UI renders the request and answer inside that Run instead of
  appending them as orphan messages

#### Scenario: Generated chart is shown as a final result

- **WHEN** an associated run produces one or more generated chart artifacts
- **THEN** the UI displays each available chart in the Run's final result area
- **AND** the execution process keeps only a bounded generated-chart event
  indicator instead of rendering the same chart as a second timeline card

#### Scenario: Run association survives live completion and reload

- **WHEN** a run receives an identifier during submission or is restored from
  persisted session data
- **THEN** the client associates the user request and assistant answer with
  that canonical run identifier and keeps them in the same Run item after
  completion or reload
- **AND** the client does not duplicate the user message or final answer

#### Scenario: Legacy messages remain visible

- **WHEN** a session contains a message that cannot be associated with a run
  identifier from the current or legacy data contract
- **THEN** the client renders the message in a compatible fallback position
- **AND** the message is not silently discarded while Run items are built

#### Scenario: Final answer renders Markdown

- **WHEN** the Agent answer contains Markdown headings, lists, tables,
  emphasis, links, or fenced code
- **THEN** the assistant answer displays those structures with safe styling in
  the final result area
- **AND** the source answer remains recoverable for copying or plain-text
  fallback

### Requirement: User can inspect persisted Agent runs

The desktop workspace SHALL display each Agent run as a compact execution group with its status, timestamps when available, and expand/collapse control. Inside the group it SHALL render a chronological user-facing timeline containing meaningful tool, observation, measurement, generation, review, recovery, and failure steps. A tool call and its result SHALL be represented as one logical step, while model-start, model-completion, operation-save, run-start, and resume-start lifecycle events SHALL remain available in the persisted history but SHALL NOT appear as ordinary visible timeline rows. A bounded or truncated tool result SHALL remain part of the corresponding tool step and SHALL NOT become an unknown standalone step when the outer tool identity is available.

#### Scenario: Completed run remains visible after reload

- **WHEN** the user reloads a session containing completed runs
- **THEN** the client restores their run summaries and can expand each one to inspect its persisted user-facing timeline

#### Scenario: Tool status is correlated

- **WHEN** a tool call and its result share a call identifier
- **THEN** the UI shows one logical tool step whose status changes from running to success or failure
- **AND** its arguments, bounded result, and visual evidence are available behind the step disclosure control

#### Scenario: Technical lifecycle events stay hidden

- **WHEN** a run history contains model-start, model-completion, or operation-save events
- **THEN** the ordinary timeline does not render separate rows or cards for those events
- **AND** the run status, tool steps, domain milestones, and terminal error remain understandable without opening raw history

#### Scenario: Truncated result remains in its tool step

- **WHEN** the Gateway marks a tool result body as truncated but preserves the originating tool name and call identifier
- **THEN** the UI keeps the result under the originating tool step
- **AND** it shows an explicit bounded or truncated-state indicator
- **AND** it does not render a separate “unknown tool” step

#### Scenario: Legacy or incomplete history is explicit

- **WHEN** a run has no recoverable events, has an event-history gap, or was interrupted by a Gateway restart
- **THEN** the UI shows an explicit unavailable, incomplete, or interrupted state
- **AND** it does not fabricate missing execution steps or expose a technical lifecycle bucket as the main user-facing process

### Requirement: User can inspect attachments

The workspace SHALL provide an attachment area showing attachment filename, media type, size, preview when available, and a visible state such as registered, unavailable, loaded, or observation available. Available image previews SHALL expose an explicit interactive preview trigger, persistent previews SHALL be loaded through the Gateway's safe session-scoped resource, and registered attachments SHALL expose an explicit remove action.

#### Scenario: Attachment preview is distinct from model loading

- **WHEN** an attachment is available in the active session
- **THEN** the UI can show its browser/client preview while separately indicating whether the Agent has loaded it

#### Scenario: Available attachment opens an interactive preview

- **WHEN** the user activates an available attachment image with a pointer or keyboard
- **THEN** the client opens the shared interactive preview for that attachment
- **AND** the attachment's filename, state, and remove action remain available when the preview closes

#### Scenario: Persistent attachment survives reload

- **WHEN** the active session is reopened after a frontend or Gateway restart and its source remains valid
- **THEN** the attachment metadata and image preview are restored without requiring the user to select the original local file again

#### Scenario: Attachment is unavailable

- **WHEN** the Gateway reports that an attachment source is missing or invalid
- **THEN** the UI shows an unavailable state and a re-upload recovery path without displaying a broken local path
- **AND** it does not open an interactive preview for the unavailable resource

#### Scenario: User removes an attachment

- **WHEN** the user confirms removal of a registered attachment
- **THEN** the client removes it from the panel and no longer includes its ID in a future message

#### Scenario: Attachment empty state

- **WHEN** the active session has no attachments
- **THEN** the attachment area shows an actionable empty state without disrupting conversation use

### Requirement: Client state has a replaceable backend boundary

The desktop UI SHALL consume sessions, conversation items, attachments, and run actions through a replaceable client boundary so mock data can be replaced by the Python backend without changing core presentation behavior.

#### Scenario: Mock adapter drives the workspace

- **WHEN** the desktop client runs in mock mode
- **THEN** session switching, new-session interaction, message submission, and attachment display work without network or provider access

#### Scenario: Backend adapter preserves UI contracts

- **WHEN** a future backend adapter returns data using the defined client contracts
- **THEN** the same workspace components can render it without direct access to Python classes or SQLite

### Requirement: User can observe a live Agent run

The desktop workspace SHALL start a run through the backend boundary and render
its current state as connecting, running, reconnecting, completed, failed,
interrupted, or unavailable. While a run is active, the workspace SHALL merge
historical replay and live events into one ordered execution group without
replacing the primary conversation with raw protocol data. The workspace SHALL
retain the run identity and last applied sequence across an event-stream
interruption, SHALL distinguish reconnect from an explicit retry, and SHALL
treat the durable terminal summary as authoritative.

#### Scenario: User submits a Gateway-backed message

- **WHEN** the user sends non-empty text with zero or more selected attachment IDs in Gateway mode
- **THEN** the workspace immediately shows the user request and a running state, then consumes the associated run events until a terminal result

#### Scenario: Execution details arrive during a run

- **WHEN** the Gateway emits model, tool-call, or tool-result events
- **THEN** the workspace adds corresponding expandable execution details in
  order and keeps the main answer area scannable

#### Scenario: Run completes successfully

- **WHEN** the associated run emits a final answer
- **THEN** the workspace renders the Markdown assistant answer, marks the run
  completed, and refreshes the session summary without duplicating the user
  message or removing its execution group

#### Scenario: Run reconnects after an event-stream interruption

- **WHEN** the event connection becomes unavailable while the run is active
- **THEN** the workspace retains rendered events, requests missing events after
  the last known sequence when possible, and resumes the run state
- **AND** it reports an explicit history-gap state if replay is unavailable

#### Scenario: Run fails or Gateway becomes unavailable

- **WHEN** the run emits a bounded failure or the event connection becomes unavailable
- **THEN** the workspace marks the run as failed or unavailable, shows
  Simplified Chinese recovery feedback, and preserves all prior events and
  completed conversation content

#### Scenario: Interrupted run is rendered as interrupted

- **WHEN** the run summary or event history reports a user, Gateway, provider,
  worker, or retention interruption reason
- **THEN** the workspace marks the run interrupted, shows the bounded reason in
  Simplified Chinese, and does not present an unfinished answer as completed

#### Scenario: Reconnect does not create duplicate work

- **WHEN** the workspace reconnects after losing an acknowledgement or SSE
  connection
- **THEN** it resumes the existing run by identity and sequence
- **AND** it does not submit another user message or Agent execution

#### Scenario: Explicit retry creates a new run

- **WHEN** the user chooses retry for a failed or interrupted run
- **THEN** the workspace starts a new run with a new identity and displays its
  bounded retry relationship to the prior run
- **AND** the prior run's events and terminal state remain inspectable

### Requirement: User can inspect live visual observations

The workspace SHALL render visual-observation events with their tool name,
caption, and an authorized image preview when the observation resource is
available. Persisted observation metadata and artifact availability SHALL be
distinct from user-local attachment previews, and expired artifacts SHALL show
an explicit bounded state.

#### Scenario: Generated observation is available

- **WHEN** a run emits a visual observation with an authorized observation ID
- **THEN** the workspace retrieves and displays the bounded image preview
  alongside its caption and execution context
- **AND** the observation remains discoverable when the run is reopened if its
  persisted artifact is still within policy

#### Scenario: Observation resource is unavailable or expired

- **WHEN** the observation ID is missing, unauthorized, or its artifact has
  expired
- **THEN** the workspace shows the persisted caption and bounded unavailable
  state without displaying a broken URL or exposing a local path

### Requirement: Backend boundary supports live events in mock and Gateway modes

The client boundary SHALL expose equivalent run and event contracts for mock
and Gateway adapters. Mock mode SHALL simulate a bounded ordered event
sequence without network access, while Gateway mode SHALL use the local event
stream and SHALL NOT silently fall back to mock events. The run submission
contract SHALL allow the client to provide an idempotency key, and the Gateway
adapter SHALL preserve the returned run identity on an equivalent repeated
submission.

#### Scenario: Mock mode exercises the live-run UI

- **WHEN** the client runs in mock mode and the user submits a message
- **THEN** the UI receives simulated running, execution-detail, and terminal events through the same boundary used by Gateway mode

#### Scenario: Gateway mode uses real events

- **WHEN** the client runs in Gateway mode and the local Gateway is ready
- **THEN** run state, execution details, visual observations, and final answer are driven by the Gateway contract rather than fabricated client data

#### Scenario: Gateway mode is not ready

- **WHEN** Gateway mode is selected but the local runtime is unavailable
- **THEN** the client shows the unavailable state and does not silently switch to mock mode

#### Scenario: Equivalent repeated submission preserves identity

- **WHEN** the adapter repeats an asynchronous submission with the same
  idempotency key and equivalent request data
- **THEN** it exposes the original run identity and state to the workspace
- **AND** it does not synthesize a second run

### Requirement: Unified startup selects the real client boundary

When the documented one-step Gateway development command is used, the desktop client SHALL connect to the local Gateway event and session APIs without requiring a second manual frontend command. The client SHALL expose startup or connection failures in Simplified Chinese and SHALL preserve explicit mock mode as a separate offline workflow.

#### Scenario: One-step Gateway startup reaches the workspace

- **WHEN** the unified development command starts the Gateway and the React client successfully
- **THEN** the workspace opens in Gateway mode and subsequent messages use real Gateway runs and SSE events

#### Scenario: One-step Gateway startup fails

- **WHEN** the unified command cannot make the Gateway ready
- **THEN** the workspace shows the unavailable state and does not fabricate mock sessions, tool events, or answers

### Requirement: User can inspect generated chart outputs

The desktop workspace SHALL display a successful generated chart as a
user-facing output distinct from temporary model visual observations. It SHALL
show a bounded preview, chart type and basic metadata, provide an interactive
preview trigger for an available image resource, provide a download action
when the artifact is available, and retain the output in the run's execution
context.

#### Scenario: Generated chart is shown after a successful run

- **WHEN** a run produces a generated chart artifact with an authorized
  reference
- **THEN** the workspace displays its preview with its chart type, title or
  caption, and bounded size metadata
- **AND** the output is labeled as a generated chart rather than a source
  attachment or tool observation

#### Scenario: Generated chart opens an interactive preview

- **WHEN** the generated chart has a usable image resource and the user activates its preview with a pointer or keyboard
- **THEN** the workspace opens the shared interactive preview for the generated chart
- **AND** the chart metadata and generated-result status remain identifiable in the preview

#### Scenario: Generated chart can be downloaded

- **WHEN** the generated artifact is available to the active session
- **THEN** the workspace exposes an accessible download action that retrieves
  the artifact through the Gateway reference
- **AND** the action does not expose a local server path or provider data
- **AND** downloading remains independent from opening the interactive preview

### Requirement: Desktop client distinguishes tool, review, and publication presentation

The desktop client SHALL render tool execution, generated-chart review, and
publication as separate user-facing concepts. Tool names SHALL use the
canonical bilingual presentation mapping when available, while lifecycle event
labels SHALL use the event label catalog and structured state fields rather
than inferring review or publication from a generic status string.

#### Scenario: Tool step uses bilingual name mapping

- **WHEN** the execution timeline renders a known tool call
- **THEN** it displays the Simplified Chinese tool name together with its stable
  English identifier
- **AND** the identifier remains available for technical inspection and
  correlation

#### Scenario: Generated chart shows independent statuses

- **WHEN** the final result or execution timeline renders a generated chart
- **THEN** it can show tool completion, review state, and publication state
  separately
- **AND** a successful render is not labeled as verified or published unless
  the corresponding publication field allows it

#### Scenario: Review labels are semantically accurate

- **WHEN** the client receives `chart_review_started`,
  `chart_review_completed`, or a publication event
- **THEN** it uses distinct Simplified Chinese labels for review start, review
  completion, publication, and rejection
- **AND** it does not label `chart_review_started` as a completed review

#### Scenario: Generated chart survives an ordinary reload

- **WHEN** the user reopens a session containing a generated chart within the
  configured retention policy
- **THEN** the run history restores its metadata and the preview or download
  action can request the authorized artifact again

#### Scenario: Generated chart is unavailable

- **WHEN** the artifact is expired, missing, unauthorized, or the run reports a
  rendering failure
- **THEN** the workspace shows an explicit bounded unavailable or failed state
- **AND** it does not render a broken image or claim that generation succeeded

### Requirement: Desktop client provides a unified preview experience

The desktop client SHALL use one preview resource boundary for uploaded
attachments, visual observations, generated candidates, and published chart
artifacts and one interactive preview presentation in mock, browser
development, and Tauri Gateway modes. It SHALL resolve resources using the
active backend configuration, validate that the response is an expected image
media type, release temporary client URLs when their owner is no longer
displayed, preserve safe metadata when bytes are unavailable, and expose
consistent pointer, keyboard, zoom, fit, and close behavior for resources
that are available.

#### Scenario: All supported image kinds use the active Gateway

- **WHEN** the client renders an uploaded attachment, visual observation,
  candidate, or published chart in Gateway mode
- **THEN** it requests the resource through the active Gateway endpoint and
  does not construct a path from a local source filename

#### Scenario: All supported image kinds use the same interactive preview

- **WHEN** the user opens an available attachment, visual observation, candidate, or published chart
- **THEN** the client uses the same bounded preview presentation and controls for each image kind
- **AND** the surrounding session and run context remains intact

#### Scenario: Tauri-managed Gateway address is honored

- **WHEN** the Tauri runtime starts the Gateway on a configured loopback host
  or non-default port
- **THEN** preview requests use that runtime address consistently with session,
  run, and event requests

#### Scenario: Preview response is not an image

- **WHEN** a preview request returns an error document, unsupported media type,
  empty body, or malformed image bytes
- **THEN** the client does not render it as an image and shows a bounded
  unavailable or invalid-preview state
- **AND** it does not open an interactive preview for that resource

#### Scenario: Preview resource is released

- **WHEN** a preview component or open interactive preview is replaced, unmounted, closed, or its resource changes
- **THEN** the client releases any temporary object URL it created and does not
  retain stale image bytes for another session or run

#### Scenario: Mock preview remains compatible

- **WHEN** the client runs in mock mode
- **THEN** the same preview presentation states and interactive controls are
  exercised with local mock resources without requiring a Gateway or provider
  connection

### Requirement: User can select the provider for the next run

The desktop workspace SHALL provide a visible provider selector with the
supported choices `OpenAI（中转站）`、`Qwen（DashScope）` and
`DeepSeek（V4.1 Flash）`. The selector SHALL
send only the provider identifier through the Gateway API, preserve the
selection for the active session, and make clear when a changed selection
applies to the next run rather than an active run.

#### Scenario: Provider selector is visible

- **WHEN** the workspace is loaded in Gateway mode
- **THEN** the user can see the current provider and choose OpenAI, Qwen, or
  DeepSeek using Simplified Chinese labels

#### Scenario: Selection is used on submission

- **WHEN** the user selects DeepSeek and submits a message
- **THEN** the client sends `provider: "deepseek"` with the run request and does not
  send API keys, endpoints, or arbitrary model parameters

#### Scenario: Selection survives session reload

- **WHEN** the active session is reloaded or revisited
- **THEN** the client restores the session's last effective provider when it is
  available, or falls back to the Gateway default with a clear state

#### Scenario: Unavailable provider is actionable

- **WHEN** Gateway health reports a provider as unavailable
- **THEN** the selector marks it unavailable or explains the bounded reason and
  prevents a misleading successful submission

### Requirement: Provider metadata is visible in run inspection

The workspace SHALL show the effective provider and model for a run when the
Gateway supplies them, while preserving the existing English machine
identifiers in any technical details.

#### Scenario: Run shows effective provider

- **WHEN** a run is accepted with provider metadata
- **THEN** its execution group or model-turn details show the corresponding
  Chinese provider label and model name

#### Scenario: Legacy run remains renderable

- **WHEN** a historical run has no provider metadata
- **THEN** the workspace renders it without fabricating a provider value

### Requirement: User can choose resume separately from reconnect and retry

The desktop client SHALL distinguish transport reconnect, explicit
continuation, and fresh retry in its run presentation. For an interrupted or
failed run, it SHALL display whether a safe checkpoint is available, show
bounded recovery block reasons in Simplified Chinese, and expose a `继续执行`
action only when the Gateway reports resume eligibility. Resume SHALL create
and display a new child run while retaining the parent timeline; reconnect
SHALL never create a new run.

#### Scenario: Recoverable interruption shows continue action

- **WHEN** a restored run is interrupted and exposes an available checkpoint
- **THEN** the client shows the interrupted reason and a `继续执行` action
- **AND** it also keeps `重新尝试` available as a from-scratch alternative

#### Scenario: Resume displays parent and child runs

- **WHEN** the user chooses `继续执行`
- **THEN** the client displays the new child run with a bounded resume
  relationship to the parent
- **AND** the original timeline and terminal state remain inspectable

#### Scenario: Blocked recovery explains the fallback

- **WHEN** a run has an uncertain in-flight operation or an expired checkpoint
- **THEN** the client hides or disables `继续执行`
- **AND** it shows a bounded Chinese explanation with the option to
  `重新尝试`

#### Scenario: Reconnect remains same-run recovery

- **WHEN** the event stream disconnects while a run is still active
- **THEN** the client reconnects with the same run identity and cursor
- **AND** it does not show the disconnect as a resume or create another user
  message

### Requirement: Execution view explains scoped reuse

桌面客户端 SHALL 在执行轨迹或结果上下文中显示当前使用的源附件、panel 名称或 panel ID、是否复用已有分区，以及分析结果是否来自局部范围。

#### Scenario: User inspects a reused panel run

- **WHEN** 后续 run 使用已有 panel handoff 完成测量
- **THEN** 用户可以看到该 run 复用了哪个面板
- **AND** 不需要通过工具原始日志推断是否重新拆解

### Requirement: Failed review remains inspectable

当生成图审核失败但仍可修复或已产生未发布候选时，客户端 SHALL 保留相关候选、诊断和状态；当最终不可恢复时，客户端 SHALL 显示失败原因和下一步行动。measurement tool observation 即使未被用于组装也可作为原始运行结果查看，但不得显示为采用/舍弃 decision 或已验证数值来源。

#### Scenario: Unpublished candidate remains visible

- **WHEN** 候选审核失败并进入修复流程
- **THEN** 用户可以查看该候选及其未发布状态
- **AND** 最终发布区域只展示通过审核的 artifact

#### Scenario: Unused measurement observation remains inspectable

- **WHEN** 主 Agent 后续未在 assembly 中引用某次 measurement observation
- **THEN** 用户仍可以查看原始工具调用、候选结果、scope 和质量信息
- **AND** 客户端不额外显示放弃决策、已采用或已验证状态

### Requirement: User can inspect measurement repair lifecycle

桌面客户端 SHALL 在 Agent 运行时间线中将每次图表测量呈现为普通工具步骤，并允许用户查看实际 scope、工具结果中的候选 refs/overlay、质量与系列 metadata。模型后续显式发起的局部重测 SHALL 显示为新的测量工具步骤；客户端 SHALL NOT 为选择/舍弃证据、repair queue、focus pending 或内部预算创建独立业务步骤。

#### Scenario: Scoped observation is visible

- **WHEN** 活跃运行收到带 `observation_scope` 的测量 tool call/result
- **THEN** 客户端在该工具步骤中显示 panel、实际观察范围、候选 overlay 和结果状态
- **AND** 客户端不把范围成功应用本身显示为测量通过或待完成门禁

#### Scenario: Local remeasurement is visible as another tool call

- **WHEN** 主 Agent 主动使用 `measurement_target` 发起局部测量
- **THEN** 客户端显示新的测量工具步骤及其 scope、refs 和诊断结果
- **AND** 不生成独立的“需要重测”“选择证据”或“修复被拒绝”卡片

#### Scenario: Measurement failure stays within the tool result

- **WHEN** 活跃运行收到局部测量失败或不充分结果
- **THEN** 客户端显示对应工具步骤及有界原因
- **AND** 不把它显示为 generated-chart review failure 或发布状态

### Requirement: Desktop client presents a unified blocking review state

桌面客户端 SHALL 区分非阻塞的 measurement tool observations 与阻塞发布的 generated-chart review。measurement warning、partial observation 和候选 refs 作为工具结果呈现；只有实际 generated-chart review 状态影响候选发布展示。客户端不得展示 measurement selected/discarded 状态或 decision gate。

#### Scenario: Measurement observation is visibly non-blocking

- **WHEN** 测量工具返回 warning、partial 或未解析标签
- **THEN** 运行时间线在工具步骤中显示观察状态、问题、scope、候选和可选局部线索
- **AND** 不显示“测量决策待处理”或阻止模型继续运行的 measurement gate

#### Scenario: Generated chart review is visibly blocking

- **WHEN** 生成图候选尚未通过审核
- **THEN** 候选卡片显示审核中、需要修复或未发布状态
- **AND** 用户不会把候选预览误认为已发布结果

#### Scenario: Actual assembly references remain inspectable

- **WHEN** 用户展开 measurement tool result 或对应 assembly tool details
- **THEN** 客户端可分别查看工具返回的候选 refs 与 assembly 实际携带的 refs、scope、质量信息和 overlay
- **AND** 不显示 selected/discarded 列表、semantic-decision 状态或独立 measurement gate

#### Scenario: Reconnected history shows the same current contract

- **WHEN** 客户端重新连接或读取可用的运行历史
- **THEN** 它根据工具调用/结果和生成审核事件恢复测量与发布展示
- **AND** 不因缺少 measurement decision 事件而显示为 pending、失败或已发布

### Requirement: Desktop client renders a grouped decision timeline

普通运行详情 SHALL 从同一份 execution events 派生内部关联和面向用户的扁平时间线。内部关联可以保留 observe、assemble、render、review、repair、publish 阶段、lineage 和去重语义，但模型内部对候选值的采用判断不得形成单独的测量状态或顶层卡片。界面顶层只 SHALL 展示可解释的测量/工具、审核、生成、发布、恢复或错误步骤；process、turn、operation 和 legacy 关联不得直接渲染为嵌套容器。

#### Scenario: User follows measurement through generation without decision cards

- **WHEN** 一个 run 包含测量、一次或多次局部测量、assembly、render、review 和 publication
- **THEN** 用户可以在一条连续时间线上看到实际工具调用及生成审核结果
- **AND** 系统不插入测量决策、证据舍弃或待处理状态卡片

#### Scenario: Tool invocation is a single visible step

- **WHEN** 一个工具依次产生 tool_call、tool_result 和 visual_observation
- **THEN** UI 将它们合并为一条可折叠工具步骤
- **AND** 用户无需阅读模型轮次或 operation-save 事件即可理解工具是否完成及其结果

#### Scenario: Pending states reflect actual blocking work only

- **WHEN** 生成图审核或其他实际阻塞操作尚未完成
- **THEN** UI 可以显示对应的真实待完成状态和下一步
- **AND** measurement scope/result 已在同一工具调用中返回时不创建 pending measurement unit

### Requirement: Client distinguishes observations, decisions, actions, gates, and publication

时间线 SHALL 区分工具观察、实际系统动作、generated-chart review gate 和发布结果；模型在主链路中选择哪些 measurement candidates SHALL 由实际后续工具输入体现，不得包装成单独的 decision card。相同 transition 的状态更新不得生成重复顶层卡片，原始工具结果仍可展开。

#### Scenario: Unused candidate does not create a decision card

- **WHEN** 主 Agent 未在 assembly 中引用某个 measurement evidence ref
- **THEN** 客户端继续显示原始测量工具结果和实际 assembly 请求
- **AND** 不新增“舍弃证据”步骤或 reason/basis 状态

#### Scenario: Review sub-checks are nested

- **WHEN** 一个 candidate review cycle 包含 deterministic audit 和 VLM semantic review
- **THEN** UI 显示一个审核父项和其子检查
- **AND** 不显示多个重复的审核开始卡片

### Requirement: Collection candidates are grouped without losing child details

当同一 render 产生 collection child candidates 时，客户端 SHALL 以 collection review parent 聚合展示，并允许展开每个 child 的 candidate、attempt、issue、scope 和 publication status。

#### Scenario: Multiple generated images share one parent

- **WHEN** 一次生成返回多个同源 child charts
- **THEN** UI 显示一个生成/审核批次和多个 child 状态
- **AND** 用户可以区分“多个子图”与“同一候选被重复审核”

### Requirement: Timeline details remain read-only and recoverable

展开、刷新和重连时间线 SHALL 只读取已有事件、诊断和安全资源，不得重新触发模型、工具、审核或发布。用户默认看到面向业务的步骤；技术生命周期字段、sequence、原始 payload 和兼容关联 SHALL 只能通过受限的按需详情读取。历史缺失、截断和不可用状态 SHALL 在对应可见步骤或运行摘要上明确展示。

#### Scenario: Refresh does not repeat a review

- **WHEN** 用户刷新一个已完成或失败的 run
- **THEN** UI 从历史记录重建相同的用户时间线和 review cycle
- **AND** 不产生新的 VLM invocation 或 publication action

### Requirement: Runtime timeline presents compatibility groups instead of event noise

桌面客户端 SHALL 将普通生命周期事件显示在可理解的运行过程或有界历史容器中；只有具备可解释 decision-unit 语义的事件才作为独立顶层决策单元。所有容器 SHALL 保留事件数量、顺序和展开入口，并使用稳定的中文状态。

#### Scenario: Test-style run is readable

- **WHEN** run 只完成加载、拆解、一次工具调用后失败
- **THEN** 用户可以看到加载、拆解、工具调用、失败原因和终态的连续过程
- **AND** 页面不会被大量相互独立的“关联不可用”卡片淹没

#### Scenario: Historical fallback is bounded

- **WHEN** 客户端读取旧版本事件且无法建立过程关联
- **THEN** 客户端将旧事件放入明确的兼容容器并标注关联能力边界
- **AND** 不把兼容容器内的事件解释为某个候选已通过审核或已发布

### Requirement: Client exposes actionable provider and scope errors

错误摘要 SHALL 优先展示结构化 failure category、provider 状态或工具字段错误、safe message 和下一步提示；原始 payload SHALL 继续以受限、只读方式展开。没有结构化字段时才使用通用 fallback 文本。

#### Scenario: Balance or authorization failure is visible

- **WHEN** provider 返回余额、授权或请求限制类拒绝
- **THEN** 客户端显示对应的可读原因和 provider 状态
- **AND** 用户不需要展开原始 JSON 才能知道失败不是图表数据问题

#### Scenario: Source scope validation failure is visible

- **WHEN** 图表工具因 source scope 缺失、不一致或歧义拒绝调用
- **THEN** 客户端显示具体字段、当前范围和 action hint
- **AND** 不把该错误显示成无上下文的 render 或 review 失败
