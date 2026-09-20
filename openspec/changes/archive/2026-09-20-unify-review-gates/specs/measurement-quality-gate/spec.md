## ADDED Requirements

### Requirement: Measurement review is a hard gate for the main chain

测量质量审核 SHALL 在测量结果提交后成为当前 run 和 panel 的主链路门禁，而不只在 `assemble_spec` 引用时做最后校验。未通过审核的测量不得用于 assemble、生成图或最终成功结论。

#### Scenario: Measurement audit blocks assembly
- **WHEN** 一次测量返回 `provisional`、`remeasure_required`、`partial`、`unsupported` 或 `failed`
- **THEN** 系统阻止依赖该测量的 assemble 和后续生成阶段
- **AND** `assemble_spec` 的引用校验继续作为防御性校验保留

#### Scenario: A failed measurement stops the current tool batch
- **WHEN** 模型一次返回多个工具调用，且其中一次测量审核产生阻断问题
- **THEN** 当前测量之后尚未开始的无关调用不得执行
- **AND** 它们被记录为未开始，并由审核修复流程重新决定是否执行

#### Scenario: Only the approved repair may run
- **WHEN** 测量审核提供同一 panel 内的定向重测 target
- **THEN** 系统只允许匹配 attachment、panel、父 attempt 和 target 的重测
- **AND** 新 attempt 重新审核并通过后，门禁才释放

#### Scenario: Measurement exhaustion prevents chart output
- **WHEN** 定向重测失败或达到预算上限
- **THEN** 当前 run 保留 attempt lineage、问题和恢复信息
- **AND** 系统不得组装或发布基于未接受测量的 ChartSpec
