## MODIFIED Requirements

### Requirement: Keeps assistant tool calls in history

The system SHALL construct assistant history entries that include the model's
`tool_calls` when present, unlike the conversation loop which strips them, so a
multi-step agent can still reference its own prior actions. The system SHALL
preserve native tool-message ordering: when one assistant turn contains
multiple tool calls, every corresponding `tool` result SHALL be appended in
the original call order before any new user or assistant continuation message,
including measurement repair context.

#### Scenario: Assistant turn retains tool calls

- **WHEN** a model turn carries tool calls
- **THEN** the appended assistant entry includes those tool calls, not only the
  text content

#### Scenario: Multiple tool calls retain a valid contiguous result sequence

- **WHEN** one assistant turn carries multiple tool calls and one or more tool
  results produce follow-up guidance
- **THEN** the history contains the assistant tool-call entry followed by one
  matching `tool` entry for every call in the original order
- **AND** repair or other continuation guidance is appended only after the
  complete tool-result sequence

#### Scenario: Reasoning stays out of history

- **WHEN** a model turn carries provider reasoning
- **THEN** that reasoning is not echoed into the assistant history entry (to keep
  deep-thinking providers valid)

### Requirement: Agent runs a bounded measurement repair loop

Agent loop SHALL 能够识别测量结果或 `assemble_spec` 门禁返回的 repair action，并在当前 run 的步数与测量修复预算允许时把它作为下一轮模型上下文。修复请求必须绑定当前 attachment、panel 和父 attempt；同一 assistant 工具批次产生的多个 repair action SHALL 全部保留并以有界、可关联的集合交给后续模型，不得以最后一个 action 覆盖前面的 panel/session 修复。修复上下文只能在该批次所有工具结果写入后进入下一轮模型上下文；修复失败或预算耗尽时 SHALL 以明确的非发布状态结束，而不得无限重测或绕过门禁。

#### Scenario: Gate failure returns to the model with repair context

- **WHEN** `assemble_spec` 因 `remeasure_required`、`partial` 或其他非 accepted 状态被阻断，且修复预算仍有剩余
- **THEN** Agent 将结构化 issue、target 和下一动作交给模型
- **AND** 后续测量调用必须在同一来源范围内创建子 attempt

#### Scenario: Multiple measurements request repair in one model turn

- **WHEN** 同一个 assistant 工具批次中的多个测量结果分别绑定不同的 panel 或 measurement session，并且各自返回 repair action
- **THEN** Agent 保留每个 repair action 的 attachment、panel、session、attempt、父 attempt、受影响字段和 target
- **AND** 后续模型可以区分并依次处理这些 repair action
- **AND** 任何一个 repair action 都不会因为另一个 action 后到达而被覆盖

#### Scenario: Measurement repair exhausts safely

- **WHEN** 模型重复提交相同 target、来源身份失配或超过修复次数上限
- **THEN** Agent 停止该修复分支并保留可恢复的 checkpoint、失败原因和 lineage
- **AND** 不把最后一个未接受结果交给生成或最终回答作为确定数据

### Requirement: Measurement repair remains compatible with direct assembly

当模型没有引用测量证据而直接基于清晰视觉输入组装合法 ChartSpec 时，Agent SHALL 保持现有直接装配路径，不得为了启用 repair loop 强制增加测量调用或 target 字段。

#### Scenario: Direct visual assembly does not enter repair mode

- **WHEN** 模型提交没有 `measurement_ref` 的合法单图或图表集合装配请求
- **THEN** Agent 按现有 ChartSpec 校验和生成审核流程继续
- **AND** 不创建虚假的 measurement session 或 repair attempt
