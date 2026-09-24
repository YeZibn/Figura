## ADDED Requirements

### Requirement: Generated candidates retain source and panel attribution

由源图面板生成的 ChartSpec、候选图和发布 artifact SHALL 保留经过校验的 attachment ID、panel ID、PanelHandoff revision 和候选 lineage。自由文本 source 描述不得单独充当源附件证据。

#### Scenario: Candidate is linked to a panel source
- **WHEN** ChartSpec 来自某个 dashboard panel
- **THEN** 候选记录包含该 panel 的结构化归因
- **AND** 审核可以使用同一个已校验的源附件

### Requirement: Failed candidates cannot bypass the review gate

审核未通过的候选 SHALL 保持未发布。修正必须生成新的候选记录；只有通过审核的候选才能进入 published 状态。

#### Scenario: Corrected candidate supersedes a rejected candidate
- **WHEN** 主 Agent 根据审核诊断生成新的 ChartSpec
- **THEN** 新候选关联旧候选并重新经过审核
- **AND** 旧候选仍保持 rejected/unpublished
