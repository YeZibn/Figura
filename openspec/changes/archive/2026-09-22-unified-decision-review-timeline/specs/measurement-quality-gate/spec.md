## ADDED Requirements

### Requirement: Focused measurement closes its observation obligation

局部测量 SHALL 区分 focus request、effective scope、measurement observation 和 evidence decision。`focus_applied` 只有在绑定到一个明确的 measurement attempt 时才有效；若该 attempt 没有产生对应 observation，系统 SHALL 将其保留为 pending、failed 或 abandoned，而不得当作有效证据。

#### Scenario: Applied focus is followed by same-scope observation

- **WHEN** 主 Agent 请求同一 panel 内的局部测量且工具成功应用该范围
- **THEN** measurement attempt 记录 effective scope 并返回对应 observation
- **AND** 后续证据选择可以引用该 attempt 的 refs

#### Scenario: Applied focus has no observation

- **WHEN** 局部范围已应用但工具没有返回该范围的有效 observation
- **THEN** 系统记录明确的 pending、failed 或 abandoned 状态和下一步
- **AND** 若该动作属于 evidence-needed gate，则 assemble 和 publication 继续保持阻塞

### Requirement: Evidence decisions are bound to one measurement attempt

每个 measurement attempt SHALL 至多拥有一个当前有效的 selected/discarded/abandoned decision。decision SHALL 绑定 session、attempt、scope 和 evidence refs，并 SHALL 在 assemble 使用前持久化；重复提交相同 decision SHALL 幂等返回已有状态。

#### Scenario: Selected and discarded refs are co-located

- **WHEN** Agent 从一个 observation 中选择 S1 并舍弃 S2
- **THEN** 系统在同一 attempt 下保存 selected refs、discarded refs 和 decision basis
- **AND** assemble 只能消费 selected refs 或明确的 legacy/direct input

#### Scenario: Assemble does not create a second decision

- **WHEN** assemble_spec 读取一个已经记录的 measurement decision
- **THEN** assemble 只验证并引用该 decision
- **AND** 工具结果快照不会再次制造一个新的证据选择事件

### Requirement: Required and optional measurement actions are distinguishable

系统 SHALL 区分由审核修复明确要求的 same-scope measurement 与 Agent 主动发起的可选 focused observation。只有 required action 未关闭时才阻塞其所属 repair gate；可选动作可以被 Agent 放弃，但必须留下可追溯的理由和状态。

#### Scenario: Required evidence repair blocks assembly

- **WHEN** generated review 返回 evidence_needed 且指定同一 panel 的 measurement target
- **THEN** 在该 target 完成 observation 或明确进入 terminal/abandoned 前，系统不得推进该候选的 assemble
- **AND** 其他不属于该 repair 的 run 状态仍然可被记录

#### Scenario: Optional focus can be abandoned explicitly

- **WHEN** Agent 判断可选的局部观察收益不足并选择放弃
- **THEN** 系统关闭该 optional target 并保存 abandonment reason
- **AND** 不自动发起下一次测量
