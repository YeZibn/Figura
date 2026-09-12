## Why

Figura 当前已经能够理解干净的柱状图、折线图和多系列笛卡尔图表，但饼图没有坐标轴，继续复用现有笛卡尔传感器会丢失扇区边界、颜色和标签之间的关系。现在增加独立的饼图传感器，可以把第二阶段的图表理解能力推进到无坐标轴图表，同时保留 Agent 自由选择工具和视觉自验证机制。

## What Changes

- 增加独立的饼图扇区检测工具，识别圆心、半径、扇区边界、角度、颜色和占比。
- 增加图例、OCR 标签及百分比/数值与扇区之间的关联证据，并对无法可靠关联的结果返回 warning。
- 增加扇区总和一致性检查，校验角度是否接近 360 度、占比是否接近 100%。
- 为饼图结果生成源尺寸视觉 overlay，标记圆形区域、扇区、稳定 ID、颜色和关联状态。
- 通过现有授权 attachment ID 将饼图工具注册到 Agent，保持惰性图片加载和自由规划，不强制固定工具顺序。
- 复用现有 `assemble_spec` 和 `validate_spec` 生成并独立校验无坐标轴的 pie ChartSpec。
- 增加干净饼图、多标签饼图、图例饼图和不完整/冲突证据样本的 fixtures、传感器测试与离线 Agent-loop 验收测试。
- 不实现散点图、图表生成/渲染或前端专用饼图结果面板；不改变现有柱状图和折线图输出契约。

## Capabilities

### New Capabilities

### Modified Capabilities

- `chart-understanding`: 增加独立饼图传感器、扇区/标签/图例关联、总和一致性检查、视觉证据和 Agent 集成要求。

## Impact

- Python 图表工具、共享图像处理与 overlay 模块、工具注册和 ChartSpec 组装验证链路。
- 离线图表 fixtures、传感器测试、授权 attachment 边界测试和 Agent-loop 验收测试。
- 现有 Gateway 继续传递通用 tool/result/visual-observation 事件，不新增 Gateway 路由或前端专用协议。
- 实现和测试继续使用 `agent` Conda 环境，并优先复用 Pillow、NumPy 和现有 OCR 依赖；如需新依赖，必须先验证本地安装和运行兼容性。
