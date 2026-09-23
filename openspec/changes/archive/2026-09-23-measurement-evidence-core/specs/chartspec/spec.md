## REMOVED Requirements

### Requirement: Source-derived ChartSpec can identify accepted measurement provenance

**Reason**: provenance should attest which candidate evidence refs were actually supplied, not imply that the measurement lifecycle automatically accepted or selected those candidates.

**Migration**: Source-derived ChartSpec provenance uses actual measurement/evidence refs and their scope; quality remains descriptive metadata and reference/scope validation remains mandatory.

## ADDED Requirements

### Requirement: Source-derived ChartSpec records referenced measurement evidence

源图恢复得到的 ChartSpec SHALL 能够关联其实际使用的测量证据摘要或引用，包括源附件、面板、measurement/evidence refs 和 attempt 身份。该 provenance 用于验证引用和来源范围；测量质量元数据作为候选证据的描述，不要求 `accepted`、`selected` 等生命周期状态。

#### Scenario: Assembled data points reference measurement evidence

- **WHEN** ChartSpec 的数据由某个 panel 的 measurement attempt 提供
- **THEN** ChartSpec 或其受控 provenance 能够识别该 attachment、panel、attempt 和实际引用的 evidence refs
- **AND** 下游可以区分源图测量证据与未绑定来源的直接视觉输入

#### Scenario: Assembly validates evidence without decision status

- **WHEN** ChartSpec 引用存在且来源范围匹配的候选 evidence refs
- **THEN** assembly 按引用和结构校验结果接受或拒绝该请求
- **AND** 不因 measurement 的 provisional/partial 质量描述或缺少 measurement decision 状态而要求单独的接受流程

#### Scenario: Invalid or cross-scope references cannot be presented as provenance

- **WHEN** ChartSpec 引用不存在、越界或来源不匹配的 evidence ref
- **THEN** 组装返回结构化问题且不将无效引用写入 ChartSpec provenance
- **AND** 错误不创建选取、舍弃或接受状态

## MODIFIED Requirements

### Requirement: Measurement provenance does not break direct ChartSpec compatibility

测量 provenance SHALL 对没有使用测量工具的现有单 ChartSpec 输入保持可选。metadata、axes、dataset 和结构化校验语义不得因为新增 provenance 关联而被迫包装成 MeasurementSession。

#### Scenario: Direct single ChartSpec remains valid

- **WHEN** 调用方提交没有 measurement provenance 的合法单图 ChartSpec
- **THEN** ChartSpec 仍可按现有规则序列化、校验和交给生成流程
- **AND** 不要求提交空的 measurement decision 或兼容字段
