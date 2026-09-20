# review-gates Specification

## Purpose

为测量审核和生成图审核提供统一、可追踪且不可绕过的主链路门禁，使不同审核领域可以共享状态、证据、修复和恢复契约，同时保留各自的专业判断逻辑。

## Requirements

### Requirement: Review subjects have a shared bounded lifecycle

系统 SHALL 为每个需要审核的测量尝试或生成图候选创建可追踪的审核记录。审核记录 SHALL 包含 subject 类型和身份、来源引用、attempt/lineage、当前状态、问题、修复动作、重试预算和时间信息，并 SHALL 使用有界、可序列化的字段。

#### Scenario: Measurement and chart subjects share the envelope
- **WHEN** 系统提交一次测量审核或生成图审核
- **THEN** 两者都返回具有审核身份、subject 引用、状态、问题和下一步动作的审核记录
- **AND** 专业检查结果仍保留在各自领域的结构化详情中

#### Scenario: Review evidence remains attributable
- **WHEN** 审核结果写入运行事件、checkpoint 或评测记录
- **THEN** 结果保留 run、attachment/panel 或 candidate/ChartSpec 的安全引用
- **AND** 不暴露本地路径、图像字节、凭证或 provider 原始 payload

### Requirement: Review gates block downstream execution

系统 SHALL 在审核状态为 `reviewing`、`repair_required`、`failed` 或 `exhausted` 时阻止主链路越过当前审核阶段。只有 `passed` 或策略允许的 `passed_with_warning` 才能释放后续阶段；审核门禁不得由模型最终文本、普通工具调用或客户端状态推断绕过。

#### Scenario: Pending review blocks the next stage
- **WHEN** 测量审核或生成图审核尚未产生可接受决定
- **THEN** 系统不得执行依赖该证据的 assemble、render、publish 或成功终结动作
- **AND** 运行记录明确显示主链路处于审核门禁中

#### Scenario: Warning is an explicit release
- **WHEN** 审核产生策略允许的 warning 决定
- **THEN** 系统记录 warning 并释放后续阶段
- **AND** 后续结果明确携带带警告的审核状态，而不是显示为未经审核的成功

### Requirement: Review repair is a controlled sub-loop

当审核返回 `repair_required` 且仍有预算时，系统 SHALL 只允许执行审核记录指定的修复动作；修复必须创建新的可归因 attempt 或 candidate，并 SHALL 在重新释放主链路前再次审核。修复动作不得被解释为普通流程继续。

#### Scenario: Unrelated work is rejected while repair is required
- **WHEN** 当前审核要求定向重测或修正 ChartSpec
- **THEN** 系统拒绝或延迟不属于该修复动作的后续工具、assemble、render 或 publish 操作
- **AND** 修复上下文包含受影响区域、字段和父审核引用

#### Scenario: Repair creates a new review attempt
- **WHEN** 指定修复动作完成
- **THEN** 系统创建新的 attempt/candidate lineage 并提交新的审核记录
- **AND** 父失败结果保持不可发布且可追踪

### Requirement: Review failures close the gate without implicit bypass

审核失败、超时、证据不可用、非法审核结果或重试耗尽 SHALL 保持门禁关闭。系统 SHALL 返回有界的失败分类和恢复信息；在没有新的有效审核通过前，不得发布候选、组装未经接受的证据或生成声称成功的最终结果。

#### Scenario: Retry budget is exhausted
- **WHEN** 审核或修复达到配置上限
- **THEN** 当前审核进入 `exhausted` 或等价终态
- **AND** 运行结果为非成功或非发布状态，并保留最后诊断

#### Scenario: Review result is stale or mismatched
- **WHEN** 审核结果引用了错误的 subject、attempt、candidate 或 ChartSpec digest
- **THEN** 系统拒绝应用该结果
- **AND** 任何其他审核对象的门禁或发布状态都不发生变化

### Requirement: Review transitions are durable and idempotent

审核开始、决定、修复和释放事件 SHALL 在允许下一阶段前持久化。重复提交同一 subject 和同一审核意图 SHALL 返回已有结果，不得重复执行审核或发布；恢复运行不得跳过未完成的审核。

#### Scenario: Duplicate review submission is replayed
- **WHEN** 同一运行重复提交相同 subject、attempt 和审核意图
- **THEN** 系统返回原审核记录或其当前状态
- **AND** 不创建重复审核 attempt，不重复发布候选

#### Scenario: Recovery resumes at the gate
- **WHEN** 运行在审核或修复边界中断后恢复
- **THEN** 系统从持久化的审核门禁和下一步动作继续
- **AND** 不把未完成审核当作已通过
