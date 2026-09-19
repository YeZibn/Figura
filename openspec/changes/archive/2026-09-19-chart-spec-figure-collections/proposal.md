## Why

当前 `ChartSpec` 只能表达并渲染一个图表候选。对于同一来源面板中的多组数据，主流程为了继续执行会把其中一组数据单独装配并生成结果，导致来源中的其他系列被遗漏；即使分别生成多个图片，也无法表达“这些子图应当属于同一张最终图”。需要把独立语义图表与最终输出画布分开，使同一 `attachment_id + panel_id` 来源下的多个子图能够一次性组合并接受统一审核。

## What Changes

- 保留 `ChartSpec` 作为单个独立子图的语义描述，并新增图表集合与最终图形容器，用于承载多个相互独立的 `ChartSpec`。
- 按精确来源键 `attachment_id + panel_id` 组织同源子图；同一来源默认生成一张 composite figure，而不是生成互相脱离的多张图片。
- 为集合增加系列覆盖信息，明确来源系列、已表示系列、遗漏系列和覆盖状态，避免装配时静默丢弃数据。
- 扩展 `assemble_spec` 的输入和输出，使单图旧路径保持兼容，同时支持原子地装配并校验多个子图。
- 扩展 `render_chart`，在有多个子图时按受限网格布局渲染一张最终图片，并保留子图标识与来源关系。
- 将审核上下文提升到 figure 级别：审核必须同时看到最终 composite、全部子图规格和覆盖信息；任一阻断性子图或覆盖问题未解决时不得发布结果。
- 保留现有单 `ChartSpec` 的 API、持久化和前端展示兼容性；本次不引入任意仪表盘布局编辑器。

## Capabilities

### New Capabilities

- `chart-spec-figure-collections`: 定义同源子图集合、最终 figure、布局和来源覆盖语义。

### Modified Capabilities

- `chartspec`: 扩展 ChartSpec 的集合化装配、来源分组、覆盖校验和序列化契约。
- `chart-generation`: 支持把同源多个 ChartSpec 渲染为一张 composite figure，并以 figure 级别保留审核与发布约束。

## Impact

- Python 图表语义模型与序列化：`src/chartagent/spec/`。
- ChartSpec 装配、渲染、审核及其调用链：`src/chartagent/tools/chart/`、Agent loop 和运行时结果持久化。
- 工具协议及前端生成结果协议：需要增加集合、figure、子图和覆盖元数据，但应保持已有单图 artifact 可读取。
- 测试：增加同一面板多系列、多子图组合、覆盖失败、原子失败和单图回归用例；使用 `conda run -n agent` 执行 Python 测试。
- 不新增外部模型或图像分割依赖；`measure_bars` 的测量质量问题不在本 change 的实现范围内。
