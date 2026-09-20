## ADDED Requirements

### Requirement: Desktop client presents a unified blocking review state

桌面客户端 SHALL 使用统一的审核展示模型呈现测量审核和生成图审核，并明确显示审核是否阻塞主链路、当前 attempt、问题、证据、修复动作和剩余预算。审核领域的专属详情可以展开查看，但不得隐藏门禁状态。

#### Scenario: Measurement review is visibly blocking
- **WHEN** 测量审核处于 reviewing 或 repair_required
- **THEN** 运行时间线显示“主链路已暂停”及同一 panel 的下一步动作
- **AND** 用户可以看到测量问题和对应的测量证据引用

#### Scenario: Generated chart review is visibly blocking
- **WHEN** 生成图候选尚未通过审核
- **THEN** 候选卡片显示审核中、需要修复或未发布状态
- **AND** 用户不会把候选预览误认为已发布结果

#### Scenario: Shared review card keeps domain details
- **WHEN** 用户展开任一种审核记录
- **THEN** 客户端使用一致的状态、时间线和问题布局
- **AND** 测量审核显示 target/attempt，生成图审核显示 candidate/ChartSpec/VLM checks

#### Scenario: Reconnected history shows the same gate
- **WHEN** 客户端重新连接或读取历史运行
- **THEN** 它根据持久化事件和 run projection 恢复审核门禁状态
- **AND** 不因事件暂时缺失而显示为已完成或已发布
