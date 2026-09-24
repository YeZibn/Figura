## ADDED Requirements

### Requirement: Decomposition is reuse-first and idempotent

当当前 session 的附件已有有效 PanelHandoff 时，dashboard 拆解入口 SHALL 优先返回已有面板目录，不得因为新 run 或模型历史不完整而重复拆解。只有不存在有效匹配、源图已变化、旧面板失效或用户明确要求重新拆解时，才允许生成新的分区结果。

#### Scenario: Follow-up request reuses existing panels
- **WHEN** 第一次 run 已为附件建立面板，后续 run 请求分析其中一个面板
- **THEN** 系统返回已有 panel ID 和范围
- **AND** 该 run 不重复调用完整 dashboard 拆解

#### Scenario: Explicit re-decomposition creates a revision
- **WHEN** 用户明确要求重新识别区域或现有面板已被标记 stale
- **THEN** 系统允许重新拆解
- **AND** 新结果与旧面板保留可追踪的 revision 或 supersedes 关系
