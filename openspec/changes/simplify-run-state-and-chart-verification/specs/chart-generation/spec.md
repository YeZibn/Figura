## REMOVED Requirements

### Requirement: Agent can request chart generation through the tool boundary

**Reason**: 旧候选、门禁或完整恢复状态契约已由提交执行事实与单一图表验证替代。
**Migration**: 使用 durable-execution-record、generated-chart-verification 及本 capability 的新增要求。

### Requirement: Generated chart output is bounded and attributable

**Reason**: 旧候选、门禁或完整恢复状态契约已由提交执行事实与单一图表验证替代。
**Migration**: 使用 durable-execution-record、generated-chart-verification 及本 capability 的新增要求。

### Requirement: Generated chart review is a mandatory publication gate

**Reason**: 旧候选、门禁或完整恢复状态契约已由提交执行事实与单一图表验证替代。
**Migration**: 使用 durable-execution-record、generated-chart-verification 及本 capability 的新增要求。

### Requirement: Generated candidates retain source and panel attribution

**Reason**: 旧候选、门禁或完整恢复状态契约已由提交执行事实与单一图表验证替代。
**Migration**: 使用 durable-execution-record、generated-chart-verification 及本 capability 的新增要求。

### Requirement: Failed candidates cannot bypass the review gate

**Reason**: 旧候选、门禁或完整恢复状态契约已由提交执行事实与单一图表验证替代。
**Migration**: 使用 durable-execution-record、generated-chart-verification 及本 capability 的新增要求。

### Requirement: Figure-level safety and review gate

**Reason**: 旧候选、门禁或完整恢复状态契约已由提交执行事实与单一图表验证替代。
**Migration**: 使用 durable-execution-record、generated-chart-verification 及本 capability 的新增要求。

### Requirement: Composite artifact metadata is attributable

**Reason**: 旧候选、门禁或完整恢复状态契约已由提交执行事实与单一图表验证替代。
**Migration**: 使用 durable-execution-record、generated-chart-verification 及本 capability 的新增要求。

### Requirement: Generated chart review uses the declared transformation semantics

**Reason**: 旧候选、门禁或完整恢复状态契约已由提交执行事实与单一图表验证替代。
**Migration**: 使用 durable-execution-record、generated-chart-verification 及本 capability 的新增要求。

### Requirement: Evidence repair preserves publication gating

**Reason**: 旧候选、门禁或完整恢复状态契约已由提交执行事实与单一图表验证替代。
**Migration**: 使用 durable-execution-record、generated-chart-verification 及本 capability 的新增要求。

## ADDED Requirements

### Requirement: Render tools return attributable staged output

合法 ChartSpec 渲染 SHALL 产生有界暂存图像和不透明引用，绑定准确 Spec、生成上下文、来源 attachment/panel 与 figure/collection 关系。返回给 Agent 的生成结果 SHALL 明确区分暂存预览与正式 artifact，不得在 JSON 中嵌入图像字节、凭证、原始 provider 内容或本地路径。自动验证及发布遵循 generated-chart-verification 契约。

#### Scenario: Rendered chart awaits verification
- **WHEN** render 产出需要源图语义比较的图像
- **THEN** 工具结果提供暂存引用和有界元数据
- **AND** 不提供正式 artifact 下载身份，系统自动启动适用验证

#### Scenario: Composite figure keeps child attribution
- **WHEN** 一个 figure 渲染多个子图
- **THEN** 暂存记录保留子图语义和来源覆盖
- **AND** 正式产物只在该图像通过所需验证后产生

### Requirement: Generation failure never becomes published output

渲染、暂存、来源绑定、验证或发布任一必需环节失败 SHALL 保持正式 artifact 不可用，并把结构化诊断交给 Agent。修正产生新尝试；原失败图仍可在授权范围内预览但不能被最终成功声明引用。

#### Scenario: Corrected spec creates a new attempt
- **WHEN** Agent 根据失败诊断提交修正后的 ChartSpec
- **THEN** 新渲染拥有新的尝试身份并重新验证
- **AND** 旧失败图保持未发布

## MODIFIED Requirements

### Requirement: Source-linked generation propagates task context

对于声明来自附件或 panel 的生成请求，生成工具 SHALL 接收并返回与 ChartSpec 绑定的
`generation_context`，并 SHALL 将 `mode`、`source_scope`、`coverage` 和
`selection_basis` 保留在不可变 chart manifest 中。渲染结果不得只依赖自由文本 source
标签来推断来源范围；验证结果和正式 artifact SHALL 引用相同的 staged chart 身份。

#### Scenario: Transform output keeps its source panel

- **WHEN** Agent 将一个 panel 的一个系列转换成另一种图表类型并请求渲染
- **THEN** 暂存 manifest 仍包含该 panel 的 source scope 和 transform mode
- **AND** 验证及发布路径读取相同的上下文与生成尝试
