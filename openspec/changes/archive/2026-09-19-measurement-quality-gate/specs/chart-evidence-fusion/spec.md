## ADDED Requirements

### Requirement: Measurement evidence must pass an acceptance gate before assembly

当 ChartSpec 数据来自图表测量工具时，证据融合流程 SHALL 在 `assemble_spec` 之前确认对应的 measurement session 存在可归属的 accepted attempt。provisional、remeasure_required、partial、unsupported 或 failed 的测量结果不得被静默当作确定性源值。

#### Scenario: Unaccepted bar measurement blocks assembly

- **WHEN** 模型使用带有基准线不确定 warning 的柱状图测量结果请求组装 ChartSpec
- **THEN** 系统返回定位到测量会话和具体问题的结构化门禁错误
- **AND** 不返回可被当作已确认数据的 ChartSpec

#### Scenario: Accepted evidence permits assembly

- **WHEN** 当前 attachment 和 panel 的测量 attempt 已通过适用的质量检查并标记为 accepted
- **THEN** 模型可以将该证据用于 `assemble_spec`
- **AND** 生成的 ChartSpec 保留已接受测量的来源摘要或引用

### Requirement: Gate failures provide a bounded recovery action

测量门禁失败 SHALL 返回有界的原因、证据位置和下一步动作。下一步动作可以是补充观测、重新测量、保留不确定值或放弃无法解决的字段，但不得要求模型猜测缺失数据。

#### Scenario: Baseline issue requests further observation

- **WHEN** 柱状图测量因基准线残差或基准线冲突未被接受
- **THEN** 门禁结果指出 baseline issue 和可用的复查动作
- **AND** Agent 可以基于该动作继续当前 panel 的证据闭环，而不是直接生成图表

### Requirement: Direct visual assembly remains compatible

对于没有调用测量工具、且模型直接基于清晰源图视觉理解组装的请求，系统 SHALL 保持现有直接 `assemble_spec` 兼容路径。该兼容路径不得绕过已经存在的 ChartSpec 结构校验和后续生成审核。

#### Scenario: No measurement session is required for direct visual input

- **WHEN** 模型没有引用任何测量工具结果而提交一个合法的单 ChartSpec
- **THEN** 系统按照现有路径完成结构装配
- **AND** 不要求调用方伪造 measurement attempt
