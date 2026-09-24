## MODIFIED Requirements

### Requirement: Agent keeps measurement evidence decisions bounded

Agent loop SHALL 将测量返回的 observation scope、evidence refs、issues、focus suggestion、attempt lineage 和主 Agent 的选择结果作为有界的模型上下文保存。多个 measurement session 的上下文 SHALL 保持来源、面板和 attempt 边界；主 Agent 的显式局部补充、重复目标拒绝、舍弃和预算耗尽 SHALL 以结构化状态反馈，但不得隐式创建全量重测或独占主链路。

#### Scenario: Observation returns decision context to the model

- **WHEN** 测量工具返回候选、warning 或局部结果
- **THEN** Agent 将结构化问题、evidence refs、overlay、scope 和下一动作交给模型
- **AND** 系统不要求模型先通过独立 measurement review 才能继续观察

#### Scenario: Multiple measurements retain independent evidence contexts

- **WHEN** 同一个 assistant 工具批次中的多个测量结果分别绑定不同 panel 或 measurement session
- **THEN** Agent 保留每个 session 的 attachment、panel、attempt、父 attempt、证据引用和选择状态
- **AND** 任何一个 session 的结果都不会因为另一个结果后到达而被覆盖

#### Scenario: Measurement target exhaustion remains bounded

- **WHEN** 主 Agent 重复提交相同 target、来源身份失配或超过局部补充次数上限
- **THEN** Agent 停止该补充分支并保留 checkpoint、失败原因和 lineage
- **AND** 其他合法观察或直接视觉路径不被错误标记为生成审核失败

### Requirement: Measurement repair remains compatible with direct assembly

当模型没有引用测量证据而直接基于清晰视觉输入组装合法 ChartSpec 时，Agent SHALL 保持直接装配路径。即使当前 run 曾经产生未采用、partial 或失败的 observation，模型也可以明确放弃该 observation 后直接装配；该路径不得绕过 ChartSpec 结构校验和后续生成审核。

#### Scenario: Direct visual assembly does not enter measurement repair mode

- **WHEN** 模型提交没有 measurement provenance 的合法单图或图表集合装配请求
- **THEN** Agent 按现有 ChartSpec 校验和生成审核流程继续
- **AND** 不创建虚假的 measurement session 或 repair attempt

#### Scenario: Unused observation remains auditable

- **WHEN** 模型放弃一个已有 measurement attempt 并改用视觉或 OCR 证据
- **THEN** Agent 保留该 attempt 的历史和 abandoned 决策
- **AND** 不阻塞当前合法的组装请求

### Requirement: Main-chain measurement decisions are model-led

主 Agent SHALL 在同一主链路中消费测量工具返回的结构化结果、稳定证据引用、overlay、观察范围和质量警告，并自主决定选择候选、舍弃误检、映射语义、请求局部补充或停止。系统不得通过独立测量审核器替主 Agent 作出语义选择。

#### Scenario: Main Agent accepts a usable observation

- **WHEN** 测量工具返回候选结果且主 Agent 判断现有证据足以支持目标图表
- **THEN** 主 Agent 可以提交 selected/discarded refs 和语义映射到 `assemble_spec`
- **AND** 系统不自动发起额外测量

#### Scenario: Main Agent requests an initial scoped observation

- **WHEN** 主 Agent 在第一次测量前能够判断 plot 或 legend 的大致范围
- **THEN** 主 Agent 可以提交 `observation_scope`
- **AND** 该调用不要求先存在父 attempt

#### Scenario: Main Agent requests focused evidence

- **WHEN** 主 Agent 发现某个候选、系列、基准线或局部区域仍不确定
- **THEN** 主 Agent 可以再次调用对应的原测量工具并提供 `measurement_target`
- **AND** 该工具调用被记录为新的有父级关系的 measurement attempt

#### Scenario: Main Agent discards a false candidate

- **WHEN** 主 Agent 根据证据引用和源图像判断某个候选是图例、文字或其他误检
- **THEN** 主 Agent 可以在组装请求中排除该引用
- **AND** 系统不得因为该候选存在 warning 而自动重测整个 panel

### Requirement: Measurement warnings do not schedule hidden tool calls

测量工具、质量审计、checkpoint 恢复和 review gate 更新 SHALL 不得仅根据 warning、`repair_action` 或 `remeasure_required` 状态自动创建或执行下一次测量调用。所有局部重测 SHALL 出现在主 Agent 的显式 tool call 中；其他观察工具不得因为测量 warning 被隐式跳过。

#### Scenario: Warning returns control to the main model

- **WHEN** 一次测量返回基准线冲突、系列未解析或覆盖不完整 warning
- **THEN** 下一轮主 Agent 上下文包含 bounded warning、候选引用、scope 和可选 focus suggestion
- **AND** 在主 Agent 选择前没有新的 hidden measurement tool call

#### Scenario: Recovery resumes without repeating a completed measurement

- **WHEN** Agent 从 checkpoint 或断线状态恢复，且最近一次测量已经完成
- **THEN** 恢复状态停留在等待主 Agent 决策的阶段
- **AND** 恢复流程不得重新执行相同的测量调用

### Requirement: Assembly is blocked until the main-chain evidence decision is explicit

主循环 SHALL 要求使用 measurement evidence 的 `assemble_spec` 请求携带主 Agent 的 selected/discarded decision，并校验来源、范围、引用和幂等约束；该要求不得扩展为“整个 attempt 必须 accepted”。未被选择的候选可以被舍弃，未采用的 observation 可以被放弃，只有被选中的非法证据或结构化 ChartSpec 才能阻止当前组装。

#### Scenario: Assembly receives an explicit candidate decision

- **WHEN** 主 Agent 根据 overlay 和 evidence refs 提交 selected/discarded refs
- **THEN** 系统校验 decision 属于当前 attachment、panel 和 attempt
- **AND** 如果 selected refs 合法，组装可以继续，即使同一 attempt 仍有非阻断 warning

#### Scenario: Invalid candidate decision is rejected safely

- **WHEN** 主 Agent 提交不存在、越界、来源失配或互相重叠的 refs
- **THEN** 系统返回结构化 decision error
- **AND** 不自动重测、不发布、不把模型的最终文本当作通过依据
