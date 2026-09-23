# tool-system Specification

## Purpose

Provides a declarative tool abstraction — tool definition, registration,
dispatch, and serialization — whose shape is designed to be exposed to external
agent hosts via MCP with minimal effort. It is the capability layer that future
agent loops call, without building the loop itself.

## Requirements

### Requirement: Declarative tool definition

The system SHALL let a tool be declared as metadata plus a callable: a stable
English name, a model-facing description, a JSON-Schema description of
accepted parameters, and a Python callable that executes the tool. A tool MAY
also carry a human-readable display name and a stable group identifier for
user interfaces and execution traces. The model-facing description SHALL be
concise, written in Simplified Chinese for natural-language guidance, and
explain the tool's purpose, applicable input or situation, when it should not
be used, returned data or visual evidence, and material limitations. Technical
identifiers, parameter names, enum values, and protocol fields SHALL retain
their stable English spelling. The metadata SHALL be independent of the
callable so the same tool can be described to an LLM or mapped to an external
protocol without touching the callable.

#### Scenario: Register a tool carrying core and display metadata

- **WHEN** a tool is created with a name, description, parameters schema, callable, and optional display metadata
- **THEN** the definition retains the stable name, description, parameters, callable, display name, and group without executing or introspecting the callable

#### Scenario: Existing tool construction remains compatible

- **WHEN** a tool is created using only the existing name, description, parameters, and callable fields
- **THEN** it remains valid with deterministic defaults for omitted optional metadata
- **AND** its existing function-calling name and callable behavior do not change

#### Scenario: Tool description gives actionable Chinese selection guidance

- **WHEN** a registered tool is exposed to a model
- **THEN** the description identifies in Chinese what the tool does, when its input is appropriate, when it should not be used, what evidence or data it returns, and any material limitation
- **AND** stable English identifiers remain recognizable to the model and external protocol adapters

#### Scenario: Tool metadata stays decoupled from the callable

- **WHEN** a tool is read back for LLM tool-definition or external mapping
- **THEN** the name, description and parameters schema are available without executing or introspecting the callable

### Requirement: Tool registry

The system SHALL provide a registry to register, retrieve and list tools by
name, and to reject duplicate registrations of the same name. Registration
SHALL preserve the complete tool metadata, and any authorized or context-bound
adapter SHALL expose the same stable identity and equivalent description while
replacing only the input contract and callable behavior required by that
authorization boundary.

#### Scenario: Register and list tools

- **WHEN** several tools are registered
- **THEN** each is retrievable by name and all are returned by the listing
- **AND** each listed definition retains its description, parameters, display
  metadata, and group

#### Scenario: Duplicate registration is rejected

- **WHEN** a tool is registered under a name already in the registry
- **THEN** the registration is rejected or raises, and the originally registered
  tool stays intact

#### Scenario: Authorized attachment adapter keeps tool identity

- **WHEN** an image tool is adapted to accept an authorized `attachment_id`
  instead of an internal image path
- **THEN** the adapted tool keeps the same stable name and model-facing
  description and exposes only the authorized attachment input
- **AND** its parameters and description do not instruct the model to provide a
  local filesystem path

### Requirement: Dispatch a tool call to execution

The system SHALL dispatch a tool call — a name plus a JSON string of arguments —
to the matching callable, running it with the parsed arguments, and SHALL handle
the case of an unknown tool name.

#### Scenario: Unknown tool name yields a structured error

- **WHEN** a dispatch names a tool that is not registered
- **THEN** it returns a structured error produced by the registry, so the caller
  can feed it back to the model

### Requirement: Structured result and serialization

The system SHALL normalize tool execution into structured data, zero or more
generated image payloads with captions, and zero or more non-fatal warnings.
The structured portion SHALL serialize as a JSON string fit to enter message
history, while generated images remain separate from JSON serialization. Tools
that return existing JSON-serializable values SHALL continue to produce the
same structured observation with no images or warnings. A failed call SHALL be
represented as a structured error object so the LLM or an external host can
read success and failure through the same observation contract.

