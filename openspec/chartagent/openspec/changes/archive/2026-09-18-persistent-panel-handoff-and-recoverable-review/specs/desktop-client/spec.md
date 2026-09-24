## ADDED Requirements

### Requirement: Execution view explains scoped reuse

桌面客户端 SHALL 在执行轨迹或结果上下文中显示当前使用的源附件、panel 名称或 panel ID、是否复用已有分区，以及分析结果是否来自局部范围。

#### Scenario: User inspects a reused panel run
- **WHEN** 后续 run 使用已有 panel handoff 完成测量
- **THEN** 用户可以看到该 run 复用了哪个面板
- **AND** 不需要通过工具原始日志推断是否重新拆解

### Requirement: Failed review remains inspectable

当审核失败但仍可修复或已产生未发布候选时，客户端 SHALL 保留相关候选、诊断和状态；当最终不可恢复时，客户端 SHALL 显示失败原因和下一步行动，不得把失败候选显示为成功结果。

#### Scenario: Unpublished candidate remains visible
- **WHEN** 候选审核失败并进入修复流程
- **THEN** 用户可以查看该候选及其未发布状态
- **AND** 最终发布区域只展示通过审核的 artifact
