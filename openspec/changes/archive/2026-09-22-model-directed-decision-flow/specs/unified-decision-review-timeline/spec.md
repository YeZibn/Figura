## MODIFIED Requirements

### Requirement: One candidate attempt has one visible review cycle

系统 SHALL 为每个 candidate attempt 建立一个 review cycle。内部 deterministic audit、semantic VLM review、状态更新和修复分类 SHALL 保持可追踪，但默认用户时间线 SHALL 只显示一次“开始审核”和一个最终审核结果；失败结果 SHALL 展示简体中文原因，内部 subcheck 不作为独立可见步骤。

#### Scenario: Candidate review is summarized once

- **WHEN** 候选执行确定性检查和语义 VLM 审核
- **THEN** 时间线显示一个审核周期
- **AND** 用户看到审核开始、最终通过或失败结果及失败原因
- **AND** 不显示多个英文 subcheck

#### Scenario: Collection children share a review parent

- **WHEN** 一次 render 返回同一 collection 的多个 child candidates
- **THEN** 时间线显示一个 collection review summary 和必要的失败 child 摘要
- **AND** child 数量不会形成多个无关顶层审核

### Requirement: Timeline preserves raw evidence and decision lineage

系统 SHALL 在内部 execution trace 和评测详情中保留工具调用、工具结果、图片、evidence refs、attempt、审核问题、修复结果和历史 decision 事件。默认用户时间线 SHALL 聚焦工具过程、生成候选和审核结果，不显示 measurement decision、focus transition、model turn 或 operation save 等控制事件；隐藏不得删除原始 sequence、call_id、lineage 或安全资源引用。

#### Scenario: Evidence use remains auditable without a visible decision card

- **WHEN** Agent使用一次 measurement observation 中的部分 refs 完成装配
- **THEN** 内部 trace 可以关联 observation、实际使用 refs 和 assemble
- **AND** 默认时间线不创建“测量决策”步骤或待处理卡片

#### Scenario: Detail is unavailable

- **WHEN** 原始工具结果因历史保留、大小或权限原因不可读取
- **THEN** 时间线保留工具或审核步骤并显示 detail unavailable/truncated 原因
- **AND** 不伪造内容或成功状态

## ADDED Requirements

### Requirement: Runtime facts do not become visible decision gates

内部运行状态 MAY 记录 scope、issues、repair hint、预算和下一次实际动作，但默认前端 SHALL NOT 将这些状态投影为要求用户或模型关闭的 measurement decision unit。只有工具执行、候选生成、最终审核和终态错误形成普通用户可见步骤。

#### Scenario: Measurement warning remains inside the tool result

- **WHEN** 测量返回 warning 或局部补充建议
- **THEN** 用户可在测量工具结果中查看该信息
- **AND** 时间线不额外显示 measurement decision pending

#### Scenario: Review failure remains actionable and concise

- **WHEN** 生成审核失败
- **THEN** 时间线显示审核失败和原因
- **AND** 模型后续选择的实际工具调用按正常工具步骤展示

## REMOVED Requirements

### Requirement: Each decision unit exposes a closed next-action contract

**Reason**: 将 allowed/blocked next action 同时暴露给模型和前端，会把内部事实升级成业务门禁，并制造待处理 decision 噪声。

**Migration**: 内部保留 scope、状态和 lineage；硬限制由授权、结构和发布边界执行，前端只显示实际动作及结果。
