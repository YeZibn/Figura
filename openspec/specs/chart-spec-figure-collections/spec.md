# chart-spec-figure-collections Specification

## Purpose

为同一来源面板中的多个独立图表提供清晰的集合和最终画布语义，使系统能够在保留每个 ChartSpec 数据含义的同时生成一张可审核、可追溯的 composite figure。

## Requirements

### Requirement: Same-source charts form one figure

系统 SHALL 提供一个 figure 容器，用于承载一个或多个相互独立的 `ChartSpec` 子图，并 SHALL 以精确的 `attachment_id + panel_id` 作为 figure 的来源键。figure SHALL 为每个子图保留稳定的子图标识、原始 ChartSpec 和受限布局信息。

#### Scenario: Two series from one panel form one figure

- **WHEN** 同一个来源面板需要分别表达 Q1 2024 和 Q2 2024 两个饼图
- **THEN** 系统创建一个 figure，其中包含两个独立的 ChartSpec 子图
- **AND** figure 的来源键同时包含该附件 ID 和该面板 ID
- **AND** 两个子图保持各自的类别和值，不将两个系列拼成一个普通饼图

#### Scenario: Different panels are not merged

- **WHEN** 两个图表来自同一附件但具有不同的 `panel_id`
- **THEN** 系统为两个来源分别创建 figure
- **AND** 不得因为附件 ID 相同而将两个面板的子图合并到同一 figure

### Requirement: A collection preserves figure boundaries

系统 SHALL 支持一个包含多个 figure 的集合，以表达一次运行中来自多个来源面板的结果。集合 SHALL 保留每个 figure 的来源键和子图边界，且不得把不同来源的子图渲染或审核成一个来源不明的结果。

#### Scenario: One run produces figures for multiple panels

- **WHEN** 一次运行从两个来源面板构造了图表
- **THEN** 集合中包含两个可独立访问的 figure
- **AND** 每个 figure 仅包含其来源面板的子图
- **AND** 下游可以按来源键定位对应的 figure

### Requirement: Series coverage is explicit

每个 figure SHALL 暴露来源系列、已表示系列、遗漏系列和覆盖状态。系统 MUST NOT 把遗漏系列静默视为已完成；当遗漏系列不为空时，figure 不得被标记为 `complete` 或作为完整来源重建结果发布。

#### Scenario: Complete coverage is publishable

- **WHEN** 来源面板声明了 Q1 2024 和 Q2 2024，figure 的子图完整表示这两个系列
- **THEN** `source_series` 和 `represented_series` 包含两者
- **AND** `omitted_series` 为空
- **AND** 覆盖状态为 `complete`

#### Scenario: Omitted series remains visible

- **WHEN** 来源面板声明了两个系列但只装配了其中一个
- **THEN** figure 将未表示的系列写入 `omitted_series`
- **AND** 覆盖状态不是 `complete`
- **AND** 系统不得以“单个子图验证通过”替代来源级完整性判断

### Requirement: Collection validation is atomic

集合 SHALL 在发布或交给生成流程前验证每一个子图、来源一致性、覆盖状态和布局约束。任一阻断性问题出现时，集合 SHALL 返回带位置的结构化问题，并 SHALL 不返回可被误认为已完成的 figure 结果。

#### Scenario: Invalid child blocks the figure

- **WHEN** 集合中的一个 ChartSpec 缺少其图表类型要求的轴或包含非法数据点
- **THEN** 集合验证返回定位到对应子图的结构化问题
- **AND** 整个集合不被标记为可生成或可发布
- **AND** 其他子图不得被静默发布为该集合的完整结果

#### Scenario: Valid collection round-trips

- **WHEN** 一个包含来源、布局、覆盖信息和多个 ChartSpec 的集合被序列化并重新构建
- **THEN** 重建后的集合保留 figure、子图顺序、来源键、覆盖字段和每个 ChartSpec 的语义内容
- **AND** 重建后的集合验证结果与原集合一致

### Requirement: Layout metadata is bounded and deterministic

figure SHALL 使用受限且可序列化的布局描述，至少能够表达网格列数和子图顺序。系统 MUST 拒绝超出配置上限的子图数量、列数或画布规模，不得根据未声明的自由布局产生不可追溯的结果。

#### Scenario: Two child charts use a deterministic grid

- **WHEN** figure 包含两个子图且布局声明为两列网格
- **THEN** 系统按稳定顺序将两个子图放入同一画布的两个网格单元
- **AND** 相同的 figure 输入在相同渲染配置下产生相同的布局语义
### Requirement: Figure coverage distinguishes complete source from requested subset

每个 figure SHALL 明确其 `coverage.basis` 是 `full_source`、`requested_subset` 或
`not_applicable`，并分别记录 source series、represented series 和 intentionally omitted
series。集合级 complete/incomplete 判断 SHALL 结合该 basis，而不得把所有省略都判成错误。

#### Scenario: Same-source requested subset remains complete for its task

- **WHEN** 一个 figure 只按 transform 请求绘制同一 panel 的 Actual 系列
- **THEN** figure 可以在该任务范围内标记 complete
- **AND** Target 作为有意省略保留在 coverage 中
- **AND** 不要求把同一附件的其他 panel 加入集合

#### Scenario: Full-source omission remains incomplete

- **WHEN** reconstruct figure 声称覆盖整个 source panel 但缺失一个源系列
- **THEN** figure 标记 incomplete 或返回结构化覆盖问题
- **AND** 不得通过 requested_subset 标签掩盖该缺失

### Requirement: Collection members preserve their individual task contexts

集合 SHALL 为每个 child figure 保留独立的 generation context、source scope、coverage 和
candidate identity；集合装配不得把一个 child 的 panel 或省略决策传播到另一个 child。

#### Scenario: Two panel transforms stay independently reviewable

- **WHEN** 一个 collection 包含两个不同 panel 的转换结果
- **THEN** 每个 child 可被单独定位和审核
- **AND** 一个 child 的 source mismatch 不会被另一个 child 的成功掩盖
