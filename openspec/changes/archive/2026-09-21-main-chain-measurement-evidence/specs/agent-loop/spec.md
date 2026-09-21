## ADDED Requirements

### Requirement: Main-chain measurement decisions are model-led

主 Agent SHALL 在同一主链路中消费测量工具返回的结构化结果、稳定证据引用、overlay 和质量警告，并自主决定接受候选、舍弃误检、请求局部补充证据或停止。系统 SHALL 不得通过独立测量审核器替主 Agent 作出语义选择。

#### Scenario: Main Agent accepts a usable observation

- **WHEN** 测量工具返回候选结果且主 Agent 判断现有证据足以支持目标图表
- **THEN** 主 Agent 可以提交带有证据引用的 `assemble_spec`
- **AND** 系统不自动发起额外测量

#### Scenario: Main Agent requests focused evidence

- **WHEN** 主 Agent 发现某个候选、系列、基准线或局部区域仍不确定
- **THEN** 主 Agent 可以再次调用对应的原测量工具并提供 `measurement_target`
- **AND** 该工具调用被记录为新的有父级关系的 measurement attempt

#### Scenario: Main Agent discards a false candidate

- **WHEN** 主 Agent 根据证据引用和源图像判断某个候选是图例、文字或其他误检
- **THEN** 主 Agent 可以在装配请求中排除该引用
- **AND** 系统不得因为该候选存在 warning 而自动重测整个 panel

### Requirement: Measurement warnings do not schedule hidden tool calls

测量工具、质量审计、checkpoint 恢复和 review gate 更新 SHALL 不得仅根据 warning、`repair_action` 或 `remeasure_required` 状态自动创建或执行下一次测量调用。所有局部重测 SHALL 出现在主 Agent 的显式 tool call 中。

#### Scenario: Warning returns control to the main model

- **WHEN** 一次测量返回基准线冲突、系列未解析或覆盖不完整 warning
- **THEN** 下一轮主 Agent 上下文包含 bounded warning、候选引用和可选 focus suggestion
- **AND** 在主 Agent 选择前没有新的 measurement tool call

#### Scenario: Recovery resumes without repeating a completed measurement

- **WHEN** Agent 从 checkpoint 或断线状态恢复，且最近一次测量已经完成
- **THEN** 恢复状态停留在等待主 Agent 决策的阶段
- **AND** 恢复流程不得重新执行相同的测量调用

### Requirement: Assembly is blocked until the main-chain evidence decision is explicit

主循环 SHALL 阻止未被主 Agent 选择或未通过基本来源、范围和幂等校验的 measurement evidence 进入 `assemble_spec`，但该阻止 SHALL 只返回结构化决策上下文，不得自动触发测量修复。

#### Scenario: Direct assembly without a decision is rejected safely

- **WHEN** 主 Agent 在测量结果仍为 provisional 或 unresolved 时直接请求 `assemble_spec`
- **THEN** 系统返回 `measurement_decision_required` 或等价的 bounded error
- **AND** 系统不调用测量工具、不切换 panel，也不发布 ChartSpec

#### Scenario: Explicit focused measurement remains in the same loop

- **WHEN** 主 Agent 根据门禁上下文提交一个合法的 `measurement_target`
- **THEN** Agent 只执行该次对应的原测量工具调用并把结果反馈给主 Agent
- **AND** 主链路再次等待主 Agent 的接受、舍弃或下一次有限补充决定
