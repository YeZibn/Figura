## REMOVED Requirements

### Requirement: Decision units have a canonical bounded identity

**Reason**: 旧候选/审核/发布生命周期和门禁展示契约由提交事实投影取代。
**Migration**: 使用本 capability 的新增要求以及 generated-chart-verification 的结果语义。

### Requirement: Timeline projection is derived from canonical execution events

**Reason**: 旧候选/审核/发布生命周期和门禁展示契约由提交事实投影取代。
**Migration**: 使用本 capability 的新增要求以及 generated-chart-verification 的结果语义。

### Requirement: One candidate attempt has one visible review cycle

**Reason**: 旧候选/审核/发布生命周期和门禁展示契约由提交事实投影取代。
**Migration**: 使用本 capability 的新增要求以及 generated-chart-verification 的结果语义。

### Requirement: Timeline preserves raw evidence and decision lineage

**Reason**: 旧候选/审核/发布生命周期和门禁展示契约由提交事实投影取代。
**Migration**: 使用本 capability 的新增要求以及 generated-chart-verification 的结果语义。

### Requirement: Timeline transitions are idempotent and lineage-safe

**Reason**: 旧候选/审核/发布生命周期和门禁展示契约由提交事实投影取代。
**Migration**: 使用本 capability 的新增要求以及 generated-chart-verification 的结果语义。

## ADDED Requirements

### Requirement: Timeline groups committed execution facts without owning state

用户时间线 SHALL 从 Run 的工具、验证、artifact 和终态事件确定性投影；它不得控制 checkpoint、审核或发布。相同 run 与 transition identity 的重放 SHALL 去重，旧候选/审核/发布状态字段不得形成新的顶层生命周期单元。工具结果与原始有界证据仍可展开。

#### Scenario: Duplicate verification event is replayed
- **WHEN** 同一个验证完成事件通过 SSE 与历史补偿重复到达
- **THEN** 用户只看到一次验证结果
- **AND** 任何发布动作不会由前端投影触发

### Requirement: Collection outcomes remain individually inspectable

同一次生成的 collection SHALL 通过稳定 parent、figure、child 和尝试身份分组；每个子图的验证结论、来源范围、issues、预览及正式产物 SHALL 独立保留。失败原因 SHALL 可定位而不能被父级汇总覆盖。

#### Scenario: One child fails and one passes
- **WHEN** collection 的两个子图有不同验证结果
- **THEN** 父级显示集合流程，展开后显示各子图真实结果
- **AND** 失败子图不会显示兄弟图的正式 artifact
