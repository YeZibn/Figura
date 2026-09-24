## MODIFIED Requirements

### Requirement: Evaluation cases use the shared decision timeline projector

评测工作台 SHALL 使用与普通运行相同的 canonical 用户时间线投影、decision unit、phase、transition 去重、工具 call/result 关联和 review cycle 规则。评测批次可以增加 case、expected result、报告上下文及只读阶段诊断，但 SHALL NOT 再解释或修正审核、测量、Gate 和发布的领域状态。时间线 SHALL 按事件类型读取其唯一规定的状态字段，不得从旧别名或 Gate 快照推断状态；不支持的历史协议 SHALL 显示明确的不可用/不支持状态。

#### Scenario: Evaluation transcript matches an ordinary run

- **WHEN** 普通运行和评测 case 指向同一份受支持的 execution history
- **THEN** 两者显示相同的测量、工具、assembly、review、repair 和 publication 时间线步骤
- **AND** 评测专有的阶段诊断不会新增、删除或改写时间线业务状态

#### Scenario: Evaluation remains read-only

- **WHEN** 用户展开或刷新 case timeline
- **THEN** 客户端只读取已保存的 timeline inputs 和安全资源
- **AND** 不重新执行测量、装配、VLM review 或发布

#### Scenario: Unsupported history is explicit

- **WHEN** 一个 case 的事件协议版本或字段形状不受当前投影支持
- **THEN** 工作台保留 case 与运行摘要并标注时间线不可用/不支持
- **AND** 不借用 Evaluation 阶段推断来伪造通过、失败或发布状态
