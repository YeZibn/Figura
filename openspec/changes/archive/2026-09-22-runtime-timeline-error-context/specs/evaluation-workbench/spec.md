## ADDED Requirements

### Requirement: Evaluation uses the runtime compatibility projection

评测工作台 SHALL 对普通 lifecycle/process/legacy 事件使用与普通运行相同的兼容分组、错误字段和去重规则。评测报告可以增加 case 上下文，但不得把同一事件重新解释成另一套顶层时间线。

#### Scenario: Evaluation shows an incomplete run faithfully

- **WHEN** case 在拆解或测量工具阶段失败，且历史中同时存在模型、operation 和 terminal events
- **THEN** case 时间线显示连续过程、失败阶段和终态
- **AND** 不因事件缺少 `unit_id` 而制造大量独立历史卡片或跳过失败上下文

#### Scenario: Evaluation replay matches ordinary run

- **WHEN** 普通运行视图和评测 case 指向同一份 execution history
- **THEN** 两者使用相同的分组、错误分类、顺序和详情引用
- **AND** 评测读取不会重新执行模型、工具或审核
