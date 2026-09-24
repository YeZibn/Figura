## REMOVED Requirements

### Requirement: Desktop client distinguishes tool, review, and publication presentation

**Reason**: 旧候选/审核/发布生命周期和门禁展示契约由提交事实投影取代。
**Migration**: 使用本 capability 的新增要求以及 generated-chart-verification 的结果语义。

### Requirement: Desktop client provides a unified preview experience

**Reason**: 旧候选/审核/发布生命周期和门禁展示契约由提交事实投影取代。
**Migration**: 使用本 capability 的新增要求以及 generated-chart-verification 的结果语义。

### Requirement: User can choose resume separately from reconnect and retry

**Reason**: 旧候选/审核/发布生命周期和门禁展示契约由提交事实投影取代。
**Migration**: 使用本 capability 的新增要求以及 generated-chart-verification 的结果语义。

### Requirement: Failed review remains inspectable

**Reason**: 旧候选/审核/发布生命周期和门禁展示契约由提交事实投影取代。
**Migration**: 使用本 capability 的新增要求以及 generated-chart-verification 的结果语义。

### Requirement: Desktop client presents a unified blocking review state

**Reason**: 旧候选/审核/发布生命周期和门禁展示契约由提交事实投影取代。
**Migration**: 使用本 capability 的新增要求以及 generated-chart-verification 的结果语义。

### Requirement: Desktop client renders a grouped decision timeline

**Reason**: 旧候选/审核/发布生命周期和门禁展示契约由提交事实投影取代。
**Migration**: 使用本 capability 的新增要求以及 generated-chart-verification 的结果语义。

### Requirement: Client distinguishes observations, decisions, actions, gates, and publication

**Reason**: 旧候选/审核/发布生命周期和门禁展示契约由提交事实投影取代。
**Migration**: 使用本 capability 的新增要求以及 generated-chart-verification 的结果语义。

### Requirement: Collection candidates are grouped without losing child details

**Reason**: 旧候选/审核/发布生命周期和门禁展示契约由提交事实投影取代。
**Migration**: 使用本 capability 的新增要求以及 generated-chart-verification 的结果语义。

### Requirement: Timeline details remain read-only and recoverable

**Reason**: 旧候选/审核/发布生命周期和门禁展示契约由提交事实投影取代。
**Migration**: 使用本 capability 的新增要求以及 generated-chart-verification 的结果语义。

### Requirement: Desktop timeline consumes one canonical event projection

**Reason**: 旧候选/审核/发布生命周期和门禁展示契约由提交事实投影取代。
**Migration**: 使用本 capability 的新增要求以及 generated-chart-verification 的结果语义。

### Requirement: User can inspect measurement repair lifecycle

**Reason**: 测量和局部重测通过普通工具调用呈现，不再维护额外的测量修复生命周期标题。
**Migration**: 使用 measurement tool-step 投影展示 scope、结果和质量诊断。

## ADDED Requirements

### Requirement: Desktop presents execution, verification and published results

客户端 SHALL 以简体中文从同一事件投影呈现工具、测量、图像验证、正式图表和终态错误。暂存失败图可以预览并显示诊断，但下载和已发布标识只适用于正式 artifact；界面不得维护独立验证状态或从互不一致的事实拼装发布结论。

#### Scenario: Failed image is inspectable
- **WHEN** 生成图验证失败但暂存预览仍有效
- **THEN** 用户可以查看图片、问题和来源范围
- **AND** 该图片不显示为可下载的成功产物

#### Scenario: Verified warning is explicit
- **WHEN** 策略允许带 warning 发布
- **THEN** 用户看到正式 artifact 和明确警告
- **AND** 不显示为无条件通过

### Requirement: Client separates reconnect, resume and retry

SSE 断线 SHALL 使用原 Run 和最后序号重连；显式 resume SHALL 仅在 Gateway 推导可恢复时可用，并创建具有父子关系的新 Run；retry SHALL 从原请求开始。客户端 SHALL 展示有界不可恢复原因，并在模型/VLM 未提交请求可能重发时说明可能增加调用费用。

