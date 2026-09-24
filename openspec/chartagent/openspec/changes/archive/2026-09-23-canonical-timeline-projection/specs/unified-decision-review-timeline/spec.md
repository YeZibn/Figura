## MODIFIED Requirements

### Requirement: Timeline projection is derived from canonical execution events

系统 SHALL 从同一份有序、持久化的 canonical execution events 生成确定性的用户时间线投影，普通运行和评测运行 SHALL 使用相同的投影规则。投影 SHALL 根据已声明的事件类型、unit identity、transition identity 及其 canonical 状态字段归并工具调用、工具结果、视觉观察、生成候选、审核和发布过程；不得从自由文本、同义字段、Gate 快照或旧字段别名猜测业务状态。Gateway 运行摘要中的派生状态只能作为查询投影，不得成为恢复或修改领域状态的权威来源。Evaluation 可以增加只读阶段诊断，但不得另建审核、测量或发布状态解释。原始受限事件详情 SHALL 仍可查看。

#### Scenario: Ordinary and evaluation views use one projection

- **WHEN** 普通运行和评测 case 引用同一份受支持的 execution history
- **THEN** 两者使用相同的用户时间线归并、工具调用/结果关联、状态标签和错误摘要
- **AND** Evaluation 的额外阶段诊断不改变该时间线及其业务状态

#### Scenario: Tool status comes from its canonical result

- **WHEN** 一个生成或测量工具先产生调用事件，随后产生符合该事件类型契约的成功或失败结果
- **THEN** 对应时间线节点按该工具结果的 canonical 执行状态更新
- **AND** 不从 `state/status` 别名、Gate 快照或嵌套自由文本推断第二种状态

#### Scenario: Timeline rebuilds after reload

- **WHEN** 用户刷新或重新打开一个已完成、失败或中断的受支持 Run
- **THEN** 客户端从历史事件重建相同的内部关联和用户时间线
- **AND** 重建不重新调用模型、工具、审核或发布动作

#### Scenario: Technical lifecycle events remain details, not duplicate steps

- **WHEN** 历史中包含模型轮次、operation 或运行生命周期事件
- **THEN** 这些记录按协议保留并可在受限技术详情中查看
- **AND** 默认用户时间线只呈现可解释的业务步骤及必要的终态错误

#### Scenario: Unsupported event history is not guessed

- **WHEN** Run 或评测 case 的事件版本/字段形状不受当前投影支持
- **THEN** 客户端显示明确的历史不可用或协议不支持状态
- **AND** 不创建 legacy/unknown 业务节点，也不推断审核通过或图表已发布
