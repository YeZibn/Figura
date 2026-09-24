## ADDED Requirements

### Requirement: Lifecycle events expose bounded process correlation

执行事件 SHALL 在可确定时携带有界的 process、turn、operation 或其他现有运行关联信息，并继续保留 run sequence 作为事实顺序。无法确定关联时，事件仍 SHALL 合法持久化并明确为未关联，不得伪造 candidate、unit 或 parent。

#### Scenario: Model and operation events share a process context

- **WHEN** 一个模型 turn 发起一个或多个工具 operation
- **THEN** 相关 lifecycle events 可以通过有界上下文归入同一过程展示
- **AND** 原始 sequence、call identity 和工具详情仍可单独展开

#### Scenario: Legacy events remain replayable

- **WHEN** 历史事件没有新增的过程关联字段
- **THEN** 系统按兼容规则持久化和投影这些事件
- **AND** 历史读取、实时追加和评测读取不会因为缺失字段而丢失事件或生成虚假 lineage

### Requirement: Execution failures carry deterministic classification

执行 trace SHALL 为失败事件保存有界的 failure category、stable code、provider status（如适用）、safe message、retryability 和第一失败引用。确定性拒绝与结果未知的失败 SHALL 使用不同的分类，不得都降级为 operation outcome uncertain。

#### Scenario: Deterministic provider error is persisted

- **WHEN** provider 明确返回不可接受当前请求的状态
- **THEN** trace 保存 provider failure 分类及其可展示原因
- **AND** trace 不生成表示远端是否已接受请求的 uncertain 结论

#### Scenario: Unknown remote outcome remains explicit

- **WHEN** 请求超时、连接中断或系统无法判断远端是否已接受操作
- **THEN** trace 标记 operation outcome uncertain 并保留恢复阻塞原因
- **AND** 用户可以看到这是结果未知，而不是已确认的 provider 拒绝
