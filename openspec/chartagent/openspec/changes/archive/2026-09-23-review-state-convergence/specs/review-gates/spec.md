## MODIFIED Requirements

### Requirement: Review subjects have a shared bounded lifecycle

系统 SHALL 为每个需要生成审核的图表候选创建唯一、可追踪的审核状态。审核状态 SHALL 包含 candidate 身份、来源引用、attempt/lineage、当前审核与发布状态、问题、修复动作、重试预算和时间信息，并 SHALL 使用有界、可序列化的字段。

测量工具返回的是候选证据，不属于共享审核对象。测量质量、warning、partial 或 remeasure 建议 SHALL 保留在测量 observation 中，不得创建独立 review identity 或生成审核 gate；主 Agent 根据这些证据自主决定是否采用、补测或继续组装。

#### Scenario: Generated chart candidate has one bounded review state
- **WHEN** 系统提交一个需要审核的生成图候选
- **THEN** 候选返回唯一审核身份、来源引用、状态、问题和下一步动作
- **AND** 专业检查结果仍保留在该候选的结构化审核详情中

#### Scenario: Review evidence remains attributable
- **WHEN** 生成审核结果写入运行事件、checkpoint 或评测记录
- **THEN** 结果保留 run、candidate、ChartSpec 和安全来源引用
- **AND** 不暴露本地路径、图像字节、凭证或 provider 原始 payload

#### Scenario: Measurement quality remains evidence
- **WHEN** 测量工具返回候选值、质量问题或定向补测建议
- **THEN** 运行记录将它们保存在测量 observation 中
- **AND** 系统不创建 measurement review identity 或独立审核 gate
- **AND** 主 Agent 可以继续调用其他证据工具或组装候选 ChartSpec

## ADDED Requirements

### Requirement: Generated review state has one authority

系统 SHALL 使用一个 canonical generated-review 状态作为审核、修复和发布的唯一权威来源。执行 gate、运行摘要和客户端审核状态 SHALL 从该状态派生，不得拥有彼此独立且可变的审核状态。恢复运行 SHALL 恢复 canonical 状态并重新计算 gate；旧的双状态 checkpoint SHALL 被明确拒绝并保持发布关闭，不得通过缺失状态推断审核通过。

#### Scenario: Gate is derived from the current candidate state
- **WHEN** 生成候选进入审核、修复、通过、失败或发布状态
- **THEN** 执行 gate 和运行摘要反映同一个 candidate attempt 与 review identity
- **AND** gate 的更新不会修改或覆盖权威审核状态

#### Scenario: Recovery restores a canonical review state
- **WHEN** 运行从包含 canonical generated-review 状态的 checkpoint 恢复
- **THEN** 系统恢复同一 candidate attempt 和 review identity
- **AND** 从恢复后的审核状态重新计算 gate，不重复创建审核记录或发布候选

#### Scenario: Unsupported split-state checkpoint fails closed
- **WHEN** 恢复数据只有旧的分离 review records 与 execution gate，且不包含 canonical generated-review 状态
- **THEN** 系统返回明确的 checkpoint review-state 不支持错误
- **AND** 候选保持不可发布，系统不将 gate 默认解释为已通过