#### Scenario: Successful result is JSON-serialized

- **WHEN** a tool call succeeds and the callable returns a value
- **THEN** the result returns as a JSON string and can enter history, with no
  generated images or warnings for a legacy JSON-serializable value

#### Scenario: Enriched result separates data from images

- **WHEN** a tool succeeds and returns structured data plus generated images
- **THEN** the structured data and image metadata are JSON-serializable while
  the image payloads are exposed separately for multimodal transport

#### Scenario: Failure becomes a structured error

- **WHEN** a tool call raises, or its result cannot be JSON-serialized
- **THEN** the result is a `{"error": ...}` structure rather than an unhandled
  exception or un-serializable object

#### Scenario: Invalid image does not invalidate structured data

- **WHEN** a tool returns serializable structured data alongside an invalid
  generated image
- **THEN** the structured observation remains successful and reports the image
  problem as a non-fatal warning

### Requirement: Convertible to an MCP tool surface

The system SHALL provide a thin conversion that maps registered tools to the MCP
tool manifest shape (name, description, input schema) and their callables to an
MCP-compatible callable form, producing the exposed surface without running a
server. The converted manifest SHALL be derived from the same registered
definition used by the Agent, and local presentation metadata MAY be retained
in the manifest object without changing the standard MCP name, description, or
input-schema fields.

#### Scenario: Registry maps to MCP tool manifests

- **WHEN** the registry is converted to an MCP tool surface
- **THEN** each registered tool yields its stable name, normalized description
  and parameters schema in MCP form, and a callable wrapper that can be invoked
  for that tool
- **AND** the manifest does not silently omit or invent required input fields

#### Scenario: Agent and MCP descriptions agree

- **WHEN** the same registered tool is exposed to the Agent and converted to an
  MCP manifest
- **THEN** both surfaces use the same stable name, description meaning, and
  parameter contract
- **AND** optional local display metadata does not replace the description or
  input schema

### Requirement: Tool parameter contracts are explicit and bounded

Every registered tool exposed to the model SHALL provide a JSON Schema whose
user-supplied fields have descriptions and whose structural constraints are
explicit where applicable. Required fields, enumerations, numeric ranges,
array item shapes and limits, and `additionalProperties` behavior SHALL be
represented in the schema rather than left only in prose. Context-bound image
tools SHALL expose an opaque authorized attachment identifier and SHALL NOT
expose an internal local path as a model input.

#### Scenario: Parameter schema explains every model input

- **WHEN** a tool is exposed through the Agent or MCP manifest
- **THEN** every model-supplied property has a type and a bounded description
- **AND** required properties, allowed values, ranges, item shapes, and
  additional-property behavior match the callable's accepted contract

#### Scenario: ChartSpec input constraints are visible

- **WHEN** a chart assembly, validation, rendering, or review tool accepts
  chart-specific structured input
- **THEN** the schema identifies applicable chart types, required fields,
  allowed values, bounded arrays, and candidate/review identifiers where
  relevant
- **AND** constraints needed to avoid a predictable tool error are not hidden
  only inside the callable

#### Scenario: Attachment input does not expose local paths

- **WHEN** a model invokes a tool that reads a user-provided image
- **THEN** the exposed schema accepts the opaque authorized attachment ID
- **AND** the model-facing schema contains no local source path parameter

### Requirement: Tool catalog provides stable presentation metadata

The system SHALL provide a bounded presentation lookup for registered tools
that maps each stable tool name to a human-readable Chinese display name,
optional English display name, and tool group. The lookup SHALL be additive to
the internal name and SHALL provide a safe fallback for unknown or newly added
tools.

#### Scenario: Known tool has bilingual presentation metadata

- **WHEN** a client or execution trace asks for presentation metadata for a
  registered tool
- **THEN** it can display a Chinese name together with the stable English tool
  name and its group

#### Scenario: Unknown tool keeps a safe fallback

- **WHEN** a client receives an event for a tool absent from the presentation
  lookup
- **THEN** it displays the stable tool name as the fallback
- **AND** the missing presentation entry does not invalidate or alter the tool
  call

