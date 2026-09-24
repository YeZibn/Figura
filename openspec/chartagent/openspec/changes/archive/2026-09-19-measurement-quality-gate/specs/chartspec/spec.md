## ADDED Requirements

### Requirement: Source-derived ChartSpec can identify accepted measurement provenance

源图恢复得到的 ChartSpec SHALL 能够关联其使用的已接受测量证据摘要或引用，包括源附件、面板和测量 attempt 身份；该 provenance SHALL 用于判断数据是否经过测量质量门禁，而不是把自由文本 source 标签当作证据。

#### Scenario: Assembled data points reference accepted evidence

- **WHEN** ChartSpec 的数据由某个 panel 的 accepted measurement attempt 提供
- **THEN** ChartSpec 或其受控 provenance 能够识别该 attachment、panel 和 attempt
- **AND** 下游可以区分该数据与未绑定来源的直接视觉输入

#### Scenario: Unaccepted provenance cannot be presented as verified

- **WHEN** ChartSpec 仅关联 provisional、partial 或 failed 的测量 evidence
- **THEN** 组装或发布链路保留未接受状态并返回结构化问题
- **AND** 不得把该 ChartSpec 宣称为已经由源图测量确认的数据

### Requirement: Measurement provenance does not break direct ChartSpec compatibility

测量 provenance SHALL 对没有使用测量工具的现有单 ChartSpec 输入保持可选。已有 metadata、axes、dataset 和结构化校验语义不得因为新增 provenance 关联而被迫包装成 MeasurementSession。

#### Scenario: Legacy single ChartSpec remains valid

- **WHEN** 调用方提交没有 measurement provenance 的合法单图 ChartSpec
- **THEN** ChartSpec 仍可按现有规则序列化、校验和交给生成流程
- **AND** 只有在调用方声明使用测量证据时才执行对应的接受状态检查
