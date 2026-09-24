## ADDED Requirements

### Requirement: Same-source child specs render as one composite artifact

生成流程 SHALL 接受一个包含多个独立 ChartSpec 的 figure，并将同一 figure 的子图渲染到一张有界的 composite 图片中。生成结果 SHALL 是一个可归属到该来源键的 artifact，而不是将同源子图默认为互相无关的多张最终图片。

#### Scenario: Q1 and Q2 are visible in one output image

- **WHEN** 一个来源面板包含 Q1 2024 和 Q2 2024 两个饼图子图，且集合覆盖状态为 `complete`
- **THEN** 生成流程输出一张 composite 图片
- **AND** 图片中可分别识别两个子图及其标题、类别和值
- **AND** artifact 元数据包含 figure ID、来源键和子图 ID 列表

#### Scenario: Single ChartSpec still renders as one artifact

- **WHEN** 生成流程收到单个 ChartSpec 而不是 figure 或集合
- **THEN** 系统继续输出原有单图 artifact
- **AND** 不额外创建只有一个子图的多余集合层，除非调用方明确请求集合模式

### Requirement: Composite rendering preserves child semantics

复合渲染 SHALL 分别应用每个子图的图表类型、数据集、类别顺序、系列身份、轴和文本语义。一个子图的缺失值、非法数据或图表类型不得被另一个子图的合法数据掩盖。

#### Scenario: Child chart types remain distinct

- **WHEN** figure 中包含一个 grouped bar ChartSpec 和一个 pie ChartSpec
- **THEN** composite 图片分别以柱状图和饼图表达两个子图
- **AND** 每个子图的数据点数量和类别顺序与其 ChartSpec 一致
- **AND** 不因为使用同一画布而把它们重分类为同一种图表

### Requirement: Figure-level safety and review gate

当 figure 来自源图像或声明需要审核时，生成流程 SHALL 在发布前同时验证 composite 图片、所有子图 ChartSpec、系列覆盖和 artifact 完整性，并 SHALL 以 figure 级上下文执行一次内部 VLM 审核。任一阻断性子图、覆盖、布局或审核问题存在时，系统 SHALL 不发布最终 artifact。

#### Scenario: Review sees the complete figure context

- **WHEN** 一个 source-linked figure 完成 composite 渲染
- **THEN** 审核上下文包含源图像、composite 图片、全部子图 ChartSpec、figure 来源键和覆盖信息
- **AND** 审核能够判断是否所有来源系列都已在最终图片中表示
- **AND** 审核路径不调用 OCR、测量、布局检查或其他图表工具

#### Scenario: One failed child blocks publication

- **WHEN** composite 中任一子图的数据或渲染审计失败，或 figure 覆盖状态不是 `complete`
- **THEN** figure 进入结构化失败或待修复状态
- **AND** 不发行最终 artifact reference
- **AND** 已成功渲染的其他子图不被单独宣称为该 figure 的完整结果

### Requirement: Composite artifact metadata is attributable

复合 artifact SHALL 暴露有界的 figure、来源、子图、布局、覆盖和审核元数据，并 SHALL 保持与现有单图 artifact 的生命周期、媒体类型、尺寸和隐私约束兼容。元数据不得包含本地路径、凭据、原始 provider payload 或图像字节。

#### Scenario: Client can identify child charts in a composite

- **WHEN** composite artifact 被返回给 Gateway 或前端
- **THEN** 客户端可以通过 figure ID、来源键和子图 ID 列表知道图片由哪些 ChartSpec 组成
- **AND** 图片仍按一个最终可展示 artifact 计数
- **AND** 返回内容不暴露本地文件路径或原始图像字节