### Requirement: Chart measurement tools share a bounded focus target

柱状图、折线图、散点图和饼图测量工具 SHALL 支持统一的可选 `observation_scope` 和 `measurement_target`。 `observation_scope` 用于第一次观察，支持当前 panel 内的归一化或源坐标 include/exclude 区域以及目标角色；`measurement_target` 用于已有 attempt 后的候选引用或局部补充。模型不需要提交内部文件路径、完整 mask 字节或伪造 session 身份。

#### Scenario: Initial observation uses a model-provided scope

- **WHEN** 主 Agent 第一次调用图表测量工具并提供 `observation_scope`
- **THEN** 工具在当前授权 panel 内解析该 scope 并返回实际应用区域
- **AND** 工具创建普通 observation attempt，不要求已有 measurement session 或父 attempt

#### Scenario: Initial observation can use normal detection

- **WHEN** 主 Agent 未提供 `observation_scope`
- **THEN** 工具在当前授权 attachment 和 panel 范围内执行一次基础测量
- **AND** 返回候选、质量信息、稳定证据引用和可关联 overlay

#### Scenario: Focused measurement resolves current candidates

- **WHEN** 主 Agent 调用同一图表测量工具并提供当前 attempt 的 `measurement_target`
- **THEN** 工具根据 refs 或区域执行 `include` 或 `exclude` focus
- **AND** 新结果记录父 attempt、target 引用和实际应用的搜索范围

### Requirement: Focused measurement never silently widens its search scope

当工具收到有效的 `observation_scope` 或 `measurement_target` 时，工具 SHALL 返回实际应用的范围、坐标空间和 overlay。若区域没有足够证据，工具 SHALL 返回有界的 `focus_empty`、`focus_insufficient` 或等价结果，且不得静默回退到整个 panel 或源图。

#### Scenario: Applied scope is observable

- **WHEN** 初次或定向范围成功应用
- **THEN** 工具结果包含 requested、applied、坐标空间、搜索区域和对应 overlay
- **AND** 主 Agent 可以判断结果是否来自指定区域

#### Scenario: Focus failure remains local

- **WHEN** 范围没有检测到候选或无法生成有效 mask
- **THEN** 工具返回局部失败或不充分状态及原因
- **AND** 工具不扩大范围、不创建隐式全量 attempt

### Requirement: Tool output separates evidence references from semantic labels

图表测量工具 SHALL 在结构化结果和 overlay 中返回稳定的候选引用，并将引用、检测序号、系列内部身份、位置、scope、质量信息和可选的人类可读 label 分开表达。未解析 label SHALL 保持 null 或 unresolved；工具不得把内部引用当作最终业务名称，也不得返回候选的 selected/discarded 生命周期状态。

#### Scenario: Candidates are returned as addressable evidence

- **WHEN** 工具检测到多个柱体、系列、轨迹、散点或扇区
- **THEN** 每个候选具有有界引用，且结构化结果和 overlay 使用同一引用
- **AND** 主 Agent 可以在后续工具调用中只引用实际使用的候选，不要求列举其余候选

#### Scenario: Internal identity is not a semantic label

- **WHEN** 工具无法从图例或文字证据解析真实系列名称
- **THEN** 工具返回内部引用、series metadata 和 `label: null` 或 unresolved 状态
- **AND** render 或 assemble 层不得自动把内部引用绘制成最终业务标签
### Requirement: Scope-aware chart tools expose bounded contracts

图表测量、assemble_spec 和 render_chart 的模型可见 JSON Schema SHALL 显式表达
`observation_scope`、`measurement_target`、`generation_context`、coverage 和候选引用的
适用关系、枚举、数量上限与字段描述。工具描述 SHALL 用简明中文说明何时使用、何时不要
使用、返回什么证据，以及工具不会替模型决定什么。

#### Scenario: Model can distinguish first observation from focused repair

- **WHEN** 主 Agent 查看图表测量工具定义
- **THEN** schema 和描述明确 observation_scope 用于当前调用范围
- **AND** measurement_target 只用于已有 attempt 的局部补充
- **AND** 不暗示工具会自动重测或自动选择业务系列

