## MODIFIED Requirements

### Requirement: Process artifacts remain structured and attributable

过程产物层 SHALL 能够表达源附件、dashboard panel、局部 crop、measurement tool 的 observation scope、OCR 或几何观测、layout 结果、候选 measurement evidence、ChartSpec、生成候选和审核结果。每个产物 SHALL 保留稳定 ID、来源引用、范围或必要 lineage、质量/状态及适用的 confidence 和 warnings；模型对候选是否采用不作为独立过程产物保存。结构化 JSON 和模型可见图片 SHALL 保持可关联，不得只保留不可验证的自由文本摘要。

#### Scenario: Observation result becomes reusable process context

- **WHEN** dashboard 拆解或图表传感器产生 panel 和局部 observation
- **THEN** 过程产物层记录 panel、scope、attempt、crop/resource、refs 和质量状态
- **AND** 后续工具和模型可以通过同一 panel/attempt 关联局部结果

#### Scenario: Evidence use is represented by the actual assembly input

- **WHEN** 主 Agent 在 ChartSpec assembly 中引用部分测量候选
- **THEN** 过程产物层保留 measurement observation 和实际 assembly refs
- **AND** 不单独记录 selected、discarded 或 semantic-decision 生命周期

### Requirement: Run and Turn state is dynamic control context

Run/Turn 动态状态层 SHALL 表示当前用户请求、active source、selected panel、当前 measurement session/current attempt、最近工具动作、可选下一动作、生成图 review gate、恢复状态、资源预算和中断状态等代码拥有的事实。普通 measurement warning SHALL 作为工具结果中的诊断和可选局部线索，不得自动将主链路置于独占 reviewing 或待决状态。

#### Scenario: Scoped observation exposes candidate facts and model agency

- **WHEN** 当前 run 已在一个 panel 中完成局部测量
- **THEN** 动态状态提供当前 panel、attempt、实际 scope、候选 refs、质量信息和可用工具
- **AND** Agent 可以在 assembly 中引用证据、忽略未用候选、显式再次测量或直接使用其他证据，无需提交 decision object

#### Scenario: Generated review remains a blocking state

- **WHEN** 生成图候选尚未通过审核
- **THEN** 动态状态明确禁止发布以及可执行的修复动作
- **AND** 该生成审核状态与非阻塞的测量诊断分开表达

### Requirement: Main Agent receives a compact current decision context

每轮主 Agent prompt SHALL 在现有四层体系中提供有界的当前状态摘要，至少表达当前 scope、measurement session/current attempt、候选 evidence refs、issues、publication status、恢复状态和剩余预算。摘要 SHALL 引用代码拥有的事实，不得包含普通业务动作的 allowed/blocked action contract；仅不可绕过的授权、结构和发布约束可以标记为硬限制。

#### Scenario: Scope and result are presented as one measurement observation

- **WHEN** 当前 attempt 包含一次有范围的测量请求
- **THEN** prompt 同时呈现请求范围、实际应用范围和该调用的 observation 结果
- **AND** 不要求模型继续一个分离的 focus/observation transition 或提交 abandonment 状态

#### Scenario: Agent sees actual evidence lineage

- **WHEN** 当前 attempt 有候选 refs 或部分 refs 已在 assembly 输入中出现
- **THEN** prompt 显示 attempt、scope、候选 refs 和已使用 provenance
- **AND** 不呈现 selected/discarded lifecycle，也不要求 Agent 维护另一套状态
