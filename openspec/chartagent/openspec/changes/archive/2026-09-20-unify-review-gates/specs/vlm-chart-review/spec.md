## ADDED Requirements

### Requirement: Generated chart review is a hard gate for publication and completion

生成图候选的结构检查和适用的 VLM 审核 SHALL 共同构成发布前的主链路门禁。候选处于审核中、需要修复或审核失败时，不得发布、不得作为成功生成结果返回，也不得由主 Agent 最终文本覆盖。

#### Scenario: Candidate remains blocked while review is pending
- **WHEN** 候选图已经渲染但审核结果尚未应用
- **THEN** 候选保持不可发布状态
- **AND** 主链路不得进入发布或成功终结阶段

#### Scenario: Failed candidate enters a controlled repair loop
- **WHEN** 审核返回可修复的语义、布局或映射问题
- **THEN** 系统只向主 Agent 提供有界诊断和修正 ChartSpec 的动作
- **AND** 修正后必须生成新的 candidate 并重新审核，旧 candidate 保持不可发布

#### Scenario: Passed candidate releases publication
- **WHEN** 候选通过全部必需审核，或策略允许带 warning 的决定
- **THEN** 系统原子地释放发布门禁
- **AND** 生成结果携带准确的审核和 warning 状态

#### Scenario: Review failure never becomes a successful run
- **WHEN** VLM 输出非法、审核超时、源证据不可用或修复次数耗尽
- **THEN** 候选进入非发布终态并保留失败诊断
- **AND** run 不能以已发布或审核通过的成功结论结束
