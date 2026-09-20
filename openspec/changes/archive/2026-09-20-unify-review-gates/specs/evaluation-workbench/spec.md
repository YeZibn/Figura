## ADDED Requirements

### Requirement: Evaluation traces reuse the unified review presentation

评测工作区 SHALL 以只读方式复用普通运行的审核记录、门禁状态和证据引用，完整展示测量审核与生成图审核的开始、阻塞、修复、重试和最终结果，不得把中间审核过程压缩成单一成功或失败标签。

#### Scenario: Evaluation shows both review domains
- **WHEN** 一个评测同时包含测量审核和生成图审核
- **THEN** case 时间线分别显示两个审核 subject，同时使用统一的状态和阻塞语义
- **AND** 用户可以展开查看各自的问题、证据和下一步动作

#### Scenario: Evaluation preserves a blocked outcome
- **WHEN** 审核失败、修复耗尽或候选未发布
- **THEN** 评测记录明确显示阻塞原因和未完成阶段
- **AND** 报告不得把该 case 标记为完整成功

#### Scenario: Evaluation remains read-only
- **WHEN** 用户在评测工作区查看审核记录
- **THEN** 客户端只读取已保存的审核事件和资源
- **AND** 展开详情、刷新或预览不得重新触发测量、审核或发布动作
