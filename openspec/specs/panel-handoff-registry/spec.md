# panel-handoff-registry Specification

## Purpose

为复杂图片建立跨运行、可验证且可追溯的面板交接记录，使一次拆解产生的局部图表区域能够在后续请求中安全复用。

## Requirements

### Requirement: Session-scoped panel handoffs are durable

系统 SHALL 为每个有效面板保存 session-scoped 的 PanelHandoff。记录至少 SHALL 关联 attachment ID、attachment 内容哈希、稳定 panel ID、显示名称、图表类型或角色、源图 bbox、分析范围、局部到源图的坐标变换、版本、置信度和状态，并 SHALL 不暴露本地文件路径或原始图像字节。

#### Scenario: Decomposition creates a reusable handoff

- **WHEN** 一个 session 中的授权附件完成一次有效 dashboard 分区
- **THEN** 每个 accepted panel 都有可持久化的稳定 panel ID 和源图坐标
- **AND** 后续 run 可以通过该 panel ID 找到同一面板的范围和来源

### Requirement: Panel reuse is validated before use

系统 SHALL 只在 session、attachment 内容哈希和面板状态均匹配时复用 PanelHandoff。附件缺失、内容变化、面板失效或无法安全匹配时 SHALL 标记旧记录不可复用，并 SHALL 返回可恢复的重新拆解或重新绑定状态。

#### Scenario: Changed attachment invalidates a handoff

- **WHEN** 后续 run 使用的附件内容哈希与 PanelHandoff 不一致
- **THEN** 系统不得静默使用旧 panel ID
- **AND** 系统返回 stale 状态并允许创建新的面板版本

### Requirement: Panel identity is stable across equivalent runs

对于同一附件中语义和几何范围等价的面板，系统 SHALL 保留原 panel ID 或创建明确关联的 revision，不得因为 `panel_1` 等运行内序号变化而让调用方无法引用原面板。

#### Scenario: Equivalent proposal reuses identity

- **WHEN** 新一次拆解提出与现有面板相同语义且空间重叠达到配置阈值的区域
- **THEN** 系统返回原 panel ID 或其新 revision 的明确关联
- **AND** 系统不得创建无法解释的重复面板
