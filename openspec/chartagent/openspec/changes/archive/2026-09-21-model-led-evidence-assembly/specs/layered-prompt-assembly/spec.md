## MODIFIED Requirements

### Requirement: Main Agent context uses four explicit layers

主 Agent 的模型上下文 SHALL 明确区分四类信息：静态职责、动态工具、过程产物和 Run/Turn 动态状态。过程产物层 SHALL 包含 observation scope、候选 refs、overlay、质量 warning 和 selected/discarded 决策；Run/Turn 层 SHALL 表示当前可执行动作，而不得把普通测量 warning 自动写成强制 repair 状态。

#### Scenario: Normal chart turn exposes the four layers

- **WHEN** 主 Agent 为一次图表分析请求准备模型调用
- **THEN** 上下文能够区分长期行为规则、当前可用工具、已产生的图表证据和当前运行状态
- **AND** 当前 attachment、panel、scope、候选图和待办动作不会被误认为静态职责

#### Scenario: Empty process layer is explicit

- **WHEN** 当前 run 尚未产生 panel、观测结果或候选图
- **THEN** 过程产物层明确表示没有可用产物
- **AND** Agent 不得引用其他 run 的产物作为当前 run 的事实

### Requirement: Process artifacts remain structured and attributable

过程产物层 SHALL 能够表达源附件、dashboard panel、局部 crop、初始 observation scope、OCR 或几何观测、layout 结果、evidence selection、ChartSpec、生成候选和审核结果。每个产物 SHALL 保留稳定 ID、来源引用、范围或 lineage、状态、confidence 和 warnings 等适用元数据；结构化 JSON 和模型可见图片 SHALL 保持可关联，不得只保留不可验证的自由文本摘要。

#### Scenario: Observation result becomes reusable process context

- **WHEN** dashboard 拆解或图表传感器产生 panel 和局部 observation
- **THEN** 过程产物层记录 panel、scope、attempt、crop/resource、refs 和状态
- **AND** 后续工具和模型可以通过同一 panel/attempt 关联局部结果

#### Scenario: Selection remains distinct from observation

- **WHEN** 主 Agent 选择或舍弃测量候选
- **THEN** 过程产物层单独记录 selected、discarded、semantic mapping 和 decision 来源
- **AND** 工具原始 observation 不被覆盖或改写为模型结论

### Requirement: Run and Turn state is dynamic control context

Run/Turn 动态状态层 SHALL 表示当前用户请求、active source、selected panel、当前 scope、最近工具动作、可选下一动作、生成图 review gate、恢复状态、资源预算和中断状态等代码拥有的事实。普通 measurement warning SHALL 以诊断和可选动作出现，不得自动将主链路置于独占 reviewing 状态。

#### Scenario: Scoped observation exposes model choices

- **WHEN** 当前 run 已选择一个 panel 并完成局部测量
- **THEN** 动态状态明确当前 panel、scope、候选 observation、可选动作和预算
- **AND** Agent 可以选择、舍弃、补充或直接组装

#### Scenario: Generated review remains a blocking state

- **WHEN** 生成图候选尚未通过审核
- **THEN** 动态状态明确禁止发布以及可执行的修复动作
- **AND** 该生成审核状态与测量 warning 分开表达