#### Scenario: Interrupted run has an eligible cursor
- **WHEN** 历史 Run 中断且 Gateway 报告可恢复
- **THEN** 客户端提供显式继续执行入口
- **AND** 继续后的执行显示在子 Run 中

### Requirement: Client groups collection verification by stable identity

客户端 SHALL 将同一 collection 的 figure/child 尝试作为一个可展开生成流程呈现，同时保留每个子图的独立结果、来源范围和问题。前端 mock 与 Gateway 模式 SHALL 实现相同客户端合约，时间线刷新不得重新发起 VLM 或发布。

#### Scenario: Collection has mixed results
- **WHEN** 一个子图发布且另一个子图验证失败
- **THEN** 展开内容分别显示正式产物和失败预览
- **AND** 刷新后仍保持相同关联

### Requirement: User can inspect measurement tool steps

桌面客户端 SHALL 在 Agent 运行时间线中将每次图表测量呈现为普通工具步骤，并允许用户查看实际 scope、工具结果中的 evidence refs/overlay、质量与系列 metadata。模型后续显式发起的局部重测 SHALL 显示为新的测量工具步骤；客户端 SHALL NOT 为证据选择、focus pending 或内部预算创建独立业务步骤。

#### Scenario: Scoped observation is visible

- **WHEN** 活跃运行收到带 `observation_scope` 的测量 tool call/result
- **THEN** 客户端在该工具步骤中显示 panel、实际观察范围、overlay 和结果状态
- **AND** 客户端不把范围成功应用本身显示为测量通过或待完成门禁

#### Scenario: Local remeasurement is visible as another tool call

- **WHEN** 主 Agent 主动使用 `measurement_target` 发起局部测量
- **THEN** 客户端显示新的测量工具步骤及其 scope、refs 和诊断结果
- **AND** 不生成独立的证据选择或焦点等待卡片

## MODIFIED Requirements

### Requirement: User can inspect a conversation

The conversation area SHALL render each completed or active Agent run as one chronological item containing the user request, execution process, and final result. Generated chart artifacts SHALL appear with the final result, with a compact event in the execution process. The client SHALL associate messages and artifacts by the canonical Gateway run identifier. Genuinely unassociated messages SHALL remain visible with an explicit incomplete-association state.

#### Scenario: Unassociated messages remain visible

- **WHEN** a session contains a message that has no associated run identifier
- **THEN** the client renders the message in an explicit incomplete-association position
- **AND** the message is not silently discarded while Run items are built

### Requirement: User can inspect persisted Agent runs

The desktop workspace SHALL display each Agent run as a compact execution group with its status, timestamps, and expand/collapse control. The chronological timeline SHALL contain meaningful tool, observation, measurement, generation, verification, recovery, and failure steps. A tool call and result SHALL form one logical step. Model-start, model-completion, internal commit-confirmation, run-start, and resume-start events SHALL remain in persisted history but not appear as ordinary visible rows. Truncated results SHALL remain in the originating tool step when its identity is available.

#### Scenario: Technical execution events stay hidden

- **WHEN** a run history contains model-start, model-completion, or internal commit-confirmation events
- **THEN** the ordinary timeline does not render separate rows for them
- **AND** run status, tool steps, domain milestones, and terminal errors remain understandable

### Requirement: Client exposes actionable provider and scope errors

错误摘要 SHALL 优先展示结构化 failure category、provider 状态或工具字段错误、safe message 和下一步提示；原始 payload SHALL 继续以受限、只读方式展开。没有结构化字段时才使用通用 fallback 文本。

#### Scenario: Source scope validation failure is visible

- **WHEN** 图表工具因 source scope 缺失、不一致或歧义拒绝调用
- **THEN** 客户端显示具体字段、当前范围和 action hint
- **AND** 不把该错误显示成无上下文的渲染失败
