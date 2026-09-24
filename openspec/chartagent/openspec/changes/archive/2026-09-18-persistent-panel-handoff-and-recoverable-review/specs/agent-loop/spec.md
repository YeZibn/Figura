## ADDED Requirements

### Requirement: Recoverable review failures return to the main Agent

当生成候选的审核失败且仍有重试预算时，Agent loop SHALL 收到结构化审核诊断并继续运行。对于语义或渲染问题，主 Agent SHALL 能够提交修正后的 ChartSpec 并生成新候选；对于源绑定问题，流程 SHALL 优先修复源上下文。

#### Scenario: Semantic failure triggers a corrected candidate
- **WHEN** VLM review 拒绝候选并返回具体语义问题
- **THEN** 主 Agent 收到该问题而不是立即得到最终失败答复
- **AND** 主 Agent 可以 assemble 新 ChartSpec、render 新候选并进入下一次审核

### Requirement: Exhausted review recovery terminates explicitly

当源绑定或候选修复达到上限时，Agent loop SHALL 以明确的非发布状态结束，保留失败原因和候选 lineage，不得绕过审核门禁发布最后一个失败候选。

#### Scenario: Retry budget is exhausted
- **WHEN** 所有允许的审核修复或重试次数均已使用
- **THEN** run 状态为 retry_exhausted 或等价的非发布失败状态
- **AND** 用户可以看到下一步是重新绑定源图还是调整规格
