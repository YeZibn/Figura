## MODIFIED Requirements

### Requirement: Main Agent context uses four explicit layers

主 Agent 上下文 SHALL 保持静态职责、动态工具、过程产物和 Run/Turn 动态状态四层。过程产物 SHALL 包含 observation scope、候选 refs、overlay、质量 warning 和实际使用的 provenance；Run/Turn 层 SHALL 提供当前事实、问题、候选状态和预算，不得把普通测量或审核修复建议表达为代码拥有的业务动作清单。

#### Scenario: Normal chart turn exposes the four layers

- **WHEN** 主 Agent为图表分析请求准备模型调用
- **THEN** 上下文区分长期规则、工具、过程产物和当前运行事实
- **AND** attachment、panel、候选与问题不会被误认为静态职责

#### Scenario: Empty process layer is explicit

- **WHEN** 当前 run 尚未产生 panel、观测或候选图
- **THEN** 过程产物层明确为空
- **AND** Agent不得引用其他 run 的产物

### Requirement: Main prompt defines an explicit evidence decision matrix

静态职责和动态状态 SHALL 帮助 Agent判断任务模式、来源范围、覆盖目标、证据充分性和可用工具，但 SHALL 将这些内容表达为决策原则和事实，而非必须提交 selected/discarded 状态的流程协议。工具 warning、remeasure suggestion 和 review repair hint SHALL 明确为非自动、非强制建议。

#### Scenario: Warning does not cause an unexplained duplicate measurement

- **WHEN** 测量返回 warning 或 remeasure suggestion
- **THEN** Agent可以采用已有证据、忽略候选、局部补测、改用其他证据或停止
- **AND** 系统不会自动调用工具，也不要求先写独立 decision 对象

### Requirement: Main Agent receives a compact current decision context

每轮主 Agent prompt SHALL 在现有四层体系中提供有界的当前状态摘要，至少表达当前 scope、可用 evidence/candidate 引用、issues、publication status、恢复状态和剩余预算。摘要 SHALL 引用代码拥有的事实，不得包含普通业务动作的 allowed/blocked action contract；仅不可绕过的授权、结构和发布约束可以标记为硬限制。

#### Scenario: Agent distinguishes focus from observation

- **WHEN** 当前范围已经应用但尚未获得 observation
- **THEN** prompt 将 focus 和 observation 作为不同事实表达
- **AND** 不指定模型必须继续同一测量或提交 abandoned 状态

#### Scenario: Agent sees evidence lineage without a decision state machine

- **WHEN** 当前 attempt 已有候选 refs 或部分 refs 已被装配使用
- **THEN** prompt 显示 attempt、scope、refs 和已使用 provenance
- **AND** Agent不需要维护另一套 selected/discarded lifecycle

### Requirement: Decision context declares allowed and blocked actions

动态状态层 SHALL 只对授权越界、无效来源、非法 ChartSpec、失败候选发布、terminal 状态和预算耗尽声明硬性阻止。对测量选择、修复工具、局部补测、ChartSpec 调整或来源恢复的建议 SHALL 作为可选 `repair_hint` 或 issue 表达，不得形成普通业务动作白名单。

#### Scenario: Failed review blocks publication only

- **WHEN** generated review 失败但仍有预算
- **THEN** prompt 明确当前候选不可发布并显示 issues 与建议
- **AND** Agent可以在授权范围内自主选择修复动作

#### Scenario: Prompt does not turn a warning into an automatic loop

- **WHEN** measurement 只有 warning
- **THEN** prompt 将其表达为证据质量事实
- **AND** 不声明模型必须测量、舍弃或关闭 decision unit

### Requirement: Prompt context remains aligned with the timeline projection

主 Agent prompt 与客户端时间线 SHALL 共享 run、candidate、attempt、scope 和 publication 身份，但两者无需共享模型内部下一动作状态。内部 decision、repair phase 和 subcheck 事件可以保留在 trace；默认客户端和模型上下文 SHALL 分别投影为适合其用途的事实摘要。

#### Scenario: Model and client share factual identity

- **WHEN** 同一 candidate 正在审核或修复
- **THEN** prompt 与客户端引用相同 candidate/review 身份和最终状态
- **AND** 客户端无需显示模型的候选动作，模型也无需遵循 UI projection 的步骤容器
