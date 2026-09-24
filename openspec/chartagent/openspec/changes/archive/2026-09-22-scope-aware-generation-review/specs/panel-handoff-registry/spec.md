## ADDED Requirements

### Requirement: Panel handoff exposes an authorized review crop

有效 PanelHandoff SHALL 为 source-linked review 和同范围补测提供稳定的 panel identity、
attachment hash、源图 bbox/坐标变换和可授权裁剪引用。调用方无需接触本地路径或原始字节。

#### Scenario: Review resolves the left panel crop

- **WHEN** candidate context 引用一个有效 panel ID
- **THEN** review path 可以解析该 panel 的来源裁剪与坐标信息
- **AND** 传给 VLM 的来源图只覆盖授权范围

### Requirement: Stale or ambiguous handoffs fail closed

当 handoff 与当前 attachment hash、session 或 panel revision 不匹配时，系统 SHALL 返回
stale/ambiguous 状态并要求重新绑定或重新拆解；不得为满足审核而把整张附件作为隐式替代。

#### Scenario: Attachment change invalidates a candidate scope

- **WHEN** 候选绑定的附件内容发生变化
- **THEN** review 和 evidence repair 均被阻止
- **AND** 返回可恢复的 source_rebind 路径

