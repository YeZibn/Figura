## ADDED Requirements

### Requirement: Measurement evidence is bound to generation scope

当测量为某个 generation candidate 提供证据时，measurement attempt SHALL 记录
candidate/attempt、attachment、panel、effective scope 和目标角色。工具返回的 evidence
reference SHALL 能够被装配和审核定位到同一来源范围。

#### Scenario: Same-panel evidence is accepted

- **WHEN** evidence-needed repair 请求左侧 panel 内的局部补测
- **THEN** 新 attempt 继承 candidate 的 attachment/panel scope
- **AND** accepted evidence 可以被 assemble_spec 引用

#### Scenario: Cross-panel measurement is not accepted as repair evidence

- **WHEN** measurement attempt 来自 candidate 未声明的 panel
- **THEN** 质量门禁返回 scope mismatch
- **AND** 该 evidence 不得作为 candidate 的 accepted measurement provenance

### Requirement: Observation scope and measurement target have distinct meanings

首次观察 SHALL 使用可选 `observation_scope` 描述当前调用要查看的区域和角色；已有
attempt 的补充测量 SHALL 使用 `measurement_target` 指向候选证据、局部区域或待确认引用。
系统 SHALL 在结果中返回实际应用的 effective scope，不得把两者混成自动重测指令。

#### Scenario: Initial scoped observation is not a remeasure

- **WHEN** 第一次测量调用带有 panel 内的 observation_scope
- **THEN** 系统创建新的 observation attempt
- **AND** 结果说明实际应用范围与发现的候选
- **AND** 不自动创建第二次测量

#### Scenario: Targeted repair starts only by Agent decision

- **WHEN** 主 Agent 根据 review 的 evidence_needed 决定补测一个候选引用
- **THEN** 调用使用 measurement_target 并关联父 attempt
- **AND** 只有该显式调用会产生新的测量 attempt

### Requirement: Evidence quality does not autonomously select semantic roles

测量质量门禁 SHALL 报告几何/数值质量、warning、候选引用和可用角色信息，但不得把
OCR/CV 的候选名称自动升级为 ChartSpec 的业务语义，也不得在发现 warning 时自动选择或
舍弃系列。主 Agent SHALL 记录 selected/discarded/abandoned 决策。

#### Scenario: Legend swatch is discarded explicitly

- **WHEN** 测量结果包含可能是 legend swatch 的候选
- **THEN** 结果将其标为候选并提供位置/角色线索
- **AND** 最终 discarded 决策记录由主 Agent 产生，而不是工具静默删除

