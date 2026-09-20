## Why

最近的柱状图+折线图评测暴露出一个确定的语义丢失问题：ChartSpec 已经保存了折线图的 `Jan`–`Jul` 类别，但最终图片仍显示为 `0`–`6` 或 `1`–`7` 的数字刻度。当前渲染器只使用折线点的数值 `x`，没有把类别序列传递到可见的横轴，因此 VLM 审核会拒绝候选图，且 Agent 的修复无法通过改写 ChartSpec 真正解决问题。

## What Changes

- 明确 ChartSpec 中类别型笛卡尔横轴的语义：`axes.x.categories` 是有序、可见的刻度标签集合，轴标题 `axes.x.label` 不替代类别标签。
- 扩展 `assemble_spec` 的单图和 figure 子图输入，允许主流程把已确认的有序横轴类别传入 ChartSpec；line/scatter 不得因为只提供了 `x_label` 而丢弃类别证据。
- 改造折线图渲染，使存在类别序列时使用稳定的内部位置映射绘制数据，并将类别按原顺序写入横轴刻度；没有类别序列时继续保留数值横轴行为。
- 让渲染前后的确定性检查验证折线图类别数量、顺序、文本和数据点位置的一致性；不一致时阻止发布并返回可定位的问题。
- 补充柱状图与折线图的回归测试，覆盖类别标签、数值横轴、旋转/密集标签和多系列折线，确保修复不会破坏已有图表。
- 在真实图表评测中保留该问题可诊断的证据，使“ChartSpec 有类别但成图缺少类别刻度”能够直接归因到渲染/生成阶段，而不是误判为 VLM 或 OCR 问题。

## Capabilities

### New Capabilities

无。本次是对现有 ChartSpec 和图表生成契约的补全。

### Modified Capabilities

- `chartspec`: 补充类别型笛卡尔轴的有序类别标签、位置映射和缺失/不匹配校验语义。
- `chart-generation`: 要求折线图在有类别轴时渲染可见类别刻度，并在确定性质量审计中验证类别刻度与数据映射。

## Impact

- 主要影响 `src/chartagent/spec/chartspec.py`、`src/chartagent/tools/chart/specification.py`、`src/chartagent/tools/chart/rendering.py` 及对应的生成、审计和回归测试。
- 不改变现有 bar、pie、scatter 的公开输入格式；数值型 line/scatter 仍使用连续数值横轴。
- 不新增模型、OCR、SAM 或外部依赖；修复位于 ChartSpec 到 Matplotlib 的生成边界。
- 评测产物只增加更明确的阶段/问题归因，不改变现有评测运行入口。
