## MODIFIED Requirements

### Requirement: Lifecycle events separate execution, review, and publication state

Lifecycle events SHALL 保持工具执行、measurement observation、evidence decision、生成图审核和 publication status 的独立字段。`measurement_observed`、`measurement_evidence_selected`、`measurement_evidence_discarded` 和 `measurement_repair_exhausted` 等事件不得被解释为生成图审核通过或失败；`chart_review_started` 仅表示生成候选进入审核。Run lifecycle events SHALL 继续区分 active、completed、failed 和 interrupted。

#### Scenario: Tool result reports observation state only

- **WHEN** 一个 OCR 或图表测量工具完成
- **THEN** `tool_result` 和对应 observation 事件独立报告执行状态、scope、refs、质量 warning 和 overlay
- **AND** 工具成功不会自动产生 accepted、published 或 generated review passed 状态

#### Scenario: Evidence decision records model agency

- **WHEN** 主 Agent 选择、舍弃或放弃一次 observation
- **THEN** trace 记录对应 attempt、selected/discarded refs、语义映射和 decision 来源
- **AND** 原始工具结果仍保持可追溯

#### Scenario: Generated review has accurate semantics

- **WHEN** 生成候选进入审核、修复或发布
- **THEN** trace 使用独立的 chart review 和 publication 状态
- **AND** 客户端不会把测量 observation 或 assemble 成功显示为已发布

### Requirement: Measurement repair lifecycle is inspectable

执行追踪 SHALL 区分普通 measurement observation、首次 scope、定向重测、证据选择、repair action 被拒绝和修复预算耗尽。相关事件 SHALL 保留 bounded run、panel、attempt、父 attempt、scope/target 类型、selected/discarded 状态和下一动作摘要，但不得记录原始图片、绝对路径、密钥或 provider 原始 payload。

#### Scenario: A scoped observation is correlated with its panel

- **WHEN** Agent 根据模型提供的 observation scope 发起测量
- **THEN** trace 可以关联 scope、panel、attempt、实际应用区域和结果状态
- **AND** 客户端能够区分首次范围观察与后续局部重测

#### Scenario: A repair attempt is correlated with its parent

- **WHEN** Agent 根据某次 observation 的问题发起定向重测
- **THEN** trace 可以关联 repair request、子 attempt、父 attempt、panel 和结果状态
- **AND** 客户端能够区分修复测量与新的无关观察

#### Scenario: Exhausted repair is explicit

- **WHEN** 定向重测无法收敛或达到预算上限
- **THEN** trace 发布明确的 repair-exhausted 或等价非发布状态及下一动作
- **AND** 该状态不被错误归类为 generated chart review failure

### Requirement: Measurement repair events have stable client presentation

执行追踪面向客户端的事件契约 SHALL 支持 measurement observation、`measurement_evidence_selected`、`measurement_repair_required`、`measurement_repair_rejected` 和 `measurement_repair_exhausted` 等事件。客户端 SHALL 保留稳定的英文事件类型，并为 observation、选择、舍弃、需要重测、修复被拒绝和预算耗尽提供有界的简体中文展示标签和诊断摘要。

#### Scenario: Selection event preserves correlation fields

- **WHEN** 客户端接收 measurement evidence selection 事件
- **THEN** 事件仍可通过 run、panel、attempt、selected refs 和 discarded refs 关联到对应运行
- **AND** 原始图片、绝对路径、密钥和 provider 原始 payload 不进入用户可见正文

#### Scenario: Replay and live delivery share the same presentation

- **WHEN** 同一 observation 或 decision 事件先通过历史回放返回、再通过实时流或重连流到达
- **THEN** 客户端使用相同的事件类型、标签和字段解释
- **AND** 按 run 与 sequence 去重，不产生重复的用户可见事件
