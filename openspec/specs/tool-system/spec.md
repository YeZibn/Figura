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

柱状图、折线图、散点图和饼图测量工具 SHALL 支持统一的可选 `measurement_target` 参数。该参数 SHALL 支持引用已有候选或提供有界区域、`include`/`exclude` 模式、受影响字段和原因；模型不需要提交内部文件路径、session 标识或完整 mask 字节。未提供 target 时工具执行一次基础测量，提供 target 时工具只执行对应的局部补充测量。

#### Scenario: Initial measurement uses the normal scope

- **WHEN** 主 Agent 调用图表测量工具但未提供 `measurement_target`
- **THEN** 工具在当前授权 attachment 和 panel 范围内执行一次基础测量
- **AND** 返回候选、质量信息、稳定证据引用和可关联 overlay

#### Scenario: Focused measurement resolves candidate references

- **WHEN** 主 Agent 调用同一图表测量工具并提供当前 attempt 中的候选引用
- **THEN** 工具根据引用解析对应的几何区域并执行 `include` 或 `exclude` focus
- **AND** 新结果记录父 attempt、target 引用和实际应用的搜索范围

#### Scenario: Explicit region is bounded

- **WHEN** 主 Agent 请求的局部区域无法通过已有引用表达
- **THEN** 工具允许使用有界源图 bbox 或 polygon 作为 target
- **AND** 工具拒绝越界、空区域、跨 panel 或无法归属当前 attachment 的 target

### Requirement: Focused measurement never silently widens its search scope

当测量工具收到有效的 focused target 时，工具 SHALL 返回实际应用的 target 状态和搜索范围。若 mask 或局部区域没有足够证据，工具 SHALL 返回有界的 `focus_empty`、`focus_insufficient` 或等价非接受结果，且不得静默回退到整个 panel 或源图。

#### Scenario: Applied focus is observable

- **WHEN** focused target 成功应用
- **THEN** 工具结果包含 `requested`、`applied`、target 引用、搜索范围和对应 overlay
- **AND** 主 Agent 可以判断本次结果是否真正来自局部测量

#### Scenario: Focus failure remains local

- **WHEN** focused target 没有检测到候选或无法生成有效 mask
- **THEN** 工具返回局部失败或不充分状态及原因
- **AND** 工具不扩大范围、不创建隐式全量 attempt

### Requirement: Tool output separates evidence references from semantic labels

图表测量工具 SHALL 在结构化结果和 overlay 中返回稳定的候选引用，并 SHALL 将引用、检测序号、系列内部身份和可选的人类可读 label 分开表达。未解析的 label SHALL 保持 null 或 unresolved，不得使用 `series_1` 等内部引用作为用户可见名称。

#### Scenario: Candidate can be cross-referenced

- **WHEN** 工具检测到多个柱体、系列、轨迹、散点或扇区
- **THEN** 每个候选具有有界引用，且结构化结果和 overlay 使用同一引用
- **AND** 主 Agent 可以基于引用发起下一次 focused measurement

#### Scenario: Internal identity is not a semantic label

- **WHEN** 工具无法从图例或文字证据解析真实系列名称
- **THEN** 工具返回内部引用和 `label: null` 或 unresolved 状态
- **AND** render 或 assemble 层不得自动把内部引用绘制成最终业务标签
