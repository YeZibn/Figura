## ADDED Requirements

### Requirement: Chart observations consume local panel scope

OCR、柱状图、折线图、饼图和散点图观测工具 SHALL 支持使用 attachment ID 与 panel ID 指定分析范围。指定 panel scope 后，工具 SHALL 在局部裁剪上运行，并在结果中同时提供 panel ID、局部尺寸、源图尺寸和局部坐标到源图坐标的映射。

#### Scenario: OCR excludes unrelated dashboard text
- **WHEN** OCR 被请求分析一个具体 chart panel
- **THEN** 返回文字主要来自该 panel 的局部范围
- **AND** 每个文字框可转换回源图坐标

#### Scenario: Bar measurement is scoped to one panel
- **WHEN** 柱状图传感器收到一个 panel ID
- **THEN** 它不得把相邻 panel 的柱子或标签作为当前图表证据
- **AND** overlay 和结构化结果保留局部及源图坐标信息

### Requirement: Unscoped dashboard analysis remains explicit

当工具没有 panel scope 且输入图像可能包含多个独立面板时，系统 SHALL 将结果标记为 unscoped 或要求先解析面板，不得把整图结果伪装成某个具体面板的确定性证据。

#### Scenario: Full-image observation is marked unscoped
- **WHEN** 模型在多面板图片上未提供 panel ID
- **THEN** 工具结果包含明确的 unscoped 警告
- **AND** 结果不得被自动归因给某一个面板
