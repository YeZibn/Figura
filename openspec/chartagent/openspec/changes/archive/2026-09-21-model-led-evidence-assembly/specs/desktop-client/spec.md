## MODIFIED Requirements

### Requirement: Desktop client presents a unified blocking review state

桌面客户端 SHALL 使用统一的审核展示模型呈现 measurement observation、证据决策和生成图审核，并明确显示某个状态是否阻塞主链路。普通测量 warning、partial observation 和未采用候选 SHALL 显示为可解释的证据状态，不得显示成全局主链路暂停；生成图审核仍 SHALL 显示候选是否阻塞发布。

#### Scenario: Measurement observation is visibly non-blocking

- **WHEN** 测量工具返回 warning、partial 或未解析标签
- **THEN** 运行时间线显示观察状态、问题、scope、候选和可选下一动作
- **AND** 用户可以看到主 Agent 仍可选择、舍弃、补充或组装

#### Scenario: Generated chart review is visibly blocking

- **WHEN** 生成图候选尚未通过审核
- **THEN** 候选卡片显示审核中、需要修复或未发布状态
- **AND** 用户不会把候选预览误认为已发布结果

#### Scenario: Selection details remain visible

- **WHEN** 用户展开 measurement observation
- **THEN** 客户端显示 selected refs、discarded refs、semantic mapping、warning 和 overlay
- **AND** 工具 observation 与主 Agent decision 保持分开

#### Scenario: Reconnected history shows the same state

- **WHEN** 客户端重新连接或读取历史运行
- **THEN** 它根据持久化事件恢复 observation、decision 和生成审核状态
- **AND** 不因测量 warning 或事件暂时缺失而显示为已完成或已发布

### Requirement: User can inspect measurement repair lifecycle

桌面客户端 SHALL 在 Agent 运行时间线中展示首次 scope、普通测量、证据选择、定向重测、修复被拒绝和修复预算耗尽。展示 SHALL 保留原始事件类型，并以简体中文说明当前状态；measurement observation SHALL 与生成图审核和最终发布状态区分开。

#### Scenario: Scoped observation is visible

- **WHEN** 活跃运行收到带有 observation scope 的测量事件
- **THEN** 客户端显示 panel、观察范围、候选 overlay 和 observation 状态
- **AND** 客户端不把范围应用显示为测量已经通过

#### Scenario: Evidence selection is visible

- **WHEN** 活跃运行收到 selected/discarded decision 事件
- **THEN** 客户端显示模型采用和舍弃的候选及其有限原因
- **AND** 用户可以区分模型决策与工具原始结果

#### Scenario: Repair exhaustion is visible

- **WHEN** 活跃运行收到 `measurement_repair_exhausted`
- **THEN** 客户端显示对应的预算耗尽状态和受限原因
- **AND** 不把该状态显示为 generated chart review failure 或已发布

### Requirement: Failed review remains inspectable

当生成图审核失败但仍可修复或已产生未发布候选时，客户端 SHALL 保留相关候选、诊断和状态；当最终不可恢复时，客户端 SHALL 显示失败原因和下一步行动。measurement observation 的失败或放弃也 SHALL 保留其 attempt lineage，但不得被显示为成功结果。

#### Scenario: Unpublished candidate remains visible

- **WHEN** 候选生成图审核失败并进入修复流程
- **THEN** 用户可以查看该候选及其未发布状态
- **AND** 最终发布区域只展示通过审核的 artifact

#### Scenario: Abandoned measurement remains inspectable

- **WHEN** 主 Agent 放弃某次测量 observation 并改用其他证据
- **THEN** 用户仍可以查看该 observation、放弃决策和 lineage
- **AND** 客户端不会把它渲染为已采用或已验证的数值来源
