## ADDED Requirements

### Requirement: Agent runs a bounded measurement repair loop

Agent loop SHALL 能够识别测量结果或 `assemble_spec` 门禁返回的 repair action，并在当前 run 的步数与测量修复预算允许时把它作为下一轮模型上下文。修复请求必须绑定当前 attachment、panel 和父 attempt；修复失败或预算耗尽时 SHALL 以明确的非发布状态结束，而不得无限重测或绕过门禁。

#### Scenario: Gate failure returns to the model with repair context

- **WHEN** `assemble_spec` 因 `remeasure_required`、`partial` 或其他非 accepted 状态被阻断，且修复预算仍有剩余
- **THEN** Agent 将结构化 issue、target 和下一动作交给模型
- **AND** 后续测量调用必须在同一来源范围内创建子 attempt

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
