## ADDED Requirements

### Requirement: Review performs source binding preflight

对 source-linked 候选执行 VLM 审核前，系统 SHALL 先确认源附件仍属于当前 session、可访问且内容哈希匹配。源附件缺失时 SHALL 返回 source binding failure，而不得把它伪装成图表语义审核失败。

#### Scenario: Active source is recovered before review
- **WHEN** 当前 run 没有新附件但 session 有有效 active source
- **THEN** 审核使用恢复后的源附件执行
- **AND** 不返回 source_evidence_unavailable

### Requirement: Review failures provide structured recovery diagnostics

VLM 审核拒绝候选时 SHALL 返回状态、问题代码、问题说明、严重级别、受影响的 ChartSpec 路径和建议动作。系统 SHALL 区分可修复语义问题、源绑定问题、运行时重试问题和不可恢复的 retry exhausted。

#### Scenario: Review reports a semantic mismatch
- **WHEN** 候选图与源图在数据、方向、标签或布局上不一致
- **THEN** 审核结果包含可供主 Agent 修正的结构化 diagnostics
- **AND** 审核阶段不调用 OCR、CV 或图表测量工具

### Requirement: Review retries are bounded and candidate-aware

系统 SHALL 对审核调用和候选修复设置有限次数。语义失败需要新候选才能重审；相同候选不得无限重复审核，且审核通过前不得发布。

#### Scenario: Review recovery reaches its limit
- **WHEN** 候选修复或审核重试达到上限
- **THEN** 系统保留候选和诊断并返回非发布的 retry_exhausted 状态
