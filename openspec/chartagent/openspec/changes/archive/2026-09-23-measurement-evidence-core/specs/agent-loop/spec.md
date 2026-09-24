## MODIFIED Requirements

### Requirement: Measurement repair remains compatible with direct assembly

当模型没有引用测量 evidence refs 而直接基于清晰视觉输入组装合法 ChartSpec 时，Agent SHALL 保持直接装配路径。任何未被引用、partial 或失败的 measurement observation 都不要求显式放弃，也不得阻塞合法装配；该路径仍必须经过 ChartSpec 结构校验和后续生成审核。

#### Scenario: Direct visual assembly does not enter measurement repair mode

- **WHEN** 模型提交没有 measurement provenance 的合法单图或图表集合装配请求
- **THEN** Agent 按现有 ChartSpec 校验和生成审核流程继续
- **AND** 不创建虚假的 measurement session 或 repair attempt

#### Scenario: Unused observation needs no abandonment decision

- **WHEN** 模型改用视觉或 OCR 证据而没有在 assembly 中引用某次 measurement attempt
- **THEN** Agent 保留该工具调用和原始结果作为运行历史
- **AND** 不创建 abandoned decision、额外测量状态或组装门禁

### Requirement: Assembly validates actual evidence use without a separate decision envelope

主循环 SHALL 允许 `assemble_spec` 直接接收模型实际使用的 `measurement_ref + evidence_refs`，或接收不带 measurement provenance 的合法视觉输入。系统 SHALL 只校验实际引用的 refs 及其 session、attachment、panel、attempt、scope、引用存在性和必要结构；装配 schema 和运行状态不得接受、推导或要求 `measurement_decision`、selected/discarded refs 或 decision status。

#### Scenario: Referenced evidence is valid

- **WHEN** 主 Agent 提交属于当前来源和 attempt 的合法 evidence refs
- **THEN** 组装继续并从实际输入保存 provenance
- **AND** 同一 observation 中未引用的候选不会阻塞组装

#### Scenario: Referenced evidence is invalid

- **WHEN** 主 Agent 提交不存在、越界、跨来源或结构不完整的 ref
- **THEN** 系统返回定位到该 ref 的结构化错误
- **AND** 不自动重测、不渲染、不发布依赖该引用的结果

#### Scenario: Direct visual assembly remains available

- **WHEN** 主 Agent 不引用测量结果而提交合法 ChartSpec
- **THEN** 系统执行通常的结构校验和生成审核
- **AND** 当前 run 中未使用的 measurement observation 不要求 decision 或 abandonment 事件

### Requirement: Measurement warnings do not schedule hidden tool calls

测量工具、质量审计和 checkpoint 恢复 SHALL NOT 仅根据 warning、`repair_action` 或质量状态自动创建或执行下一次测量调用。局部重测必须作为主 Agent 的显式测量 tool call 出现在主链路中；恢复只需将当前 measurement session/attempt 事实提供给模型，不维护独立 repair queue，也不因缺少 decision 阻塞模型继续工作。

#### Scenario: Warning returns control to the main model

- **WHEN** 一次测量返回基准线冲突、系列未解析或覆盖不完整 warning
- **THEN** 下一轮主 Agent 上下文包含 bounded warning、候选引用、scope 和可选局部线索
- **AND** 主 Agent 决定是否直接装配、使用其他观察工具或显式调用局部测量

#### Scenario: Recovery resumes without repeating a completed measurement

- **WHEN** Agent 从 checkpoint 或断线状态恢复，且最近一次测量已经完成
- **THEN** 恢复上下文包含相同 session/current attempt 和工具结果
- **AND** 恢复流程不重放相同测量、不恢复 pending decision 或隐式创建新调用
