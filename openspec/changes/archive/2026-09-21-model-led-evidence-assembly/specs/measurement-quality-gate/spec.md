## MODIFIED Requirements

### Requirement: Measurement evidence has an explicit lifecycle

系统 SHALL 为每次源图测量提供可追踪的执行状态、质量结果和主 Agent 决策状态。执行状态至少区分完成与失败；质量结果 SHALL 保留 `provisional`、`partial`、`remeasure_required`、`unsupported` 和 `failed` 等适用诊断；主 Agent 决策 SHALL 独立记录 selected、discarded、abandoned 或 pending。质量 warning 或局部问题不得自动成为主流程的全局阻塞条件。

#### Scenario: Initial measurement remains observable evidence

- **WHEN** 柱状图、折线图、饼图或散点图传感器完成一次测量
- **THEN** 结果包含有界的执行状态、质量信息、证据引用、overlay 和 attempt 身份
- **AND** 结果在主 Agent 选择前保持为候选证据，不被系统自动声明为最终事实

#### Scenario: Warning does not force a workflow retry

- **WHEN** 测量发现基准线、坐标标定、系列关联、覆盖范围或几何支持存在问题
- **THEN** 结果保留对应 warning 和可选的补充范围建议
- **AND** 系统不得自动重测、阻塞其他观察工具或结束主链路

#### Scenario: Main Agent selects a candidate subset

- **WHEN** 主 Agent 根据原图、overlay、证据引用和质量信息选择或舍弃候选
- **THEN** 系统记录 selected、discarded 和未采用的 attempt 信息
- **AND** `assemble_spec` 只对被引用的证据执行来源、范围和结构校验

### Requirement: Measurement quality state is bounded and serializable

测量执行状态、质量检查、问题、观察范围、证据决策和 attempt lineage SHALL 使用有界、可序列化的结果表达，并 SHALL 能够在 Agent observation、run artifact index、checkpoint 和恢复流程之间保持一致。结果不得暴露本地路径、图像字节或 provider 原始 payload。

#### Scenario: Observation and recovery preserve the same quality state

- **WHEN** 测量结果通过工具观察返回后被写入运行记录并在后续恢复
- **THEN** 恢复后的执行状态、质量问题、证据选择和来源身份与原结果一致
- **AND** 恢复不会凭空新增 selected evidence 或改变模型尚未作出的决策

### Requirement: Measurement issues expose machine-readable repair targets

当测量质量审计发现需要补充证据的问题时，系统 SHALL 返回有界的 `observation_scope` 或 `measurement_target`。首次观察可以使用 `observation_scope` 表达当前 panel 内的 plot、legend、axis 等 include/exclude 范围；已有 attempt 的局部补充 SHALL 使用 `measurement_target` 表达候选引用或区域、受影响字段、模式和原因。两类范围都必须保持 attachment、panel 和源坐标边界，且不得由代码自动执行。

#### Scenario: Initial scope identifies a bounded plot

- **WHEN** 主 Agent 在第一次调用测量工具前能够从源图判断绘图区和图例位置
- **THEN** 主 Agent 可以提交相对于当前 panel 的归一化 include/exclude 范围
- **AND** 工具返回实际应用的源坐标、局部坐标和 overlay

#### Scenario: Repair target identifies a bounded candidate set

- **WHEN** 已有测量结果中的候选需要补充或排除
- **THEN** 主 Agent 可以提交同一 panel 的 refs、区域、受影响字段和原因
- **AND** 系统校验 target 归属，但不把 target 建议自动转换成工具调用

#### Scenario: Scope cannot cross panel boundaries

- **WHEN** 主 Agent 提交的 scope 或 target 不属于当前 measurement session 的 attachment 或 panel
- **THEN** 系统拒绝该范围并返回结构化来源不匹配问题
- **AND** 不创建新的 observation 或 repair attempt

### Requirement: Remeasurement attempts are bounded and re-audited

每次定向重测 SHALL 由主 Agent 在主链路中显式调用原图表测量工具发起，并 SHALL 在同一 run、attachment 和 panel 的 measurement session 中创建新的 attempt，记录父 attempt、target、证据引用和原因。重测结果 SHALL 重新经过质量审计；重复的等价请求 SHALL 幂等；超过预算时 SHALL 保留明确的耗尽状态。代码不得在质量审计或恢复过程中自动重复调用测量工具。

#### Scenario: A corrected local attempt supplies better candidates

- **WHEN** 当前 panel 的定向重测解决了父 attempt 的局部问题
- **THEN** 新 attempt 被记录为当前 observation，并可由主 Agent 选择其中的候选
- **AND** 旧 attempt 保持可追踪但不会自动覆盖新结果

#### Scenario: Repair budget is exhausted

- **WHEN** 同一 panel 的重测次数达到配置上限，或同一 target 被重复拒绝
- **THEN** session 返回明确的耗尽状态、问题、attempt lineage 和下一动作
- **AND** 系统不再自动创建 attempt，也不把未选择的候选交给组装器

#### Scenario: A failed target does not fall back to full-panel measurement

- **WHEN** 定向区域内没有足够证据或 mask 无法应用
- **THEN** 工具返回有界的 `focus_empty`、`focus_insufficient` 或等价局部结果
- **AND** 工具不得静默扩大到整个 panel 或源图再次搜索

### Requirement: Measurement review is a hard gate for the main chain

测量结果 SHALL 经过质量审计并保留主 Agent 的证据选择，但 measurement review 不得作为独占的共享执行门禁。进入 `assemble_spec` 时，系统 SHALL 对被选择的 evidence refs 执行 attachment、panel、attempt、范围、幂等和必要结构校验；warning、未解析系列标签或未被选择的误检候选不得阻塞其他观察和组装。

#### Scenario: Measurement observation does not block unrelated evidence

- **WHEN** 一次测量返回 warning、`partial` 或 `remeasure_required`
- **THEN** 主 Agent 仍可以调用 OCR、布局观察、其他测量或查看原图
- **AND** 系统不得创建独占 measurement review gate 来跳过同一工具批次中的其他工作

#### Scenario: Assembly validates selected evidence

- **WHEN** 主 Agent 提交当前 panel 的 evidence decision 和 ChartSpec
- **THEN** 系统校验 selected/discarded refs 属于当前 attachment、panel 和 attempt
- **AND** 未被选择的错误候选不会使被选择的有效候选整体失效

#### Scenario: Invalid selected evidence is rejected safely

- **WHEN** 主 Agent 选择不存在、越界、来源不匹配或缺少必要数值的 ref
- **THEN** `assemble_spec` 返回定位到具体 ref 的结构化错误
- **AND** 系统不发布或渲染依赖该非法 ref 的结果
