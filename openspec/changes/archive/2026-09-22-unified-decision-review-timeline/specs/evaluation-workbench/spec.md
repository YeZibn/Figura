## ADDED Requirements

### Requirement: Evaluation cases use the shared decision timeline projector

评测工作台 SHALL 使用与普通运行相同的 decision unit、phase、transition 去重和 review cycle 投影。评测批次可以增加 case、expected result 和报告上下文，但不得为 timeline 另定义一套事件解释。

#### Scenario: Evaluation transcript matches an ordinary run

- **WHEN** 普通运行和评测 case 指向等价的 execution history
- **THEN** 两者显示相同的测量、证据、assemble、review、repair 和 publication 顺序
- **AND** 评测界面不会额外制造审核或工具步骤

#### Scenario: Evaluation remains read-only

- **WHEN** 用户展开或刷新 case timeline
- **THEN** 客户端只读取已保存的 timeline projection inputs 和安全资源
- **AND** 不重新执行测量、装配、VLM review 或发布

### Requirement: Evaluation timeline preserves unresolved and blocked decisions

评测 case SHALL 保留 pending、abandoned、failed、blocked、partial 和 not_reached 等决策状态，并显示当前 unit 的 reason、next action 和第一失败引用。任何中间摘要不得把未发布候选标记为完整成功。

#### Scenario: Focus application has no follow-up observation

- **WHEN** case 在 focused measurement applied 后中断或没有 observation
- **THEN** 评测时间线显示未完成的 measurement unit 和 interruption/absence reason
- **AND** case 不得被报告为已完成生成

#### Scenario: Review repair is exhausted

- **WHEN** candidate review 的 repair budget 用尽
- **THEN** case 显示父 candidate、最后 attempt、repair kind 和 blocked/unpublished 终态
- **AND** 报告保留已经产生的证据和失败诊断

### Requirement: Evaluation expands the same safe evidence details

评测工作台 SHALL 使用与普通运行相同的工具 call/result、decision、review sub-check 和 visual resource 关联规则。展开详情时 SHALL 保留 bounded structured values、sequence 和安全资源引用，不得通过本地路径或原始数据库补全内容。

#### Scenario: User expands a discarded evidence decision

- **WHEN** 用户展开一个 case 的 evidence decision
- **THEN** UI 显示 attempt、selected/discarded refs、basis 和后续 assemble 关系
- **AND** 原始 observation 仍然可追溯且未被摘要覆盖
