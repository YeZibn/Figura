## REMOVED Requirements

### Requirement: Agent performs semantic chart review automatically without an exposed review tool

**Reason**: 旧候选、门禁或完整恢复状态契约已由提交执行事实与单一图表验证替代。
**Migration**: 使用 durable-execution-record、generated-chart-verification 及本 capability 的新增要求。

### Requirement: Agent distinguishes candidate previews from published artifacts

**Reason**: 旧候选、门禁或完整恢复状态契约已由提交执行事实与单一图表验证替代。
**Migration**: 使用 durable-execution-record、generated-chart-verification 及本 capability 的新增要求。

### Requirement: Run a single user turn to completion

**Reason**: 旧候选、门禁或完整恢复状态契约已由提交执行事实与单一图表验证替代。
**Migration**: 使用 durable-execution-record、generated-chart-verification 及本 capability 的新增要求。

### Requirement: Agent uses a layered behavior prompt and automatic review obligations

**Reason**: 旧候选、门禁或完整恢复状态契约已由提交执行事实与单一图表验证替代。
**Migration**: 使用 durable-execution-record、generated-chart-verification 及本 capability 的新增要求。

### Requirement: Agent resumes from a committed execution checkpoint

**Reason**: 旧候选、门禁或完整恢复状态契约已由提交执行事实与单一图表验证替代。
**Migration**: 使用 durable-execution-record、generated-chart-verification 及本 capability 的新增要求。

### Requirement: Recoverable review failures return to the main Agent

**Reason**: 旧候选、门禁或完整恢复状态契约已由提交执行事实与单一图表验证替代。
**Migration**: 使用 durable-execution-record、generated-chart-verification 及本 capability 的新增要求。

### Requirement: Exhausted review recovery terminates explicitly

**Reason**: 旧候选、门禁或完整恢复状态契约已由提交执行事实与单一图表验证替代。
**Migration**: 使用 durable-execution-record、generated-chart-verification 及本 capability 的新增要求。

## ADDED Requirements

### Requirement: Agent runs one turn through committed actions

Agent SHALL 按模型响应、有序工具调用、自动生成图验证与最终回答推进一个用户请求；文本和多模态输入的原始结构 SHALL 保持有效。模型无工具调用时，只有不存在未决必需验证且最终产物引用均已正式发布，Run 才能成功完成。中断信号 SHALL 在安全边界停止新工作，迟到结果不得覆盖中断终态。

#### Scenario: Final text with no generation
- **WHEN** 模型结束且没有工具调用或未决生成图
- **THEN** Agent 提交最终回答并完成 Run

#### Scenario: Pending generated image blocks success
- **WHEN** 模型试图用未验证的暂存图作最终成功回答
- **THEN** Agent 不完成成功 Run
- **AND** 继续有界验证或返回明确未完成原因

### Requirement: Agent resumes from the committed next action

显式续接 SHALL 使用受限私有执行记录和已提交 checkpoint 重建必要模型上下文，从下一动作继续。Agent SHALL 复用已提交工具与验证结果，并按副作用契约处理未提交动作；不可核对外部副作用不得自动重放。

#### Scenario: Completed tool is not repeated
- **WHEN** 子 Run 从工具结果后的 checkpoint 恢复
- **THEN** 模型看到该结果且工具不重新执行

### Requirement: Verification failures return bounded facts to the main Agent

生成图验证失败 SHALL 向主 Agent 返回暂存尝试、来源范围、issues、修复提示和剩余预算。Agent SHALL 自主选择合法观察、测量、装配、重新生成或停止；提示内容不得自动调度工具或限制可用工具。预算耗尽 SHALL 以明确非成功终态保留诊断。

#### Scenario: Evidence repair is model selected
- **WHEN** 验证返回 evidence-needed 诊断
- **THEN** Agent 可以显式选择当前授权范围的测量工具
- **AND** 新图仍经过完整验证

### Requirement: Layered prompt exposes verification facts

主 Agent 的分层提示 SHALL 描述工具、ChartSpec、证据范围及自动验证/发布事实。运行时层只提供当前已提交的暂存尝试、验证结果及正式 artifact 引用；未提交或非权威状态不得暗示成功。

#### Scenario: Failed output is explained without a gate snapshot
- **WHEN** 暂存图的验证失败
- **THEN** 下一模型上下文包含有界 issues 与来源绑定
- **AND** 不包含另一份可变 gate 状态
