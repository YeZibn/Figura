## MODIFIED Requirements

### Requirement: Gate failures provide a bounded recovery action

证据引用或组装校验失败 SHALL 返回有界的原因、位置、当前来源范围和可选修复提示。修复提示可以包括补充观察、局部测量、忽略候选、改用视觉证据或停止，但 SHALL 作为建议而非代码拥有的唯一下一动作；系统不得自动执行修复，也不得要求模型猜测缺失数据。

#### Scenario: Evidence issue suggests targeted observation

- **WHEN** 当前候选的基准线、文字、系列关系或局部几何仍不确定
- **THEN** 结果指出相关 ref/字段和可用 scope/target 建议
- **AND** 主 Agent可以自主选择该建议或其他同范围合法动作

#### Scenario: Unrecoverable evidence remains non-final

- **WHEN** 主 Agent不再补充证据，或补充后仍不能解决关键字段
- **THEN** 融合结果保留未解析字段、问题和 attempt lineage
- **AND** 系统不得用未确认候选自动替代模型判断

### Requirement: Direct visual assembly remains compatible

对于没有采用测量证据、且模型直接基于清晰源图视觉理解组装合法 ChartSpec 的请求，系统 SHALL 保持直接装配路径。当前 run 曾产生但未被引用的 observation SHALL 留在内部历史中，不得要求模型提交 abandoned decision；该路径仍不得绕过 ChartSpec 结构校验和生成审核。

#### Scenario: No measurement evidence is required

- **WHEN** 模型没有引用测量工具结果而提交合法 ChartSpec 或 collection
- **THEN** 系统完成结构装配
- **AND** 不要求伪造 measurement attempt 或 decision

#### Scenario: Unused observation remains auditable

- **WHEN** 模型改用视觉或其他合法证据而未引用已有 measurement observation
- **THEN** observation 继续保留在内部历史
- **AND** 不阻塞当前装配

## ADDED Requirements

### Requirement: Measurement evidence is validated when referenced

当 ChartSpec 使用图表测量结果时，证据融合流程 SHALL 只验证请求通过 `measurement_ref + evidence_refs` 实际引用的 session、attachment、panel、attempt 和 refs。有效引用 SHALL 形成 ChartSpec provenance；未引用候选、普通 warning 和未解析标签不得成为组装门禁，也不得被静默写入最终数据。

#### Scenario: Referenced valid evidence permits assembly

- **WHEN** 模型引用当前来源和 attempt 中的合法 refs
- **THEN** 系统校验这些 refs 并保存来源摘要和适用 warning
- **AND** 组装不要求独立 evidence decision 状态

#### Scenario: Unreferenced false candidates do not block assembly

- **WHEN** measurement observation 同时包含有效候选和图例色块等误检
- **THEN** 组装器只处理请求中实际引用的候选
- **AND** 不要求重新测量或显式舍弃其余候选

#### Scenario: Invalid referenced evidence blocks only dependent assembly

- **WHEN** 被引用 ref 不存在、跨来源或缺少必要结构
- **THEN** 系统返回定位到该 ref 的错误
- **AND** 模型可以改正引用、改用其他证据或停止

## REMOVED Requirements

### Requirement: Measurement evidence must pass an acceptance gate before assembly

**Reason**: 该门禁要求 evidence decision 预先存在，与模型直接在装配请求中表达实际证据使用重复，并限制直接视觉路径。

**Migration**: 将 acceptance gate 替换为按实际引用执行的来源、范围和结构校验。
