## REMOVED Requirements

### Requirement: Measurement quality state is bounded and serializable

**Reason**: 旧状态或快照控制契约已由提交事实和单一验证链路替代。
**Migration**: 使用 durable-execution-record 或 generated-chart-verification 的对应要求。

## ADDED Requirements

### Requirement: Current measurement facts derive from committed attempts

每次测量 SHALL 保存有界、可归属的 attempt、attachment/panel、effective scope、质量、measurement/evidence refs 和系列元数据。当前测量结果 SHALL 从已提交 attempt 推导；checkpoint 只保留恢复所需的安全引用，不复制完整 measurement session。质量状态仅描述观察，不驱动自动采用、舍弃或重测。

#### Scenario: Resume after a committed measurement
- **WHEN** 测量结果已经提交而下一次模型调用前中断
- **THEN** 显式 resume 恢复相同来源范围和 refs
- **AND** 不重复测量或建立 measurement decision gate