### Requirement: Scope violations return structured tool errors

工具收到与 generation context 不一致的 attachment、panel、bbox、measurement reference
或 coverage 时 SHALL 返回字段级结构化错误，且不得读取或测量越界区域。错误 SHALL 包含
可恢复的 action hint，例如重新绑定 source 或请求同 panel evidence。

#### Scenario: Measurement cannot widen to the dashboard

- **WHEN** evidence repair 的工具参数省略 panel scope 并试图扫描整张附件
- **THEN** 工具拒绝调用或要求明确的同范围 target
- **AND** 不返回可被误当作当前 candidate 证据的全图结果

### Requirement: Tool results keep evidence separate from semantic decisions

测量工具 SHALL 返回候选几何/数值、稳定 `measurement_ref` 与 `evidence_refs`、effective scope、质量元数据和系列元数据。`assemble_spec` SHALL 接收实际使用的 measurement/evidence refs、必要来源范围及图表意图，并 SHALL 校验引用存在性、来源归属和 ChartSpec 结构；工具 schema 和运行时不得接受、转换或兼容 `measurement_decision`、selected refs、discarded refs 或 decision status。

#### Scenario: Assembly uses only the referenced candidate evidence

- **WHEN** 主 Agent 根据图像和候选结果提交 `measurement_ref + evidence_refs` 以及图表意图
- **THEN** assemble 只校验并保存这些实际引用的候选及其来源
- **AND** 同次 measurement 中未引用的候选既不需要 decision，也不阻塞组装

#### Scenario: Invalid references return a focused error

- **WHEN** assembly 引用不存在、越界或跨来源的 evidence ref
- **THEN** 工具返回指向实际输入字段的结构化校验错误
- **AND** 不自动重测或将质量状态转换为 selected/discarded decision

#### Scenario: Legacy decision fields are not part of the model-visible contract

- **WHEN** 模型读取 measurement 或 assembly 工具 JSON Schema
- **THEN** schema 只声明候选 refs、scope、质量/系列信息与 assembly 所需的 ChartSpec 输入
- **AND** 不暴露 `measurement_decision`、`selected_refs`、`discarded_refs` 或其兼容别名

### Requirement: Source-linked generation context has one conditional contract

图表测量、assemble 和 render 的模型可见 schema 与运行时校验 SHALL 对 source-linked generation context 使用同一套条件约束：需要来源范围时必须得到有效的 attachment/panel scope；当请求已经唯一指向一个已授权的来源范围时，系统可以绑定该有效范围并返回 `effective_scope`；无法唯一确定时必须返回字段级错误。source-free synthesis SHALL 继续使用明确的非来源 coverage 语义。

#### Scenario: Unique authorized panel binds the effective scope

- **WHEN** 工具请求包含当前 attachment 和唯一已授权 panel，但 generation context 缺少可解析的 source scope
- **THEN** 系统只在该唯一范围内绑定并校验 effective scope
- **AND** 工具结果记录实际范围，主 Agent 不需要重复提交内部文件路径或 mask 字节

#### Scenario: Ambiguous source scope is rejected

- **WHEN** 请求涉及多个 panel、来源不一致或无法从 active handoff 唯一解析 source scope
- **THEN** 工具返回结构化字段错误和 action hint
- **AND** 工具不得静默选择一个 panel 或扩大到整张附件

### Requirement: Scope contract failures are distinguishable from chart failures

工具返回的 source scope/schema 错误 SHALL 使用稳定错误类别并包含 location、reason、effective/expected scope（在安全范围内）和可恢复提示；该错误不得伪装成测量数值为空、render 失败或 review 失败。

#### Scenario: Runtime and schema agree on missing scope

- **WHEN** 模型提交的 JSON 在通用 schema 层可解析，但 source-linked context 在运行时缺少必要范围
- **THEN** 工具按统一 source-scope contract 返回明确错误或安全绑定结果
- **AND** 前端和 execution trace 可以定位到 generation_context.source_scope
