## Why

Figura 已经能够理解柱状图、折线图和饼图，ChartSpec 也已经支持散点图的
`x/y` 数据与 Cartesian 坐标轴，但 Agent 还缺少从图像中恢复散点几何和系列
语义的工具。现在补齐干净二维散点图，可以完成既定的第三阶段图表理解路线，
同时继续沿用附件授权、视觉自验证和 Agent 自由规划能力。

## What Changes

- 增加独立的 `extract_scatter_points` 散点传感器，识别绘图区、点中心、颜色、
  像素坐标和可校准的语义坐标。
- 支持干净的单系列和多系列散点图，并通过图例颜色保留系列身份；无法可靠
  关联时返回稳定回退身份和明确 warning。
- 对点大小、透明度、相邻点合并、重叠点和潜在离群点保留证据与不确定性，
  不把低置信度检测静默转换为确定数据。
- 返回源尺寸视觉 overlay，标记绘图区、点、稳定 ID、系列颜色、校准状态和
  需要复核的点。
- 将散点传感器注册到 Agent 工具系统，使用授权 `attachment_id`，保持工具
  调用、结构化错误和视觉观察的既有协议。
- 复用现有 `assemble_spec` 与 `validate_spec`，允许 Agent 将散点证据组装为
  带坐标轴的 scatter ChartSpec，并独立校验结果。
- 增加确定性散点 fixtures、传感器测试、附件边界测试和离线 Agent-loop 验收
  测试，覆盖完整、部分校准、重叠和非散点输入。
- 不改变现有柱状图、折线图和饼图输出契约，也不强制固定的散点工具调用顺序。

## Capabilities

### New Capabilities

### Modified Capabilities

- `chart-understanding`: 增加散点检测、系列关联、坐标校准、置信度、warning、
  overlay 和 Agent 自由规划要求。

## Impact

- Python 图表传感器、Cartesian 证据工具、overlay 渲染和 Agent 工具注册。
- ChartSpec 的现有 scatter 数据形状和坐标轴校验被复用，不预期改变序列化契约。
- 新增离线 fixtures 与测试；散点确定性传感器测试继续使用 `agent` Conda 环境，
  不依赖外部模型调用。
- Gateway、桌面前端和 Tauri 不增加专用散点接口或 UI，继续消费通用工具结果
  与视觉观察事件。
