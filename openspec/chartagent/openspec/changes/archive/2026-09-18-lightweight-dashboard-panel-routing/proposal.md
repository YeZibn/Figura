## Why

当前复杂图表分区默认引入 SAM，但 SAM 只提供边界证据，实际 crop 仍主要来自 VLM bbox，后续图表传感器也继续读取原始图片，导致分区结果没有成为可执行的分析输入。现在应先建立轻量、可复现的 VLM bbox 到局部 ROI 的真实 handoff，再将 SAM 降级为可选扩展。

## What Changes

- 将 dashboard 分区默认流程改为 VLM 语义 bbox 加确定性校验、padding 和矩形局部区域生成。
- 保留稳定的 `panel_id`、源图坐标、局部坐标变换、crop 预览和不确定性信息。
- 让柱状图、折线图、饼图和散点图传感器通过 `panel_id` 消费对应的局部 ROI，而不是只接收一个未执行的布局提示。
- 区分语义 panel 区域、传感器分析范围和图表内部 MeasurementFrame，避免把整张卡片直接当作绘图区。
- 保留 SAM adapter 作为显式可选后端；默认路径不加载 checkpoint、不导入或调用 SAM。
- 保持 OCR 不参与 dashboard 拓扑发现；OCR 仍可在后续图表分析中按需使用。
- **BREAKING** 更新 dashboard 分区和图表传感器的规格契约，明确没有 SAM 时也必须完整工作。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `dashboard-decomposition`: 将确定性矩形分区设为默认，并定义可执行的 panel handoff 与可选 SAM 后端。
- `chart-layout-context`: 区分 panel/analysis scope 与真正的 measurement frame，并保留源图坐标映射。
- `chart-understanding`: 要求图表传感器按 panel 标识消费局部 ROI，同时保持独立绘图区检测和源坐标归因。

## Impact

- 影响 `src/chartagent/tools/chart/observation/dashboard.py`、`segmentation.py`、图表传感器和 Agent 的 panel 路由逻辑。
- 影响工具参数说明、运行时 prompt、dashboard 与图表理解的 OpenSpec 规格。
- 需要补充真实 dashboard fixture 的端到端测试，覆盖分区、panel 路由、局部测量、坐标映射和无 SAM 环境。
- 不新增强制 Python 依赖；默认运行路径不需要 SAM checkpoint 或 `segment_anything`。
