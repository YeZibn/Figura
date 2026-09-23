## MODIFIED Requirements

### Requirement: Failed review remains inspectable

当生成图审核失败但仍可修复或已产生未发布候选时，客户端 SHALL 保留相关候选、诊断和状态；当最终不可恢复时，客户端 SHALL 显示失败原因和下一步行动。measurement tool observation 即使未被用于组装也可作为原始运行结果查看，但不得显示为采用/舍弃 decision 或已验证数值来源。

#### Scenario: Unpublished candidate remains visible

- **WHEN** 候选审核失败并进入修复流程
- **THEN** 用户可以查看该候选及其未发布状态
- **AND** 最终发布区域只展示通过审核的 artifact

#### Scenario: Unused measurement observation remains inspectable

- **WHEN** 主 Agent 后续未在 assembly 中引用某次 measurement observation
- **THEN** 用户仍可以查看原始工具调用、候选结果、scope 和质量信息
- **AND** 客户端不额外显示放弃决策、已采用或已验证状态

### Requirement: User can inspect measurement repair lifecycle

桌面客户端 SHALL 在 Agent 运行时间线中将每次图表测量呈现为普通工具步骤，并允许用户查看实际 scope、工具结果中的候选 refs/overlay、质量与系列 metadata。模型后续显式发起的局部重测 SHALL 显示为新的测量工具步骤；客户端 SHALL NOT 为选择/舍弃证据、repair queue、focus pending 或内部预算创建独立业务步骤。

#### Scenario: Scoped observation is visible

- **WHEN** 活跃运行收到带 `observation_scope` 的测量 tool call/result
- **THEN** 客户端在该工具步骤中显示 panel、实际观察范围、候选 overlay 和结果状态
- **AND** 客户端不把范围成功应用本身显示为测量通过或待完成门禁

#### Scenario: Local remeasurement is visible as another tool call

- **WHEN** 主 Agent 主动使用 `measurement_target` 发起局部测量
- **THEN** 客户端显示新的测量工具步骤及其 scope、refs 和诊断结果
- **AND** 不生成独立的“需要重测”“选择证据”或“修复被拒绝”卡片

#### Scenario: Measurement failure stays within the tool result

- **WHEN** 活跃运行收到局部测量失败或不充分结果
- **THEN** 客户端显示对应工具步骤及有界原因
- **AND** 不把它显示为 generated-chart review failure 或发布状态

### Requirement: Desktop client presents a unified blocking review state

桌面客户端 SHALL 区分非阻塞的 measurement tool observations 与阻塞发布的 generated-chart review。measurement warning、partial observation 和候选 refs 作为工具结果呈现；只有实际 generated-chart review 状态影响候选发布展示。客户端不得展示 measurement selected/discarded 状态或 decision gate。

#### Scenario: Measurement observation is visibly non-blocking

- **WHEN** 测量工具返回 warning、partial 或未解析标签
- **THEN** 运行时间线在工具步骤中显示观察状态、问题、scope、候选和可选局部线索
- **AND** 不显示“测量决策待处理”或阻止模型继续运行的 measurement gate

#### Scenario: Generated chart review is visibly blocking

- **WHEN** 生成图候选尚未通过审核
- **THEN** 候选卡片显示审核中、需要修复或未发布状态
- **AND** 用户不会把候选预览误认为已发布结果

#### Scenario: Actual assembly references remain inspectable

- **WHEN** 用户展开 measurement tool result 或对应 assembly tool details
- **THEN** 客户端可分别查看工具返回的候选 refs 与 assembly 实际携带的 refs、scope、质量信息和 overlay
- **AND** 不显示 selected/discarded 列表、semantic-decision 状态或独立 measurement gate

#### Scenario: Reconnected history shows the same current contract

- **WHEN** 客户端重新连接或读取可用的运行历史
- **THEN** 它根据工具调用/结果和生成审核事件恢复测量与发布展示
- **AND** 不因缺少 measurement decision 事件而显示为 pending、失败或已发布

### Requirement: Desktop client renders a grouped decision timeline

普通运行详情 SHALL 从同一份 execution events 派生内部关联和面向用户的扁平时间线。内部关联可以保留 observe、assemble、render、review、repair、publish 阶段、lineage 和去重语义，但模型内部对候选值的采用判断不得形成单独的测量状态或顶层卡片。界面顶层只 SHALL 展示可解释的测量/工具、审核、生成、发布、恢复或错误步骤；process、turn、operation 和 legacy 关联不得直接渲染为嵌套容器。

#### Scenario: User follows measurement through generation without decision cards

- **WHEN** 一个 run 包含测量、一次或多次局部测量、assembly、render、review 和 publication
- **THEN** 用户可以在一条连续时间线上看到实际工具调用及生成审核结果
- **AND** 系统不插入测量决策、证据舍弃或待处理状态卡片

#### Scenario: Tool invocation is a single visible step

- **WHEN** 一个工具依次产生 tool_call、tool_result 和 visual_observation
- **THEN** UI 将它们合并为一条可折叠工具步骤
- **AND** 用户无需阅读模型轮次或 operation-save 事件即可理解工具是否完成及其结果

#### Scenario: Pending states reflect actual blocking work only

- **WHEN** 生成图审核或其他实际阻塞操作尚未完成
- **THEN** UI 可以显示对应的真实待完成状态和下一步
- **AND** measurement scope/result 已在同一工具调用中返回时不创建 pending measurement unit

### Requirement: Client distinguishes observations, decisions, actions, gates, and publication

时间线 SHALL 区分工具观察、实际系统动作、generated-chart review gate 和发布结果；模型在主链路中选择哪些 measurement candidates SHALL 由实际后续工具输入体现，不得包装成单独的 decision card。相同 transition 的状态更新不得生成重复顶层卡片，原始工具结果仍可展开。

#### Scenario: Unused candidate does not create a decision card

- **WHEN** 主 Agent 未在 assembly 中引用某个 measurement evidence ref
- **THEN** 客户端继续显示原始测量工具结果和实际 assembly 请求
- **AND** 不新增“舍弃证据”步骤或 reason/basis 状态

#### Scenario: Review sub-checks are nested

- **WHEN** 一个 candidate review cycle 包含 deterministic audit 和 VLM semantic review
- **THEN** UI 显示一个审核父项和其子检查
- **AND** 不显示多个重复的审核开始卡片
