## MODIFIED Requirements

### Requirement: Review repair kind controls the next allowed action

审核结果 SHALL 返回有界 `repair_kind`、issues 和适用 target，作为主 Agent理解失败原因的结构化提示。代码拥有的门禁 SHALL 继续阻止失败候选发布并拒绝未授权、失效或与 generation context 不兼容的来源引用，但 SHALL NOT 根据 repair kind 将后续动作限定为唯一工具类别或固定阶段。改变任务 mode、source scope 或 coverage 时 SHALL 创建新的 candidate attempt。

#### Scenario: Evidence-needed repair remains source-safe

- **WHEN** 审核指出当前 panel 的一个系列值缺少证据
- **THEN** 主 Agent可以选择当前授权范围内的测量、OCR、视觉复查或 ChartSpec 修正
- **AND** 对其他 panel 的引用必须经过新的合法 source binding，而不能静默扩大原候选范围
- **AND** 任何新候选都必须重新审核

#### Scenario: Repair kind does not reject an alternative legal action

- **WHEN** 审核返回 `spec_only`，但主 Agent发现问题实际来自当前 scope 内的来源证据
- **THEN** 系统允许主 Agent调用该 scope 内已授权的观察工具
- **AND** repair kind 仍作为诊断保留而不成为工具白名单

#### Scenario: Terminal review failure does not silently end as success

- **WHEN** 审核返回 `terminal` 或修复次数耗尽
- **THEN** Run 返回明确的未发布状态和可定位诊断
- **AND** 不得把候选图作为已验证结果交给用户
