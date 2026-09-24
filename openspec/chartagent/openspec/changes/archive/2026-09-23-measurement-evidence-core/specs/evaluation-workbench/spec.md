## MODIFIED Requirements

### Requirement: Evaluation timeline preserves unresolved and blocked decisions

评测 case SHALL 保留真实的 pending、failed、blocked、partial 和 not_reached 运行/审核状态，并显示当前运行单元的原因和必要的后续信息。measurement scope 与 observation 属于同一次工具调用；不得把它们之间不存在的间隔显示为 pending/abandoned measurement decision。任何中间摘要不得把未发布候选标记为完整成功。

#### Scenario: Scoped measurement result is atomic

- **WHEN** case 在局部测量 tool call 执行期间中断，或工具返回失败/不充分结果
- **THEN** 评测时间线显示真实的工具执行状态及 interruption/结果原因
- **AND** 不构造等待 follow-up observation 的 measurement unit

#### Scenario: Review repair is exhausted

- **WHEN** candidate review 的 repair budget 用尽
- **THEN** case 显示父 candidate、最后 attempt、repair kind 和 blocked/unpublished 终态
- **AND** 报告保留已经产生的证据和失败诊断

### Requirement: Evaluation expands the same safe evidence details

评测工作台 SHALL 使用与普通运行相同的工具 call/result、实际 assembly 输入、review sub-check 和 visual resource 关联规则。展开详情时 SHALL 保留 bounded structured values、sequence 和安全资源引用，不得通过本地路径或原始数据库补全内容；measurement 候选选择不得表现为单独的 decision record。

#### Scenario: User inspects measurement and assembly evidence

- **WHEN** 用户展开一个评测 case 的测量或 ChartSpec assembly 工具步骤
- **THEN** UI 显示 attempt、scope、工具输出 refs/质量信息及 assembly 实际引用关系
- **AND** 不显示 selected/discarded refs、decision basis 或额外 evidence-decision 步骤

#### Scenario: Original observation remains inspectable

- **WHEN** assembly 未引用某个 measurement candidate
- **THEN** 原始 measurement tool result 仍可查看
- **AND** 工作台不推断 abandoned/discarded 状态或把该候选写入最终 ChartSpec
